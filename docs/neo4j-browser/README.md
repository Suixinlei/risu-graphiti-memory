# 用 Neo4j Browser 查看记忆图谱

Browser 随 Neo4j 自带，不需要安装额外服务。入口：[本机 Browser](http://127.0.0.1:7474/browser/)。HTTP 用 7474，数据库 Bolt 用 7687；本项目都只绑定本机。

## 连接

1. 按根 README 启动 Neo4j 后打开上述入口。
2. Connection URL 填 127.0.0.1:7687，协议选择 bolt://（直连本机单实例）；默认 neo4j:// 在本机路由正常时也可用。
3. Database user 为 neo4j，密码使用你配置的 NEO4J_PASSWORD；Database 选择 neo4j。已有卷用原密码，不要重置或关闭认证。
4. 顶部应显示 connected。HTTP 200 只说明页面可用，真正连接成功后才能运行查询。

## 五个可保存的查询

在 Browser 的 Queries 中新建查询，粘贴下列文件内容。当前界面会自动保存编辑内容；双击顶部查询标签可改名。不同 Browser 版本也可能使用 Favorites/星标入口。

| 名称 | 查询文件 | 结果 |
| --- | --- | --- |
| 01 会话概览 | [01-groups.cypher](01-groups.cypher) | 每个 group 的实体数和 episode 数 |
| 02 关系图谱 | [02-graph.cypher](02-graph.cypher) | 最近创建的最多 80 条关系，切到 Graph 查看 |
| 03 事实时间线 | [03-facts.cypher](03-facts.cypher) | 事实正文、失效标记、剧情时间与来源 UUID |
| 04 入库记录 | [04-episodes.cypher](04-episodes.cypher) | 最近 100 条 episode 元数据，不展示原始聊天正文 |
| 05 assistant 摘要 | [05-assistant-summaries.cypher](05-assistant-summaries.cypher) | 按 group 查看持久任务状态及摘要 |

先运行会话概览，复制目标 group_id。回到 Stream，单独执行：

```text
:param group_id => '替换为会话概览中的完整 group_id'
```

然后运行 02–05。要找最近创建 episode 所属的 group，可以先执行下面的查询，再把返回值复制到上面的 :param 命令；**它可能是测试或回填 group，不保证是当前 RisuAI 会话**：

```cypher
MATCH (e:Episodic)
RETURN e.group_id AS group_id
ORDER BY e.created_at DESC
LIMIT 1;
```

空数据库先等待一次成功入库。要切换故事就重新设置参数；查询对关系及两端实体同时按 group 过滤，不能仅用同名角色判断会话。

## 怎样读图

- 节点是 Character、Location、Item、Event、Organization、Concept 等实体；关系的 fact 属性是抽取的自然语言事实。
- 点击关系查看 valid_at、invalid_at、expired_at；不能只看线条判断当前状态，03 事实时间线提供与插件一致的标记。
- 图谱包含历史失效关系。需要仅看未标记失效的关系时，在 02 的 WHERE 中追加 `AND r.expired_at IS NULL AND r.invalid_at IS NULL`。
- Browser 的自动展开可能显示查询之外的邻居；严格检查查询结果时关闭自动连接/展开，保持 group 过滤。
- Queries/参数保存在该浏览器环境中，换浏览器或清除站点数据后按仓库文件恢复。不要将包含真实聊天的截图、导出结果或认证信息提交到公开仓库。

## 推荐的可视化设置

本机 Browser 已按以下方式设置，其他浏览器可手动恢复：

1. 运行 02 关系图谱，右侧 Results overview 点击节点类型，在 Customize Style 中将 Caption 设为 name。
2. Character 用蓝色、60px；Event 用黄色、Item 用绿色、Location 用紫色、Organization 用橙色，大小均为 54px；Entity 用灰色、54px。
3. 点击节点列表旁的 Update styling priority，将通用 Entity 移到具体类型后面，避免所有节点被 Entity 样式覆盖，再退出排序模式。
4. 点击 Zoom to fit。事实正文较长，保留在线条详情或 03 时间线中阅读，避免把全文堆在线条上。

这些只是 Browser 本地展示设置，不改变数据库节点、关系或向量索引。

所有附带查询都是只读 MATCH/RETURN，带结果上限。它们不调用模型，也不写入、删除或修复图谱。Browser 是查看/诊断工具，不代替入库完成及召回质量验收。

## 验证方法与来源

检查前的失败场景：HTTP 可用但 Bolt 不可用、登录失败或选错数据库、参数缺失/选错 group、关系属性或标签不匹配、查询语法不兼容、跨 group 结果及大图渲染问题。先用只读查询验证，再检查 Browser 的 connected、查询表格与 Graph 视图。

界面和参数语法参考 [Neo4j Browser 参数文档](https://github.com/neo4j/neo4j-browser/blob/master/docs/modules/ROOT/pages/operations/query-parameters.adoc)，关系/属性名称核对本地 Graphiti 0.31.2 源码。当前本机验证结果见 [Browser 检查记录](../verification/neo4j-browser-2026-10-28.md)。

## v0.2.0：assistant 摘要

`05-assistant-summaries.cypher` 按 group 显示 AssistantTurn 状态和摘要，不主动显示原文。pending/error 表示尚未完成摘要或图谱写入；只有 completed 确认两阶段完成。原文和摘要均保留在独立节点，v0.1.3 发布包没有此查询。
