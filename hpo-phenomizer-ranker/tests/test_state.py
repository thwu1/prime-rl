
import subprocess
import sqlite3
import pytest

PIPELINE = "/app/pipeline/run_pipeline.sh"
SIMILARITY = "/app/pipeline/similarity.py"
DB_PATH = "/app/data/hpo.db"
TIMEOUT = 30


@pytest.fixture(scope="session", autouse=True)
def build_pipeline():
    """Run the full pipeline before any tests."""
    result = subprocess.run(
        ["bash", PIPELINE],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Pipeline failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def run_sim(args):
    """Run similarity.py CLI and return stdout."""
    result = subprocess.run(
        ["python3", SIMILARITY, "--db", DB_PATH] + args,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, (
        f"Command failed: similarity.py {' '.join(args)}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout.strip()


def parse_float(args):
    return float(run_sim(args))


# ---------------------------------------------------------------------------
# Database structure tests
# ---------------------------------------------------------------------------
class TestDatabaseStructure:
    """Verify the SQLite database has correct structure after pipeline run."""

    def test_alt_ids_table_populated(self):
        """alt_ids table must contain mappings from the ontology."""
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT alt_id, primary_id FROM alt_ids").fetchall()
        conn.close()
        alt_map = dict(rows)
        assert alt_map.get("HP:0005484") == "HP:0000252"
        assert alt_map.get("HP:0011097") == "HP:0001250"

    def test_alt_ids_not_stored_as_terms(self):
        """Alt_ids must not appear as standalone entries in terms table."""
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT COUNT(*) FROM terms WHERE id = 'HP:0005484'"
        ).fetchone()
        conn.close()
        assert row[0] == 0, "HP:0005484 should be in alt_ids, not terms"

    def test_ancestors_multiple_parents(self):
        """HP:0000252 has two parents; ancestors must include both paths."""
        conn = sqlite3.connect(DB_PATH)
        ancestors = {
            r[0]
            for r in conn.execute(
                "SELECT ancestor_id FROM ancestors WHERE term_id = 'HP:0000252'"
            ).fetchall()
        }
        conn.close()
        # From morphology path (HP:0002060 parent)
        assert "HP:0002060" in ancestors
        assert "HP:0012639" in ancestors
        # From head path (HP:0000234 parent)
        assert "HP:0000234" in ancestors
        assert "HP:0000152" in ancestors
        # Self
        assert "HP:0000252" in ancestors

    def test_no_not_annotations(self):
        """Annotations with Qualifier=NOT must be excluded."""
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM annotations WHERE qualifier = 'NOT'"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_no_non_phenotype_annotations(self):
        """Only Aspect=P annotations should be in the database."""
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute(
            "SELECT COUNT(*) FROM annotations WHERE aspect != 'P'"
        ).fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# IC tests
# ---------------------------------------------------------------------------
class TestInformationContent:

    def test_root_ic_is_zero(self):
        """HP:0000001 (All) — universal root, IC must be 0."""
        ic = parse_float(["ic", "HP:0000001"])
        assert abs(ic - 0.0) < 0.005

    def test_phenotypic_abnormality_ic_zero(self):
        """HP:0000118 — annotates all diseases, IC must be 0."""
        ic = parse_float(["ic", "HP:0000118"])
        assert abs(ic - 0.0) < 0.005

    def test_hypotonia_ic(self):
        """HP:0001290 (Generalized hypotonia) — single disease annotation."""
        ic = parse_float(["ic", "HP:0001290"])
        assert abs(ic - 2.302585) < 0.005

    def test_microcephaly_ic_with_alt_id(self):
        """HP:0000252 — must aggregate annotations using alt_id HP:0005484."""
        ic = parse_float(["ic", "HP:0000252"])
        assert abs(ic - 0.916291) < 0.005

    def test_macrocephaly_ic_not_qualifier(self):
        """HP:0000256 — one disease has NOT qualifier, must be excluded."""
        ic = parse_float(["ic", "HP:0000256"])
        assert abs(ic - 2.302585) < 0.005

    def test_seizure_ic_propagation(self):
        """HP:0001250 — direct plus propagated from child HP:0002197."""
        ic = parse_float(["ic", "HP:0001250"])
        assert abs(ic - 1.203973) < 0.005

    def test_generalized_seizure_ic(self):
        """HP:0002197 (Generalized-onset seizure)."""
        ic = parse_float(["ic", "HP:0002197"])
        assert abs(ic - 1.609438) < 0.005

    def test_nervous_system_physiology_ic(self):
        """HP:0012638 — broad propagation target."""
        ic = parse_float(["ic", "HP:0012638"])
        assert abs(ic - 0.356675) < 0.005

    def test_growth_abnormality_ic(self):
        """HP:0001507 — broad propagation target."""
        ic = parse_float(["ic", "HP:0001507"])
        assert abs(ic - 0.356675) < 0.005

    def test_cerebellar_hypoplasia_ic(self):
        """HP:0007360 (Aplasia/Hypoplasia of the cerebellum)."""
        ic = parse_float(["ic", "HP:0007360"])
        assert abs(ic - 1.609438) < 0.005

    def test_inheritance_mode_ic_zero(self):
        """HP:0000005 (Mode of inheritance) — no Aspect=P annotations."""
        ic = parse_float(["ic", "HP:0000005"])
        assert abs(ic - 0.0) < 0.005

    def test_autosomal_dominant_ic_zero(self):
        """HP:0000006 — only Aspect=I annotation, must not contribute IC."""
        ic = parse_float(["ic", "HP:0000006"])
        assert abs(ic - 0.0) < 0.005


# ---------------------------------------------------------------------------
# Resnik similarity tests
# ---------------------------------------------------------------------------
class TestResnik:
    def test_identical_terms(self):
        """Self-similarity equals IC of the term."""
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000252", "--method", "resnik"]
        )
        assert abs(score - 0.916291) < 0.005

    def test_microcephaly_vs_macrocephaly(self):
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000256", "--method", "resnik"]
        )
        assert abs(score - 0.693147) < 0.005

    def test_child_parent(self):
        """HP:0002197 vs HP:0001250 — child-parent pair."""
        score = parse_float(
            ["similarity", "HP:0002197", "HP:0001250", "--method", "resnik"]
        )
        assert abs(score - 1.203973) < 0.005

    def test_ataxia_vs_spasticity(self):
        """HP:0001251 vs HP:0001257 — sibling terms."""
        score = parse_float(
            ["similarity", "HP:0001251", "HP:0001257", "--method", "resnik"]
        )
        assert abs(score - 0.356675) < 0.005

    def test_microcephaly_vs_cerebral(self):
        """HP:0000252 vs HP:0002060 — parent-child in morphology branch."""
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0002060", "--method", "resnik"]
        )
        assert abs(score - 0.916291) < 0.005

    def test_cross_branch_distant(self):
        """HP:0001250 vs HP:0002209 — distant, across major branches."""
        score = parse_float(
            ["similarity", "HP:0001250", "HP:0002209", "--method", "resnik"]
        )
        assert score < 0.005

    def test_microcephaly_vs_cerebellar(self):
        """HP:0000252 vs HP:0007360 — requires correct multiple-parent traversal."""
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0007360", "--method", "resnik"]
        )
        assert abs(score - 0.510826) < 0.005


# ---------------------------------------------------------------------------
# Lin similarity tests
# ---------------------------------------------------------------------------
class TestLin:
    def test_microcephaly_vs_macrocephaly(self):
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000256", "--method", "lin"]
        )
        assert abs(score - 0.430677) < 0.005

    def test_identical_terms_lin(self):
        """Lin self-similarity must be 1.0."""
        score = parse_float(
            ["similarity", "HP:0001250", "HP:0001250", "--method", "lin"]
        )
        assert abs(score - 1.0) < 0.005

    def test_child_parent_lin(self):
        score = parse_float(
            ["similarity", "HP:0002197", "HP:0001250", "--method", "lin"]
        )
        assert abs(score - 0.855939) < 0.005


# ---------------------------------------------------------------------------
# JC similarity tests
# ---------------------------------------------------------------------------
class TestJC:
    def test_identical_terms(self):
        """JC self-similarity must be 1.0."""
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000252", "--method", "jc"]
        )
        assert abs(score - 1.0) < 0.005

    def test_ataxia_vs_spasticity(self):
        score = parse_float(
            ["similarity", "HP:0001251", "HP:0001257", "--method", "jc"]
        )
        assert abs(score - 0.415465) < 0.005

    def test_microcephaly_vs_macrocephaly_jc(self):
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000256", "--method", "jc"]
        )
        assert abs(score - 0.353013) < 0.005


# ---------------------------------------------------------------------------
# GraphIC similarity tests
# ---------------------------------------------------------------------------
class TestGraphIC:
    def test_identical_terms(self):
        """GraphIC self-similarity must be 1.0."""
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000252", "--method", "graphic"]
        )
        assert abs(score - 1.0) < 0.005

    def test_ataxia_vs_spasticity(self):
        score = parse_float(
            ["similarity", "HP:0001251", "HP:0001257", "--method", "graphic"]
        )
        assert abs(score - 0.251753) < 0.005

    def test_microcephaly_vs_macrocephaly_graphic(self):
        score = parse_float(
            ["similarity", "HP:0000252", "HP:0000256", "--method", "graphic"]
        )
        assert abs(score - 0.200917) < 0.005


# ---------------------------------------------------------------------------
# Set-level combiner / ranking tests
# ---------------------------------------------------------------------------
class TestSetCombiners:
    """Test disease ranking with query {HP:0001250, HP:0000252, HP:0001290}."""

    def _get_ranking(self, method, combiner):
        out = run_sim([
            "rank",
            "HP:0001250,HP:0000252,HP:0001290",
            "--method", method,
            "--combiner", combiner,
        ])
        rows = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            rows.append({
                "rank": int(parts[0]),
                "disease_id": parts[1],
                "disease_name": parts[2],
                "score": float(parts[3]),
            })
        return rows

    def test_funsimavg_top_disease(self):
        """Resnik+funSimAvg: OMIM:100100 should rank first."""
        rows = self._get_ranking("resnik", "funsimavg")
        top = rows[0]
        assert top["disease_id"] == "OMIM:100100"
        assert top["rank"] == 1
        assert abs(top["score"] - 1.404534) < 0.01

    def test_funsimavg_last_disease(self):
        """Lowest-ranking disease should have near-zero score."""
        rows = self._get_ranking("resnik", "funsimavg")
        last = rows[-1]
        assert last["rank"] == 10
        assert last["score"] < 0.01

    def test_funsimmax_top_disease(self):
        """Resnik+funSimMax: OMIM:100100 should rank first."""
        rows = self._get_ranking("resnik", "funsimmax")
        top = rows[0]
        assert top["disease_id"] == "OMIM:100100"
        assert abs(top["score"] - 1.474283) < 0.01

    def test_bma_top_disease(self):
        """Resnik+BMA: OMIM:100100 should rank first."""
        rows = self._get_ranking("resnik", "bma")
        top = rows[0]
        assert top["disease_id"] == "OMIM:100100"
        assert abs(top["score"] - 1.394570) < 0.01

    def test_ranking_has_all_diseases(self):
        """Output must include all 10 diseases."""
        rows = self._get_ranking("resnik", "funsimavg")
        assert len(rows) == 10

    def test_ranks_are_sequential(self):
        """Ranks must be 1..10."""
        rows = self._get_ranking("resnik", "funsimavg")
        ranks = [r["rank"] for r in rows]
        assert ranks == list(range(1, 11))

    def test_ranking_descending(self):
        """Scores must be in non-increasing order."""
        rows = self._get_ranking("resnik", "funsimavg")
        scores = [r["score"] for r in rows]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1] - 0.0001

    def test_graphic_bma_ranking_first(self):
        """GraphIC+BMA: OMIM:100100 should still rank first."""
        rows = self._get_ranking("graphic", "bma")
        assert rows[0]["disease_id"] == "OMIM:100100"


# ---------------------------------------------------------------------------
# Integration / edge-case tests
# ---------------------------------------------------------------------------
class TestIntegration:
    def test_alt_id_in_query(self):
        """Using alt_id HP:0005484 must give same IC as primary HP:0000252."""
        ic_primary = parse_float(["ic", "HP:0000252"])
        ic_alt = parse_float(["ic", "HP:0005484"])
        assert abs(ic_primary - ic_alt) < 0.005

    def test_alt_id_in_similarity(self):
        """Alt_id HP:0005484 must behave identically to HP:0000252."""
        s1 = parse_float(
            ["similarity", "HP:0005484", "HP:0000256", "--method", "resnik"]
        )
        s2 = parse_float(
            ["similarity", "HP:0000252", "HP:0000256", "--method", "resnik"]
        )
        assert abs(s1 - s2) < 0.005

    def test_symmetry_resnik(self):
        """Resnik similarity must be symmetric."""
        ab = parse_float(
            ["similarity", "HP:0001251", "HP:0000252", "--method", "resnik"]
        )
        ba = parse_float(
            ["similarity", "HP:0000252", "HP:0001251", "--method", "resnik"]
        )
        assert abs(ab - ba) < 0.001

    def test_symmetry_lin(self):
        """Lin similarity must be symmetric."""
        ab = parse_float(
            ["similarity", "HP:0001251", "HP:0000252", "--method", "lin"]
        )
        ba = parse_float(
            ["similarity", "HP:0000252", "HP:0001251", "--method", "lin"]
        )
        assert abs(ab - ba) < 0.001

    def test_symmetry_graphic(self):
        """GraphIC similarity must be symmetric."""
        ab = parse_float(
            ["similarity", "HP:0001290", "HP:0001257", "--method", "graphic"]
        )
        ba = parse_float(
            ["similarity", "HP:0001257", "HP:0001290", "--method", "graphic"]
        )
        assert abs(ab - ba) < 0.001

    def test_eye_phenotype_ranking(self):
        """Query with eye phenotypes should rank eye-related diseases high."""
        out = run_sim([
            "rank",
            "HP:0000518,HP:0000486",
            "--method", "resnik",
            "--combiner", "funsimavg",
        ])
        rows = out.strip().split("\n")
        top_3_ids = [rows[i].split("\t")[1] for i in range(3)]
        eye_diseases = {"OMIM:100200", "OMIM:100500", "OMIM:100600", "OMIM:100900"}
        assert any(d in eye_diseases for d in top_3_ids)

    def test_score_format(self):
        """Scores must have exactly 6 decimal places."""
        out = run_sim([
            "rank",
            "HP:0001250",
            "--method", "resnik",
            "--combiner", "funsimavg",
        ])
        first_line = out.strip().split("\n")[0]
        score_str = first_line.split("\t")[3]
        assert "." in score_str
        decimal_digits = len(score_str.split(".")[1])
        assert decimal_digits == 6

    def test_alt_id_in_rank_query(self):
        """Alt_id HP:0005484 in rank query must produce same results as HP:0000252."""
        out1 = run_sim([
            "rank", "HP:0000252,HP:0001250",
            "--method", "resnik", "--combiner", "bma",
        ])
        out2 = run_sim([
            "rank", "HP:0005484,HP:0001250",
            "--method", "resnik", "--combiner", "bma",
        ])
        rows1 = out1.strip().split("\n")
        rows2 = out2.strip().split("\n")
        for r1, r2 in zip(rows1, rows2):
            p1, p2 = r1.split("\t"), r2.split("\t")
            assert p1[1] == p2[1]  # same disease order
            assert abs(float(p1[3]) - float(p2[3])) < 0.005  # same scores

    def test_lin_ranking_order(self):
        """Lin+funSimAvg ranking should have OMIM:100100 at top."""
        out = run_sim([
            "rank", "HP:0001250,HP:0000252,HP:0001290",
            "--method", "lin", "--combiner", "funsimavg",
        ])
        first = out.strip().split("\n")[0]
        assert first.split("\t")[1] == "OMIM:100100"
