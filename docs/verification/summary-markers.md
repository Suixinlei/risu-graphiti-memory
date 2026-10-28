# 摘要标识与代码收尾 · 2026-10-28

按用户要求采用轻量验证：本轮不启动 RisuAI/Neo4j，不调用真实模型，不重跑完整 E2E。6001 未升级，本轮没有提交、推送或发布。

## 格式约定

```text
<assistant_summary>摘要正文</assistant_summary>
```

只保存内部正文。缺少结尾即失败；缺少开头、错配、重复/嵌套、标识外的非空白文字、空正文、超过 2000 字符也失败。格式检查发生在摘要持久化与 Graphiti 入库之前，失败沿用 error 状态和原文保留流程。完整标识周围允许空白；不额外依赖 finish_reason。

先在 [失败场景计划](assistant-memory-plan.md) 写下约定，再编写本地 HTTP 验证脚本，确认旧实现失败后修改实现。检查通过真实 OpenAI SDK 请求本机 HTTP fixture，使用合成回复；不是完整产品 E2E。

## 复现

前置条件：已按 README 安装 sidecar Python 依赖与 plugin npm 依赖。从仓库根目录运行：

```bash
sidecar/.venv/bin/python tools/check_assistant_summary.py \
  --out /tmp/graphmem-summary-markers.json
python3 docs/verification/check_release.py
git diff --check
```

预期：14 项本地 HTTP 检查全部 PASS，real_model_calls 为 0；类型检查、构建、元数据、Python 语法、离线导出、文档链接检查通过。check_release.py 仅生成本地构建附件，不创建 Release。

## 结果与整理范围

- [类型检查、构建与离线检查](assistant-memory/final-checks.json)均通过。
- [标识检查：14 项通过](assistant-memory/summary-markers.json)，包括缺失结束标识的截断响应，以及长原文逐段完整处理。
- [回填整理对照：12 组输出一致](assistant-memory/cleanup-cli.json)。合成数据覆盖 legacy/assistant-only、batch 1/2、全量/尾部窗口，清理前后 JSONL 逐字节一致，包含名称、正文和时间。
- 摘要提示词、格式校验和长度常量集中管理；异步 worker 的任务处理与失败恢复分开，持久化和重试顺序保持一致。
- 回填正文只清理一次，明确区分两种提交协议；修正插件过时的 afterRequest/v2 注释和未使用字段，更新开发说明与 AGENTS.md。
- 沿用宿主滑动窗口，不替换、压缩或删减已有消息。

当前真实模型的标识遵守率、提取质量及完整浏览器链路未在本轮重测。此前隔离验收记录保留，各自只代表当时版本；本轮结果不冒充完整 E2E。
