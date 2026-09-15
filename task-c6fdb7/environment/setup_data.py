#!/usr/bin/env python3
"""Generate search evaluation benchmark data files."""

import csv
import gzip
import json
import os
import sqlite3

os.makedirs('/app/data/systems', exist_ok=True)

# Document corpus
topics = ['machine learning', 'information retrieval', 'natural language processing',
          'computer vision', 'database systems', 'distributed computing',
          'search engines', 'recommendation systems', 'data mining', 'web crawling']

corpus = []
for i in range(50):
    topic = topics[i % len(topics)]
    corpus.append({
        'id': f'doc_{i+1:03d}',
        'title': f'Research on {topic} #{i+1}',
        'text': f'This paper presents novel approaches to {topic}. Entry {i+1}.'
    })

with open('/app/data/corpus.jsonl', 'w') as f:
    for doc in corpus:
        f.write(json.dumps(doc) + '\n')

# Ground truth graded relevance judgments (0-3 scale)
qrels_data = {
    'q01': {'doc_001': 3, 'doc_011': 3, 'doc_021': 2, 'doc_031': 2, 'doc_041': 2,
            'doc_002': 1, 'doc_003': 1, 'doc_012': 1, 'doc_022': 1,
            'doc_032': 0, 'doc_004': 0, 'doc_005': 0, 'doc_014': 0, 'doc_024': 0},
    'q02': {'doc_007': 3, 'doc_017': 3, 'doc_027': 2, 'doc_037': 2,
            'doc_047': 1, 'doc_008': 1, 'doc_018': 1,
            'doc_028': 0, 'doc_009': 0, 'doc_019': 0, 'doc_038': 0},
    'q03': {'doc_005': 3, 'doc_015': 3, 'doc_025': 2, 'doc_035': 2,
            'doc_045': 1, 'doc_006': 1, 'doc_016': 1, 'doc_026': 1,
            'doc_036': 0, 'doc_046': 0, 'doc_010': 0},
    'q04': {'doc_008': 3, 'doc_018': 2, 'doc_028': 2,
            'doc_038': 1, 'doc_048': 1, 'doc_009': 1,
            'doc_019': 0, 'doc_029': 0, 'doc_039': 0, 'doc_049': 0, 'doc_010': 0},
    'q05': {'doc_006': 3, 'doc_016': 3, 'doc_026': 2, 'doc_036': 2,
            'doc_046': 1, 'doc_001': 1, 'doc_011': 1,
            'doc_021': 0, 'doc_031': 0, 'doc_041': 0},
    'q06': {'doc_003': 3, 'doc_013': 2, 'doc_023': 2, 'doc_033': 2,
            'doc_043': 1, 'doc_004': 1,
            'doc_014': 0, 'doc_024': 0, 'doc_034': 0, 'doc_044': 0},
    'q07': {'doc_010': 3, 'doc_020': 2, 'doc_030': 2,
            'doc_040': 1, 'doc_050': 1, 'doc_002': 1,
            'doc_012': 0, 'doc_022': 0, 'doc_032': 0},
    'q08': {'doc_007': 3, 'doc_017': 2, 'doc_027': 2,
            'doc_037': 1, 'doc_047': 1,
            'doc_008': 0, 'doc_018': 0, 'doc_028': 0, 'doc_038': 0}
}

# ---------------------------------------------------------------------------
# SQLite database with multi-annotator judgments and expertise weights
# ---------------------------------------------------------------------------
conn = sqlite3.connect('/app/data/judgments.db')

conn.execute('''CREATE TABLE annotators (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    expertise TEXT NOT NULL,
    weight REAL NOT NULL
)''')

conn.execute('''CREATE TABLE judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    annotator_id INTEGER NOT NULL,
    relevance INTEGER NOT NULL,
    confidence REAL,
    timestamp TEXT,
    FOREIGN KEY (annotator_id) REFERENCES annotators(id)
)''')

# Four annotators with different expertise levels and reliability weights.
# The correct aggregation method is expertise-weighted mean, rounded to
# nearest integer. Using MAX or simple average will produce WRONG results.
conn.execute("INSERT INTO annotators VALUES (1, 'Dr. Chen', 'expert', 4.0)")
conn.execute("INSERT INTO annotators VALUES (2, 'Dr. Patel', 'senior', 3.0)")
conn.execute("INSERT INTO annotators VALUES (3, 'M. Garcia', 'junior', 1.0)")
conn.execute("INSERT INTO annotators VALUES (4, 'A. Wilson', 'crowd', 0.5)")

# Annotator rating patterns:
#   Dr. Chen  (expert, w=4.0): rates at ground truth
#   Dr. Patel (senior, w=3.0): rates at ground truth
#   M. Garcia (junior, w=1.0): always rates 0 (overly strict / doesn't understand domain)
#   A. Wilson (crowd,  w=0.5): always rates 3 (spam / reflexive high ratings)
#
# Expertise-weighted mean = (4*gt + 3*gt + 1*0 + 0.5*3) / 8.5
#                         = (7*gt + 1.5) / 8.5
#   gt=0: 0.176 -> 0     gt=1: 1.0 -> 1     gt=2: 1.824 -> 2     gt=3: 2.647 -> 3
# This recovers ground truth.  MAX gives 3 for everything.  Simple avg differs.
for qid in sorted(qrels_data.keys()):
    for did in sorted(qrels_data[qid].keys()):
        gt = qrels_data[qid][did]
        conn.execute(
            'INSERT INTO judgments (query_id, doc_id, annotator_id, relevance, confidence, timestamp) VALUES (?,?,?,?,?,?)',
            (qid, did, 1, gt, 0.95, '2024-06-01T10:00:00'))
        conn.execute(
            'INSERT INTO judgments (query_id, doc_id, annotator_id, relevance, confidence, timestamp) VALUES (?,?,?,?,?,?)',
            (qid, did, 2, gt, 0.90, '2024-06-02T14:30:00'))
        conn.execute(
            'INSERT INTO judgments (query_id, doc_id, annotator_id, relevance, confidence, timestamp) VALUES (?,?,?,?,?,?)',
            (qid, did, 3, 0, 0.50, '2024-06-03T09:15:00'))
        conn.execute(
            'INSERT INTO judgments (query_id, doc_id, annotator_id, relevance, confidence, timestamp) VALUES (?,?,?,?,?,?)',
            (qid, did, 4, 3, 0.30, '2024-06-04T16:45:00'))

conn.commit()
conn.execute('CREATE INDEX idx_judgments_query ON judgments(query_id, doc_id)')
conn.close()

# ---------------------------------------------------------------------------
# Search system retrieval results
# ---------------------------------------------------------------------------

bm25_runs = {
    'q01': [('doc_001',12.5),('doc_032',11.2),('doc_011',10.8),('doc_004',9.5),
            ('doc_002',8.9),('doc_021',7.3),('doc_014',6.8),('doc_003',6.1),
            ('doc_031',5.5),('doc_024',4.8),('doc_012',4.2),('doc_041',3.5),
            ('doc_022',3.0),('doc_005',2.5),('doc_042',1.8)],
    'q02': [('doc_007',11.8),('doc_009',10.5),('doc_017',9.2),('doc_028',8.5),
            ('doc_027',7.8),('doc_019',6.5),('doc_008',5.8),('doc_038',5.2),
            ('doc_018',4.5),('doc_037',3.8),('doc_047',3.2),('doc_020',2.5),
            ('doc_029',1.8),('doc_039',1.2)],
    'q03': [('doc_005',13.2),('doc_036',11.8),('doc_015',10.5),('doc_010',9.2),
            ('doc_006',8.5),('doc_025',7.8),('doc_046',6.5),('doc_016',5.8),
            ('doc_026',5.2),('doc_035',4.5),('doc_045',3.8),('doc_001',3.2),
            ('doc_002',2.5),('doc_020',1.8)],
    'q04': [('doc_019',10.5),('doc_008',9.8),('doc_029',8.5),('doc_009',7.8),
            ('doc_018',7.2),('doc_039',6.5),('doc_028',5.8),('doc_049',5.2),
            ('doc_038',4.5),('doc_048',3.8),('doc_010',3.2),('doc_030',2.5),
            ('doc_020',1.8),('doc_040',1.2)],
    'q05': [('doc_021',10.2),('doc_006',9.5),('doc_031',8.8),('doc_016',8.2),
            ('doc_041',7.5),('doc_001',6.8),('doc_026',6.2),('doc_011',5.5),
            ('doc_036',4.8),('doc_046',4.2),('doc_002',3.5),('doc_012',2.8),
            ('doc_022',2.2),('doc_032',1.5)],
    'q06': [('doc_014',11.2),('doc_003',10.5),('doc_024',9.8),('doc_034',9.2),
            ('doc_013',8.5),('doc_044',7.8),('doc_004',7.2),('doc_023',6.5),
            ('doc_033',5.8),('doc_043',5.2),('doc_015',4.5),('doc_025',3.8),
            ('doc_035',3.2),('doc_005',2.5)],
    'q07': [('doc_012',10.8),('doc_010',9.5),('doc_022',8.8),('doc_032',8.2),
            ('doc_020',7.5),('doc_002',6.8),('doc_030',6.2),('doc_040',5.5),
            ('doc_050',4.8),('doc_001',4.2),('doc_011',3.5),('doc_021',2.8),
            ('doc_031',2.2),('doc_041',1.5)],
    'q08': [('doc_008',11.5),('doc_007',10.8),('doc_018',9.5),('doc_028',8.8),
            ('doc_017',8.2),('doc_038',7.5),('doc_027',6.8),('doc_037',6.2),
            ('doc_047',5.5),('doc_009',4.8),('doc_019',4.2),('doc_029',3.5),
            ('doc_039',2.8),('doc_049',2.2)]
}

dense_runs = {
    'q01': [('doc_011',0.95),('doc_021',0.89),('doc_031',0.85),('doc_041',0.80),
            ('doc_001',0.75),('doc_012',0.68),('doc_022',0.62),('doc_003',0.55),
            ('doc_002',0.48),('doc_032',0.42),('doc_005',0.35),('doc_014',0.28),
            ('doc_004',0.22),('doc_024',0.15),('doc_042',0.10)],
    'q02': [('doc_017',0.93),('doc_037',0.88),('doc_007',0.82),('doc_027',0.76),
            ('doc_047',0.70),('doc_018',0.65),('doc_008',0.58),('doc_028',0.52),
            ('doc_009',0.45),('doc_038',0.38),('doc_019',0.32),('doc_029',0.25),
            ('doc_039',0.18),('doc_020',0.12)],
    'q03': [('doc_015',0.92),('doc_025',0.86),('doc_035',0.80),('doc_005',0.74),
            ('doc_045',0.68),('doc_016',0.62),('doc_006',0.55),('doc_026',0.48),
            ('doc_036',0.42),('doc_046',0.35),('doc_010',0.28),('doc_001',0.22),
            ('doc_020',0.15),('doc_030',0.10)],
    'q04': [('doc_008',0.94),('doc_018',0.87),('doc_028',0.80),('doc_038',0.72),
            ('doc_048',0.65),('doc_009',0.58),('doc_019',0.50),('doc_029',0.42),
            ('doc_039',0.35),('doc_049',0.28),('doc_010',0.22),('doc_020',0.15),
            ('doc_030',0.10),('doc_040',0.05)],
    'q05': [('doc_006',0.92),('doc_016',0.85),('doc_026',0.78),('doc_036',0.72),
            ('doc_046',0.65),('doc_001',0.58),('doc_011',0.52),('doc_021',0.45),
            ('doc_031',0.38),('doc_041',0.32),('doc_002',0.25),('doc_012',0.18),
            ('doc_022',0.12),('doc_032',0.08)],
    'q06': [('doc_013',0.90),('doc_023',0.84),('doc_033',0.78),('doc_003',0.72),
            ('doc_043',0.65),('doc_004',0.58),('doc_014',0.50),('doc_024',0.42),
            ('doc_034',0.35),('doc_044',0.28),('doc_005',0.22),('doc_015',0.15),
            ('doc_025',0.10),('doc_035',0.05)],
    'q07': [('doc_020',0.91),('doc_030',0.85),('doc_010',0.78),('doc_040',0.72),
            ('doc_050',0.65),('doc_002',0.58),('doc_012',0.50),('doc_022',0.42),
            ('doc_032',0.35),('doc_001',0.28),('doc_011',0.22),('doc_021',0.15),
            ('doc_031',0.10),('doc_041',0.05)],
    'q08': [('doc_007',0.93),('doc_017',0.86),('doc_027',0.80),('doc_037',0.73),
            ('doc_047',0.65),('doc_008',0.58),('doc_018',0.50),('doc_028',0.42),
            ('doc_038',0.35),('doc_009',0.28),('doc_019',0.22),('doc_029',0.15),
            ('doc_039',0.10),('doc_049',0.05)]
}

sparse_runs = {
    'q01': [('doc_001',16.5),('doc_011',15.2),('doc_002',13.8),('doc_021',12.5),
            ('doc_031',11.2),('doc_003',10.0),('doc_041',8.8),('doc_012',7.5),
            ('doc_022',6.2),('doc_032',5.0),('doc_004',4.2),('doc_005',3.5),
            ('doc_014',2.8),('doc_024',2.0),('doc_042',1.2)],
    'q02': [('doc_017',15.5),('doc_007',14.2),('doc_008',12.8),('doc_027',11.5),
            ('doc_037',10.2),('doc_018',9.0),('doc_047',7.8),('doc_028',6.5),
            ('doc_009',5.2),('doc_019',4.0),('doc_038',3.2),('doc_020',2.5),
            ('doc_029',1.8),('doc_039',1.2)],
    'q03': [('doc_005',17.0),('doc_015',15.5),('doc_006',14.0),('doc_025',12.5),
            ('doc_035',11.0),('doc_016',9.5),('doc_026',8.0),('doc_045',6.5),
            ('doc_036',5.0),('doc_046',3.5),('doc_010',2.5),('doc_001',1.8),
            ('doc_020',1.2),('doc_030',0.8)],
    'q04': [('doc_008',15.8),('doc_009',14.2),('doc_018',12.5),('doc_028',11.0),
            ('doc_038',9.5),('doc_048',8.0),('doc_019',6.5),('doc_029',5.0),
            ('doc_039',3.5),('doc_049',2.5),('doc_010',1.8),('doc_020',1.2),
            ('doc_030',0.8),('doc_040',0.5)],
    'q05': [('doc_006',16.2),('doc_016',14.8),('doc_001',13.2),('doc_026',11.8),
            ('doc_036',10.5),('doc_011',9.0),('doc_021',7.5),('doc_046',6.0),
            ('doc_031',4.5),('doc_041',3.2),('doc_002',2.2),('doc_012',1.5),
            ('doc_022',1.0),('doc_032',0.5)],
    'q06': [('doc_003',15.0),('doc_013',13.5),('doc_023',12.0),('doc_033',10.5),
            ('doc_043',9.0),('doc_004',7.5),('doc_014',6.0),('doc_024',4.5),
            ('doc_034',3.2),('doc_044',2.0),('doc_005',1.2),('doc_015',0.8),
            ('doc_025',0.5),('doc_035',0.2)],
    'q07': [('doc_010',14.5),('doc_020',13.0),('doc_030',11.5),('doc_002',10.0),
            ('doc_040',8.5),('doc_050',7.0),('doc_012',5.5),('doc_022',4.0),
            ('doc_032',2.8),('doc_001',2.0),('doc_011',1.2),('doc_021',0.8),
            ('doc_031',0.5),('doc_041',0.2)],
    'q08': [('doc_007',15.2),('doc_017',13.8),('doc_027',12.2),('doc_008',10.8),
            ('doc_037',9.5),('doc_047',8.0),('doc_018',6.5),('doc_028',5.0),
            ('doc_038',3.5),('doc_009',2.5),('doc_019',1.8),('doc_029',1.0),
            ('doc_039',0.5),('doc_049',0.2)]
}

# ---------------------------------------------------------------------------
# Write retrieval results in three different formats
# ---------------------------------------------------------------------------

# BM25 -> standard TREC run format
def write_trec_run(runs, sys_name, filepath):
    with open(filepath, 'w') as f:
        for qid in sorted(runs.keys()):
            for rank, (doc_id, score) in enumerate(runs[qid], 1):
                f.write(f'{qid} Q0 {doc_id} {rank} {score:.4f} {sys_name}\n')

write_trec_run(bm25_runs, 'bm25', '/app/data/systems/bm25.run')

# Dense -> gzipped JSON
dense_json = {}
for qid in sorted(dense_runs.keys()):
    dense_json[qid] = [{'doc_id': did, 'score': score} for did, score in dense_runs[qid]]

with gzip.open('/app/data/systems/dense.json.gz', 'wt') as f:
    json.dump(dense_json, f, indent=2)

# Sparse -> CSV with headers
with open('/app/data/systems/sparse.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['query_id', 'doc_id', 'rank', 'score', 'system'])
    for qid in sorted(sparse_runs.keys()):
        for rank, (doc_id, score) in enumerate(sparse_runs[qid], 1):
            writer.writerow([qid, doc_id, rank, f'{score:.4f}', 'sparse'])

print("Data generation complete.")
