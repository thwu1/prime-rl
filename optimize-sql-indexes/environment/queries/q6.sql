-- Message queue: fetch unprocessed messages for a specific user
SELECT message_id, sender, subject, message_text, created_at
FROM messages
WHERE processed = 'N'
  AND receiver = 'user_42'
ORDER BY created_at ASC
LIMIT 50;
