"""Verify Parquet analytics cache and query results against SQLite ground truth."""


import pytest
import json
import os
import glob
import sqlite3
from datetime import datetime
from statistics import median
from collections import defaultdict
import pyarrow.parquet as pq

DB_PATH = '/app/archive.db'
ANALYTICS_DIR = '/app/analytics'
RESULTS_DIR = '/app/results'


# ---------------------------------------------------------------------------
# Parquet structure tests
# ---------------------------------------------------------------------------

class TestParquetStructure:
    def test_analytics_dir_exists(self):
        assert os.path.isdir(ANALYTICS_DIR), \
            f"{ANALYTICS_DIR} directory does not exist"

    def test_parquet_files_exist(self):
        pq_files = glob.glob(f'{ANALYTICS_DIR}/**/*.parquet', recursive=True)
        assert len(pq_files) > 0, "No Parquet files found under /app/analytics/"

    def test_year_partitioning_exists(self):
        year_dirs = glob.glob(f'{ANALYTICS_DIR}/**/year=*', recursive=True)
        assert len(year_dirs) >= 3, \
            "Expected Hive-style year partitioning with at least 3 year directories"

    def test_results_dir_exists(self):
        assert os.path.isdir(RESULTS_DIR), \
            f"{RESULTS_DIR} directory does not exist"

    def test_all_result_files_exist(self):
        for i in range(1, 6):
            path = f'{RESULTS_DIR}/q{i}.json'
            assert os.path.exists(path), f"Missing result file: {path}"


# ---------------------------------------------------------------------------
# Parquet metadata tests
# ---------------------------------------------------------------------------

class TestParquetMetadata:
    def test_snappy_compression(self):
        """Every column chunk in every Parquet file must use Snappy compression."""
        pq_files = glob.glob(f'{ANALYTICS_DIR}/**/*.parquet', recursive=True)
        assert len(pq_files) > 0, "No Parquet files to check"
        for path in pq_files:
            pf = pq.ParquetFile(path)
            md = pf.metadata
            for rg_idx in range(md.num_row_groups):
                rg = md.row_group(rg_idx)
                for col_idx in range(rg.num_columns):
                    col = rg.column(col_idx)
                    assert col.compression == 'SNAPPY', \
                        f"{path}: column {col.path_in_schema} uses " \
                        f"{col.compression}, expected SNAPPY"

    def test_dictionary_encoding_low_cardinality(self):
        """At least 3 distinct string columns must use dictionary encoding."""
        pq_files = glob.glob(f'{ANALYTICS_DIR}/**/*.parquet', recursive=True)
        assert len(pq_files) > 0
        dict_encoded_cols = set()
        for path in pq_files:
            pf = pq.ParquetFile(path)
            md = pf.metadata
            for rg_idx in range(md.num_row_groups):
                rg = md.row_group(rg_idx)
                for col_idx in range(rg.num_columns):
                    col = rg.column(col_idx)
                    enc_repr = repr(col.encodings).upper()
                    if 'DICT' in enc_repr:
                        dict_encoded_cols.add(col.path_in_schema)
        assert len(dict_encoded_cols) >= 3, \
            f"Expected >=3 dictionary-encoded columns, found: {dict_encoded_cols}"

    def test_column_statistics_enabled(self):
        """Every Parquet file must have column statistics for predicate pushdown."""
        pq_files = glob.glob(f'{ANALYTICS_DIR}/**/*.parquet', recursive=True)
        assert len(pq_files) > 0
        for path in pq_files:
            pf = pq.ParquetFile(path)
            md = pf.metadata
            for rg_idx in range(md.num_row_groups):
                rg = md.row_group(rg_idx)
                has_stats = any(
                    rg.column(c).is_stats_set
                    for c in range(rg.num_columns)
                )
                assert has_stats, \
                    f"{path}: row group {rg_idx} has no column statistics"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load_result(n):
    with open(f'{RESULTS_DIR}/q{n}.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Q1: Thread Response Times
# ---------------------------------------------------------------------------

class TestQ1ResponseTimes:
    @pytest.fixture(autouse=True)
    def compute_expected(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT conversation_id, sent_at FROM messages "
            "ORDER BY conversation_id, sent_at"
        ).fetchall()
        conn.close()

        convs = defaultdict(list)
        for cid, sat in rows:
            convs[cid].append(datetime.strptime(sat, '%Y-%m-%d %H:%M:%S'))

        cat_stats = defaultdict(lambda: {'count': 0, 'total_len': 0,
                                         'total_med': 0.0})
        for cid, times in convs.items():
            if len(times) < 3:
                continue
            times.sort()
            gaps = [(times[i + 1] - times[i]).total_seconds() / 60.0
                    for i in range(len(times) - 1)]
            med = median(gaps)
            if med < 60:
                cat = 'fast'
            elif med < 1440:
                cat = 'medium'
            else:
                cat = 'slow'
            cat_stats[cat]['count'] += 1
            cat_stats[cat]['total_len'] += len(times)
            cat_stats[cat]['total_med'] += med

        self.expected = []
        for cat in sorted(cat_stats):
            d = cat_stats[cat]
            self.expected.append({
                'category': cat,
                'thread_count': d['count'],
                'avg_thread_length': d['total_len'] / d['count'],
                'avg_median_response_min': d['total_med'] / d['count'],
            })

    def test_q1_category_count(self):
        actual = _load_result(1)
        assert len(actual) == len(self.expected), \
            f"Expected {len(self.expected)} categories, got {len(actual)}"

    def test_q1_values(self):
        actual = _load_result(1)
        actual_sorted = sorted(actual, key=lambda x: x['category'])
        for exp, act in zip(self.expected, actual_sorted):
            assert act['category'] == exp['category']
            assert act['thread_count'] == exp['thread_count'], \
                f"thread_count mismatch for {exp['category']}"
            assert act['avg_thread_length'] == pytest.approx(
                exp['avg_thread_length'], rel=0.01)
            assert act['avg_median_response_min'] == pytest.approx(
                exp['avg_median_response_min'], rel=0.01)


# ---------------------------------------------------------------------------
# Q2: Sender Influence via PageRank
# ---------------------------------------------------------------------------

class TestQ2PageRank:
    @pytest.fixture(autouse=True)
    def compute_expected(self):
        conn = sqlite3.connect(DB_PATH)

        # Build weighted directed edge list: sender -> to-recipient
        edge_rows = conn.execute("""
            SELECT p_s.email_address AS sender,
                   p_r.email_address AS recipient,
                   COUNT(*) AS weight
            FROM messages m
            JOIN participants p_s ON m.sender_id = p_s.id
            JOIN message_recipients mr ON m.id = mr.message_id
            JOIN participants p_r ON mr.participant_id = p_r.id
            WHERE mr.recipient_type = 'to'
            GROUP BY p_s.email_address, p_r.email_address
        """).fetchall()

        # Additional metrics
        msgs_sent_rows = conn.execute("""
            SELECT p.email_address, COUNT(DISTINCT m.id)
            FROM messages m JOIN participants p ON m.sender_id = p.id
            GROUP BY p.email_address
        """).fetchall()

        msgs_recv_rows = conn.execute("""
            SELECT p.email_address, COUNT(DISTINCT mr.message_id)
            FROM message_recipients mr
            JOIN participants p ON mr.participant_id = p.id
            WHERE mr.recipient_type = 'to'
            GROUP BY p.email_address
        """).fetchall()

        out_deg_rows = conn.execute("""
            SELECT p_s.email_address, COUNT(DISTINCT p_r.email_address)
            FROM messages m
            JOIN participants p_s ON m.sender_id = p_s.id
            JOIN message_recipients mr ON m.id = mr.message_id
            JOIN participants p_r ON mr.participant_id = p_r.id
            WHERE mr.recipient_type = 'to'
            GROUP BY p_s.email_address
        """).fetchall()

        in_deg_rows = conn.execute("""
            SELECT p_r.email_address, COUNT(DISTINCT p_s.email_address)
            FROM messages m
            JOIN participants p_s ON m.sender_id = p_s.id
            JOIN message_recipients mr ON m.id = mr.message_id
            JOIN participants p_r ON mr.participant_id = p_r.id
            WHERE mr.recipient_type = 'to'
            GROUP BY p_r.email_address
        """).fetchall()

        conn.close()

        # Build graph
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

        # Power iteration PageRank
        n = len(nodes)
        damping = 0.85
        pr = {node: 1.0 / n for node in nodes}

        for _ in range(100):
            dangling_sum = sum(
                pr[node] for node in nodes
                if out_weight.get(node, 0) == 0
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

        # Build lookup dicts
        msgs_sent = dict(msgs_sent_rows)
        msgs_recv = dict(msgs_recv_rows)
        out_deg = dict(out_deg_rows)
        in_deg = dict(in_deg_rows)

        results = []
        for email in nodes:
            results.append({
                'email': email,
                'pagerank_score': pr[email],
                'messages_sent': msgs_sent.get(email, 0),
                'messages_received': msgs_recv.get(email, 0),
                'out_degree': out_deg.get(email, 0),
                'in_degree': in_deg.get(email, 0),
            })

        results.sort(key=lambda x: (-x['pagerank_score'], x['email']))
        self.expected = results[:20]

    def test_q2_count(self):
        actual = _load_result(2)
        assert len(actual) == 20, f"Expected 20 entries, got {len(actual)}"

    def test_q2_ranking(self):
        actual = _load_result(2)
        for i, (exp, act) in enumerate(zip(self.expected, actual)):
            assert act['email'] == exp['email'], \
                f"Rank {i}: expected {exp['email']}, got {act['email']}"

    def test_q2_pagerank_scores(self):
        actual = _load_result(2)
        for exp, act in zip(self.expected, actual):
            assert act['pagerank_score'] == pytest.approx(
                exp['pagerank_score'], abs=1e-6), \
                f"pagerank_score mismatch for {exp['email']}"

    def test_q2_metrics(self):
        actual = _load_result(2)
        for exp, act in zip(self.expected, actual):
            assert act['messages_sent'] == exp['messages_sent'], \
                f"messages_sent mismatch for {exp['email']}"
            assert act['messages_received'] == exp['messages_received'], \
                f"messages_received mismatch for {exp['email']}"
            assert act['out_degree'] == exp['out_degree'], \
                f"out_degree mismatch for {exp['email']}"
            assert act['in_degree'] == exp['in_degree'], \
                f"in_degree mismatch for {exp['email']}"


# ---------------------------------------------------------------------------
# Q3: Label Co-occurrence
# ---------------------------------------------------------------------------

class TestQ3LabelCooccurrence:
    @pytest.fixture(autouse=True)
    def compute_expected(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT ml.message_id, l.name "
            "FROM message_labels ml JOIN labels l ON ml.label_id = l.id"
        ).fetchall()
        conn.close()

        msg_labels = defaultdict(set)
        label_msgs = defaultdict(set)
        for mid, lname in rows:
            msg_labels[mid].add(lname)
            label_msgs[lname].add(mid)

        pair_counts = defaultdict(int)
        for mid, labels in msg_labels.items():
            if len(labels) < 2:
                continue
            sl = sorted(labels)
            for i in range(len(sl)):
                for j in range(i + 1, len(sl)):
                    pair_counts[(sl[i], sl[j])] += 1

        results = []
        for (la, lb), cnt in pair_counts.items():
            union_sz = len(label_msgs[la] | label_msgs[lb])
            results.append({
                'label_a': la,
                'label_b': lb,
                'co_occurrence_count': cnt,
                'jaccard_similarity': cnt / union_sz if union_sz else 0,
            })

        results.sort(key=lambda x: (-x['co_occurrence_count'],
                                     x['label_a'], x['label_b']))
        self.expected = results[:20]

    def test_q3_count(self):
        actual = _load_result(3)
        assert len(actual) == len(self.expected)

    def test_q3_values(self):
        actual = _load_result(3)
        for exp, act in zip(self.expected, actual):
            assert act['label_a'] == exp['label_a']
            assert act['label_b'] == exp['label_b']
            assert act['co_occurrence_count'] == exp['co_occurrence_count']
            assert act['jaccard_similarity'] == pytest.approx(
                exp['jaccard_similarity'], rel=0.01)


# ---------------------------------------------------------------------------
# Q4: Communication Burstiness
# ---------------------------------------------------------------------------

class TestQ4Burstiness:
    @pytest.fixture(autouse=True)
    def compute_expected(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT p.email_address, m.sent_at
            FROM messages m
            JOIN participants p ON m.sender_id = p.id
            ORDER BY p.email_address, m.sent_at
        """).fetchall()
        conn.close()

        sender_times = defaultdict(list)
        for email, sent_at in rows:
            sender_times[email].append(
                datetime.strptime(sent_at, '%Y-%m-%d %H:%M:%S'))

        cat_stats = defaultdict(lambda: {
            'count': 0, 'total_b': 0.0, 'total_msgs': 0
        })

        for email, times in sender_times.items():
            if len(times) < 15:
                continue
            times.sort()
            gaps = [(times[i + 1] - times[i]).total_seconds() / 3600.0
                    for i in range(len(times) - 1)]

            n = len(gaps)
            mean_g = sum(gaps) / n
            if mean_g == 0:
                continue
            variance = sum((g - mean_g) ** 2 for g in gaps) / n
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

        self.expected = []
        for cat in sorted(cat_stats):
            d = cat_stats[cat]
            self.expected.append({
                'category': cat,
                'sender_count': d['count'],
                'avg_burstiness': d['total_b'] / d['count'],
                'avg_messages_per_sender': d['total_msgs'] / d['count'],
            })

    def test_q4_category_count(self):
        actual = _load_result(4)
        assert len(actual) == len(self.expected), \
            f"Expected {len(self.expected)} categories, got {len(actual)}"

    def test_q4_values(self):
        actual = _load_result(4)
        actual_sorted = sorted(actual, key=lambda x: x['category'])
        for exp, act in zip(self.expected, actual_sorted):
            assert act['category'] == exp['category']
            assert act['sender_count'] == exp['sender_count'], \
                f"sender_count mismatch for {exp['category']}"
            assert act['avg_burstiness'] == pytest.approx(
                exp['avg_burstiness'], rel=0.02)
            assert act['avg_messages_per_sender'] == pytest.approx(
                exp['avg_messages_per_sender'], rel=0.01)


# ---------------------------------------------------------------------------
# Q5: Attachments by Domain
# ---------------------------------------------------------------------------

class TestQ5AttachmentsByDomain:
    @pytest.fixture(autouse=True)
    def compute_expected(self):
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT p.domain, a.message_id, a.mime_type, a.size "
            "FROM attachments a "
            "JOIN messages m ON a.message_id = m.id "
            "JOIN participants p ON m.sender_id = p.id"
        ).fetchall()
        conn.close()

        dom = defaultdict(lambda: {
            'messages': set(), 'count': 0,
            'mimes': set(), 'total_bytes': 0, 'sizes': []
        })
        for domain, mid, mime, size in rows:
            dom[domain]['messages'].add(mid)
            dom[domain]['count'] += 1
            dom[domain]['mimes'].add(mime)
            dom[domain]['total_bytes'] += size
            dom[domain]['sizes'].append(size)

        results = []
        for domain, d in dom.items():
            results.append({
                'sender_domain': domain,
                'total_messages_with_attachments': len(d['messages']),
                'total_attachments': d['count'],
                'distinct_mime_types': len(d['mimes']),
                'avg_attachment_size_bytes': sum(d['sizes']) / len(d['sizes']),
                'total_attachment_bytes': d['total_bytes'],
            })
        results.sort(key=lambda x: (-x['total_attachments'],
                                     x['sender_domain']))
        self.expected = results

    def test_q5_count(self):
        actual = _load_result(5)
        assert len(actual) == len(self.expected), \
            f"Expected {len(self.expected)} domains, got {len(actual)}"

    def test_q5_values(self):
        actual = _load_result(5)
        for exp, act in zip(self.expected, actual):
            assert act['sender_domain'] == exp['sender_domain']
            assert act['total_messages_with_attachments'] == \
                exp['total_messages_with_attachments']
            assert act['total_attachments'] == exp['total_attachments']
            assert act['distinct_mime_types'] == exp['distinct_mime_types']
            assert act['avg_attachment_size_bytes'] == pytest.approx(
                exp['avg_attachment_size_bytes'], rel=0.01)
            assert act['total_attachment_bytes'] == exp['total_attachment_bytes']
