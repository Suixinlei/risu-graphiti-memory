# RisuAI Graphiti Memory

给 [RisuAI](https://risuai.net) 增加基于 [Graphiti](https://github.com/getzep/graphiti) 和 Neo4j 的长期叙事记忆：记住发生过什么、关系怎样变化、哪些约定被后续剧情推翻，再把相关事实放回模型上下文。

**当前版本：v0.1.3，早期版本。** 适合本机试用；需要配套 sidecar、Neo4j，以及可用的抽取模型和 embedding 服务，不能仅安装 JS 就运行。

[下载 plugin.js](https://github.com/Suixinlei/risu-graphiti-memory/releases/download/v0.1.3/plugin.js) · [Release](https://github.com/Suixinlei/risu-graphiti-memory/releases/tag/v0.1.3) · [功能 Review](docs/review-2026-10-28.md) · [验证记录](docs/verification/v0.1.3.md)

## 能做什么

| 功能 | 当前行为 |
| --- | --- |
| 生成前召回 | 从近期消息构造查询，按当前角色/会话检索事实，作为 system 消息插入请求 |
| 生成后记忆 | 将待处理消息和本次角色回复合并成带角色标签的 episode，后台抽取实体和关系 |
| 时序事实 | 保留有效时间、失效时间和来源；旧事实标注为 `[已失效]` / `[被推翻]` |
| 剧情时间 | 从 `<statusData>` 读取故事时钟，无时钟的后续轮次沿用已有时间 |
| 历史导入 | 离线 CLI 显式导出、回填；新装插件不会自动扫描整个历史 |
| 故障降级 | 检索失败或无结果时保持原请求；回复先存入插件本地待提交记录；网络恢复后重试，服务确认完成后才移除 |

记忆层用于事件、关系和变化历史。好感度、物品数量等当前数值仍由原来的变量系统维护。入库正文会移除 `<Thoughts>`、`<statusData>`、`<trim>` 内容。

```text
RisuAI 插件 ── beforeRequest ──▶ sidecar /search ──▶ Neo4j
     │                              │                ▲
     └── afterRequest ──▶ /episode/submit 队列 ── Graphiti ──┘
                                          ├── 抽取 LLM
                                          └── Embedding API
```

聊天正文会发送给配置的抽取端点，文本/查询会发送给 embedding 端点。group_id 是逻辑隔离标识，不是访问认证。

## 安装

以下步骤适用于 RisuAI 与 sidecar 在同一台电脑的场景。准备 Docker（含 Compose）、Python 3.10+；下载插件不需要 Node.js，源码构建才需要 Node.js 18+ 和 npm。

### 1. 下载源码并填写配置

```bash
git clone --branch v0.1.3 https://github.com/Suixinlei/risu-graphiti-memory.git
cd risu-graphiti-memory
cp .env.example sidecar/.env
```

编辑 `sidecar/.env`；模型名、地址和 API key 按你的服务填写：

| 配置 | 要求 |
| --- | --- |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 可用的 OpenAI-compatible Chat Completions 端点，支持 json_schema 结构化输出 |
| `LLM_EXTRA_BODY` | 默认关闭 GLM thinking；其他服务不接受时设为 `{}` |
| `LLM_MAX_TOKENS` | 模板为 8192；长 episode 失败时检查模型限制和日志，优先缩小分批 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` | 可用的多语言 embedding 端点，不是普通聊天模型 |
| `EMBEDDING_DIM` | 与实际向量输出一致；已有索引不能只改此值就完成迁移 |
| `NEO4J_PASSWORD` | 将 change-me 换成自己的密码，数据库与 sidecar 使用同一个值 |
| `HOST` / `PORT` | 保持 `127.0.0.1` / `8710` |
| `INGEST_CONCURRENCY` | 保持 `1`，避免并发实体去重竞态 |

配置使用不带引号的 `KEY=value`，JSON 值直接写 JSON。`INGEST_RETRY` 没有接入 worker，修改它不会开启自动重试。

`sidecar/roster.txt` 是内置的特定故事角色名册，启动时应用到所有会话。使用其他角色卡前，将它移出 sidecar 目录或替换为自己的名册；当前不能按会话选择名册。

### 2. 启动 Neo4j

在仓库根目录执行：

```bash
docker compose --env-file sidecar/.env up -d neo4j
docker compose --env-file sidecar/.env logs --tail 50 neo4j
```

等待日志显示数据库已启动。端口只绑定本机，数据保存在 Docker volume 中。

只启动 `neo4j` 服务：仓库缺少 sidecar Dockerfile，全量 `docker compose up` 不是可用的完整安装路径。若已有 neo4j-graphmem 容器或数据库卷，先确认用途和原密码；修改 .env 不会重置已有数据库密码，不要删除原数据。

### 3. 启动 sidecar

```bash
cd sidecar
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

保持终端运行，在另一个终端检查：

```bash
curl --fail http://127.0.0.1:8710/health
```

预期包含 `"status":"ok"`、`"neo4j":"ok"` 与 `"ingest_protocol":2`。这仅验证服务与数据库连通性，不证明模型端点可用，也不证明历史已经入库。

### 4. 在 RisuAI 导入插件

1. 从 [v0.1.3 Release](https://github.com/Suixinlei/risu-graphiti-memory/releases/tag/v0.1.3) 下载附件 **plugin.js**。
2. 打开 RisuAI → 设置 → 插件 → **＋**，在文件选择器中选中 JS。
3. 启用 **Graphiti Long-Term Memory**，按提示授予 replacer 权限。
4. 设置 `sidecar_url=http://127.0.0.1:8710`、`enabled=true`。
5. 导入或更新后刷新 RisuAI 页面，再进入测试会话发送消息，等待后台抽取后继续对话。首次接入不导入已有历史，默认至少 8 条请求消息才执行召回。

手机的 127.0.0.1 指手机自身，不能直接访问电脑 sidecar。本版本没有手机/LAN 的完整配置和验收方案；不要仅将服务开放到公网解决连接问题。

### 插件参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| sidecar_url | http://127.0.0.1:8710 | 服务地址 |
| enabled | true | 字符串 `true` / `false`，同时控制召回与入库；空值为 true |
| top_k | 8 | 召回数量；服务端允许 1–50 |
| min_messages | 8 | 请求消息数门槛，只约束召回，不约束 afterRequest 入库 |
| inject_depth | 0 | 从消息末尾向前插入的位置；0 为末尾 |
| query_window | 2000 | 客户端文本窗口；服务端最终只使用查询的前 400 字符 |

RisuAI 新建整数参数时显示 0；top_k、min_messages、query_window 的 0 或非法值回退到上表默认值，inject_depth=0 保持有效。参数每次请求重新读取。min_messages 只是启发式门槛，不能保证识别所有辅助生成。

### 从旧版升级

先停止你自己的 sidecar，更新源码到 v0.1.3，并用原配置重新启动。确认 `/health` 的 `ingest_protocol=2`，然后在 RisuAI 导入新版 plugin.js、同意更新并刷新页面。必须同时升级插件与 sidecar；新版客户端遇到旧服务会保留待提交记录，不能完成入库。不要删除原数据库、插件存储或 .env。

修复只保护新版已捕获的轮次，无法自动找回旧版已经跳过的消息；需要补记时，请按下面步骤显式导出历史。

## 用 Neo4j Browser 看图谱

打开 [本机 Neo4j Browser](http://127.0.0.1:7474/browser/)，连接 `bolt://127.0.0.1:7687`，用户名 neo4j，密码使用自己的 NEO4J_PASSWORD，数据库选择 neo4j。

仓库提供四个可保存的只读查询：**会话概览、关系图谱、事实时间线、入库记录**。按 [Browser 使用指南](docs/neo4j-browser/README.md) 设置 group_id 并运行即可；关系图默认最多显示 80 条关系，点击关系可检查事实及失效时间。Browser 随 Neo4j 自带，不需要另装服务。

## 可选：导入历史

backfill.py 读取外部工具已生成的 JSON dump，不直接解析 database.bin，本仓库也不附带 dump 工具。输入结构为 `characters/<名称>--<角色标识>/chats/*.json`，聊天 JSON 含 message 数组。

在仓库根目录执行：

```bash
python3 tools/backfill.py export \
  --dump /path/to/db-dump --char YOUR_CHARACTER_ID --chat 0 \
  --last 100 --batch 2 --out messages.jsonl

python3 tools/backfill.py ingest \
  --file messages.jsonl --group YOUR_CHARACTER_ID-YOUR_CHAT_ID \
  --sidecar http://127.0.0.1:8710 --skip-existing
```

--chat 是按文件名排序后的聊天文件索引。正常 group 必须匹配插件 `${chaId}-${chat.id}`，不能用角色显示名；插件另有字段缺失回退，并截到 128 字符。

episode 名称包含角色、会话、原始消息绝对位置及内容的 SHA-256。相同位置和内容在重叠导出窗口中保持同名，不同位置或编辑后的内容不会碰撞。改变 --batch 会形成新的分组名称，不会错误跳过，但也不承诺跨批次边界的语义去重。

CLI 会等待 `completed` 回执才报告成功；超时或失败非零退出，保留 JSONL 后重跑即可续传。`--wait-timeout` 默认每批 600 秒，`--interval` 默认 1。`--skip-existing` 作为兼容参数保留，所有提交都自动检查幂等性。旧版 JSONL 也可重跑：服务核对正文、来源和时间，相同内容复用已有记录，同名不同内容会用新名称入库。

202、queued、queue_depth=0 均不等于完成。检查 episode 是否出现、失败计数是否增长，再验证事实：

```bash
curl --get --data-urlencode 'group_id=YOUR_CHARACTER_ID-YOUR_CHAT_ID' \
  http://127.0.0.1:8710/episodes
python3 tools/eval.py --group YOUR_CHARACTER_ID-YOUR_CHAT_ID \
  --question '这里填写该会话中可核实的问题'
```

eval.py 是人工检查辅助工具，默认问题来自特定故事，不是自动通过/失败判定，也不验证所有孤立 episode。

## 已知限制与排查

- **恢复依赖插件存储**：每轮正文和游标一起写入本地待提交记录；约每 15 秒重试，并在启动和聊天时触发。页面关闭时不重试，重开后恢复。sidecar 队列仍在内存中，服务重启由客户端重新提交；本地存储写入失败、清空存储或卸载插件仍可能丢失待处理内容。永久失败会继续重试，需检查日志和配置。
- **服务状态**：202 可能是 pending 或 completed，只有协议 2 的 completed 回执确认入库；`active` 包含执行中的任务，`pending` 包含排队和执行中的任务，计数在进程重启后归零。单 sidecar 进程、INGEST_CONCURRENCY=1 是去重和顺序保证的前提。
- **语义抽取有不确定性**：模型可能只把“归还”识别为事件，没有提取新的所有权或标记旧状态失效。重要状态应核对图谱；可靠入库不等于每次语义判断正确。
- **剧情时钟有假设**：固定 2026 年、UTC+8；多状态块时在线取最后可解析块，离线取首块。跨年及其他日期格式未支持。
- **编辑/重新生成不等于撤销**：旧事实不会随聊天修改自动删除，后续抽取可能将其失效，但不保证立即修正。
- **查询被截短**：整个 Graphiti 查询取前 400 字符，语义检索也使用该查询，尾部近期内容可能丢失。
- **名册并非通用**：内置别名有共享姓氏等歧义；跨角色卡前应移除或调整，准确率需样本验收。
- **服务无认证**：保持本机访问，CORS 放开不代表访问控制。
- **无记忆注入**：检查开关、权限、消息门槛、group 和成功入库事实；空结果不会插入空记忆块。
- **failed 增长**：检查日志、结构化输出、模型额度与向量维度；缩小导入批次，不要直接重置数据库。

## 开发与验证

```bash
cd plugin
npm ci
npm run typecheck
npm run build
```

产物为 plugin/dist/plugin.js；build 不包含类型检查，两个命令都要运行。dist 不提交，通过 Release 分发。

在仓库根目录运行发布检查：

```bash
python3 docs/verification/check_release.py
```

检查类型、构建、Python 语法、版本，并使用合成 dump 执行离线导出 CLI，不启动现有服务或读取真实聊天。详见 [验证记录](docs/verification/v0.1.3.md)。

`python3 tools/fake_llm.py` 在 127.0.0.1:18090 提供固定回复，将请求保存到 /tmp/fakellm-captures/，用于检查真实 RisuAI 发出的提示词，不能替代 Graphiti 抽取服务。其 /seed/database.bin 依赖开发者本地文件，不属于通用安装步骤。

v0.1.3 的验证使用独立 RisuAI、Neo4j、sidecar 和真实抽取/embedding 端点；聊天回复由可控端点提供，以复现故障和时间变化。覆盖范围、复现步骤和证据见上面的验证记录；不代表所有宿主版本、流式生成及模型组合均兼容。贡献前请读 [AGENTS.md](AGENTS.md)。

## License

MIT（沿用项目原有声明；仓库尚未附独立 LICENSE 文件）。
