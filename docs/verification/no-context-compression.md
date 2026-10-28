# 移除上下文压缩 · 2026-10-28

用户明确要求保留 RisuAI 滑动窗口，不需要额外压缩 assistant 回复。

已删除插件的旧 assistant 摘要替换、原文哈希匹配查询及服务端替换映射接口。现有消息原样保留，插件只追加独立记忆块。只对正式 assistant 输出进行后台摘要的链路保持不变。visible_message_ids 仅用于避免重复召回当前窗口里的来源消息，不用于改写。

## 当前验收

在 6001 私有副本的新端口 6072，使用更新后插件与独立 sidecar/Neo4j，发送 NO_COMPRESSION_CHECK 合成消息，读取实际发给本地聊天端点的请求：

- 四条旧 assistant 长回复均与原文逐字相同，每条 2819 字符。
- 无“此前 assistant 回复摘要”替换标记，改写消息数为 0。
- 仍追加 1 个独立记忆块，原消息未被删减或替换。
- /memory 不再返回 context 替换映射，客户端不再传递原文哈希列表。
- 类型检查、构建、Python 语法、离线 CLI 检查、文档链接及 git diff --check 通过。

[实际请求脱敏结果](assistant-memory/no-compression.json) · [构建摘要](assistant-memory/no-compression-build.json)

此前压缩与 token 减少实验保留在 [已撤回实验](assistant-memory/withdrawn-compression/README.md)，不作为当前版本的能力或验收依据。原 6001 未升级，没有提交、推送或发布。
