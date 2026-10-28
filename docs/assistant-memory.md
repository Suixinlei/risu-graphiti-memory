# v0.2.0：assistant-only 异步记忆

按用户要求，摘要只依据 assistant 返回的消息，在后台生成。用户消息用于当前对话与检索查询，不进入摘要原文。

## 链路

1. RisuAI 正式输出写入聊天后，output 事件给出角色/会话/消息快照。流式完成与普通回复使用同一入口，辅助模型请求不触发此事件。
2. 插件只取事件中 char/assistant 消息，清理 Thoughts/statusData/trim。原文、消息 ID、原文版本一起持久化到新版本地 outbox，不等待模型或网络。
3. `/assistant/submit` 持久化 AssistantTurn 原文，再返回协议 3 的 pending。相同名称不同请求返回 409。
4. 后台分块摘要完整原文；生成成功先保存摘要，再交 Graphiti 抽取实体/事实。模型或图谱失败保留原文和已完成摘要，客户端重试或服务重启可恢复。
5. 两个阶段都完成后返回 completed，插件才移除 outbox 项。原文与摘要不会因确认而从数据库删除。

新链路不使用 afterRequest，也不会把用户发言、Hypa 副模型摘要、情绪判断等辅助响应当成剧情入库。失败且没有提交 assistant 消息的请求不生成记忆；宿主已经提交的部分输出，以实际已提交内容为准。

## 摘要格式与失败处理

模型必须返回 `<assistant_summary>摘要正文</assistant_summary>`，只保存标识内部的正文。缺少结尾即失败；缺少开头、标识错配/重复/嵌套、标识外有文字、空正文或正文超过 2000 字符也会失败。完整标识周围的空白允许存在。

格式失败沿用任务错误处理：不写入半截摘要或图谱，保留 assistant 原文，状态设为 error，客户端重试或服务重启可恢复。不额外依赖模型的 finish_reason，结尾标识完整才可能通过。多段长回复的每一段摘要及再次合并时均使用同一规则。

本次收尾采用[轻量本地验证](verification/summary-markers.md)，不调用真实模型，也不重跑完整 E2E。

## 记忆召回与滑动窗口

上下文裁剪完全沿用 RisuAI 的滑动窗口。插件不替换、压缩或删减窗口中已有的 assistant、user、system 消息，只追加独立的记忆块。

`/memory` 返回相关图谱事实和当前窗口之外的近期 assistant 叙事摘要。客户端只传递可见 assistant 消息 ID，用来避免重复召回已经在窗口里的来源消息，不请求任何原文替换映射。

额外摘要/事实块默认合计上限 4000 字符，参数为 memory_chars。辅助请求不注入；正常聊天仍受 min_messages 门槛控制。字符上限不等同于模型的 token 上限，具体模型仍需留出记忆注入空间。

## 历史接续

只对显式指定的 dump 操作，不扫描或修改用户真实数据库。新安装只记新产生的正式回复；已有长档应在隔离副本核对历史导入后再切换。

```bash
python3 tools/backfill.py export \
  --dump /absolute/db-dump --char CHARACTER_ID --chat 0 \
  --last 100 --batch 1 --assistant-only --out assistant-history.jsonl
python3 tools/backfill.py ingest \
  --file assistant-history.jsonl --group CHARACTER_ID-CHAT_ID \
  --sidecar http://127.0.0.1:8710
```

只导出 assistant 原文，不读取 hypaV3Data.summaries。batch=1 会保留原消息 chatId，便于避免重复召回当前窗口中已有的回复；大于 1 的批次仍可生成摘要/事实。完成前保留原历史，不把 pending 当作已迁移。

旧 v0.1.3 的 cursor/outbox 可能含辅助摘要，因此保留在旧 namespace，不自动重放或删除。旧图谱也不会自动清理；新版 /memory 只返回能对应 AssistantTurn 摘要来源的图谱事实，未被新链路确认的 legacy 事实不注入。需用户确认来源后再处理旧数据。新版服务拒绝旧 live-v2 在线提交，防止未刷新的旧插件继续污染。旧 `/episode/submit` 和默认历史导出仍为 legacy 路径，不会自动转为新摘要任务。

## 运行和观察

v0.2.0 需要支持 addRisuChatListener 的 RisuAI API v3（本次验证 2026.10.220），以及同版 sidecar。安装/更新后刷新页面。`/health` 的 assistant_memory_protocol 应为 3，assistant_pending 表示当前进程排队/执行的任务，不代表数据库所有 error 任务。

[Browser 摘要查询](neo4j-browser/05-assistant-summaries.cypher)显示 pending、summarized、error、completed。completed 才说明摘要和图谱都完成；数据库保存原始 assistant 正文，按私有数据保护，不开放服务公网访问。
