// Metadata header (prepended to the bundle by the build script; keep in sync):
// //@name graphiti_memory
// //@display-name Graphiti Long-Term Memory
// //@api 3.0
// //@version 0.1.0
// //@author risu-graphiti-memory
// //@link https://github.com/Suixinlei/risu-graphiti-memory
// //@description Long-term memory layer backed by a Graphiti temporal knowledge graph sidecar. Retrieves relevant facts (with change history) into the prompt and ingests new messages. Requires the sidecar service (see repo README).
// //@arg sidecar_url string Sidecar base URL (default http://127.0.0.1:8710)
// //@arg enabled bool Enable memory injection and ingestion (default true)
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
  const num = async (k: string, d: number) => {
    const v = await risuai.getArgument(k);
    const n = v !== null && v !== undefined && v !== '' ? parseInt(String(v), 10) : NaN;
    return Number.isFinite(n) ? n : d;
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
    topK: await num('top_k', DEFAULTS.top_k),
    minMessages: await num('min_messages', DEFAULTS.min_messages),
    injectDepth: await num('inject_depth', DEFAULTS.inject_depth),
    queryWindow: await num('query_window', DEFAULTS.query_window),
  };
}

async function sidecarPost<T>(cfg: Config, path: string, body: unknown, timeoutMs = 8000): Promise<T | null> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const resp = await risuai.nativeFetch(cfg.sidecar + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    clearTimeout(timer);
    if (!resp.ok) return null;
    return (await resp.json()) as T;
  } catch {
    return null;
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

interface Cursor {
  count: number;
}

let ingestBusy = false;

async function syncIngest(cfg: Config, aiContent: string): Promise<string> {
  if (!cfg.enabled) return aiContent;
  // Fire-and-forget: never let memory problems break or delay the chat.
  if (ingestBusy) return aiContent;
  ingestBusy = true;
  (async () => {
    try {
      const ctx = await currentContext();
      if (!ctx || !ctx.chat) return;
      const storage = await risuai.getLocalPluginStorage();
      const key = `graphiti-memory:cursor:${ctx.group}`;
      const msgs: ChatMsg[] = ctx.chat.message || [];
      let cursor = await storage.getItem<Cursor>(key);
      if (!cursor) {
        // First contact: do NOT ingest the whole history (an accidental full
        // backfill through the live path floods the sidecar queue); start
        // from the current user message. Use tools/backfill.py to ingest
        // history deliberately.
        const lastMsg = msgs[msgs.length - 1];
        cursor = {
          count: lastMsg && lastMsg.role === 'user' ? msgs.length - 1 : msgs.length,
        };
      }

      // History truncated/edited/regenerated below the cursor: resync forward
      // (the skipped range is not re-ingested; stale facts are handled by the
      // graph's temporal invalidation).
      if (cursor.count > msgs.length) {
        await storage.setItem(key, { count: msgs.length } as Cursor);
        return;
      }
      const delta = msgs.slice(cursor.count).map((m) => ({
        role: m.role,
        data: clean(m.data || ''),
      }));
      const aiText = clean(aiContent);
      if (aiText) delta.push({ role: 'char', data: aiText });
      const toIngest = delta.filter((m) => m.data);
      for (let i = 0; i < toIngest.length; i++) {
        const m = toIngest[i];
        await sidecarPost(
          cfg,
          '/episode',
          {
            group_id: ctx.group,
            name: `live-${Date.now()}-${i}`,
            body: m.data,
            source: 'message',
            source_description: `${ctx.charName || 'chat'}/${m.role}`,
            reference_time: new Date().toISOString(),
          },
          6000,
        );
      }
      if (toIngest.length) {
        await storage.setItem(key, { count: msgs.length + (aiText ? 1 : 0) } as Cursor);
      } else {
        await storage.setItem(key, { count: msgs.length } as Cursor);
      }
    } catch {
      // swallow — memory sync must never surface in the chat
    } finally {
      ingestBusy = false;
    }
  })();
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
    return injectMemory(cfg, messages);
  });
  await risuai.addRisuReplacer('afterRequest', async (content: string) => {
    const cfg = await loadConfig();
    if (!cfg.enabled) return content;
    return syncIngest(cfg, content);
  });
})();
