
"""
Tests for the CCS Clinical Simulation Engine modules:
- OrderMatcher: fuzzy text matching for clinical orders
- SimulationEngine: discrete-event simulation with conditional events
- Scorer: rubric-based transcript evaluation
"""

import json
import sys
import pytest

sys.path.insert(0, "/app")

with open("/data/catalog.json") as f:
    CATALOG = json.load(f)
with open("/data/case.json") as f:
    CASE = json.load(f)
with open("/data/rubric.json") as f:
    RUBRIC = json.load(f)


# ============ ORDER MATCHER TESTS ============


class TestOrderMatcherExact:
    """Test exact matching on canonical names and aliases."""

    def setup_method(self):
        from order_matcher import OrderMatcher

        self.matcher = OrderMatcher(CATALOG)

    def test_exact_alias_match_ecg(self):
        results = self.matcher.match("ECG")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Electrocardiogram"
        assert results[0]["score"] == 1.0

    def test_exact_canonical_match(self):
        results = self.matcher.match("Aspirin")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Aspirin"
        assert results[0]["score"] == 1.0

    def test_case_insensitive_exact(self):
        results = self.matcher.match("ecg")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Electrocardiogram"
        assert results[0]["score"] == 1.0

    def test_abbreviation_cbc(self):
        results = self.matcher.match("CBC")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Complete Blood Count"
        assert results[0]["score"] == 1.0

    def test_abbreviation_bmp(self):
        results = self.matcher.match("BMP")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Basic Metabolic Panel"
        assert results[0]["score"] == 1.0

    def test_abbreviation_cxr(self):
        results = self.matcher.match("CXR")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Chest X-Ray"
        assert results[0]["score"] == 1.0

    def test_alias_o2(self):
        results = self.matcher.match("O2")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Oxygen Supplementation"
        assert results[0]["score"] == 1.0


class TestOrderMatcherPrefix:
    """Test prefix-based matching."""

    def setup_method(self):
        from order_matcher import OrderMatcher

        self.matcher = OrderMatcher(CATALOG)

    def test_prefix_trop(self):
        results = self.matcher.match("trop")
        assert len(results) >= 2
        names = [r["canonical_name"] for r in results]
        assert "Troponin I" in names
        assert "Troponin T" in names
        trop_results = [r for r in results if r["canonical_name"].startswith("Troponin")]
        for r in trop_results:
            assert r["score"] >= 0.8

    def test_prefix_electro(self):
        results = self.matcher.match("electro")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Electrocardiogram"
        assert results[0]["score"] >= 0.8

    def test_prefix_heparin_drip(self):
        results = self.matcher.match("heparin d")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Heparin"
        assert results[0]["score"] >= 0.8


class TestOrderMatcherFuzzy:
    """Test fuzzy matching via edit distance."""

    def setup_method(self):
        from order_matcher import OrderMatcher

        self.matcher = OrderMatcher(CATALOG)

    def test_fuzzy_asprin_typo(self):
        results = self.matcher.match("asprin")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Aspirin"
        assert results[0]["score"] >= 0.3

    def test_fuzzy_nitroglycerine(self):
        # "nitroglycerine" is actually an alias, should be exact
        results = self.matcher.match("nitroglycerine")
        assert len(results) > 0
        assert results[0]["canonical_name"] == "Nitroglycerin"
        assert results[0]["score"] == 1.0


class TestOrderMatcherLocation:
    """Test location-based filtering."""

    def setup_method(self):
        from order_matcher import OrderMatcher

        self.matcher = OrderMatcher(CATALOG)

    def test_mri_not_in_ed(self):
        results = self.matcher.match("MRI", location="emergency_department")
        names = [r["canonical_name"] for r in results]
        assert "MRI Brain" not in names

    def test_mri_available_inpatient(self):
        results = self.matcher.match("MRI", location="inpatient_unit")
        names = [r["canonical_name"] for r in results]
        assert "MRI Brain" in names

    def test_abg_not_in_inpatient(self):
        results = self.matcher.match("ABG", location="inpatient_unit")
        names = [r["canonical_name"] for r in results]
        assert "Arterial Blood Gas" not in names

    def test_abg_available_in_ed(self):
        results = self.matcher.match("ABG", location="emergency_department")
        names = [r["canonical_name"] for r in results]
        assert "Arterial Blood Gas" in names


class TestOrderMatcherEdgeCases:
    """Test edge cases and constraints."""

    def setup_method(self):
        from order_matcher import OrderMatcher

        self.matcher = OrderMatcher(CATALOG)

    def test_no_match_nonsense(self):
        results = self.matcher.match("xyzzy123nonsense")
        assert len(results) == 0

    def test_top_k_limit(self):
        results = self.matcher.match("blood", top_k=3)
        assert len(results) <= 3

    def test_score_ordering(self):
        results = self.matcher.match("troponin")
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    def test_result_has_required_keys(self):
        results = self.matcher.match("ECG")
        assert len(results) > 0
        for r in results:
            assert "canonical_name" in r
            assert "category" in r
            assert "score" in r


# ============ SIMULATION ENGINE TESTS ============


class TestSimulationEngineInit:
    """Test simulation initialization."""

    def setup_method(self):
        from simulation import SimulationEngine

        self.engine = SimulationEngine(CASE, CATALOG)

    def test_initial_time(self):
        state = self.engine.get_state()
        assert state["current_time"] == 0

    def test_initial_location(self):
        state = self.engine.get_state()
        assert state["location"] == "emergency_department"

    def test_initial_vitals(self):
        state = self.engine.get_state()
        assert state["vitals"]["heart_rate"] == 98
        assert state["vitals"]["systolic_bp"] == 145
        assert state["vitals"]["diastolic_bp"] == 92
        assert state["vitals"]["spo2"] == 96.0

    def test_initial_empty_orders(self):
        state = self.engine.get_state()
        assert len(state["pending_orders"]) == 0
        assert len(state["completed_orders"]) == 0
        assert len(state["active_medications"]) == 0


class TestSimulationEngineOrders:
    """Test order placement."""

    def setup_method(self):
        from simulation import SimulationEngine

        self.engine = SimulationEngine(CASE, CATALOG)

    def test_place_valid_order(self):
        result = self.engine.place_order("ECG")
        assert result["status"] == "accepted"
        assert result["canonical_name"] == "Electrocardiogram"
        assert result["report_time"] == 5

    def test_place_invalid_order(self):
        result = self.engine.place_order("xyzzy123nonsense")
        assert result["status"] == "rejected"

    def test_place_medication_immediate(self):
        result = self.engine.place_order("Aspirin")
        assert result["status"] == "accepted"
        assert result["canonical_name"] == "Aspirin"
        assert result["report_time"] == 0
        state = self.engine.get_state()
        assert "Aspirin" in state["active_medications"]

    def test_location_filter_on_order(self):
        # MRI Brain not available in ED
        result = self.engine.place_order("MRI Brain")
        assert result["status"] == "rejected"

    def test_order_added_to_pending(self):
        self.engine.place_order("ECG")
        state = self.engine.get_state()
        pending_names = [o["canonical_name"] for o in state["pending_orders"]]
        assert "Electrocardiogram" in pending_names


class TestSimulationEngineClock:
    """Test clock advancement and result delivery."""

    def setup_method(self):
        from simulation import SimulationEngine

        self.engine = SimulationEngine(CASE, CATALOG)

    def test_advance_clock_updates_time(self):
        result = self.engine.advance_clock(10)
        assert result["new_time"] == 10
        state = self.engine.get_state()
        assert state["current_time"] == 10

    def test_order_result_delivery(self):
        self.engine.place_order("ECG")
        self.engine.advance_clock(10)
        state = self.engine.get_state()
        completed_names = [o["canonical_name"] for o in state["completed_orders"]]
        assert "Electrocardiogram" in completed_names

    def test_pending_order_not_delivered_early(self):
        self.engine.place_order("Troponin I")  # processing_time = 30
        self.engine.advance_clock(10)
        state = self.engine.get_state()
        pending_names = [o["canonical_name"] for o in state["pending_orders"]]
        assert "Troponin I" in pending_names

    def test_max_time_cap(self):
        result = self.engine.advance_clock(200)
        assert result["new_time"] <= 120  # max_simulated_time


class TestSimulationEngineEvents:
    """Test conditional event evaluation."""

    def setup_method(self):
        from simulation import SimulationEngine

        self.engine = SimulationEngine(CASE, CATALOG)

    def test_event_fires_on_condition(self):
        self.engine.place_order("ECG")
        result = self.engine.advance_clock(10)
        assert any("STEMI" in e for e in result.get("events_fired", []))

    def test_event_skipped_without_condition(self):
        # Don't order ECG, advance past t=5
        result = self.engine.advance_clock(10)
        events = result.get("events_fired", [])
        assert not any("STEMI" in e for e in events)

    def test_deterioration_without_aspirin(self):
        self.engine.advance_clock(35)
        state = self.engine.get_state()
        assert state["vitals"]["heart_rate"] == 112
        assert state["vitals"]["systolic_bp"] == 105

    def test_improvement_with_treatment(self):
        self.engine.place_order("Aspirin")
        self.engine.place_order("Heparin")
        self.engine.advance_clock(20)
        state = self.engine.get_state()
        assert state["vitals"]["heart_rate"] == 88
        assert state["vitals"]["systolic_bp"] == 138

    def test_no_deterioration_with_aspirin(self):
        self.engine.place_order("Aspirin")
        self.engine.advance_clock(35)
        state = self.engine.get_state()
        # Should NOT have deteriorated since aspirin was given
        assert state["vitals"]["heart_rate"] != 112


class TestSimulationEngineLocation:
    """Test location changes."""

    def setup_method(self):
        from simulation import SimulationEngine

        self.engine = SimulationEngine(CASE, CATALOG)

    def test_change_location_success(self):
        result = self.engine.change_location("intensive_care_unit")
        assert result["status"] == "success"
        state = self.engine.get_state()
        assert state["location"] == "intensive_care_unit"

    def test_change_location_invalid(self):
        result = self.engine.change_location("mars_colony")
        assert result["status"] == "failure"

    def test_location_in_transcript(self):
        self.engine.change_location("intensive_care_unit")
        transcript = self.engine.get_transcript()
        loc_entries = [e for e in transcript if e["action_type"] == "change_location"]
        assert len(loc_entries) == 1
        assert loc_entries[0]["details"]["location"] == "intensive_care_unit"


class TestSimulationEngineTranscript:
    """Test transcript recording."""

    def setup_method(self):
        from simulation import SimulationEngine

        self.engine = SimulationEngine(CASE, CATALOG)

    def test_transcript_records_orders(self):
        self.engine.place_order("ECG")
        transcript = self.engine.get_transcript()
        assert len(transcript) >= 1
        assert transcript[0]["action_type"] == "order"
        assert transcript[0]["details"]["canonical_name"] == "Electrocardiogram"

    def test_transcript_records_clock(self):
        self.engine.advance_clock(5)
        transcript = self.engine.get_transcript()
        assert len(transcript) >= 1
        clock_entries = [e for e in transcript if e["action_type"] == "advance_clock"]
        assert len(clock_entries) == 1

    def test_transcript_ordering(self):
        self.engine.place_order("ECG")
        self.engine.advance_clock(5)
        self.engine.place_order("Aspirin")
        transcript = self.engine.get_transcript()
        assert len(transcript) == 3
        assert transcript[0]["action_type"] == "order"
        assert transcript[1]["action_type"] == "advance_clock"
        assert transcript[2]["action_type"] == "order"


# ============ SCORER TESTS ============


class TestScorerCredit:
    """Test credit calculation for required/recommended actions."""

    def setup_method(self):
        from scorer import Scorer

        self.scorer = Scorer(RUBRIC)

    def _make_transcript(self, actions):
        """Helper: actions are (type, timestamp, value) tuples."""
        transcript = []
        for a in actions:
            if a[0] == "order":
                transcript.append(
                    {
                        "action_type": "order",
                        "timestamp": a[1],
                        "details": {"canonical_name": a[2]},
                    }
                )
            elif a[0] == "location":
                transcript.append(
                    {
                        "action_type": "change_location",
                        "timestamp": a[1],
                        "details": {"location": a[2]},
                    }
                )
            elif a[0] == "clock":
                transcript.append(
                    {
                        "action_type": "advance_clock",
                        "timestamp": a[1],
                        "details": {"minutes": a[2]},
                    }
                )
        return transcript

    def test_perfect_management(self):
        transcript = self._make_transcript(
            [
                ("order", 0, "Electrocardiogram"),
                ("order", 1, "Aspirin"),
                ("order", 2, "Oxygen Supplementation"),
                ("order", 2, "Cardiac Monitor"),
                ("order", 3, "Troponin I"),
                ("order", 3, "Nitroglycerin"),
                ("order", 5, "Heparin"),
                ("order", 5, "Complete Blood Count"),
                ("order", 5, "Basic Metabolic Panel"),
                ("order", 5, "Chest X-Ray"),
                ("order", 8, "Cardiology Consultation"),
                ("location", 15, "intensive_care_unit"),
            ]
        )
        result = self.scorer.score(transcript)
        assert result["total_score"] >= 95

    def test_delayed_ecg(self):
        transcript = self._make_transcript(
            [
                ("order", 20, "Electrocardiogram"),  # Past window (end=10)
                ("order", 1, "Aspirin"),
            ]
        )
        result = self.scorer.score(transcript)
        ecg_detail = next(
            d for d in result["item_details"] if d["action"] == "Electrocardiogram"
        )
        # ECG at t=20, window_end=10, decay=1.0/min -> credit = max(0, 15 - 10*1.0) = 5
        assert ecg_detail["credit"] == 5.0

    def test_missing_critical_action(self):
        transcript = self._make_transcript(
            [
                ("order", 1, "Aspirin"),
                ("order", 5, "Troponin I"),
            ]
        )
        result = self.scorer.score(transcript)
        ecg_detail = next(
            d for d in result["item_details"] if d["action"] == "Electrocardiogram"
        )
        assert ecg_detail["credit"] == 0.0

    def test_fully_decayed_action(self):
        transcript = self._make_transcript(
            [
                ("order", 100, "Electrocardiogram"),  # Way past window, fully decayed
            ]
        )
        result = self.scorer.score(transcript)
        ecg_detail = next(
            d for d in result["item_details"] if d["action"] == "Electrocardiogram"
        )
        # credit = max(0, 15 - 90*1.0) = 0
        assert ecg_detail["credit"] == 0.0


class TestScorerPenalties:
    """Test penalty calculation for contraindicated actions."""

    def setup_method(self):
        from scorer import Scorer

        self.scorer = Scorer(RUBRIC)

    def _make_transcript(self, actions):
        transcript = []
        for a in actions:
            if a[0] == "order":
                transcript.append(
                    {
                        "action_type": "order",
                        "timestamp": a[1],
                        "details": {"canonical_name": a[2]},
                    }
                )
            elif a[0] == "location":
                transcript.append(
                    {
                        "action_type": "change_location",
                        "timestamp": a[1],
                        "details": {"location": a[2]},
                    }
                )
        return transcript

    def test_contraindicated_metoprolol(self):
        transcript = self._make_transcript(
            [
                ("order", 0, "Electrocardiogram"),
                ("order", 1, "Aspirin"),
                ("order", 5, "Metoprolol"),
            ]
        )
        result = self.scorer.score(transcript)
        assert len(result["penalties"]) > 0
        metoprolol_penalty = next(
            p for p in result["penalties"] if p["action"] == "Metoprolol"
        )
        assert metoprolol_penalty["penalty"] == 5.0

    def test_contraindicated_thrombolytics(self):
        transcript = self._make_transcript(
            [
                ("order", 5, "Thrombolytics"),
            ]
        )
        result = self.scorer.score(transcript)
        thrombo_penalty = next(
            p for p in result["penalties"] if p["action"] == "Thrombolytics"
        )
        assert thrombo_penalty["penalty"] == 8.0

    def test_score_clamped_to_zero(self):
        transcript = self._make_transcript(
            [
                ("order", 5, "Metoprolol"),
                ("order", 5, "Thrombolytics"),
                ("order", 5, "CT Chest"),
            ]
        )
        result = self.scorer.score(transcript)
        assert result["total_score"] == 0.0

    def test_no_penalty_without_contraindicated(self):
        transcript = self._make_transcript(
            [
                ("order", 0, "Electrocardiogram"),
                ("order", 1, "Aspirin"),
            ]
        )
        result = self.scorer.score(transcript)
        assert len(result["penalties"]) == 0


class TestScorerPrerequisites:
    """Test prerequisite sequencing validation."""

    def setup_method(self):
        from scorer import Scorer

        self.scorer = Scorer(RUBRIC)

    def _make_transcript(self, actions):
        transcript = []
        for a in actions:
            if a[0] == "order":
                transcript.append(
                    {
                        "action_type": "order",
                        "timestamp": a[1],
                        "details": {"canonical_name": a[2]},
                    }
                )
            elif a[0] == "location":
                transcript.append(
                    {
                        "action_type": "change_location",
                        "timestamp": a[1],
                        "details": {"location": a[2]},
                    }
                )
        return transcript

    def test_prerequisite_not_met_order(self):
        transcript = self._make_transcript(
            [
                ("order", 5, "Heparin"),  # Prereq: Electrocardiogram
                ("order", 10, "Electrocardiogram"),  # After heparin
            ]
        )
        result = self.scorer.score(transcript)
        heparin_detail = next(
            d for d in result["item_details"] if d["action"] == "Heparin"
        )
        assert heparin_detail["credit"] == 0.0
        assert "prerequisite" in heparin_detail["reason"].lower()

    def test_prerequisite_met(self):
        transcript = self._make_transcript(
            [
                ("order", 0, "Electrocardiogram"),
                ("order", 5, "Heparin"),
            ]
        )
        result = self.scorer.score(transcript)
        heparin_detail = next(
            d for d in result["item_details"] if d["action"] == "Heparin"
        )
        assert heparin_detail["credit"] > 0

    def test_prerequisite_missing_entirely(self):
        transcript = self._make_transcript(
            [
                ("order", 5, "Heparin"),  # Prereq ECG never ordered
            ]
        )
        result = self.scorer.score(transcript)
        heparin_detail = next(
            d for d in result["item_details"] if d["action"] == "Heparin"
        )
        assert heparin_detail["credit"] == 0.0

    def test_location_change_prerequisites(self):
        transcript = self._make_transcript(
            [
                ("order", 0, "Electrocardiogram"),
                ("order", 1, "Aspirin"),
                ("location", 20, "intensive_care_unit"),
            ]
        )
        result = self.scorer.score(transcript)
        icu_detail = next(
            d
            for d in result["item_details"]
            if d["action"] == "change_location:intensive_care_unit"
        )
        assert icu_detail["credit"] == 10.0

    def test_location_change_prereq_not_met(self):
        transcript = self._make_transcript(
            [
                # Aspirin not ordered, but it's a prereq for ICU
                ("order", 0, "Electrocardiogram"),
                ("location", 20, "intensive_care_unit"),
            ]
        )
        result = self.scorer.score(transcript)
        icu_detail = next(
            d
            for d in result["item_details"]
            if d["action"] == "change_location:intensive_care_unit"
        )
        assert icu_detail["credit"] == 0.0


class TestScorerOutputFormat:
    """Test that scorer output has the correct structure."""

    def setup_method(self):
        from scorer import Scorer

        self.scorer = Scorer(RUBRIC)

    def test_output_keys(self):
        transcript = [
            {
                "action_type": "order",
                "timestamp": 0,
                "details": {"canonical_name": "Electrocardiogram"},
            }
        ]
        result = self.scorer.score(transcript)
        assert "total_score" in result
        assert "category_scores" in result
        assert "item_details" in result
        assert "penalties" in result

    def test_item_detail_keys(self):
        transcript = [
            {
                "action_type": "order",
                "timestamp": 0,
                "details": {"canonical_name": "Electrocardiogram"},
            }
        ]
        result = self.scorer.score(transcript)
        for detail in result["item_details"]:
            assert "action" in detail
            assert "credit" in detail
            assert "max_credit" in detail
            assert "reason" in detail

    def test_empty_transcript(self):
        result = self.scorer.score([])
        assert result["total_score"] == 0.0
        assert all(d["credit"] == 0.0 for d in result["item_details"])


# ============ INTEGRATION TESTS ============


class TestIntegration:
    """End-to-end tests running all three modules together."""

    def test_full_case_good_management(self):
        from order_matcher import OrderMatcher
        from simulation import SimulationEngine
        from scorer import Scorer

        engine = SimulationEngine(CASE, CATALOG)
        scorer_obj = Scorer(RUBRIC)

        # Good management: all actions within time windows
        engine.place_order("ECG")
        engine.place_order("Aspirin")
        engine.place_order("O2")
        engine.place_order("cardiac monitor")
        engine.advance_clock(5)

        engine.place_order("troponin")
        engine.place_order("nitroglycerin")
        engine.place_order("heparin")
        engine.place_order("CBC")
        engine.place_order("BMP")
        engine.place_order("CXR")
        engine.advance_clock(5)

        engine.place_order("cardiology consult")
        engine.advance_clock(5)

        engine.change_location("intensive_care_unit")
        engine.advance_clock(30)

        transcript = engine.get_transcript()
        result = scorer_obj.score(transcript)

        assert result["total_score"] >= 90
        assert len(result["penalties"]) == 0

    def test_full_case_poor_management(self):
        from simulation import SimulationEngine
        from scorer import Scorer

        engine = SimulationEngine(CASE, CATALOG)
        scorer_obj = Scorer(RUBRIC)

        # Poor management: just advance clock, do nothing
        engine.advance_clock(60)

        transcript = engine.get_transcript()
        result = scorer_obj.score(transcript)

        assert result["total_score"] < 10

    def test_simulation_and_scorer_consistency(self):
        """Verify that the simulation transcript format is compatible with scorer."""
        from simulation import SimulationEngine
        from scorer import Scorer

        engine = SimulationEngine(CASE, CATALOG)
        scorer_obj = Scorer(RUBRIC)

        engine.place_order("ECG")
        engine.place_order("Aspirin")
        engine.advance_clock(10)
        engine.change_location("intensive_care_unit")

        transcript = engine.get_transcript()

        # Transcript should have order entries with canonical_name
        order_entries = [e for e in transcript if e["action_type"] == "order"]
        for entry in order_entries:
            assert "canonical_name" in entry["details"]

        # Location entries should have location
        loc_entries = [e for e in transcript if e["action_type"] == "change_location"]
        for entry in loc_entries:
            assert "location" in entry["details"]

        # Scorer should handle it without errors
        result = scorer_obj.score(transcript)
        assert isinstance(result["total_score"], (int, float))
        assert result["total_score"] >= 0
