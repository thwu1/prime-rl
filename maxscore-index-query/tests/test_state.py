"""Verification tests for search index evaluation pipeline."""


import struct
import json
import math
import os
import sqlite3
import pytest


def read_uint32s(path):
    """Read entire binary file as array of uint32 LE values."""
    with open(path, 'rb') as f:
        data = f.read()
    count = len(data) // 4
    return list(struct.unpack('<' + 'I' * count, data))


def vbyte_decode_stream(data):
    """Decode all VByte-encoded integers from a bytes object."""
    values = []
    offset = 0
    while offset < len(data):
        value = 0
        shift = 0
        while True:
            byte = data[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if byte & 0x80:
                break
            shift += 7
        values.append(value)
    return values


def load_index():
    """Load the binary inverted index independently."""
    base = '/app/index/collection'

    # Sizes
    raw = read_uint32s(base + '.sizes')
    num_docs = raw[0]
    sizes = raw[1:num_docs + 1]

    # Docs
    raw = read_uint32s(base + '.docs')
    assert raw[0] == 1 and raw[1] == num_docs
    posting_docs = []
    i = 2
    while i < len(raw):
        length = raw[i]
        i += 1
        posting_docs.append(raw[i:i + length])
        i += length

    # Freqs (VByte encoded)
    with open(base + '.freqs', 'rb') as f:
        freq_data = f.read()
    vbytes = vbyte_decode_stream(freq_data)
    posting_freqs = []
    j = 0
    while j < len(vbytes):
        length = vbytes[j]
        j += 1
        posting_freqs.append(vbytes[j:j + length])
        j += length

    # Terms from SQLite
    db = sqlite3.connect('/app/metadata.db')
    cur = db.cursor()
    cur.execute('SELECT term_id, term FROM terms ORDER BY term_id')
    term_to_id = {}
    for tid, term in cur.fetchall():
        term_to_id[term] = tid
    db.close()

    return num_docs, sizes, posting_docs, posting_freqs, term_to_id


def load_config():
    """Load BM25 config from SQLite."""
    db = sqlite3.connect('/app/metadata.db')
    cur = db.cursor()
    cur.execute('SELECT key, value FROM config')
    config = {}
    for key, value in cur.fetchall():
        try:
            config[key] = float(value)
        except ValueError:
            config[key] = value
    db.close()
    return config


def load_doc_mapping():
    """Load doc_id -> external_id mapping from SQLite."""
    db = sqlite3.connect('/app/metadata.db')
    cur = db.cursor()
    cur.execute('SELECT doc_id, external_id FROM documents ORDER BY doc_id')
    mapping = {}
    for did, ext_id in cur.fetchall():
        mapping[did] = ext_id
    db.close()
    return mapping


def load_qrels():
    """Load qrels file."""
    qrels = {}
    with open('/app/qrels/eval.qrels', 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 4:
                qid, _, docno, rel = parts
                if qid not in qrels:
                    qrels[qid] = {}
                qrels[qid][docno] = int(rel)
    return qrels


def bm25(tf, df, dl, avgdl, N, k1, b):
    """Reference BM25 scoring."""
    idf = math.log((N + 1.0) / (df + 0.5))
    tf_norm = (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))
    return idf * tf_norm


def exhaustive_topk(query_tids, posting_docs, posting_freqs,
                    sizes, avgdl, N, k1, b, top_k):
    """Compute ground-truth top-k via exhaustive BM25 scoring."""
    scores = {}
    for tid in query_tids:
        docs = posting_docs[tid]
        freqs = posting_freqs[tid]
        df = len(docs)
        for i in range(len(docs)):
            d = docs[i]
            s = bm25(freqs[i], df, sizes[d], avgdl, N, k1, b)
            scores[d] = scores.get(d, 0.0) + s
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]


def compute_ndcg(ranked_docs, qrels_for_query, k=10):
    """Compute NDCG@k matching trec_eval formulation."""
    dcg = 0.0
    for i in range(min(k, len(ranked_docs))):
        docno = ranked_docs[i]
        rel = qrels_for_query.get(docno, 0)
        dcg += rel / math.log2(i + 2)

    ideal_rels = sorted(qrels_for_query.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels):
        idcg += rel / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def compute_ap(ranked_docs, qrels_for_query, k=10):
    """Compute Average Precision at k matching trec_eval formulation."""
    num_rel = 0
    sum_prec = 0.0
    total_rel = sum(1 for r in qrels_for_query.values() if r > 0)

    for i in range(min(k, len(ranked_docs))):
        docno = ranked_docs[i]
        if qrels_for_query.get(docno, 0) > 0:
            num_rel += 1
            sum_prec += num_rel / (i + 1)

    return sum_prec / total_rel if total_rel > 0 else 0.0


# Fixtures

@pytest.fixture(scope='module')
def index_data():
    return load_index()


@pytest.fixture(scope='module')
def config():
    return load_config()


@pytest.fixture(scope='module')
def doc_mapping():
    return load_doc_mapping()


@pytest.fixture(scope='module')
def qrels():
    return load_qrels()


@pytest.fixture(scope='module')
def queries(index_data):
    _, _, _, _, term_to_id = index_data
    qs = []
    with open('/app/queries.txt', 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            qid, terms_str = line.split(':', 1)
            tnames = terms_str.strip().split()
            tids = [term_to_id[t] for t in tnames if t in term_to_id]
            qs.append((qid, tids))
    return qs


@pytest.fixture(scope='module')
def agent_output():
    assert os.path.exists('/app/results.json'), \
        "Agent must produce /app/results.json"
    with open('/app/results.json', 'r') as f:
        return json.load(f)


# Tests

class TestOutputFiles:
    def test_results_json_exists(self):
        assert os.path.exists('/app/results.json')

    def test_results_run_exists(self):
        assert os.path.exists('/app/results.run')

    def test_has_index_stats(self, agent_output):
        assert 'index_stats' in agent_output
        for key in ('num_docs', 'num_terms', 'avg_doc_len', 'total_postings'):
            assert key in agent_output['index_stats'], \
                "Missing index_stats.%s" % key

    def test_has_queries(self, agent_output):
        assert 'queries' in agent_output
        assert isinstance(agent_output['queries'], list)
        assert len(agent_output['queries']) > 0

    def test_has_eval_metrics(self, agent_output):
        assert 'eval_metrics' in agent_output
        for key in ('ndcg_cut_10', 'map'):
            assert key in agent_output['eval_metrics'], \
                "Missing eval_metrics.%s" % key


class TestIndexStats:
    def test_num_docs(self, agent_output, index_data):
        assert agent_output['index_stats']['num_docs'] == index_data[0]

    def test_num_terms(self, agent_output, index_data):
        assert agent_output['index_stats']['num_terms'] == len(index_data[2])

    def test_avg_doc_len(self, agent_output, index_data):
        sizes = index_data[1]
        expected = sum(sizes) / len(sizes)
        assert abs(agent_output['index_stats']['avg_doc_len'] - expected) < 0.5

    def test_total_postings(self, agent_output, index_data):
        expected = sum(len(pl) for pl in index_data[2])
        assert agent_output['index_stats']['total_postings'] == expected


class TestTrecRunFormat:
    def test_run_file_structure(self, doc_mapping):
        valid_ext_ids = set(doc_mapping.values())
        with open('/app/results.run', 'r') as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) > 0, "Run file is empty"
        for line in lines:
            parts = line.strip().split()
            assert len(parts) == 6, \
                "TREC run line must have 6 fields: %s" % line.strip()
            qid, q0, docno, rank, score, run_id = parts
            assert q0 == 'Q0', \
                "Second field must be 'Q0': %s" % line.strip()
            assert docno in valid_ext_ids, \
                "Unknown external doc ID: %s" % docno
            int(rank)
            float(score)

    def test_run_covers_all_queries(self, queries):
        qids_in_run = set()
        with open('/app/results.run', 'r') as f:
            for line in f:
                parts = line.strip().split()
                if parts:
                    qids_in_run.add(parts[0])
        expected_qids = set(qid for qid, _ in queries)
        assert qids_in_run == expected_qids, \
            "Run file missing queries: %s" % (expected_qids - qids_in_run)


class TestQueryCount:
    def test_num_queries(self, agent_output, queries):
        assert len(agent_output['queries']) == len(queries)

    def test_query_ids(self, agent_output, queries):
        for i, (qid, _) in enumerate(queries):
            assert agent_output['queries'][i]['qid'] == qid


class TestQueryCorrectness:
    """Verify top-k results match exhaustive BM25 for each query."""

    @pytest.mark.parametrize("qi", range(8))
    def test_topk_docids(self, qi, agent_output, queries,
                         index_data, config):
        num_docs, sizes, posting_docs, posting_freqs, _ = index_data
        avgdl = sum(sizes) / len(sizes)
        qid, tids = queries[qi]
        expected = exhaustive_topk(
            tids, posting_docs, posting_freqs, sizes, avgdl,
            num_docs, config['k1'], config['b'], int(config['top_k'])
        )
        agent_results = agent_output['queries'][qi]['results']
        assert len(agent_results) == len(expected), \
            "Q%s: expected %d results, got %d" % (
                qid, len(expected), len(agent_results))
        for j, (exp_did, _) in enumerate(expected):
            assert agent_results[j]['docid'] == exp_did, \
                "%s rank %d: expected doc %d, got %d" % (
                    qid, j, exp_did, agent_results[j]['docid'])

    @pytest.mark.parametrize("qi", range(8))
    def test_topk_scores(self, qi, agent_output, queries,
                         index_data, config):
        num_docs, sizes, posting_docs, posting_freqs, _ = index_data
        avgdl = sum(sizes) / len(sizes)
        qid, tids = queries[qi]
        expected = exhaustive_topk(
            tids, posting_docs, posting_freqs, sizes, avgdl,
            num_docs, config['k1'], config['b'], int(config['top_k'])
        )
        agent_results = agent_output['queries'][qi]['results']
        for j, (_, exp_score) in enumerate(expected):
            agent_score = agent_results[j]['score']
            assert abs(agent_score - exp_score) < 1e-3, \
                "%s rank %d: expected %.6f, got %.6f" % (
                    qid, j, exp_score, agent_score)


class TestPruningBehavior:
    def test_num_scored_positive(self, agent_output):
        for q in agent_output['queries']:
            assert 'num_scored' in q, \
                "Missing num_scored for %s" % q['qid']
            assert q['num_scored'] > 0

    def test_num_scored_within_bounds(self, agent_output, queries,
                                     index_data):
        posting_docs = index_data[2]
        for i, (qid, tids) in enumerate(queries):
            all_docs = set()
            for tid in tids:
                all_docs.update(posting_docs[tid])
            assert agent_output['queries'][i]['num_scored'] <= len(all_docs), \
                "%s: scored more docs than candidates" % qid

    def test_multiterm_pruning_effective(self, agent_output, queries,
                                        index_data):
        """For queries with 3+ terms, num_scored must be < total candidates."""
        posting_docs = index_data[2]
        for i, (qid, tids) in enumerate(queries):
            if len(tids) < 3:
                continue
            all_docs = set()
            for tid in tids:
                all_docs.update(posting_docs[tid])
            total = len(all_docs)
            scored = agent_output['queries'][i]['num_scored']
            assert scored < total, \
                "%s: num_scored=%d must be < %d for %d-term query" % (
                    qid, scored, total, len(tids))


class TestEvalMetrics:
    def test_ndcg_within_range(self, agent_output):
        ndcg = agent_output['eval_metrics']['ndcg_cut_10']
        assert 0.0 <= ndcg <= 1.0, \
            "NDCG@10 must be in [0, 1], got %s" % ndcg

    def test_map_within_range(self, agent_output):
        map_val = agent_output['eval_metrics']['map']
        assert 0.0 <= map_val <= 1.0, \
            "MAP must be in [0, 1], got %s" % map_val

    def test_ndcg_correctness(self, agent_output, queries, index_data,
                              config, doc_mapping, qrels):
        """Verify NDCG@10 matches independently computed value."""
        num_docs, sizes, posting_docs, posting_freqs, _ = index_data
        avgdl = sum(sizes) / len(sizes)

        ndcg_sum = 0.0
        n_queries = 0
        for qi, (qid, tids) in enumerate(queries):
            top_results = exhaustive_topk(
                tids, posting_docs, posting_freqs, sizes, avgdl,
                num_docs, config['k1'], config['b'], int(config['top_k'])
            )
            ranked_docs = [doc_mapping[did] for did, _ in top_results]
            q_qrels = qrels.get(qid, {})
            ndcg_sum += compute_ndcg(ranked_docs, q_qrels, k=10)
            n_queries += 1

        expected_ndcg = ndcg_sum / n_queries
        agent_ndcg = agent_output['eval_metrics']['ndcg_cut_10']
        assert abs(agent_ndcg - expected_ndcg) < 0.03, \
            "NDCG@10: expected ~%.4f, got %.4f" % (
                expected_ndcg, agent_ndcg)

    def test_map_correctness(self, agent_output, queries, index_data,
                             config, doc_mapping, qrels):
        """Verify MAP matches independently computed value."""
        num_docs, sizes, posting_docs, posting_freqs, _ = index_data
        avgdl = sum(sizes) / len(sizes)

        ap_sum = 0.0
        n_queries = 0
        for qi, (qid, tids) in enumerate(queries):
            top_results = exhaustive_topk(
                tids, posting_docs, posting_freqs, sizes, avgdl,
                num_docs, config['k1'], config['b'], int(config['top_k'])
            )
            ranked_docs = [doc_mapping[did] for did, _ in top_results]
            q_qrels = qrels.get(qid, {})
            ap_sum += compute_ap(ranked_docs, q_qrels, k=10)
            n_queries += 1

        expected_map = ap_sum / n_queries
        agent_map = agent_output['eval_metrics']['map']
        assert abs(agent_map - expected_map) < 0.03, \
            "MAP: expected ~%.4f, got %.4f" % (expected_map, agent_map)
