// 事实时间线：状态与插件标记一致，不把 null invalid_at 当作完整事实验证。
MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
WHERE a.group_id = $group_id AND b.group_id = $group_id
  AND r.group_id = $group_id
RETURN a.name AS source, b.name AS target, r.fact AS fact,
       CASE WHEN r.expired_at IS NOT NULL THEN '已失效'
            WHEN r.invalid_at IS NOT NULL THEN '被推翻'
            ELSE '未标记失效' END AS state,
       r.valid_at AS valid_at, r.invalid_at AS invalid_at,
       r.created_at AS recorded_at, r.episodes AS episode_uuids
ORDER BY valid_at DESC, recorded_at DESC
LIMIT 100;
