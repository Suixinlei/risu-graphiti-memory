// Generate only synthetic data in a NEW directory; never copies user saves.
// node tools/e2e_seed.cjs /absolute/RisuAI /absolute/new-test-risu-directory
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { createRequire } = require('node:module');
const [risuRoot, target] = process.argv.slice(2);
if (!path.isAbsolute(risuRoot || '') || !path.isAbsolute(target || '') || fs.existsSync(target)) {
  throw new Error('Pass an absolute RisuAI directory and a NEW absolute test directory');
}
const { Packr } = createRequire(path.join(risuRoot, 'package.json'))('msgpackr');
fs.mkdirSync(path.join(target, 'save'), { recursive: true });
fs.symlinkSync(path.join(risuRoot, 'dist'), path.join(target, 'dist'));
const characters = ['A', 'B'].map((suffix) => ({
  type: 'character', name: 'Graphmem E2E ' + suffix, chaId: randomUUID(),
  firstMessage: '这是合成测试会话。', desc: '合成测试，只讨论阿澄、林舟和钥匙。', notes: '',
  chats: [{ id: randomUUID(), name: 'E2E ' + suffix, note: '', localLore: [],
    message: Array.from({ length: 8 }, (_, i) => ({
      chatId: randomUUID(), role: i % 2 ? 'char' : 'user',
      data: `合成历史 HISTORY_ONLY_${suffix}_${i}，无需回填。`, time: 1700000000000 + i * 1000,
    })),
  }],
  chatFolders: [], chatPage: 0, viewScreen: 'none', bias: [], emotionImages: [],
  globalLore: [], sdData: [], customscript: [], triggerscript: [], utilityBot: false,
  exampleMessage: '', creatorNotes: '', systemPrompt: '', postHistoryInstructions: '',
  alternateGreetings: [], tags: [], creator: 'E2E', characterVersion: '1',
  personality: '', scenario: '', firstMsgIndex: -1,
}));
const model = {
  id: 'xcustom:::graphmem-e2e', internalId: 'graphmem-e2e',
  url: 'http://127.0.0.1:18093/v1/chat/completions', format: 0, tokenizer: 0,
  key: 'e2e-placeholder', name: 'Graphmem E2E', params: '', flags: [6, 8],
};
const db = {
  characters, characterOrder: characters.map((c) => c.chaId), didFirstSetup: true,
  language: 'en', username: 'E2E User', aiModel: model.id, subModel: model.id,
  customModels: [model], plugins: [], mainPrompt: 'Continue this synthetic narrative in Chinese.',
  jailbreak: '', globalNote: '', useStreaming: false, maxContext: 8000, maxResponse: 256,
  temperature: 0, botSettingAtStart: false, pluginCustomStorage: {},
};
const header = Buffer.from([0, 82, 73, 83, 85, 83, 65, 86, 69, 0, 7]);
fs.writeFileSync(path.join(target, 'save', Buffer.from('database/database.bin').toString('hex')),
  Buffer.concat([header, new Packr({ useRecords: false }).pack(db)]));
fs.writeFileSync(path.join(target, 'identities.json'), JSON.stringify(characters.map((c) => ({
  name: c.name, character: c.chaId, chat: c.chats[0].id, group: `${c.chaId}-${c.chats[0].id}`,
})), null, 2));
console.log('Fresh synthetic RisuAI save and identities.json generated');
