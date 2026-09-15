
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"
NT_PATH = "/app/results.nt"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


def approx(val, abs_tol=0.001):
    return pytest.approx(val, abs=abs_tol)


class TestResultsStructure:
    def test_results_file_exists(self, results):
        assert results is not None

    def test_has_systems(self, results):
        assert "systems" in results
        for sys in ["system_A", "system_B", "system_C"]:
            assert sys in results["systems"]

    def test_has_rankings(self, results):
        assert "rankings" in results
        for key in ["cea_f1", "cta_f1", "cpa_f1"]:
            assert key in results["rankings"]

    def test_has_category_metrics(self, results):
        assert "category_metrics" in results
        for sys in ["system_A", "system_B", "system_C"]:
            assert sys in results["category_metrics"]

    def test_system_has_all_tasks(self, results):
        for sys in ["system_A", "system_B", "system_C"]:
            for task in ["cea", "cta", "cpa"]:
                assert task in results["systems"][sys], f"{sys} missing {task}"

    def test_task_has_all_metrics(self, results):
        for sys in ["system_A", "system_B", "system_C"]:
            for task in ["cea", "cta", "cpa"]:
                metrics = results["systems"][sys][task]
                for key in ["precision", "recall", "f1", "coverage", "abstention_rate"]:
                    assert key in metrics, f"{sys}/{task} missing {key}"


class TestCEAMetrics:
    """System A: 27 submitted (all correct via owl:sameAs equivalence), 28 GT.
    Key: Q2 matches Q100 via symmetry inference (Q3->Q2 stated, Q3->Q100 stated).
    P=27/27=1.0, R=27/28, F1=54/55"""

    def test_system_a_precision(self, results):
        assert results["systems"]["system_A"]["cea"]["precision"] == approx(1.0)

    def test_system_a_recall(self, results):
        assert results["systems"]["system_A"]["cea"]["recall"] == approx(27 / 28)

    def test_system_a_f1(self, results):
        assert results["systems"]["system_A"]["cea"]["f1"] == approx(54 / 55)

    def test_system_a_coverage(self, results):
        assert results["systems"]["system_A"]["cea"]["coverage"] == approx(27 / 28)

    def test_system_a_abstention_rate(self, results):
        assert results["systems"]["system_A"]["cea"]["abstention_rate"] == approx(0.0)

    """System B: 28 submitted, 23 correct, 5 wrong.
    Q10 is in equivalence class {Q10,Q11}, NOT {Q200,Q201}. P=R=F1=23/28"""

    def test_system_b_precision(self, results):
        assert results["systems"]["system_B"]["cea"]["precision"] == approx(23 / 28)

    def test_system_b_recall(self, results):
        assert results["systems"]["system_B"]["cea"]["recall"] == approx(23 / 28)

    def test_system_b_f1(self, results):
        assert results["systems"]["system_B"]["cea"]["f1"] == approx(23 / 28)

    def test_system_b_abstention_rate(self, results):
        assert results["systems"]["system_B"]["cea"]["abstention_rate"] == approx(0.0)

    """System C: 28 total submissions, 8 ABSTAIN, 20 actual predictions (all correct).
    P=20/20=1.0, R=20/28, F1=5/6"""

    def test_system_c_precision(self, results):
        assert results["systems"]["system_C"]["cea"]["precision"] == approx(1.0)

    def test_system_c_recall(self, results):
        assert results["systems"]["system_C"]["cea"]["recall"] == approx(20 / 28)

    def test_system_c_f1(self, results):
        assert results["systems"]["system_C"]["cea"]["f1"] == approx(5 / 6)

    def test_system_c_coverage(self, results):
        assert results["systems"]["system_C"]["cea"]["coverage"] == approx(20 / 28)

    def test_system_c_abstention_rate(self, results):
        assert results["systems"]["system_C"]["cea"]["abstention_rate"] == approx(8 / 28)


class TestCTAMetrics:
    """System A: 5/5 correct. Q7930989 matches Q515 via owl:equivalentClass.
    Q5 matches Q215627 (ancestor). Q4671277 matches Q3918 (ancestor).
    P=R=F1=1.0"""

    def test_system_a_precision(self, results):
        assert results["systems"]["system_A"]["cta"]["precision"] == approx(1.0)

    def test_system_a_f1(self, results):
        assert results["systems"]["system_A"]["cta"]["f1"] == approx(1.0)

    """System B: 4/5 correct. Q43229 matches Q3918 (depth-2 ancestor).
    Q999 does not match Q215627. P=R=F1=0.8"""

    def test_system_b_precision(self, results):
        assert results["systems"]["system_B"]["cta"]["precision"] == approx(0.8)

    def test_system_b_f1(self, results):
        assert results["systems"]["system_B"]["cta"]["f1"] == approx(0.8)

    """System C: 4 submitted (1 ABSTAIN), 4 correct.
    P=1.0, R=0.8, F1=8/9"""

    def test_system_c_precision(self, results):
        assert results["systems"]["system_C"]["cta"]["precision"] == approx(1.0)

    def test_system_c_recall(self, results):
        assert results["systems"]["system_C"]["cta"]["recall"] == approx(0.8)

    def test_system_c_f1(self, results):
        assert results["systems"]["system_C"]["cta"]["f1"] == approx(8 / 9)


class TestCPAMetrics:
    """CPA uses rdfs:subPropertyOf subsumption (not exact match). 3 GT entries.
    System A: 3/3 exact match. P=R=F1=1.0.
    System B: 2/3 correct. P625 NOT related to P131. P=R=F1=2/3.
    System C: 2/2 correct + 1 ABSTAIN. P276 matches P131 via subPropertyOf.
    P=1.0, R=2/3, F1=4/5."""

    def test_system_a_precision(self, results):
        assert results["systems"]["system_A"]["cpa"]["precision"] == approx(1.0)

    def test_system_a_f1(self, results):
        assert results["systems"]["system_A"]["cpa"]["f1"] == approx(1.0)

    def test_system_b_precision(self, results):
        assert results["systems"]["system_B"]["cpa"]["precision"] == approx(2 / 3)

    def test_system_b_recall(self, results):
        assert results["systems"]["system_B"]["cpa"]["recall"] == approx(2 / 3)

    def test_system_b_f1(self, results):
        assert results["systems"]["system_B"]["cpa"]["f1"] == approx(2 / 3)

    def test_system_c_precision(self, results):
        assert results["systems"]["system_C"]["cpa"]["precision"] == approx(1.0)

    def test_system_c_recall(self, results):
        assert results["systems"]["system_C"]["cpa"]["recall"] == approx(2 / 3)

    def test_system_c_f1(self, results):
        assert results["systems"]["system_C"]["cpa"]["f1"] == approx(4 / 5)

    def test_system_c_coverage(self, results):
        assert results["systems"]["system_C"]["cpa"]["coverage"] == approx(2 / 3)

    def test_system_c_abstention_rate(self, results):
        assert results["systems"]["system_C"]["cpa"]["abstention_rate"] == approx(1 / 3)


class TestRankings:
    def test_cea_ranking(self, results):
        ranking = results["rankings"]["cea_f1"]
        assert ranking == ["system_A", "system_C", "system_B"]

    def test_cta_ranking(self, results):
        ranking = results["rankings"]["cta_f1"]
        assert ranking == ["system_A", "system_C", "system_B"]

    def test_cpa_ranking(self, results):
        ranking = results["rankings"]["cpa_f1"]
        assert ranking == ["system_A", "system_C", "system_B"]


class TestCategoryMetrics:
    """Per-category CEA accuracy."""

    def test_system_a_disambiguation(self, results):
        cat = results["category_metrics"]["system_A"]["disambiguation"]
        assert cat["correct"] == 4
        assert cat["total"] == 4
        assert cat["accuracy"] == approx(1.0)

    def test_system_a_alias(self, results):
        cat = results["category_metrics"]["system_A"]["alias"]
        assert cat["correct"] == 0
        assert cat["total"] == 1
        assert cat["accuracy"] == approx(0.0)

    def test_system_a_nil(self, results):
        cat = results["category_metrics"]["system_A"]["nil"]
        assert cat["correct"] == 3
        assert cat["total"] == 3

    def test_system_b_disambiguation(self, results):
        cat = results["category_metrics"]["system_B"]["disambiguation"]
        assert cat["correct"] == 3
        assert cat["total"] == 4
        assert cat["accuracy"] == approx(0.75)

    def test_system_b_nil(self, results):
        cat = results["category_metrics"]["system_B"]["nil"]
        assert cat["correct"] == 1
        assert cat["total"] == 3
        assert cat["accuracy"] == approx(1 / 3)

    def test_system_b_noise(self, results):
        cat = results["category_metrics"]["system_B"]["noise"]
        assert cat["correct"] == 1
        assert cat["total"] == 2
        assert cat["accuracy"] == approx(0.5)

    def test_system_c_disambiguation(self, results):
        cat = results["category_metrics"]["system_C"]["disambiguation"]
        assert cat["correct"] == 1
        assert cat["total"] == 4
        assert cat["accuracy"] == approx(0.25)

    def test_system_c_noise(self, results):
        cat = results["category_metrics"]["system_C"]["noise"]
        assert cat["correct"] == 0
        assert cat["total"] == 2
        assert cat["accuracy"] == approx(0.0)


class TestOwlSameAsResolution:
    """Verify owl:sameAs equivalence-dependent results are correct,
    proving symmetric + transitive closure works properly."""

    def test_symmetry_inference_q2_matches_q100(self, results):
        """System A uses Q2 for GT Q100 in T005:0:0.
        KG has Q3 owl:sameAs Q2 and Q3 owl:sameAs Q100 but NOT Q2 owl:sameAs anything.
        Agent must infer Q2 sameAs Q3 (symmetry) then Q2 sameAs Q100 (transitivity).
        If this works, System A CEA precision stays 1.0."""
        assert results["systems"]["system_A"]["cea"]["precision"] == approx(1.0)

    def test_equivalence_class_separation(self, results):
        """System B uses Q10 for GT Q200. Q10 owl:sameAs Q11 forms class {Q10,Q11}.
        Q201 owl:sameAs Q200 forms class {Q200,Q201}. These are separate classes.
        Q10 should NOT match Q200. System B has exactly 23 correct out of 28."""
        p = results["systems"]["system_B"]["cea"]["precision"]
        assert p == approx(23 / 28)

    def test_transitive_chain(self, results):
        """System A uses equivalent entity IDs via transitive owl:sameAs chains.
        Q1 sameAs Q100, Q201 sameAs Q200, Q700 sameAs Q600, Q301 sameAs Q300.
        All should be correct, keeping precision at 1.0."""
        assert results["systems"]["system_A"]["cea"]["precision"] == approx(1.0)
        assert results["systems"]["system_A"]["cea"]["recall"] == approx(27 / 28)


class TestOwlEquivalentClass:
    """Verify owl:equivalentClass handling in CTA evaluation.
    Q515 owl:equivalentClass Q7930989 in the KG implies mutual rdfs:subClassOf.
    Without recognizing this, System A CTA F1 would be 4/5=0.8 (Q7930989 != Q515
    without equivalentClass expansion) instead of 5/5=1.0."""

    def test_equivalentclass_enables_cta_match(self, results):
        """System A predicts Q7930989 for GT Q515 (T002 col 0).
        This only matches if the solver expands owl:equivalentClass
        into mutual rdfs:subClassOf before computing subsumption."""
        assert results["systems"]["system_A"]["cta"]["f1"] == approx(1.0)

    def test_equivalentclass_does_not_affect_exact(self, results):
        """System C predicts Q515 for GT Q515 (exact match).
        Unaffected by equivalentClass -- still correct."""
        assert results["systems"]["system_C"]["cta"]["precision"] == approx(1.0)


class TestSubPropertyOf:
    """Verify rdfs:subPropertyOf handling in CPA evaluation.
    P276 rdfs:subPropertyOf P131 in the KG. P625 has no such relationship.
    Without property subsumption, System C CPA precision would be 1/2 (not 1.0)."""

    def test_subproperty_match_p276_p131(self, results):
        """System C predicts P276 for GT P131. P276 rdfs:subPropertyOf P131.
        Without subPropertyOf reasoning, System C CPA precision = 1/2 = 0.5.
        With it, precision = 2/2 = 1.0."""
        assert results["systems"]["system_C"]["cpa"]["precision"] == approx(1.0)

    def test_subproperty_effect_on_recall(self, results):
        """System C CPA recall = 2/3 proves two matches (P27 exact + P276 via
        subPropertyOf) out of 3 GT entries. Without subPropertyOf, recall = 1/3."""
        assert results["systems"]["system_C"]["cpa"]["recall"] == approx(2 / 3)

    def test_no_subproperty_relation_p625_p131(self, results):
        """System B predicts P625 for GT P131. P625 has NO rdfs:subPropertyOf
        relationship with P131. Should not match, keeping System B CPA F1 at 2/3."""
        assert results["systems"]["system_B"]["cpa"]["f1"] == approx(2 / 3)


class TestNTriplesOutput:
    """Verify the N-Triples RDF output file is valid and contains
    correct evaluation results per the eval ontology."""

    @pytest.fixture
    def eval_graph(self):
        from rdflib import Graph
        assert os.path.exists(NT_PATH), f"{NT_PATH} does not exist"
        g = Graph()
        g.parse(NT_PATH, format="nt")
        return g

    def test_ntriples_file_exists(self):
        assert os.path.exists(NT_PATH), f"{NT_PATH} does not exist"

    def test_ntriples_parseable(self, eval_graph):
        assert len(eval_graph) > 0, "N-Triples graph is empty"

    def test_correct_number_of_evaluations(self, eval_graph):
        from rdflib import URIRef
        from rdflib.namespace import RDF
        eval_cls = URIRef("http://example.org/eval#Evaluation")
        evals = list(eval_graph.subjects(RDF.type, eval_cls))
        assert len(evals) == 9, f"Expected 9 Evaluation instances (3 systems x 3 tasks), got {len(evals)}"

    def test_system_a_cea_type(self, eval_graph):
        from rdflib import URIRef
        from rdflib.namespace import RDF
        subject = URIRef("http://example.org/eval#system_A_cea")
        eval_cls = URIRef("http://example.org/eval#Evaluation")
        assert (subject, RDF.type, eval_cls) in eval_graph

    def test_system_a_cea_precision(self, eval_graph):
        from rdflib import URIRef
        subject = URIRef("http://example.org/eval#system_A_cea")
        pred = URIRef("http://example.org/eval#precision")
        val = eval_graph.value(subject, pred)
        assert val is not None, "system_A_cea missing precision"
        assert abs(float(str(val)) - 1.0) < 0.001

    def test_system_a_cea_f1(self, eval_graph):
        from rdflib import URIRef
        subject = URIRef("http://example.org/eval#system_A_cea")
        pred = URIRef("http://example.org/eval#f1")
        val = eval_graph.value(subject, pred)
        assert val is not None, "system_A_cea missing f1"
        assert abs(float(str(val)) - 54 / 55) < 0.001

    def test_system_b_cea_f1(self, eval_graph):
        from rdflib import URIRef
        subject = URIRef("http://example.org/eval#system_B_cea")
        pred = URIRef("http://example.org/eval#f1")
        val = eval_graph.value(subject, pred)
        assert val is not None, "system_B_cea missing f1"
        assert abs(float(str(val)) - 23 / 28) < 0.001

    def test_system_c_cea_abstention_rate(self, eval_graph):
        from rdflib import URIRef
        subject = URIRef("http://example.org/eval#system_C_cea")
        pred = URIRef("http://example.org/eval#abstentionRate")
        val = eval_graph.value(subject, pred)
        assert val is not None, "system_C_cea missing abstentionRate"
        assert abs(float(str(val)) - 8 / 28) < 0.001

    def test_system_b_cpa_f1(self, eval_graph):
        """CPA F1 for System B = 2/3 (P625 does not match P131)."""
        from rdflib import URIRef
        subject = URIRef("http://example.org/eval#system_B_cpa")
        pred = URIRef("http://example.org/eval#f1")
        val = eval_graph.value(subject, pred)
        assert val is not None, "system_B_cpa missing f1"
        assert abs(float(str(val)) - 2 / 3) < 0.001

    def test_system_c_cpa_abstention_rate(self, eval_graph):
        """CPA abstention rate for System C = 1/3 (1 ABSTAIN out of 3 submissions)."""
        from rdflib import URIRef
        subject = URIRef("http://example.org/eval#system_C_cpa")
        pred = URIRef("http://example.org/eval#abstentionRate")
        val = eval_graph.value(subject, pred)
        assert val is not None, "system_C_cpa missing abstentionRate"
        assert abs(float(str(val)) - 1 / 3) < 0.001

    def test_system_a_rank_1_all_tasks(self, eval_graph):
        from rdflib import URIRef
        rank_pred = URIRef("http://example.org/eval#rank")
        for task in ["cea", "cta", "cpa"]:
            subject = URIRef(f"http://example.org/eval#system_A_{task}")
            rank = eval_graph.value(subject, rank_pred)
            assert rank is not None, f"system_A_{task} missing rank"
            assert int(str(rank)) == 1, f"system_A_{task} rank should be 1, got {rank}"

    def test_system_b_rank_3_all_tasks(self, eval_graph):
        from rdflib import URIRef
        rank_pred = URIRef("http://example.org/eval#rank")
        for task in ["cea", "cta", "cpa"]:
            subject = URIRef(f"http://example.org/eval#system_B_{task}")
            rank = eval_graph.value(subject, rank_pred)
            assert rank is not None, f"system_B_{task} missing rank"
            assert int(str(rank)) == 3, f"system_B_{task} rank should be 3, got {rank}"

    def test_all_evaluations_have_required_properties(self, eval_graph):
        from rdflib import URIRef
        from rdflib.namespace import RDF
        eval_cls = URIRef("http://example.org/eval#Evaluation")
        required_props = [
            URIRef("http://example.org/eval#system"),
            URIRef("http://example.org/eval#task"),
            URIRef("http://example.org/eval#precision"),
            URIRef("http://example.org/eval#recall"),
            URIRef("http://example.org/eval#f1"),
            URIRef("http://example.org/eval#coverage"),
            URIRef("http://example.org/eval#abstentionRate"),
            URIRef("http://example.org/eval#rank"),
        ]
        subjects = list(eval_graph.subjects(RDF.type, eval_cls))
        for subj in subjects:
            for prop in required_props:
                val = eval_graph.value(subj, prop)
                assert val is not None, f"{subj} missing property {prop}"
