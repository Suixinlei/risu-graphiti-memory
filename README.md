# RisuAI Graphiti Memory

给 [RisuAI](https://risuai.net) 增加长期叙事记忆：只根据正式 assistant 回复在后台生成摘要，再通过 [Graphiti](https://github.com/getzep/graphiti) 和 Neo4j 记录事件、关系和约定，供后续聊天召回。

**当前版本：v0.2.0。插件与 sidecar 必须一起升级。** 上下文裁剪沿用 RisuAI 滑动窗口，插件只追加记忆块。

[下载 plugin.js](https://github.com/Suixinlei/risu-graphiti-memory/releases/download/v0.2.0/plugin.js) · [Release](https://github.com/Suixinlei/risu-graphiti-memory/releases/tag/v0.2.0) · [安装到已有 6001](docs/install-6001.md) · [本版验证](docs/verification/v0.2.0.md)

## 功能

| 功能 | 行为 |
| --- | --- |
| 正式回复捕获 | 使用聊天 output 事件，普通与流式回复共用入口；不捕获用户消息或 Hypa 等辅助模型响应 |
| 异步摘要 | 先在插件 outbox 和服务端 AssistantTurn 持久保存原文，再后台摘要、抽取图谱；不等待模型才显示回复 |
| 完整性检查 | 摘要必须有 `<assistant_summary>...</assistant_summary>`；缺少结尾、空内容或格式异常判为失败，保留原文供重试 |
| 生成前召回 | 按角色/会话检索事实及窗口之外的近期摘要，追加独立 system 记忆块 |
| 时序事实 | 保留来源、有效/失效时间，标注 `[已失效]` / `[被推翻]` |
| 故障恢复 | 只有协议 3 的 completed 回执才移除 outbox；后台失败保留原文，服务重启恢复未完成任务 |
| 历史导入 | CLI 显式导出 assistant 原文再异步入库；新安装不会自动回填历史 |

好感度、物品数量等当前数值仍由变量系统维护。摘要原文会移除 Thoughts、statusData、trim 块；剧情时间在清理前读取。模型语义抽取仍有不确定性。

```text
RisuAI beforeRequest(model) ──▶ /memory ──▶ 摘要 + Graphiti 事实
RisuAI output ──▶ 本地 outbox ──▶ /assistant/submit ──▶ AssistantTurn
                                                          │
                                             后台摘要 ──▶ Graphiti / Neo4j
```

assistant 正文和摘要会发送到配置的模型端点，查询/抽取文本会发送到 embedding 端点。数据库保存原文及摘要；保持服务仅本机可访问。

## 首次安装

准备 Docker Compose、Python 3.10+、可用的 OpenAI-compatible Chat Completions 和 embedding 服务。RisuAI 必须提供 API v3 的 addRisuChatListener；隔离验证所用宿主版本为 2026.10.220。

已有本机 6001 和 sidecar 的用户直接读 [6001 升级指南](docs/install-6001.md)。以下为全新安装，不要用模板覆盖已有配置。

### 1. 下载源码与配置

```bash
git clone --branch v0.2.0 https://github.com/Suixinlei/risu-graphiti-memory.git
cd risu-graphiti-memory
cp .env.example sidecar/.env
```

编辑 sidecar/.env：

| 配置 | 要求 |
| --- | --- |
| LLM_BASE_URL / LLM_API_KEY / LLM_MODEL | 摘要与 Graphiti 抽取使用；抽取需要 json_schema 结构化输出 |
| LLM_EXTRA_BODY | 默认关闭 GLM thinking；不兼容时改为 `{}` |
| LLM_MAX_TOKENS | 控制 Graphiti 抽取预算；独立摘要请求当前上限为 800 tokens，必须通过结束标识检查 |
| EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL | 可用的 embedding 服务，不是普通聊天模型 |
| EMBEDDING_DIM | 必须匹配模型及现有索引，不能只改配置来迁移索引 |
| NEO4J_PASSWORD | 新安装将 change-me 换成自己的密码；已有数据库使用原密码 |
| HOST / PORT | 保持 127.0.0.1 / 8710 |
| INGEST_CONCURRENCY | 保持 1，并且只运行一个 sidecar 进程 |

配置为不带引号的 KEY=value，JSON 值直接写 JSON。INGEST_RETRY 尚未接入 worker。内置 roster.txt 仅用于 legacy 路径，新版 assistant 摘要抽取不附加该故事名册。

### 2. 启动数据库与 sidecar

```bash
docker compose --env-file sidecar/.env up -d neo4j
cd sidecar
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

只启动 compose 的 neo4j 服务；仓库缺少 sidecar Dockerfile，不能全量 compose up。已有容器/卷不要删除或重新初始化。

另开终端检查：

```bash
curl --fail http://127.0.0.1:8710/health
```

应包含 status=ok、neo4j=ok、assistant_memory_protocol=3。ingest_protocol=2 属于保留的 legacy 接口，不能用它判断新版已就绪。health 只验证数据库及进程状态，不验证模型质量或历史导入完成。

### 3. 导入插件

1. 从 [v0.2.0 Release](https://github.com/Suixinlei/risu-graphiti-memory/releases/tag/v0.2.0) 下载 **plugin.js**。
2. RisuAI → 设置 → 插件 → ＋，选择该文件；已有同名插件时确认更新，按提示授予 replacer 权限。
3. 设置 sidecar_url=http://127.0.0.1:8710、enabled=true，刷新页面，只保留一份启用的 Graphiti 插件。
4. 在测试会话发送一条回复，通过 [Browser](docs/neo4j-browser/README.md) 的 05 查询确认该 group 有 completed 的 AssistantTurn。

无需更换聊天主模型；摘要和抽取使用 sidecar/.env 的模型配置。本指南针对同一电脑上的浏览器，手机/LAN 场景不在本版验收范围。

### 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| sidecar_url | http://127.0.0.1:8710 | 服务地址 |
| enabled | true | 字符串 true/false，同时控制召回和捕获 |
| top_k | 8 | 召回事实数量，1–50 |
| min_messages | 8 | 只限制召回；辅助请求另按宿主请求类型排除 |
| inject_depth | 0 | 从末尾向前插入的位置；0 为末尾 |
| query_window | 2000 | 客户端查询窗口；服务端使用查询末尾 400 字符 |
| memory_chars | 4000 | 额外摘要/事实正文合计字符上限，500–12000 |

整数参数初始化为 0 时，除 inject_depth 外均回退默认值。参数每轮重读；字符上限不是所有模型的 token 预算保证。

## Hypa V3 与旧版升级

v0.2.0 已移除会误捕获辅助摘要的 afterRequest 入库，隔离副本中验证了 Hypa 双开时只捕获正式 assistant 输出。可以保留 Hypa 过渡，但两套记忆同时运行会增加请求和上下文消耗。

若目标是替代 Hypa：新会话可关闭 Hypa；已有长档应先补齐所需 assistant 历史，再关闭 Hypa。插件不会导入旧 Hypa 摘要，也不会自动恢复旧窗口之外的历史。关闭开关不需要删除已有 Hypa 数据。具体顺序见 [6001 指南](docs/install-6001.md)。

升级保留原数据库、.env、插件本地存储。旧 outbox 隔离保留、不自动重放；旧图谱不自动清理。新版召回只接受能对应 AssistantTurn 摘要来源的事实；旧 live-v2 在线提交会被拒绝。源码与插件必须同版。

## 显式导入历史

backfill.py 读取外部工具已生成的 JSON dump，不直接解析 database.bin，本仓库不附带 dump 工具。输入结构为 characters/名称--角色标识/chats/*.json，聊天 JSON 含 message 数组。

```bash
python3 tools/backfill.py export \
  --dump /path/to/db-dump --char YOUR_CHARACTER_ID --chat 0 \
  --last 100 --batch 1 --assistant-only --out assistant-history.jsonl
python3 tools/backfill.py ingest \
  --file assistant-history.jsonl --group YOUR_CHARACTER_ID-YOUR_CHAT_ID \
  --sidecar http://127.0.0.1:8710
```

--chat 是按文件名排序的索引；group 必须匹配插件的角色/会话标识，不能用显示名。batch=1 保留原 chatId，避免重复召回窗口内来源。名称包含角色、会话、绝对位置及内容摘要；重叠窗口保持同名，不同 batch 边界不承诺语义去重。

CLI 等待 completed 后才报告成功，失败非零退出；保留 JSONL，重跑相同文件可续传。默认导出仍是 legacy 格式，**新版历史摘要必须显式加 --assistant-only**。待完成前保留所有历史原文。

## Neo4j Browser

打开 [本机 Browser](http://127.0.0.1:7474/browser/)，连接 bolt://127.0.0.1:7687，使用自己的 neo4j 密码。附带五条只读查询：会话概览、关系图谱、事实时间线、episode 记录、assistant 摘要状态。[使用说明](docs/neo4j-browser/README.md)。

## 排查与边界

- 202、queue_depth=0 或 assistant_pending=0 都不保证完成。05 查询中的 completed 才确认摘要和图谱两阶段完成；health 计数只反映当前进程。
- error 可能来自摘要缺结束标识、模型故障或图谱失败。原文保留，客户端重试或服务启动恢复；已保存摘要时重试只补图谱步骤。永久故障会持续重试并消耗模型额度，应检查日志/配置。
- 剧情时间固定 2026 年、UTC+8；在线取最后可解析状态块，离线取首块，不支持通用跨年日历。
- 编辑/重新生成不会自动删除旧事实。抽取、事实失效及召回质量需要人工核对。
- 清空插件存储/卸载可能丢失尚未提交到服务端的回复。不要以此解决升级问题。
- 保留的 legacy 队列仍为内存队列；旧协议不能获得新版任务持久化保证。
- 单进程、INGEST_CONCURRENCY=1；服务没有认证，group_id 不是访问控制，不开放公网/LAN。

## 开发与验证

```bash
cd plugin
npm ci
npm run typecheck
npm run build
cd ..
sidecar/.venv/bin/python tools/check_assistant_summary.py
python3 docs/verification/check_release.py
```

产物为 plugin/dist/plugin.js，通过 Release 附件交付。发布检查不创建 Release、不调用真实模型；最后收尾按用户要求采用轻量检查，未重新跑完整 E2E。此前隔离链路证据、当前结果和未验证项见 [v0.2.0 验证范围](docs/verification/v0.2.0.md)。贡献前读 [AGENTS.md](AGENTS.md)。

## License

MIT（沿用项目原有声明；仓库尚未附独立 LICENSE 文件）。
