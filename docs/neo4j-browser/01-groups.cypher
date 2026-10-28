// 会话概览：先找出要查看的 group_id，再设置 Browser 的 $group_id 参数。
MATCH (n)
WHERE n.group_id IS NOT NULL
RETURN n.group_id AS group_id,
       count(CASE WHEN n:Entity THEN 1 END) AS entities,
       count(CASE WHEN n:Episodic THEN 1 END) AS episodes
ORDER BY episodes DESC, entities DESC
LIMIT 100;
