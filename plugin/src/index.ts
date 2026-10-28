// Metadata header (prepended to the bundle by the build script; keep in sync):
// //@name graphiti_memory
// //@display-name Graphiti Long-Term Memory
// //@api 3.0
// //@version 0.1.3
// //@author risu-graphiti-memory
// //@link https://github.com/Suixinlei/risu-graphiti-memory
// //@description Long-term memory layer backed by a Graphiti temporal knowledge graph sidecar. Retrieves relevant facts (with change history) into the prompt and ingests new messages. Requires the sidecar service (see repo README).
// //@arg sidecar_url string Sidecar base URL (default http://127.0.0.1:8710)
// //@arg enabled string Enable memory injection and ingestion: true or false (default true)
// //@arg top_k int Facts to inject per request (default 8)
// //@arg min_messages int Only inject when the prompt already has at least this many messages; keeps auxiliary calls (suggestions, summarizers) clean (default 8)
// //@arg inject_depth int Insert the memory block this many messages from the end (0 = very end) (default 0)
// //@arg query_window int Characters of recent conversation used to build the search query (default 2000)

type ChatMsg = { role: string; data: string; time?: number; name?: string | null };

const DEFAULTS = {
  sidecar_url: 'http://127.0.0.1:8710',
  enabled: true,
  top_k: 8,
  min_messages: 8,
  inject_depth: 0,
  query_window: 2000,
};

const THOUGHTS_RE = /<Thoughts>[\s\S]*?<\/Thoughts>\s*/gi;
const STATUS_RE = /<statusData>[\s\S]*?<\/statusData>\s*/gi;
const TRIM_RE = /<trim>[\s\S]*?<\/trim>\s*/gi;

function clean(text: string): string {
  return text.replace(THOUGHTS_RE, '').replace(STATUS_RE, '').replace(TRIM_RE, '').trim();
}

interface Config {
  sidecar: string;
  enabled: boolean;
  topK: number;
  minMessages: number;
  injectDepth: number;
  queryWindow: number;
}

async function loadConfig(): Promise<Config> {
  const str = async (k: string, d: string) => {
    const v = await risuai.getArgument(k);
    return v === null || v === undefined || v === '' ? d : String(v);
  };
  const num = async (k: string, d: number, min = 0, max = Infinity) => {
    const v = await risuai.getArgument(k);
    const n = v !== null && v !== undefined && v !== '' ? parseInt(String(v), 10) : NaN;
    // RisuAI initializes int arguments to 0 even when no value was chosen.
    return Number.isFinite(n) && n >= min && n <= max ? n : d;
  };
  const bool = async (k: string, d: boolean) => {
    const v = await risuai.getArgument(k);
    if (v === null || v === undefined || v === '') return d;
    const s = String(v);
    return s === 'true' || s === '1';
  };
  return {
    sidecar: (await str('sidecar_url', DEFAULTS.sidecar_url)).replace(/\/+$/, ''),
    enabled: await bool('enabled', DEFAULTS.enabled),
    topK: await num('top_k', DEFAULTS.top_k, 1, 50),
    minMessages: await num('min_messages', DEFAULTS.min_messages, 1),
    injectDepth: await num('inject_depth', DEFAULTS.inject_depth),
    queryWindow: await num('query_window', DEFAULTS.query_window, 1),
  };
}

async function sidecarPost<T>(cfg: Config, path: string, body: unknown, timeoutMs = 8000): Promise<T | null> {
  const ctrl = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const request = (async () => {
      const resp = await risuai.nativeFetch(cfg.sidecar + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      return resp.ok ? (await resp.json()) as T : null;
    })();
    // Some hosts cannot forward AbortSignal across the plugin iframe. Bound
    // our own wait too; a late accepted submission is safe to replay by name.
    return await Promise.race([request, new Promise<null>((resolve) => {
      timer = setTimeout(() => { ctrl.abort(); resolve(null); }, timeoutMs);
    })]);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ---- context helpers -------------------------------------------------------

async function currentContext(): Promise<{
  group: string;
  chat: { message: ChatMsg[] } | null;
  charName: string;
} | null> {
  try {
    const [charIdx, chatIdx] = [
      await risuai.getCurrentCharacterIndex(),
      await risuai.getCurrentChatIndex(),
    ];
    const char = await risuai.getCharacterFromIndex(charIdx);
    const chat = await risuai.getChatFromIndex(charIdx, chatIdx);
    if (!char || !chat) return null;
    // char.id doesn't exist on character objects — chaId is the field (full
    // UUID). Fallback chain keeps it working if the API ever adds .id.
    const charKey = char.chaId ?? char.id ?? 'char';
    const groupId = `${charKey}-${chat.id ?? chatIdx}`.slice(0, 128);
    return { group: groupId, chat, charName: char.name || '' };
  } catch {
    return null;
  }
}

// ---- ingestion (afterRequest) ----------------------------------------------

interface StoryTime {
  dt: string;
  label: string;
}

interface Episode {
  group_id: string;
  name: string;
  body: string;
  source: 'message';
  source_description: string;
  reference_time: string;
}

interface Cursor {
  // Captured through this position, not necessarily committed to Neo4j.
  // Advancing count and storing the pending body are one local write.
  count: number;
  story?: StoryTime | null;
  pending?: Episode[];
}

const CURSOR_PREFIX = 'graphiti-memory:cursor:';
let storageChain: Promise<unknown> = Promise.resolve();

function withStorage<T>(operation: () => Promise<T>): Promise<T> {
  const result = storageChain.then(operation);
  storageChain = result.catch(() => undefined);
  return result;
}

const STATUS_BLOCK_RE = /<statusData>([\s\S]*?)<\/statusData>/gi;

/**
 * Parse the in-story clock out of a raw message's <statusData> block
 * (time:21:30|date:4月22日 周三|daysElapsed:16|...). The story calendar is
 * anchored to year 2026, wall-clock UTC+8. Uses the LAST statusData block
 * found (latest scene time). Returns null when the text carries no clock.
 */
function parseStoryTime(text: string): StoryTime | null {
  const blocks = [...text.matchAll(STATUS_BLOCK_RE)];
  for (let i = blocks.length - 1; i >= 0; i--) {
    const fields: Record<string, string> = {};
    for (const kv of blocks[i][1].split('|')) {
      const p = kv.indexOf(':');
      if (p > 0) fields[kv.slice(0, p).trim()] = kv.slice(p + 1).trim();
    }
    const md = /(\d{1,2})月(\d{1,2})日/.exec(fields.date || '');
    const hm = /^(\d{1,2}):(\d{2})/.exec(fields.time || '');
    if (!md || !hm) continue;
    const dt = new Date(Date.UTC(2026, +md[1] - 1, +md[2], +hm[1] - 8, +hm[2]));
    if (isNaN(dt.getTime())) continue;
    const label =
      `${fields.date || ''} ${fields.time || ''}`.trim() +
      (fields.daysElapsed ? `（故事第${fields.daysElapsed}天）` : '');
    return { dt: dt.toISOString(), label };
  }
  return null;
}

let draining = false;

async function drainPending(): Promise<void> {
  if (draining) return;
  draining = true;
  try {
    const cfg = await loadConfig();
    if (!cfg.enabled) return;
    const storage = await risuai.getLocalPluginStorage();
    const keys = (await storage.keys()).filter((key) => key.startsWith(CURSOR_PREFIX));
    for (const key of keys) {
      const episode = await withStorage(async () => (await storage.getItem<Cursor>(key))?.pending?.[0]);
      if (!episode) continue;
      // Dedicated v2 endpoint: an old sidecar returns 404 and cannot silently
      // accept retries as independent episodes. 202 alone is NOT an ack.
      const receipt = await sidecarPost<{ protocol: number; status: string; name: string }>(
        cfg, '/episode/submit', episode, 6000,
      );
      if (receipt?.protocol !== 2 || receipt.status !== 'completed' || receipt.name !== episode.name) continue;
      await withStorage(async () => {
        const latest = await storage.getItem<Cursor>(key);
        if (!latest) return;
        // Re-read under the same lock used by capture: an ack must not erase
        // a newer turn appended while the network request was in flight.
        latest.pending = (latest.pending || []).filter((item) => item.name !== episode.name);
        await storage.setItem(key, latest);
      });
    }
  } catch {
    // Storage/network failure retains the outbox for the next tick or reload.
  } finally {
    draining = false;
  }
}

async function syncIngest(cfg: Config, aiContent: string): Promise<string> {
  if (!cfg.enabled) return aiContent;
  try {
    // Snapshot the current conversation before waiting on another capture.
    const ctx = await currentContext();
    if (!ctx?.chat) return aiContent;
    const msgs = ctx.chat.message || [];
    const storage = await risuai.getLocalPluginStorage();
    const key = CURSOR_PREFIX + ctx.group;
    await withStorage(async () => {
      let cursor = await storage.getItem<Cursor>(key);
      if (!cursor) {
        const last = msgs[msgs.length - 1];
        cursor = { count: last?.role === 'user' ? msgs.length - 1 : msgs.length };
      }
      const start = Math.min(cursor.count, msgs.length);
      const parts: string[] = [];
      for (const m of msgs.slice(start)) {
        const body = clean(m.data || '');
        if (body) parts.push(`——${m.role === 'user' ? '用户' : '角色'}——\n${body}`);
      }
      const aiText = clean(aiContent);
      if (aiText) parts.push(`——角色——\n${aiText}`);
      let story = parseStoryTime(aiContent);
      for (let i = msgs.length - 1; i >= start && !story; i--) story = parseStoryTime(msgs[i].data || '');
      story = story || cursor.story || null;
      const pending = cursor.pending || [];
      if (parts.length) {
        pending.push({
          group_id: ctx.group,
          name: `live-v2-${crypto.randomUUID()}`,
          body: (story ? `【剧情时间】${story.label}\n\n` : '') + parts.join('\n\n'),
          source: 'message',
          source_description: `${ctx.charName || 'chat'}/turn`,
          reference_time: story ? story.dt : new Date().toISOString(),
        });
      }
      // Persist the complete turn BEFORE returning to the host or contacting
      // the sidecar. Never advance the cursor independently of this payload.
      await storage.setItem(key, { count: msgs.length + (aiText ? 1 : 0), story, pending } as Cursor);
    });
    void drainPending();
  } catch {
    console.warn('[graphiti_memory] Could not persist this turn; memory capture needs attention.');
  }
  return aiContent;
}

// ---- retrieval (beforeRequest) ---------------------------------------------

interface Fact {
  fact: string;
  valid_at: string | null;
  invalid_at: string | null;
  expired: boolean;
}

function buildQuery(messages: OpenAIChat[], charName: string, windowChars: number): string {
  const parts: string[] = [];
  let used = 0;
  for (let i = messages.length - 1; i >= 0 && used < windowChars; i--) {
    const m = messages[i];
    const c = (m.content || '').slice(0, 800);
    if (!c || m.role === 'system') continue;
    parts.unshift(c);
    used += c.length;
  }
  const q = parts.join('\n').slice(-windowChars);
  return charName ? `${charName}\n${q}` : q;
}

function formatFacts(facts: Fact[]): string {
  const lines = facts.map((f) => {
    const mark = f.expired ? '[已失效]' : f.invalid_at ? '[被推翻]' : '';
    return `${mark ? mark + ' ' : ''}${f.fact}`;
  });
  return [
    '[长期记忆 · 时序事实检索]',
    '以下事实检索自本对话的更早历史，按相关性排序。标注[已失效]/[被推翻]的是已被后续剧情改变的旧状态，仅用于理解变化过程。',
    ...lines.map((l, i) => `${i + 1}. ${l}`),
  ].join('\n');
}

async function injectMemory(cfg: Config, messages: OpenAIChat[]): Promise<OpenAIChat[]> {
  if (!cfg.enabled || messages.length < cfg.minMessages) return messages;
  try {
    const ctx = await currentContext();
    if (!ctx) return messages;
    const query = buildQuery(messages, ctx.charName, cfg.queryWindow);
    if (!query.trim()) return messages;
    const res = await sidecarPost<{ facts: Fact[] }>(
      cfg,
      '/search',
      { group_id: ctx.group, query, limit: cfg.topK },
      10000,
    );
    const facts = (res?.facts || []).filter((f) => f && f.fact);
    if (!facts.length) return messages;
    const block: OpenAIChat = { role: 'system', content: formatFacts(facts) };
    const depth = Math.max(0, Math.min(cfg.injectDepth, messages.length));
    const at = messages.length - depth;
    const out = messages.slice();
    out.splice(at, 0, block);
    return out;
  } catch {
    return messages;
  }
}

// ---- bootstrap --------------------------------------------------------------

(async () => {
  // Config is re-read inside the replacers so setting changes apply without a
  // plugin reload.
  await risuai.addRisuReplacer('beforeRequest', async (messages: OpenAIChat[]) => {
    const cfg = await loadConfig();
    if (!cfg.enabled) return messages;
    void drainPending();
    return injectMemory(cfg, messages);
  });
  await risuai.addRisuReplacer('afterRequest', async (content: string) => {
    const cfg = await loadConfig();
    if (!cfg.enabled) return content;
    return syncIngest(cfg, content);
  });
  // Recover all groups after reload, including chats no longer selected.
  void drainPending();
  setInterval(() => { void drainPending(); }, 15000);
})();
