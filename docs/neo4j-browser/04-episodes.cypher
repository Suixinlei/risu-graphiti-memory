// 入库记录：只返回元数据，不主动展示聊天原文。
MATCH (e:Episodic)
WHERE e.group_id = $group_id
RETURN e.name AS name, e.uuid AS uuid,
       e.valid_at AS story_time, e.created_at AS recorded_at,
       e.source_description AS source
ORDER BY recorded_at DESC
LIMIT 100;
