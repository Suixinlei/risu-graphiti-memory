# Neo4j Browser 检查 · 2026-10-28

用户明确追加 Browser 配置任务后执行。本次只连接本机已有 Neo4j 并读取图谱，修改 Browser 本地查询与样式；未重启容器、修改认证、开放网络或写入数据库。与离线发布检查分别记录。

## 复现步骤

1. `docker ps -a --filter 'name=^/neo4j-graphmem$'`：确认已有容器和 loopback 端口映射。
2. `curl --fail http://127.0.0.1:7474/browser/`：确认 Browser 页面响应。
3. 在 Codex In-app Browser 打开上述页面，使用本地已有凭据连接，数据库选择 neo4j，确认顶部 connected。
4. 执行 [会话概览](../neo4j-browser/01-groups.cypher)，选择目标 group，并单独运行 `:param group_id => '目标值'`。
5. 分别执行 [关系图](../neo4j-browser/02-graph.cypher)、[事实时间线](../neo4j-browser/03-facts.cypher)、[入库记录](../neo4j-browser/04-episodes.cypher)。
6. 保存四个查询标签，按 [样式步骤](../neo4j-browser/README.md) 设置名称、颜色和优先级，在 Graph 视图确认节点与连线可见。

## 实际结果

- 已有容器运行；7474/7687 均只绑定 127.0.0.1；Browser HTTP 200。
- Browser 显示 connected，数据库为 neo4j；使用已有凭据完成连接，未输出密码。
- 四条查询均执行成功。额外通过只读 Neo4j driver 会话运行同一批查询，确认 counters.contains_updates=false；图谱返回的所有节点和关系均匹配所选 group。
- Browser 中已保存 01 会话概览、02 关系图谱、03 事实时间线、04 入库记录；分别检查结果表格或 Graph。
- 已设置节点 name caption、类型颜色及大小，并将 Entity 样式放在具体类型之后。截图保留在本机交付目录，不上传包含用户图谱的截图到公开仓库。

## 发现并规避的版本差异

上游文档所示 `:param name => { MATCH ... }` 在本机 Browser/数据库组合中报 SyntaxError。最终文档采用已验证的两步方法：先运行 MATCH 取得 group_id，再用字符串形式 :param 设置参数。最初失败尝试没有写入数据库。

## 边界

Browser 可用及既有数据可查，不代表本次新增聊天已入库或抽取模型已经复验。未测试空库安装、异机/手机访问、其他 Browser 版本或浏览器清除站点数据后的自动恢复。仓库查询文件可用于手动恢复。
