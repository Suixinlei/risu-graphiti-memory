// Assistant-only 异步摘要（v0.2.0）；不展示 assistant 原文。
MATCH (t:AssistantTurn)
WHERE t.group_id = $group_id
RETURN t.name AS name, t.message_id AS message_id, t.status AS status,
       t.summary AS summary, t.created_at AS recorded_at
ORDER BY recorded_at DESC
LIMIT 80;
