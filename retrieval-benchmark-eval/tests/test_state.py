
import json
import math
import os
from collections import defaultdict

import pytest

REPORT_PATH = "/app/evaluation_report.json"
BENCH_DIR = "/app/data/benchmark"
METRICS = ["ndcg@10", "map@100", "mrr@10", "recall@100"]
SYSTEMS = ["system_alpha", "system_beta", "system_gamma"]
TOL = 1e-6


# ── reference implementation (correct parsing + correct metrics) ────────────


def _ld_qrels(p):
    q = {}
    with open(p) as f:
        for ln in f:
            c = ln.strip().split()
            if len(c) < 4:
                continue
            q[(c[0], c[2])] = int(c[3])
    return q


def _ld_run(p):
    r = defaultdict(list)
    with open(p) as f:
        for ln in f:
            c = ln.strip().split()
            if len(c) < 6:
                continue
            r[c[0]].append((c[2], int(c[3]), float(c[4])))
    for k in r:
        r[k].sort(key=lambda x: x[1])
    return dict(r)


def _ndcg(qr, rn, q, k=10):
    rl = rn.get(q, [])[:k]
    dcg = sum(
        (2 ** qr.get((q, d), 0) - 1) / math.log2(i + 2)
        for i, (d, _, _) in enumerate(rl)
    )
    iv = sorted([v for (qi, _), v in qr.items() if qi == q], reverse=True)[:k]
    idcg = sum((2 ** v - 1) / math.log2(i + 2) for i, v in enumerate(iv))
    return dcg / idcg if idcg > 0 else 0.0


def _ap(qr, rn, q, k=100):
    R = sum(1 for (qi, _), v in qr.items() if qi == q and v >= 1)
    if R == 0:
        return 0.0
    rl = rn.get(q, [])[:k]
    nr = 0
    sp = 0.0
    for i, (d, _, _) in enumerate(rl):
        if qr.get((q, d), 0) >= 1:
            nr += 1
            sp += nr / (i + 1)
    return sp / R


def _mrr(qr, rn, q, k=10):
    for i, (d, _, _) in enumerate(rn.get(q, [])[:k]):
        if qr.get((q, d), 0) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def _recall(qr, rn, q, k=100):
    R = sum(1 for (qi, _), v in qr.items() if qi == q and v >= 1)
    if R == 0:
        return 0.0
    return sum(1 for d, _, _ in rn.get(q, [])[:k] if qr.get((q, d), 0) >= 1) / R


def _task_metrics(qr, rn, qs):
    fn = {
        "ndcg@10": lambda q: _ndcg(qr, rn, q, 10),
        "map@100": lambda q: _ap(qr, rn, q, 100),
        "mrr@10": lambda q: _mrr(qr, rn, q, 10),
        "recall@100": lambda q: _recall(qr, rn, q, 100),
    }
    return {m: sum(f(q) for q in qs) / len(qs) for m, f in fn.items()}


def _build_ref():
    with open(os.path.join(BENCH_DIR, "tasks.json")) as f:
        meta = json.load(f)

    pt = {}
    dt = defaultdict(list)

    for tid in sorted(meta):
        dt[meta[tid]["domain"]].append(tid)
        td = os.path.join(BENCH_DIR, "tasks", tid)
        qr = _ld_qrels(os.path.join(td, "qrels.tsv"))
        qs = sorted(set(q for q, _ in qr))
        pt[tid] = {}
        for sn_short in ["alpha", "beta", "gamma"]:
            sn = f"system_{sn_short}"
            rp = os.path.join(td, f"run_{sn_short}.tsv")
            rn = _ld_run(rp) if os.path.exists(rp) else {}
            pt[tid][sn] = _task_metrics(qr, rn, qs)

    # Domain: macro-average over tasks
    pd = {}
    for dom in sorted(dt):
        pd[dom] = {}
        for sn in SYSTEMS:
            dm = defaultdict(list)
            for tid in dt[dom]:
                for m, v in pt[tid][sn].items():
                    dm[m].append(v)
            pd[dom][sn] = {m: sum(v) / len(v) for m, v in dm.items()}

    # Overall: macro-average over all tasks
    ov = {}
    for sn in SYSTEMS:
        om = defaultdict(list)
        for tid in sorted(meta):
            for m, v in pt[tid][sn].items():
                om[m].append(v)
        ov[sn] = {m: sum(v) / len(v) for m, v in om.items()}

    sr = sorted(SYSTEMS, key=lambda s: -ov[s]["ndcg@10"])

    return {
        "per_task": pt,
        "per_domain": pd,
        "overall": ov,
        "system_ranking": sr,
    }


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ref():
    return _build_ref()


# ── structural tests ────────────────────────────────────────────────────────


class TestStructure:
    def test_top_level_keys(self, report):
        for k in ["per_task", "per_domain", "overall", "system_ranking"]:
            assert k in report, f"Missing key: {k}"

    def test_task_ids(self, report, ref):
        for tid in ref["per_task"]:
            assert tid in report["per_task"], f"Missing task {tid}"

    def test_system_keys(self, report, ref):
        for tid in ref["per_task"]:
            for sn in SYSTEMS:
                assert sn in report["per_task"][tid], f"Missing {sn} in {tid}"

    def test_metric_keys(self, report, ref):
        for tid in ref["per_task"]:
            for sn in SYSTEMS:
                for m in METRICS:
                    assert m in report["per_task"][tid][sn], (
                        f"Missing {m} for {sn}/{tid}"
                    )

    def test_domain_keys(self, report, ref):
        for dom in ref["per_domain"]:
            assert dom in report["per_domain"], f"Missing domain {dom}"

    def test_overall_system_keys(self, report):
        for sn in SYSTEMS:
            assert sn in report["overall"], f"Missing {sn} in overall"


# ── per-task metric accuracy ────────────────────────────────────────────────


class TestPerTaskMetrics:
    @pytest.mark.parametrize("metric", METRICS)
    def test_system_alpha(self, report, ref, metric):
        for tid in ref["per_task"]:
            exp = ref["per_task"][tid]["system_alpha"][metric]
            act = report["per_task"][tid]["system_alpha"][metric]
            assert abs(act - exp) < TOL, (
                f"{tid}/system_alpha/{metric}: expected {exp:.8f}, got {act}"
            )

    @pytest.mark.parametrize("metric", METRICS)
    def test_system_beta(self, report, ref, metric):
        for tid in ref["per_task"]:
            exp = ref["per_task"][tid]["system_beta"][metric]
            act = report["per_task"][tid]["system_beta"][metric]
            assert abs(act - exp) < TOL, (
                f"{tid}/system_beta/{metric}: expected {exp:.8f}, got {act}"
            )

    @pytest.mark.parametrize("metric", METRICS)
    def test_system_gamma(self, report, ref, metric):
        for tid in ref["per_task"]:
            exp = ref["per_task"][tid]["system_gamma"][metric]
            act = report["per_task"][tid]["system_gamma"][metric]
            assert abs(act - exp) < TOL, (
                f"{tid}/system_gamma/{metric}: expected {exp:.8f}, got {act}"
            )


# ── domain aggregation ──────────────────────────────────────────────────────


class TestDomainMetrics:
    @pytest.mark.parametrize("metric", METRICS)
    def test_domain_values(self, report, ref, metric):
        for dom in ref["per_domain"]:
            for sn in SYSTEMS:
                exp = ref["per_domain"][dom][sn][metric]
                act = report["per_domain"][dom][sn][metric]
                assert abs(act - exp) < TOL, (
                    f"{dom}/{sn}/{metric}: expected {exp:.8f}, got {act}"
                )


# ── overall aggregation ─────────────────────────────────────────────────────


class TestOverall:
    @pytest.mark.parametrize("metric", METRICS)
    def test_overall_values(self, report, ref, metric):
        for sn in SYSTEMS:
            exp = ref["overall"][sn][metric]
            act = report["overall"][sn][metric]
            assert abs(act - exp) < TOL, (
                f"overall/{sn}/{metric}: expected {exp:.8f}, got {act}"
            )


# ── system ranking ──────────────────────────────────────────────────────────


class TestSystemRanking:
    def test_ranking_order(self, report, ref):
        assert report["system_ranking"] == ref["system_ranking"], (
            f"System ranking mismatch:\n"
            f"  expected: {ref['system_ranking']}\n"
            f"  got: {report['system_ranking']}"
        )

    def test_ranking_descending_ndcg(self, report, ref):
        ranking = ref["system_ranking"]
        ndcgs = [ref["overall"][s]["ndcg@10"] for s in ranking]
        for i in range(len(ndcgs) - 1):
            assert ndcgs[i] >= ndcgs[i + 1] - TOL, (
                f"Ranking not descending at {i}: {ndcgs[i]:.6f} < {ndcgs[i+1]:.6f}"
            )
