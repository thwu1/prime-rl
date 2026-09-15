#!/usr/bin/env python3
"""Build denormalized Parquet analytics cache from normalized SQLite archive.

"""
import sqlite3
import os
from datetime import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

conn = sqlite3.connect('/app/archive.db')

# ---- Messages (Hive-partitioned by year) ----
msg_df = pd.read_sql("""
    SELECT m.id        AS message_id,
           m.conversation_id,
           m.source_id,
           m.sender_id,
           p.email_address AS sender_email,
           p.domain        AS sender_domain,
           m.sent_at,
           m.subject,
           m.size_estimate,
           m.has_attachments
    FROM messages m
    JOIN participants p ON m.sender_id = p.id
""", conn)

msg_df['sent_at'] = pd.to_datetime(msg_df['sent_at'])
msg_df['year'] = msg_df['sent_at'].dt.year.astype('int32')
msg_df['month'] = msg_df['sent_at'].dt.month.astype('int32')
msg_df['hour'] = msg_df['sent_at'].dt.hour.astype('int32')
msg_df['day_of_week'] = msg_df['sent_at'].dt.day_name()
msg_df['has_attachments'] = msg_df['has_attachments'].astype(bool)

msg_table = pa.Table.from_pandas(msg_df, preserve_index=False)

os.makedirs('/app/analytics/messages', exist_ok=True)
pq.write_to_dataset(
    msg_table,
    '/app/analytics/messages',
    partition_cols=['year'],
    compression='snappy',
    use_dictionary=True,
)

# ---- Recipients ----
recip_df = pd.read_sql("""
    SELECT mr.message_id,
           mr.recipient_type,
           p.email_address AS recipient_email,
           p.domain        AS recipient_domain
    FROM message_recipients mr
    JOIN participants p ON mr.participant_id = p.id
""", conn)

os.makedirs('/app/analytics', exist_ok=True)
pq.write_table(
    pa.Table.from_pandas(recip_df, preserve_index=False),
    '/app/analytics/recipients.parquet',
    compression='snappy',
    use_dictionary=True,
)

# ---- Message labels ----
label_df = pd.read_sql("""
    SELECT ml.message_id,
           l.name      AS label_name,
           l.label_type
    FROM message_labels ml
    JOIN labels l ON ml.label_id = l.id
""", conn)

pq.write_table(
    pa.Table.from_pandas(label_df, preserve_index=False),
    '/app/analytics/message_labels.parquet',
    compression='snappy',
    use_dictionary=True,
)

# ---- Attachments ----
attach_df = pd.read_sql("""
    SELECT a.id   AS attachment_id,
           a.message_id,
           a.filename,
           a.mime_type,
           a.size
    FROM attachments a
""", conn)

pq.write_table(
    pa.Table.from_pandas(attach_df, preserve_index=False),
    '/app/analytics/attachments.parquet',
    compression='snappy',
    use_dictionary=True,
)

conn.close()
print("Parquet analytics cache built at /app/analytics/")
