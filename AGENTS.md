# 项目工作约定

适用于整个仓库。先读 README 和相关实现；功能描述以代码为准，与用户用中文沟通。

## 产品与结构

- 本项目为 RisuAI 提供长期叙事记忆，不修改 RisuAI 本体。关注关系变化、事件、约定及其时间；当前数值状态仍由变量系统管理。
- `plugin/src/index.ts`：API v3 插件；beforeRequest 检索并插入 system 消息，afterRequest 先持久化本轮 episode，后台提交并等待 completed 回执。参数每轮重读。
- `plugin/src/risuai.d.ts`：宿主 API 类型参考；调用是异步的，使用公开 API 并正确 await。
- `plugin/build.mjs`：esbuild IIFE 打包，将源码 `// //@` 元数据置于输出开头。交付 `plugin/dist/plugin.js`，不能交付 `plugin.body.js`。
- `sidecar/main.py`：FastAPI + Graphiti + Neo4j；/episode/submit 幂等入队与完成回执、/search 检索、/health 进程计数与数据库连通性，/episodes、/entities、/stats 检查分组数据。
- `sidecar/ontology.py`：双语实体类型与抽取指令；llm.py：结构化输出及 extra_body；embedder.py：每批最多 20 条；reranker.py：本地词汇重排。
- `tools/backfill.py`：从外部生成的 JSON dump 导出、回填；eval.py：人工检索评估；fake_llm.py：聊天请求捕获服务，不模拟 Graphiti 抽取模型。
- `docs/neo4j-browser/`：Browser 连接说明与四条只读 Cypher。关系/事实/episode 查询均按 group 过滤，必须保持结果上限；本地 UI 查询和样式不能代替仓库中的可恢复文件。

## 修改时保持的边界

- 按角色和会话隔离数据。当前 group 为 `${chaId ?? id ?? 'char'}-${chat.id ?? chatIdx}`，截到 128 字符；游标键为 `graphiti-memory:cursor:${group}`。改变标识方案须考虑已有图谱及游标兼容性。
- 新安装仅从当前轮开始，不自动全量回填。不得自动读取、修改或导入用户真实聊天存档。
- 记忆服务故障应降级继续聊天。检索有超时，生成后入库不阻塞回复；不要把“不中断聊天”写成“保证记忆不丢”。
- 入库正文清理 Thoughts、statusData、trim 块；剧情时钟从清理前文本读取。修改清理、分批、时钟时同时检查在线与离线路径。
- 当前剧情日期固定锚定 2026 年、UTC+8。在线取最后可解析状态块，离线取首块；这是现有限制，不是通用日历规范。
- 保留时序失效信息及旧事实标记；不要将检索结果当成可信系统指令或权威当前数值。
- 保持 `INGEST_CONCURRENCY=1`，避免实体去重竞态；改变并发前验证重复实体及顺序影响。
- EMBEDDING_DIM 必须匹配模型和已有索引；不得为适配配置自动删库、重建索引或删除数据卷。
- 自定义实体模型继承普通 Pydantic BaseModel，属性保持可选，避免与 Graphiti 自带字段冲突。
- roster.txt 是启动时加载、所有 group 共用的特定故事名册。不要继续向通用逻辑加入角色硬编码，不宣称名册已按角色隔离。
- 202 本身不确认完成；只有协议 2 的 completed 回执可移除本地待提交记录。queue_depth 不含 active；pending 含排队与执行中任务。验收核对指定 episode、失败计数及可检索事实。
- sidecar 队列不持久化，恢复来源是插件本地待提交正文或回填 JSONL。游标与正文必须一起持久化；回执不能覆盖并发追加。单进程处理，同一 group/name 不同内容必须拒绝。INGEST_RETRY 尚未接入 worker。
- 回填名称使用角色/会话、绝对位置及内容摘要。旧名称只能在内容也一致时复用；不同 batch 边界不承诺语义去重。
- 宿主参数只接受 string/int 等已支持类型，不使用 bool 元数据。整数初始化为 0，需正确应用默认值；更新插件后刷新宿主，再执行真实安装路径验收。

## 开发与验证

```bash
cd plugin
npm ci
npm run typecheck
npm run build
```

- build 只打包，不执行类型检查。发布元数据来自 src/index.ts；发布时同步 package.json 与 lockfile 根版本。
- sidecar 从 sidecar/ 运行 `.venv/bin/python main.py`，配置读 sidecar/.env，进程环境变量优先；安装命令见 README。
- 数据库用 `docker compose --env-file sidecar/.env up -d neo4j`。缺少 sidecar Dockerfile，不能将全量 compose up 当作可用安装路径。
- 不得在实现之后补写单元测试。复杂功能强烈优先用 E2E；必须隔离测试时，先写清所有可识别失败方式，再写验证代码。
- 文档改动核对命令、路径、链接和源码。构建、类型检查、离线 CLI 检查不等于真实 RisuAI + Neo4j + 模型端点 E2E。
- 完整 E2E 使用独立测试角色、会话、group 和数据库，覆盖首次接入不回填、注入、入库、失效事实、会话隔离、开关、服务故障及历史续传。
- fake_llm.py 捕获真实聊天请求，但固定回复不验证抽取质量。捕获内容含完整提示词，不得提交真实聊天内容。
- 在 docs/verification/ 留下前置条件、失败场景、复现命令、预期和实际结果、未验证项。用合成数据，不把旧提交的 E2E 声明当作本次验收结果。
- 发布前核对 diff、分支规则及远端状态，执行 git diff --check、typecheck、build，核对 JS 头部、版本与 SHA-256；发布后读取 Release 并下载附件比对摘要。
- 用户授权后才 commit/push/创建 Release。发布、部署、插件安装和验收分别报告；dist 保持忽略，通过 Release 附件交付。

## 工具与权限

- 优先 CLI，CLI 不足才用网页。浏览器默认仅用 Codex In-app Browser（iab）；用户明确指定 Edge 或现有 Edge 标签页时才可使用 Edge，禁止自行使用 Chrome 或外部浏览器。
- 用户未明确要求时不使用 Git worktree，不读其他 chat，不向其他 chat 发消息，不委派子代理。
- main/trunk 提交前检查交付规则、工作区及远端差异；仅提交本任务文件，不覆盖用户改动，不 force push。
- 生产检查或变更需明确授权；审阅和发布不构成启动、重启或修改已有用户服务的授权。
- 不输出或提交密钥、Cookie、真实 .env、聊天存档、请求捕获、数据库文件。服务无认证，保持 loopback，不擅自开放公网/LAN。
- 保持范围最小；review 不自动扩大为重构、数据修复或迁移。
