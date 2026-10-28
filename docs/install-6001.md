# 把 v0.2.0 安装到已有的 RisuAI 6001

适用：同一电脑访问 http://127.0.0.1:6001，已有 sidecar 8710 和 Neo4j 7474/7687。只升级记忆插件和 sidecar，无需升级或重启 RisuAI 6001，不要重建数据库卷。本指南不代表这些步骤已在你的 6001 上执行。

## 1. 备份并暂停聊天

在 6001 导出完整 RisuAI 备份，保留角色卡、聊天和 Hypa 数据。停止发送消息，暂时将旧 Graphiti 插件 enabled 设为 false，刷新页面并关闭其他打开的 6001 标签页。保留旧 plugin.js 和原 sidecar 源码、.env；不要卸载插件或清空站点存储。

## 2. 下载同版插件和服务端

从 [v0.2.0 Release](https://github.com/Suixinlei/risu-graphiti-memory/releases/tag/v0.2.0) 下载 plugin.js、neo4j-browser.zip、install-6001.md、SHA256SUMS 到同一文件夹。macOS 可执行：

```bash
shasum -a 256 -c SHA256SUMS
```

三份附件都应显示 OK。源码需另取相同 tag；在终端执行以下命令，新目录已有时不要覆盖，直接核对其版本：

```bash
cd ~/Projects
git clone --branch v0.2.0 https://github.com/Suixinlei/risu-graphiti-memory.git risu-graphiti-memory-v0.2.0
cd risu-graphiti-memory-v0.2.0
cp ../risu-graphiti-memory/sidecar/.env sidecar/.env
chmod 600 sidecar/.env
cd sidecar
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

这里复用已有配置，**不要用 .env.example 覆盖它**。核对 HOST=127.0.0.1、PORT=8710、INGEST_CONCURRENCY=1，Neo4j 地址/密码、embedding 维度继续使用原值，模型继续使用原服务。配置文件不要上传或分享。

## 3. 切换 sidecar

在原 sidecar 终端按 Ctrl+C 停止旧服务；由进程管理器启动的，用原管理器停止。只停 8710 的记忆服务，不停止 6001、Neo4j 或模型服务；不要根据过期 PID 杀进程。

在新目录的 sidecar 终端启动：

```bash
.venv/bin/python main.py
```

确保只运行一个 sidecar。数据库保持现有容器和卷，启动时会增加 AssistantTurn 约束，不删除旧节点/索引。另开终端检查：

```bash
curl --fail http://127.0.0.1:8710/health
```

必须看到 status=ok、neo4j=ok、**assistant_memory_protocol=3**。同时出现 ingest_protocol=2 是保留的旧接口，正常；如果只有 2，没有 assistant_memory_protocol，则仍是旧服务。

## 4. 在 6001 更新插件

1. 打开原来的 http://127.0.0.1:6001，进入 设置 → 插件 → ＋，选择刚下载的 v0.2.0 plugin.js。
2. 出现同名更新提示时确认更新，按提示授予 replacer 权限；不要同时保留两份启用的 Graphiti 插件。
3. 设置 sidecar_url=http://127.0.0.1:8710、enabled=true。
4. 其余先用默认值：top_k=8、min_messages=8、memory_chars=4000、inject_depth=0、query_window=2000。
5. 刷新整个 6001 页面，确认插件版本为 0.2.0。其他设备/标签页下次使用前也刷新，避免旧插件继续运行。

聊天主模型和滑动窗口设置保持原来的值。插件不会压缩或替换已有回复。

## 5. Hypa V3 如何切换

v0.2.0 修复了旧版把 Hypa 辅助摘要当作正式回复的问题，可以双开过渡；双开仍有两套模型/上下文成本。

- 新会话：可以在 RisuAI 的记忆设置中将 Hypa V3 切换为关闭/无，后续由 Graphiti 累积记忆。
- 已有长会话：先保留 Hypa，用下面的小检查确认新链路；如果需要保留旧窗口之外的剧情，再按 [assistant-only 历史导入](https://github.com/Suixinlei/risu-graphiti-memory/blob/v0.2.0/docs/assistant-memory.md#历史接续) 显式补齐所需历史，完成后关闭 Hypa。

旧 Hypa 摘要不会自动转换成 Graphiti 记忆。旧摘要、旧图谱和旧 outbox 均无需删除；新 outbox 使用独立 namespace，旧内容不会自动重放。关闭 Hypa 不等于删除它的数据。未回填的历史不能承诺由新插件记住。

## 6. 一条回复的小检查

在独立测试会话里让角色给出一条简单、可核对的正式回复。等待后台处理，然后打开 [Neo4j Browser](http://127.0.0.1:7474/browser/)，使用原密码连接 bolt://127.0.0.1:7687。

运行下面的只读查询，找出刚生成的 AssistantTurn；不显示原始聊天正文，也不会调用模型：

```cypher
MATCH (t:AssistantTurn)
RETURN t.group_id AS group_id, t.name AS name, t.status AS status,
       t.summary AS summary, t.created_at AS recorded_at
ORDER BY recorded_at DESC
LIMIT 10;
```

确认 group 对应测试会话，status 最终为 completed，summary 只依据该条 assistant 回复且不含外层标识。pending/summarized 表示尚未完成；error 时检查 sidecar 日志，原文会保留供重试。仅看 health 或队列归零不能判断成功。

需要检查注入时，在请求消息达到 min_messages 后继续一轮，核对召回事实；当前窗口里的同一回复摘要会被去重，不保证立刻出现近期摘要块。使用 [Browser 五条查询](https://github.com/Suixinlei/risu-graphiti-memory/blob/v0.2.0/docs/neo4j-browser/README.md) 按 group 检查。没有旧历史或未达到门槛时，暂时没有注入属于预期。

## 回退

先关闭 Graphiti 插件 enabled 并刷新页面，保留原 Hypa 设置或重新开启 Hypa，聊天可继续使用原记忆方式。需要回到 v0.1.3 时，再停新版 sidecar、用原配置启动保留的旧源码，并导入旧 plugin.js；插件与 sidecar 必须成对回退。v0.1.3 已知会误捕获 Hypa 辅助摘要，不要恢复它与 Hypa 的双开。

不删除 AssistantTurn、旧图谱、Hypa 摘要、插件存储或数据库卷。回退不会撤销已经发生的图谱写入。上述安装和小检查由你在 6001 执行；Release 发布本身不会改变运行实例。
