
"""
Reference evaluator and audit verification for BioASQ evaluation forensics.
Independently computes correct metrics and verifies the agent's audit report,
bootstrap confidence intervals, and SQL analytical views.
"""

import json
import math
import os
import glob
import sqlite3
import statistics
import pytest
import numpy as np

GOLDEN_PATH = "/app/data/golden.json"
SUBMISSIONS_DIR = "/app/data/submissions"
AUDIT_PATH = "/app/audit.json"
HISTORICAL_DB = "/app/data/historical.db"
TOLERANCE = 1e-4
EPSILON = 1e-5
BOOT_TOLERANCE = 0.15
PROB_TOLERANCE = 0.05

# ─── Reference Implementation (CORRECT) ─────────────────────────────────────


def load_json(path):
    with open(path) as f:
        return json.load(f)


def question_index(questions):
    return {q["id"]: q for q in questions}


def compute_ap(submitted_docs, golden_docs):
    golden_set = set(golden_docs)
    n_relevant = len(golden_set)
    if n_relevant == 0:
        return 0.0
    denominator = min(n_relevant, 10)
    cumulative = 0
    ap_sum = 0.0
    for rank, doc in enumerate(submitted_docs[:10], start=1):
        if doc in golden_set:
            cumulative += 1
            ap_sum += cumulative / rank
    return ap_sum / denominator


def ref_document_retrieval(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    aps = []
    for qid in gidx:
        golden_docs = gidx[qid].get("documents", [])
        submitted_docs = sidx.get(qid, {}).get("documents", [])
        aps.append(compute_ap(submitted_docs, golden_docs))
    n = len(aps)
    map_score = sum(aps) / n if n > 0 else 0.0
    # CORRECT: use natural log
    log_sum = sum(math.log(max(ap, EPSILON)) for ap in aps)
    gmap = math.exp(log_sum / n) if n > 0 else 0.0
    return map_score, gmap


def ref_yesno(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    yesno_qs = {qid: gq for qid, gq in gidx.items() if gq["type"] == "yesno"}
    correct = 0
    total = 0
    tp = {"yes": 0, "no": 0}
    fp = {"yes": 0, "no": 0}
    fn = {"yes": 0, "no": 0}
    for qid, gq in yesno_qs.items():
        gold = gq["exact_answer"].strip().lower()
        sq = sidx.get(qid, {})
        pred_raw = sq.get("exact_answer", "")
        pred = pred_raw.strip().lower() if isinstance(pred_raw, str) else ""
        total += 1
        if pred == gold:
            correct += 1
            tp[gold] += 1
        else:
            if pred in ("yes", "no"):
                fp[pred] += 1
            fn[gold] += 1
    accuracy = correct / total if total > 0 else 0.0
    f1s = []
    for cls in ("yes", "no"):
        p = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
        r = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        f1s.append(f1)
    macro_f1 = sum(f1s) / len(f1s)
    return accuracy, macro_f1


def factoid_match(candidate, golden_answer_groups):
    cand_lower = str(candidate).strip().lower()
    for group in golden_answer_groups:
        for synonym in group:
            if cand_lower == synonym.strip().lower():
                return True
    return False


def ref_factoid(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    factoid_qs = {qid: gq for qid, gq in gidx.items() if gq["type"] == "factoid"}
    strict_correct = 0
    lenient_correct = 0
    rr_sum = 0.0
    total = len(factoid_qs)
    for qid, gq in factoid_qs.items():
        golden_ea = gq["exact_answer"]
        sq = sidx.get(qid, {})
        candidates = sq.get("exact_answer", [])
        if not isinstance(candidates, list):
            candidates = [candidates]
        candidates = candidates[:5]
        if not candidates:
            # CORRECT: count as 0 reciprocal rank, still in denominator
            continue
        if factoid_match(candidates[0], golden_ea):
            strict_correct += 1
        for i, cand in enumerate(candidates):
            if factoid_match(cand, golden_ea):
                lenient_correct += 1
                rr_sum += 1.0 / (i + 1)
                break
    strict_acc = strict_correct / total if total > 0 else 0.0
    lenient_acc = lenient_correct / total if total > 0 else 0.0
    # CORRECT: divide by total factoid questions, not just answered ones
    mrr = rr_sum / total if total > 0 else 0.0
    return strict_acc, lenient_acc, mrr


def ref_list(golden_qs, system_qs):
    gidx = question_index(golden_qs)
    sidx = question_index(system_qs)
    list_qs = {qid: gq for qid, gq in gidx.items() if gq["type"] == "list"}
    precisions = []
    recalls = []
    f1s = []
    for qid, gq in list_qs.items():
        golden_items = gq["exact_answer"]
        sq = sidx.get(qid, {})
        submitted = sq.get("exact_answer", [])
        if not isinstance(submitted, list):
            submitted = [submitted]
        n_submitted = len(submitted)
        n_golden = len(golden_items)
        # Count correct submitted items
        n_correct = 0
        for item in submitted:
            item_lower = str(item).strip().lower()
            for golden_group in golden_items:
                if any(item_lower == syn.strip().lower() for syn in golden_group):
                    n_correct += 1
                    break
        # CORRECT: check ALL synonyms for recall (not just the first)
        n_found = 0
        for golden_group in golden_items:
            syns_lower = {syn.strip().lower() for syn in golden_group}
            if any(str(s).strip().lower() in syns_lower for s in submitted):
                n_found += 1
        precision = n_correct / n_submitted if n_submitted > 0 else 0.0
        recall = n_found / n_golden if n_golden > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    mean_p = sum(precisions) / len(precisions) if precisions else 0.0
    mean_r = sum(recalls) / len(recalls) if recalls else 0.0
    mean_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    return mean_p, mean_r, mean_f1


def ref_ranking(system_results):
    systems = list(system_results.keys())
    metric_keys = [
        ("yesno", "macro_f1"),
        ("factoid", "mrr"),
        ("list", "mean_f1"),
    ]
    rank_sums = {s: 0.0 for s in systems}
    for category, metric in metric_keys:
        values = [(s, system_results[s][category][metric]) for s in systems]
        values.sort(key=lambda x: -x[1])
        i = 0
        while i < len(values):
            j = i
            while j < len(values) and abs(values[j][1] - values[i][1]) < 1e-10:
                j += 1
            avg_rank = sum(range(i + 1, j + 1)) / (j - i)
            for k in range(i, j):
                rank_sums[values[k][0]] += avg_rank
            i = j
    n_metrics = len(metric_keys)
    avg_ranks = {s: rank_sums[s] / n_metrics for s in systems}
    ranking = sorted(systems, key=lambda s: avg_ranks[s])
    return [
        {"rank": i + 1, "system": s, "avg_rank": avg_ranks[s]}
        for i, s in enumerate(ranking)
    ]


def compute_all_expected():
    golden = load_json(GOLDEN_PATH)
    submission_files = sorted(glob.glob(os.path.join(SUBMISSIONS_DIR, "system_*.json")))
    submissions = {}
    for path in submission_files:
        data = load_json(path)
        name = data.get(
            "system_name",
            os.path.basename(path).replace(".json", "").replace("system_", ""),
        )
        submissions[name] = data

    system_results = {}
    for sys_name, sub_data in submissions.items():
        sys_qs = sub_data["questions"]
        map_score, gmap = ref_document_retrieval(golden["questions"], sys_qs)
        accuracy, macro_f1 = ref_yesno(golden["questions"], sys_qs)
        strict_acc, lenient_acc, mrr = ref_factoid(golden["questions"], sys_qs)
        mean_p, mean_r, mean_f1 = ref_list(golden["questions"], sys_qs)
        system_results[sys_name] = {
            "document_retrieval": {"map": map_score, "gmap": gmap},
            "yesno": {"accuracy": accuracy, "macro_f1": macro_f1},
            "factoid": {
                "strict_accuracy": strict_acc,
                "lenient_accuracy": lenient_acc,
                "mrr": mrr,
            },
            "list": {
                "mean_precision": mean_p,
                "mean_recall": mean_r,
                "mean_f1": mean_f1,
            },
        }

    ranking = ref_ranking(system_results)
    return {"systems": system_results, "ranking": ranking}


def compute_expected_anomalies(corrected_systems):
    """Compute expected historical anomalies using rounds 1-3 as baseline."""
    if not os.path.exists(HISTORICAL_DB):
        return []

    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()

    # Systems with data in original rounds (1-3)
    c.execute("""
        SELECT DISTINCT s.system_name FROM systems s
        JOIN results r ON s.system_id = r.system_id
        WHERE r.round_id <= 3
    """)
    historical_systems = {row[0] for row in c.fetchall()}

    ranking_metrics = ["yesno_macro_f1", "factoid_mrr", "list_mean_f1"]
    metric_map = {
        "yesno_macro_f1": ("yesno", "macro_f1"),
        "factoid_mrr": ("factoid", "mrr"),
        "list_mean_f1": ("list", "mean_f1"),
    }

    anomalies = []
    for sys_name in corrected_systems:
        if sys_name not in historical_systems:
            continue
        for metric_name in ranking_metrics:
            c.execute("""
                SELECT r.metric_value FROM results r
                JOIN systems s ON r.system_id = s.system_id
                WHERE s.system_name = ? AND r.metric_name = ?
                AND r.round_id <= 3
                ORDER BY r.round_id
            """, (sys_name, metric_name))
            hist_values = [row[0] for row in c.fetchall()]
            if len(hist_values) < 2:
                continue
            hist_mean = statistics.mean(hist_values)
            hist_std = statistics.stdev(hist_values)
            if hist_std < 1e-10:
                continue
            cat, met = metric_map[metric_name]
            current_val = corrected_systems[sys_name][cat][met]
            z_score = (current_val - hist_mean) / hist_std
            if abs(z_score) > 2.0:
                anomalies.append({
                    "system": sys_name,
                    "metric": metric_name,
                    "current_value": current_val,
                    "historical_mean": hist_mean,
                    "z_score": z_score,
                })

    conn.close()
    return anomalies


# ─── Bootstrap Reference Implementation ────────────────────────────────────


def _boot_yesno_f1(gidx, sidx, sample_qids):
    """Compute yesno macro_F1 from a bootstrap sample of question IDs."""
    tp = {"yes": 0, "no": 0}
    fp = {"yes": 0, "no": 0}
    fn = {"yes": 0, "no": 0}
    for qid in sample_qids:
        gq = gidx[qid]
        gold = gq["exact_answer"].strip().lower()
        sq = sidx.get(qid, {})
        pred_raw = sq.get("exact_answer", "")
        pred = pred_raw.strip().lower() if isinstance(pred_raw, str) else ""
        if pred == gold:
            tp[gold] += 1
        else:
            if pred in ("yes", "no"):
                fp[pred] += 1
            fn[gold] += 1
    f1s = []
    for cls in ("yes", "no"):
        p = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
        r = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        f1s.append(f1)
    return sum(f1s) / len(f1s)


def _boot_factoid_mrr(gidx, sidx, sample_qids):
    """Compute factoid MRR from a bootstrap sample of question IDs."""
    rr_sum = 0.0
    total = len(sample_qids)
    for qid in sample_qids:
        gq = gidx[qid]
        golden_ea = gq["exact_answer"]
        sq = sidx.get(qid, {})
        candidates = sq.get("exact_answer", [])
        if not isinstance(candidates, list):
            candidates = [candidates]
        candidates = candidates[:5]
        for i, cand in enumerate(candidates):
            if factoid_match(cand, golden_ea):
                rr_sum += 1.0 / (i + 1)
                break
    return rr_sum / total if total > 0 else 0.0


def _boot_list_f1(gidx, sidx, sample_qids):
    """Compute list mean_F1 from a bootstrap sample of question IDs."""
    f1s = []
    for qid in sample_qids:
        gq = gidx[qid]
        golden_items = gq["exact_answer"]
        sq = sidx.get(qid, {})
        submitted = sq.get("exact_answer", [])
        if not isinstance(submitted, list):
            submitted = [submitted]
        n_submitted = len(submitted)
        n_golden = len(golden_items)
        n_correct = 0
        for item in submitted:
            item_lower = str(item).strip().lower()
            for golden_group in golden_items:
                if any(item_lower == syn.strip().lower() for syn in golden_group):
                    n_correct += 1
                    break
        n_found = 0
        for golden_group in golden_items:
            syns_lower = {syn.strip().lower() for syn in golden_group}
            if any(str(s).strip().lower() in syns_lower for s in submitted):
                n_found += 1
        precision = n_correct / n_submitted if n_submitted > 0 else 0.0
        recall = n_found / n_golden if n_golden > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1s.append(f1)
    return sum(f1s) / len(f1s) if f1s else 0.0


def compute_expected_bootstrap():
    """Reference bootstrap CI computation with same seed and algorithm."""
    golden = load_json(GOLDEN_PATH)
    golden_qs = golden["questions"]
    gidx = question_index(golden_qs)

    submission_files = sorted(glob.glob(os.path.join(SUBMISSIONS_DIR, "system_*.json")))
    submissions = {}
    for path in submission_files:
        data = load_json(path)
        name = data.get("system_name",
                        os.path.basename(path).replace(".json", "").replace("system_", ""))
        submissions[name] = data

    sub_indices = {name: question_index(sub["questions"])
                   for name, sub in submissions.items()}

    yesno_qids = sorted([qid for qid, q in gidx.items() if q["type"] == "yesno"])
    factoid_qids = sorted([qid for qid, q in gidx.items() if q["type"] == "factoid"])
    list_qids = sorted([qid for qid, q in gidx.items() if q["type"] == "list"])

    systems = sorted(submissions.keys())
    B = 1000
    rng = np.random.default_rng(42)

    rank_records = {s: [] for s in systems}

    for _ in range(B):
        yn_sample = rng.choice(yesno_qids, size=len(yesno_qids), replace=True).tolist()
        f_sample = rng.choice(factoid_qids, size=len(factoid_qids), replace=True).tolist()
        l_sample = rng.choice(list_qids, size=len(list_qids), replace=True).tolist()

        boot_metrics = {}
        for s in systems:
            sidx = sub_indices[s]
            yn_f1 = _boot_yesno_f1(gidx, sidx, yn_sample)
            f_mrr = _boot_factoid_mrr(gidx, sidx, f_sample)
            l_f1 = _boot_list_f1(gidx, sidx, l_sample)
            boot_metrics[s] = {"yesno_macro_f1": yn_f1,
                               "factoid_mrr": f_mrr,
                               "list_mean_f1": l_f1}

        # Compute ranking from resampled metrics
        metric_keys_b = ["yesno_macro_f1", "factoid_mrr", "list_mean_f1"]
        rank_sums = {s: 0.0 for s in systems}
        for mk in metric_keys_b:
            values = [(s, boot_metrics[s][mk]) for s in systems]
            values.sort(key=lambda x: -x[1])
            i = 0
            while i < len(values):
                j = i
                while j < len(values) and abs(values[j][1] - values[i][1]) < 1e-10:
                    j += 1
                avg_r = sum(range(i + 1, j + 1)) / (j - i)
                for k in range(i, j):
                    rank_sums[values[k][0]] += avg_r
                i = j
        avg_ranks = {s: rank_sums[s] / 3 for s in systems}
        ranked = sorted(systems, key=lambda s: avg_ranks[s])

        # Assign final ranks with ties
        i = 0
        while i < len(ranked):
            j = i
            while j < len(ranked) and abs(avg_ranks[ranked[j]] - avg_ranks[ranked[i]]) < 1e-10:
                j += 1
            tied_rank = sum(range(i + 1, j + 1)) / (j - i)
            for k in range(i, j):
                rank_records[ranked[k]].append(tied_rank)
            i = j

    result = {}
    for s in systems:
        ranks = np.array(rank_records[s])
        result[s] = {
            "rank_ci_lower": float(np.percentile(ranks, 2.5)),
            "rank_ci_upper": float(np.percentile(ranks, 97.5)),
            "prob_rank_1": float(np.mean(ranks == 1.0)),
        }
    return result


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def expected():
    return compute_all_expected()


@pytest.fixture(scope="module")
def expected_anomalies(expected):
    return compute_expected_anomalies(expected["systems"])


@pytest.fixture(scope="module")
def expected_bootstrap():
    return compute_expected_bootstrap()


@pytest.fixture(scope="module")
def actual():
    assert os.path.exists(AUDIT_PATH), f"Audit file not found at {AUDIT_PATH}"
    with open(AUDIT_PATH) as f:
        return json.load(f)


# ─── Structure Tests ────────────────────────────────────────────────────────


def test_audit_file_exists():
    assert os.path.exists(AUDIT_PATH), f"Expected audit report at {AUDIT_PATH}"


def test_audit_structure(actual):
    assert "corrected_results" in actual, "Missing 'corrected_results'"
    assert "corrected_ranking" in actual, "Missing 'corrected_ranking'"
    assert "bugs" in actual, "Missing 'bugs'"
    assert "historical_anomalies" in actual, "Missing 'historical_anomalies'"
    assert "bootstrap_analysis" in actual, "Missing 'bootstrap_analysis'"


def test_all_systems_present(actual, expected):
    for sys_name in expected["systems"]:
        assert sys_name in actual["corrected_results"], f"Missing system: {sys_name}"


def test_system_metrics_structure(actual):
    for sys_name, metrics in actual["corrected_results"].items():
        assert "document_retrieval" in metrics, f"{sys_name}: missing document_retrieval"
        assert "map" in metrics["document_retrieval"], f"{sys_name}: missing map"
        assert "gmap" in metrics["document_retrieval"], f"{sys_name}: missing gmap"
        assert "yesno" in metrics, f"{sys_name}: missing yesno"
        assert "factoid" in metrics, f"{sys_name}: missing factoid"
        assert "list" in metrics, f"{sys_name}: missing list"


# ─── Corrected Metric Tests ─────────────────────────────────────────────────


SYSTEMS = ["alpha", "beta", "gamma", "delta", "epsilon"]


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_map(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["document_retrieval"]["map"]
    act = actual["corrected_results"][sys_name]["document_retrieval"]["map"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} MAP: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_gmap(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["document_retrieval"]["gmap"]
    act = actual["corrected_results"][sys_name]["document_retrieval"]["gmap"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} GMAP: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_yesno_accuracy(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["yesno"]["accuracy"]
    act = actual["corrected_results"][sys_name]["yesno"]["accuracy"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} YN accuracy: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_yesno_macro_f1(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["yesno"]["macro_f1"]
    act = actual["corrected_results"][sys_name]["yesno"]["macro_f1"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} YN macro F1: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_factoid_strict_accuracy(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["factoid"]["strict_accuracy"]
    act = actual["corrected_results"][sys_name]["factoid"]["strict_accuracy"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} factoid strict: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_factoid_lenient_accuracy(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["factoid"]["lenient_accuracy"]
    act = actual["corrected_results"][sys_name]["factoid"]["lenient_accuracy"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} factoid lenient: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_factoid_mrr(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["factoid"]["mrr"]
    act = actual["corrected_results"][sys_name]["factoid"]["mrr"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} factoid MRR: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_list_precision(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["list"]["mean_precision"]
    act = actual["corrected_results"][sys_name]["list"]["mean_precision"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} list precision: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_list_recall(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["list"]["mean_recall"]
    act = actual["corrected_results"][sys_name]["list"]["mean_recall"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} list recall: expected {exp:.6f}, got {act:.6f}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_list_f1(actual, expected, sys_name):
    exp = expected["systems"][sys_name]["list"]["mean_f1"]
    act = actual["corrected_results"][sys_name]["list"]["mean_f1"]
    assert abs(act - exp) < TOLERANCE, f"{sys_name} list F1: expected {exp:.6f}, got {act:.6f}"


# ─── Ranking Tests ───────────────────────────────────────────────────────────


def test_ranking_length(actual):
    assert len(actual["corrected_ranking"]) == 5


def test_ranking_order(actual, expected):
    exp_order = [r["system"] for r in expected["ranking"]]
    act_order = [r["system"] for r in actual["corrected_ranking"]]
    assert act_order == exp_order, f"Ranking order: expected {exp_order}, got {act_order}"


def test_ranking_avg_ranks(actual, expected):
    for exp_r, act_r in zip(expected["ranking"], actual["corrected_ranking"]):
        assert act_r["system"] == exp_r["system"]
        assert abs(act_r["avg_rank"] - exp_r["avg_rank"]) < TOLERANCE, (
            f"{act_r['system']} avg_rank: expected {exp_r['avg_rank']:.4f}, got {act_r['avg_rank']:.4f}"
        )


# ─── Bug Tests ───────────────────────────────────────────────────────────────


def test_bugs_count(actual):
    assert len(actual["bugs"]) == 3, f"Expected 3 bugs, got {len(actual['bugs'])}"


def test_bugs_have_required_fields(actual):
    for bug in actual["bugs"]:
        assert "id" in bug, "Bug missing 'id'"
        assert "description" in bug, "Bug missing 'description'"
        assert "affected_metric" in bug, "Bug missing 'affected_metric'"
        assert "ranking_impact" in bug, "Bug missing 'ranking_impact'"


def test_bugs_ranking_impact_distribution(actual):
    """Exactly one bug should NOT affect ranking (GMAP), two should."""
    impacts = [b["ranking_impact"] for b in actual["bugs"]]
    assert impacts.count(False) == 1, (
        f"Expected exactly 1 bug with ranking_impact=false, got {impacts.count(False)}"
    )
    assert impacts.count(True) == 2, (
        f"Expected exactly 2 bugs with ranking_impact=true, got {impacts.count(True)}"
    )


def test_bugs_cover_key_areas(actual):
    """Bug descriptions should collectively mention GMAP/log, MRR/factoid, and list/recall/synonym."""
    all_text = " ".join(
        (b.get("description", "") + " " + b.get("affected_metric", "")).lower()
        for b in actual["bugs"]
    )
    has_gmap = any(kw in all_text for kw in [
        "gmap", "geometric mean", "log10", "log_10", "logarithm", "log base", "natural log"
    ])
    has_mrr = any(kw in all_text for kw in [
        "mrr", "reciprocal rank", "denominator", "unanswered", "factoid"
    ])
    has_list = any(kw in all_text for kw in [
        "synonym", "recall", "list", "first synonym", "primary"
    ])
    assert has_gmap, "No bug mentions GMAP/logarithm issue"
    assert has_mrr, "No bug mentions MRR/factoid issue"
    assert has_list, "No bug mentions list recall/synonym issue"


def test_gmap_bug_has_no_ranking_impact(actual):
    """The bug about GMAP/log should have ranking_impact=false."""
    gmap_keywords = ["gmap", "geometric mean", "log10", "log_10", "logarithm", "log base", "natural log"]
    for bug in actual["bugs"]:
        desc = (bug.get("description", "") + " " + bug.get("affected_metric", "")).lower()
        if any(kw in desc for kw in gmap_keywords):
            assert bug["ranking_impact"] is False, (
                f"GMAP bug should have ranking_impact=false, got {bug['ranking_impact']}"
            )
            return
    pytest.fail("Could not identify GMAP bug")


# ─── Historical Anomaly Tests ────────────────────────────────────────────────


def test_historical_anomalies_structure(actual):
    for anomaly in actual["historical_anomalies"]:
        assert "system" in anomaly
        assert "metric" in anomaly
        assert "current_value" in anomaly
        assert "historical_mean" in anomaly
        assert "z_score" in anomaly


def test_historical_beta_mrr_anomaly(actual):
    """Beta's factoid_mrr should be flagged as anomalous."""
    beta_mrr_anomalies = [
        a for a in actual["historical_anomalies"]
        if a["system"] == "beta" and "mrr" in a["metric"].lower()
    ]
    assert len(beta_mrr_anomalies) >= 1, (
        "Expected beta factoid_mrr to be flagged as anomalous"
    )
    a = beta_mrr_anomalies[0]
    assert abs(a["z_score"]) > 2.0, f"Beta MRR z-score should exceed 2.0, got {a['z_score']}"


def test_no_false_alpha_anomalies(actual):
    """Alpha should have no anomalies (all z-scores < 2)."""
    alpha_anomalies = [
        a for a in actual["historical_anomalies"]
        if a["system"] == "alpha"
        and a["metric"] in ("yesno_macro_f1", "factoid_mrr", "list_mean_f1")
    ]
    assert len(alpha_anomalies) == 0, (
        f"Alpha should have no anomalies, got {alpha_anomalies}"
    )


def test_no_false_gamma_anomalies(actual):
    """Gamma should have no anomalies with corrected values."""
    gamma_anomalies = [
        a for a in actual["historical_anomalies"]
        if a["system"] == "gamma"
        and a["metric"] in ("yesno_macro_f1", "factoid_mrr", "list_mean_f1")
    ]
    assert len(gamma_anomalies) == 0, (
        f"Gamma should have no anomalies with corrected values, got {gamma_anomalies}"
    )


# ─── Reference Sanity Checks ────────────────────────────────────────────────


def test_reference_beta_perfect_yesno(expected):
    """Beta answers all yes/no correctly."""
    beta_acc = expected["systems"]["beta"]["yesno"]["accuracy"]
    assert abs(beta_acc - 1.0) < TOLERANCE, f"Beta YN acc should be 1.0, got {beta_acc}"


def test_reference_gamma_mrr(expected):
    """Gamma skips 2 factoid questions, correct MRR = 2/4 = 0.5."""
    gamma_mrr = expected["systems"]["gamma"]["factoid"]["mrr"]
    assert abs(gamma_mrr - 0.5) < TOLERANCE, f"Gamma MRR should be 0.5, got {gamma_mrr}"


def test_reference_epsilon_mrr(expected):
    """Epsilon skips 2 factoid questions, correct MRR should reflect that."""
    epsilon_mrr = expected["systems"]["epsilon"]["factoid"]["mrr"]
    assert epsilon_mrr < 1.0, f"Epsilon MRR should be < 1.0, got {epsilon_mrr}"


def test_reference_beta_perfect_list(expected):
    """Beta uses synonyms correctly; with correct recall, list F1 should be 1.0."""
    beta_f1 = expected["systems"]["beta"]["list"]["mean_f1"]
    assert abs(beta_f1 - 1.0) < TOLERANCE, f"Beta list F1 should be 1.0, got {beta_f1}"


def test_reference_delta_list(expected):
    """Delta uses some synonyms; correct list F1 should be 1.0."""
    delta_f1 = expected["systems"]["delta"]["list"]["mean_f1"]
    assert abs(delta_f1 - 1.0) < TOLERANCE, f"Delta list F1 should be 1.0, got {delta_f1}"


def test_reference_ranking_first(expected):
    """Beta should rank first overall."""
    assert expected["ranking"][0]["system"] == "beta", (
        f"Expected beta first, got {expected['ranking'][0]['system']}"
    )


# ─── Bootstrap CI Tests ─────────────────────────────────────────────────────


def test_bootstrap_exists(actual):
    assert "bootstrap_analysis" in actual, "Missing 'bootstrap_analysis'"


def test_bootstrap_all_systems(actual):
    for s in SYSTEMS:
        assert s in actual["bootstrap_analysis"], f"Missing bootstrap for {s}"


def test_bootstrap_structure(actual):
    for s in SYSTEMS:
        ba = actual["bootstrap_analysis"][s]
        assert "rank_ci_lower" in ba, f"{s}: missing rank_ci_lower"
        assert "rank_ci_upper" in ba, f"{s}: missing rank_ci_upper"
        assert "prob_rank_1" in ba, f"{s}: missing prob_rank_1"


def test_bootstrap_ci_range(actual):
    for s in SYSTEMS:
        ba = actual["bootstrap_analysis"][s]
        assert 1.0 <= ba["rank_ci_lower"] <= 5.0, (
            f"{s}: rank_ci_lower {ba['rank_ci_lower']} out of [1,5]"
        )
        assert 1.0 <= ba["rank_ci_upper"] <= 5.0, (
            f"{s}: rank_ci_upper {ba['rank_ci_upper']} out of [1,5]"
        )


def test_bootstrap_ci_consistency(actual):
    for s in SYSTEMS:
        ba = actual["bootstrap_analysis"][s]
        assert ba["rank_ci_lower"] <= ba["rank_ci_upper"], (
            f"{s}: CI lower {ba['rank_ci_lower']} > upper {ba['rank_ci_upper']}"
        )


def test_bootstrap_prob_range(actual):
    for s in SYSTEMS:
        ba = actual["bootstrap_analysis"][s]
        assert 0.0 <= ba["prob_rank_1"] <= 1.0, (
            f"{s}: prob_rank_1 {ba['prob_rank_1']} out of [0,1]"
        )


def test_bootstrap_prob_sum(actual):
    total = sum(actual["bootstrap_analysis"][s]["prob_rank_1"] for s in SYSTEMS)
    assert abs(total - 1.0) < 0.1, f"prob_rank_1 sum should be ~1.0, got {total}"


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_bootstrap_ci_lower(actual, expected_bootstrap, sys_name):
    exp = expected_bootstrap[sys_name]["rank_ci_lower"]
    act = actual["bootstrap_analysis"][sys_name]["rank_ci_lower"]
    assert abs(act - exp) < BOOT_TOLERANCE, (
        f"{sys_name} rank_ci_lower: expected {exp:.4f}, got {act:.4f}"
    )


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_bootstrap_ci_upper(actual, expected_bootstrap, sys_name):
    exp = expected_bootstrap[sys_name]["rank_ci_upper"]
    act = actual["bootstrap_analysis"][sys_name]["rank_ci_upper"]
    assert abs(act - exp) < BOOT_TOLERANCE, (
        f"{sys_name} rank_ci_upper: expected {exp:.4f}, got {act:.4f}"
    )


@pytest.mark.parametrize("sys_name", SYSTEMS)
def test_bootstrap_prob_rank_1(actual, expected_bootstrap, sys_name):
    exp = expected_bootstrap[sys_name]["prob_rank_1"]
    act = actual["bootstrap_analysis"][sys_name]["prob_rank_1"]
    assert abs(act - exp) < PROB_TOLERANCE, (
        f"{sys_name} prob_rank_1: expected {exp:.4f}, got {act:.4f}"
    )


def test_bootstrap_beta_dominance(actual):
    """Beta should have the highest prob_rank_1."""
    beta_prob = actual["bootstrap_analysis"]["beta"]["prob_rank_1"]
    for s in SYSTEMS:
        if s != "beta":
            assert beta_prob >= actual["bootstrap_analysis"][s]["prob_rank_1"], (
                f"Beta should dominate but {s} has higher prob_rank_1"
            )


# ─── SQL View Tests ──────────────────────────────────────────────────────────


def test_round_4_inserted():
    """Round 4 should exist in the historical DB."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("SELECT round_name FROM rounds WHERE round_id = 4")
    row = c.fetchone()
    conn.close()
    assert row is not None, "Round 4 not found in historical DB"


def test_new_systems_registered():
    """Delta and epsilon should be in the systems table."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("SELECT system_name FROM systems")
    names = {row[0] for row in c.fetchall()}
    conn.close()
    assert "delta" in names, "System 'delta' not registered"
    assert "epsilon" in names, "System 'epsilon' not registered"


def test_round_4_results_count():
    """Round 4 should have results for all 5 systems across 5 metrics."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM results WHERE round_id = 4")
    count = c.fetchone()[0]
    conn.close()
    assert count == 25, f"Expected 25 round-4 results (5 systems x 5 metrics), got {count}"


def test_v_metric_trends_exists():
    """The v_metric_trends view should exist."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='v_metric_trends'")
    row = c.fetchone()
    conn.close()
    assert row is not None, "View v_metric_trends not found"


def test_v_metric_trends_columns():
    """v_metric_trends should have prev_value and delta columns."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("SELECT * FROM v_metric_trends LIMIT 1")
    columns = [desc[0] for desc in c.description]
    conn.close()
    assert "prev_value" in columns, f"View missing 'prev_value' column, got {columns}"
    assert "delta" in columns, f"View missing 'delta' column, got {columns}"


def test_v_metric_trends_lag_values():
    """Check LAG values for alpha yesno_macro_f1 across rounds."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("""
        SELECT round_id, metric_value, prev_value, delta
        FROM v_metric_trends
        WHERE system_name = 'alpha' AND metric_name = 'yesno_macro_f1'
        ORDER BY round_id
    """)
    rows = c.fetchall()
    conn.close()
    assert len(rows) >= 3, f"Expected >= 3 rows for alpha yesno_macro_f1, got {len(rows)}"
    # Round 1: prev_value should be NULL
    assert rows[0][2] is None, f"Round 1 prev_value should be NULL, got {rows[0][2]}"
    # Round 2: prev_value should be round 1 value (0.72)
    assert abs(rows[1][2] - 0.72) < TOLERANCE, (
        f"Round 2 prev_value should be 0.72, got {rows[1][2]}"
    )
    # Round 2: delta should be 0.78 - 0.72 = 0.06
    assert abs(rows[1][3] - 0.06) < TOLERANCE, (
        f"Round 2 delta should be 0.06, got {rows[1][3]}"
    )


def test_v_current_anomalies_exists():
    """The v_current_anomalies view should exist."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='v_current_anomalies'")
    row = c.fetchone()
    conn.close()
    assert row is not None, "View v_current_anomalies not found"


def test_v_current_anomalies_columns():
    """v_current_anomalies should have expected columns."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM v_current_anomalies LIMIT 0")
        columns = [desc[0] for desc in c.description]
    except Exception:
        columns = []
    conn.close()
    for col in ["system_name", "metric_name", "current_value", "hist_mean", "hist_std", "z_score"]:
        assert col in columns, f"View missing '{col}' column, got {columns}"


def test_v_current_anomalies_beta_mrr():
    """Beta's factoid_mrr z-score from the view should be anomalous."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    try:
        c.execute("""
            SELECT z_score FROM v_current_anomalies
            WHERE system_name = 'beta' AND metric_name = 'factoid_mrr'
        """)
        row = c.fetchone()
    except Exception:
        row = None
    conn.close()
    assert row is not None, "Beta factoid_mrr not in v_current_anomalies"
    assert abs(row[0]) > 2.0, f"Beta factoid_mrr z-score should be > 2.0, got {row[0]}"


def test_view_anomalies_consistency(actual):
    """Anomalies in v_current_anomalies should be consistent with audit.json."""
    conn = sqlite3.connect(HISTORICAL_DB)
    c = conn.cursor()
    try:
        c.execute("""
            SELECT system_name, metric_name, z_score
            FROM v_current_anomalies
            WHERE ABS(z_score) > 2.0
        """)
        view_anomalous = {(row[0], row[1]) for row in c.fetchall()}
    except Exception:
        view_anomalous = set()
    conn.close()

    audit_anomalous = {(a["system"], a["metric"]) for a in actual["historical_anomalies"]}

    # Every audit anomaly for returning systems should appear in the view
    for key in audit_anomalous:
        sys_name, metric = key
        if sys_name in ("alpha", "beta", "gamma"):
            assert key in view_anomalous, (
                f"Audit anomaly {key} not flagged in v_current_anomalies"
            )
