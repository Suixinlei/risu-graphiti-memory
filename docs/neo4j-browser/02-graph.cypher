// 关系图：包含有效及历史事实。点击关系查看 fact 和时间属性。
MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
WHERE a.group_id = $group_id AND b.group_id = $group_id
  AND r.group_id = $group_id
RETURN a, r, b
ORDER BY r.created_at DESC
LIMIT 80;
