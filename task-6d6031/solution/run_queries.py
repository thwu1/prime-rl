#!/usr/bin/env python3
"""Run analytical queries against the Parquet analytics cache using DuckDB.

"""
import duckdb
import json
import os
from collections import defaultdict

os.makedirs('/app/results', exist_ok=True)
con = duckdb.connect()

MESSAGES = "read_parquet('/app/analytics/messages/*/*.parquet', hive_partitioning=true)"
RECIPIENTS = "read_parquet('/app/analytics/recipients.parquet')"
LABELS = "read_parquet('/app/analytics/message_labels.parquet')"
ATTACHMENTS = "read_parquet('/app/analytics/attachments.parquet')"

# =========================================================================
# Q1: Thread Response Times
# =========================================================================
q1_rows = con.execute(f"""
    WITH msg_ordered AS (
        SELECT conversation_id, sent_at,
               LAG(sent_at) OVER (
                   PARTITION BY conversation_id ORDER BY sent_at
               ) AS prev_sent
        FROM {MESSAGES}
    ),
    gaps AS (
        SELECT conversation_id,
               EXTRACT(EPOCH FROM (sent_at - prev_sent)) / 60.0 AS gap_min
        FROM msg_ordered
        WHERE prev_sent IS NOT NULL
    ),
    conv_stats AS (
        SELECT conversation_id,
               MEDIAN(gap_min) AS median_gap,
               COUNT(*) + 1    AS thread_len
        FROM gaps
        GROUP BY conversation_id
        HAVING COUNT(*) >= 2        -- i.e. thread_len >= 3
    ),
    categorized AS (
        SELECT *,
            CASE
                WHEN median_gap < 60   THEN 'fast'
                WHEN median_gap < 1440 THEN 'medium'
                ELSE 'slow'
            END AS category
        FROM conv_stats
    )
    SELECT category,
           CAST(COUNT(*) AS INTEGER)           AS thread_count,
           AVG(CAST(thread_len AS DOUBLE))     AS avg_thread_length,
           AVG(median_gap)                     AS avg_median_response_min
    FROM categorized
    GROUP BY category
    ORDER BY category
""").fetchall()

q1 = [{'category': r[0],
       'thread_count': int(r[1]),
       'avg_thread_length': float(r[2]),
       'avg_median_response_min': float(r[3])}
      for r in q1_rows]

with open('/app/results/q1.json', 'w') as f:
    json.dump(q1, f, indent=2)

# =========================================================================
# Q2: Sender Influence via PageRank
# =========================================================================

# Step 1: Extract weighted directed edge list from Parquet
edge_rows = con.execute(f"""
    SELECT m.sender_email, r.recipient_email,
           CAST(COUNT(*) AS INTEGER) AS weight
    FROM {MESSAGES} m
    JOIN {RECIPIENTS} r
        ON m.message_id = r.message_id AND r.recipient_type = 'to'
    GROUP BY m.sender_email, r.recipient_email
""").fetchall()

# Step 2: Build graph and compute PageRank via power iteration
nodes = set()
out_weight = {}
adj = {}

for src, dst, w in edge_rows:
    nodes.add(src)
    nodes.add(dst)
    out_weight[src] = out_weight.get(src, 0) + w
    if src not in adj:
        adj[src] = {}
    adj[src][dst] = adj[src].get(dst, 0) + w

n = len(nodes)
damping = 0.85
pr = {node: 1.0 / n for node in nodes}

for iteration in range(100):
    dangling_sum = sum(
        pr[node] for node in nodes if out_weight.get(node, 0) == 0
    )
    new_pr = {}
    for node in nodes:
        new_pr[node] = (1 - damping) / n + damping * dangling_sum / n

    for src in nodes:
        if out_weight.get(src, 0) == 0:
            continue
        for dst, w in adj.get(src, {}).items():
            new_pr[dst] += damping * pr[src] * w / out_weight[src]

    max_diff = max(abs(new_pr[node] - pr[node]) for node in nodes)
    pr = new_pr
    if max_diff < 1e-8:
        break

# Step 3: Get additional metrics from Parquet via DuckDB
msg_sent = dict(con.execute(f"""
    SELECT sender_email, CAST(COUNT(DISTINCT message_id) AS INTEGER)
    FROM {MESSAGES} GROUP BY sender_email
""").fetchall())

msg_recv = dict(con.execute(f"""
    SELECT recipient_email, CAST(COUNT(DISTINCT message_id) AS INTEGER)
    FROM {RECIPIENTS} WHERE recipient_type = 'to'
    GROUP BY recipient_email
""").fetchall())

out_deg = dict(con.execute(f"""
    SELECT m.sender_email, CAST(COUNT(DISTINCT r.recipient_email) AS INTEGER)
    FROM {MESSAGES} m
    JOIN {RECIPIENTS} r
        ON m.message_id = r.message_id AND r.recipient_type = 'to'
    GROUP BY m.sender_email
""").fetchall())

in_deg = dict(con.execute(f"""
    SELECT r.recipient_email, CAST(COUNT(DISTINCT m.sender_email) AS INTEGER)
    FROM {MESSAGES} m
    JOIN {RECIPIENTS} r
        ON m.message_id = r.message_id AND r.recipient_type = 'to'
    GROUP BY r.recipient_email
""").fetchall())

# Step 4: Combine results
q2_results = []
for email in nodes:
    q2_results.append({
        'email': email,
        'pagerank_score': pr[email],
        'messages_sent': msg_sent.get(email, 0),
        'messages_received': msg_recv.get(email, 0),
        'out_degree': out_deg.get(email, 0),
        'in_degree': in_deg.get(email, 0),
    })

q2_results.sort(key=lambda x: (-x['pagerank_score'], x['email']))
q2 = q2_results[:20]

with open('/app/results/q2.json', 'w') as f:
    json.dump(q2, f, indent=2)

# =========================================================================
# Q3: Label Co-occurrence
# =========================================================================
q3_rows = con.execute(f"""
    WITH labeled AS (
        SELECT message_id, label_name
        FROM {LABELS}
    ),
    pairs AS (
        SELECT a.message_id,
               LEAST(a.label_name, b.label_name)    AS label_a,
               GREATEST(a.label_name, b.label_name) AS label_b
        FROM labeled a
        JOIN labeled b
            ON a.message_id = b.message_id AND a.label_name < b.label_name
    ),
    pair_counts AS (
        SELECT label_a, label_b,
               CAST(COUNT(*) AS INTEGER) AS co_occurrence_count
        FROM pairs
        GROUP BY label_a, label_b
    ),
    label_sizes AS (
        SELECT label_name, COUNT(DISTINCT message_id) AS cnt
        FROM labeled
        GROUP BY label_name
    )
    SELECT pc.label_a, pc.label_b, pc.co_occurrence_count,
           pc.co_occurrence_count * 1.0
               / (la.cnt + lb.cnt - pc.co_occurrence_count) AS jaccard_similarity
    FROM pair_counts pc
    JOIN label_sizes la ON pc.label_a = la.label_name
    JOIN label_sizes lb ON pc.label_b = lb.label_name
    ORDER BY pc.co_occurrence_count DESC, pc.label_a ASC, pc.label_b ASC
    LIMIT 20
""").fetchall()

q3 = [{'label_a': r[0],
       'label_b': r[1],
       'co_occurrence_count': int(r[2]),
       'jaccard_similarity': float(r[3])}
      for r in q3_rows]

with open('/app/results/q3.json', 'w') as f:
    json.dump(q3, f, indent=2)

# =========================================================================
# Q4: Communication Burstiness
# =========================================================================

# Extract per-sender timestamps from Parquet
sender_msg_rows = con.execute(f"""
    SELECT sender_email, sent_at
    FROM {MESSAGES}
    ORDER BY sender_email, sent_at
""").fetchall()

sender_times = defaultdict(list)
for email, sent_at in sender_msg_rows:
    sender_times[email].append(sent_at)

cat_stats = defaultdict(lambda: {'count': 0, 'total_b': 0.0, 'total_msgs': 0})

for email, times in sender_times.items():
    if len(times) < 15:
        continue
    times.sort()
    gaps = [(times[i + 1] - times[i]).total_seconds() / 3600.0
            for i in range(len(times) - 1)]

    n_gaps = len(gaps)
    mean_g = sum(gaps) / n_gaps
    if mean_g == 0:
        continue
    variance = sum((g - mean_g) ** 2 for g in gaps) / n_gaps
    std_g = variance ** 0.5

    denom = std_g + mean_g
    if denom == 0:
        b = 0.0
    else:
        b = (std_g - mean_g) / denom

    if b > 0.2:
        cat = 'bursty'
    elif b < -0.2:
        cat = 'periodic'
    else:
        cat = 'random'

    cat_stats[cat]['count'] += 1
    cat_stats[cat]['total_b'] += b
    cat_stats[cat]['total_msgs'] += len(times)

q4 = []
for cat in sorted(cat_stats):
    d = cat_stats[cat]
    q4.append({
        'category': cat,
        'sender_count': d['count'],
        'avg_burstiness': d['total_b'] / d['count'],
        'avg_messages_per_sender': d['total_msgs'] / d['count'],
    })

with open('/app/results/q4.json', 'w') as f:
    json.dump(q4, f, indent=2)

# =========================================================================
# Q5: Attachments by Domain
# =========================================================================
q5_rows = con.execute(f"""
    SELECT m.sender_domain,
           CAST(COUNT(DISTINCT m.message_id) AS INTEGER)  AS total_messages_with_attachments,
           CAST(COUNT(*) AS INTEGER)                      AS total_attachments,
           CAST(COUNT(DISTINCT a.mime_type) AS INTEGER)   AS distinct_mime_types,
           AVG(CAST(a.size AS DOUBLE))                    AS avg_attachment_size_bytes,
           CAST(SUM(a.size) AS BIGINT)                    AS total_attachment_bytes
    FROM {ATTACHMENTS} a
    JOIN {MESSAGES} m ON a.message_id = m.message_id
    GROUP BY m.sender_domain
    ORDER BY total_attachments DESC, m.sender_domain ASC
""").fetchall()

q5 = [{'sender_domain': r[0],
       'total_messages_with_attachments': int(r[1]),
       'total_attachments': int(r[2]),
       'distinct_mime_types': int(r[3]),
       'avg_attachment_size_bytes': float(r[4]),
       'total_attachment_bytes': int(r[5])}
      for r in q5_rows]

with open('/app/results/q5.json', 'w') as f:
    json.dump(q5, f, indent=2)

print("All query results written to /app/results/")
