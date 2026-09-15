
"""Tests for the sr_verify screen reader speech verification engine."""

import sys
import json
import pytest
import xml.etree.ElementTree as ET

sys.path.insert(0, '/app')


# ============================================================
# Normalizer tests
# ============================================================

class TestNormalize:
    def test_basic_lowercase(self):
        from sr_verify.normalizer import normalize
        assert normalize("Hello World") == "hello world"

    def test_punctuation_removal(self):
        from sr_verify.normalizer import normalize
        assert normalize("Hello, World!") == "hello world"

    def test_number_simple(self):
        from sr_verify.normalizer import normalize
        assert normalize("29 push button") == "twenty nine push button"

    def test_number_hundred(self):
        from sr_verify.normalizer import normalize
        assert normalize("100 items") == "one hundred items"

    def test_number_compound(self):
        from sr_verify.normalizer import normalize
        assert normalize("451") == "four hundred fifty one"

    def test_number_thousand(self):
        from sr_verify.normalizer import normalize
        assert normalize("1000") == "one thousand"

    def test_number_zero(self):
        from sr_verify.normalizer import normalize
        assert normalize("0 errors") == "zero errors"

    def test_mixed_alphanumeric_preserved(self):
        from sr_verify.normalizer import normalize
        assert normalize("Press F1") == "press f1"

    def test_whitespace_collapse(self):
        from sr_verify.normalizer import normalize
        assert normalize("  hello   world  ") == "hello world"

    def test_mixed_punctuation_and_numbers(self):
        from sr_verify.normalizer import normalize
        assert normalize("Item #42: selected!") == "item forty two selected"

    def test_number_teens(self):
        from sr_verify.normalizer import normalize
        assert normalize("13 items") == "thirteen items"

    def test_number_round_tens(self):
        from sr_verify.normalizer import normalize
        assert normalize("50 percent") == "fifty percent"

    def test_number_9999(self):
        from sr_verify.normalizer import normalize
        result = normalize("9999")
        assert result == "nine thousand nine hundred ninety nine"

    def test_number_above_range_unchanged(self):
        from sr_verify.normalizer import normalize
        assert normalize("10000") == "10000"

    def test_empty_string(self):
        from sr_verify.normalizer import normalize
        assert normalize("") == ""

    def test_number_in_sentence(self):
        from sr_verify.normalizer import normalize
        assert normalize("Row 3, Column 12") == "row three column twelve"

    def test_standalone_zero(self):
        from sr_verify.normalizer import normalize
        assert normalize("0") == "zero"

    def test_multiple_mixed_tokens(self):
        from sr_verify.normalizer import normalize
        assert normalize("Use F2 or F3") == "use f2 or f3"


# ============================================================
# WER tests
# ============================================================

class TestWER:
    def test_identical(self):
        from sr_verify.metrics import wer
        assert wer("hello world", "hello world") == 0.0

    def test_substitution(self):
        from sr_verify.metrics import wer
        assert wer("hello world", "hello word") == pytest.approx(0.5)

    def test_insertion(self):
        from sr_verify.metrics import wer
        assert wer("hello world", "hello beautiful world") == pytest.approx(0.5)

    def test_deletion(self):
        from sr_verify.metrics import wer
        assert wer("hello beautiful world", "hello world") == pytest.approx(1.0 / 3.0)

    def test_both_empty(self):
        from sr_verify.metrics import wer
        assert wer("", "") == 0.0

    def test_empty_ref_nonempty_hyp(self):
        from sr_verify.metrics import wer
        assert wer("", "hello") == 1.0

    def test_empty_hyp_nonempty_ref(self):
        from sr_verify.metrics import wer
        assert wer("hello world", "") == 1.0

    def test_completely_different(self):
        from sr_verify.metrics import wer
        assert wer("a b", "c d") == 1.0

    def test_normalizes_case_and_punctuation(self):
        from sr_verify.metrics import wer
        assert wer("Hello World!", "hello world") == 0.0

    def test_single_word_match(self):
        from sr_verify.metrics import wer
        assert wer("test", "test") == 0.0

    def test_single_word_mismatch(self):
        from sr_verify.metrics import wer
        assert wer("test", "best") == 1.0

    def test_multiple_substitutions(self):
        from sr_verify.metrics import wer
        # 3 subs out of 4 ref words
        assert wer("the quick brown fox", "a slow green fox") == pytest.approx(0.75)


# ============================================================
# Segmented WER tests
# ============================================================

class TestSegmentedWER:
    def test_single_segment_perfect(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            ["hello", "world"],
            [["hello", "world"]],
        )
        assert overall == 0.0
        assert len(results) == 1
        assert results[0].edit_distance == 0
        assert results[0].wer == 0.0

    def test_two_segments_perfect(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            ["hello", "beautiful", "world"],
            [["hello"], ["beautiful", "world"]],
        )
        assert overall == 0.0
        assert results[0].edit_distance == 0
        assert results[1].edit_distance == 0

    def test_three_segments_perfect(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            ["a", "b", "c", "d", "e", "f"],
            [["a", "b"], ["c", "d"], ["e", "f"]],
        )
        assert overall == 0.0
        assert all(r.edit_distance == 0 for r in results)

    def test_noise_between_segments(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            ["screen", "reader", "twenty", "nine", "push", "button"],
            [["screen"], ["twenty", "nine", "push", "button"]],
        )
        assert overall == pytest.approx(0.2)

    def test_empty_hypothesis(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            [],
            [["hello"], ["world"]],
        )
        assert overall == pytest.approx(1.0)

    def test_single_word_segments(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            ["alpha", "beta", "gamma"],
            [["alpha"], ["beta"], ["gamma"]],
        )
        assert overall == 0.0

    def test_hypothesis_longer_than_refs(self):
        from sr_verify.metrics import segmented_wer
        overall, results = segmented_wer(
            ["the", "quick", "brown", "fox"],
            [["quick", "fox"]],
        )
        assert overall == pytest.approx(1.0)

    def test_segment_result_dataclass(self):
        from sr_verify.metrics import segmented_wer, SegmentResult
        _, results = segmented_wer(["a"], [["a"]])
        r = results[0]
        assert hasattr(r, 'ref_words')
        assert hasattr(r, 'hyp_words')
        assert hasattr(r, 'wer')
        assert hasattr(r, 'edit_distance')
        assert isinstance(r, SegmentResult)


# ============================================================
# Interruption model tests
# ============================================================

class TestInterruptions:
    def test_full_duration_no_interrupt(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Screen reader on", 2000, 2000) == "Screen reader on"

    def test_partial_first_word_heard(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Screen reader on", 2000, 800) == "Screen"

    def test_very_early_interrupt_nothing_heard(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Hello world", 2000, 100) == ""

    def test_two_word_input(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("OK button", 1200, 500) == "OK"

    def test_interrupt_at_zero(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Hello", 1000, 0) == ""

    def test_interrupt_past_duration(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Hello world", 1000, 1500) == "Hello world"

    def test_single_word_full(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Hello", 1000, 1000) == "Hello"

    def test_single_word_partial_not_heard(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Hello", 1000, 800) == ""

    def test_empty_text(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("", 1000, 500) == ""

    def test_multiple_words_boundary(self):
        from sr_verify.interruptions import compute_heard_text
        assert compute_heard_text("Cancel button", 1200, 600) == "Cancel"

    def test_multiple_words_all_heard(self):
        from sr_verify.interruptions import compute_heard_text
        # "Apply button focused" (20 chars), 1500ms
        # time_per_char = 75ms
        # "Apply": ends at 5*75=375 <= 900
        # "button": ends at 12*75=900 <= 900
        # "focused": ends at 20*75=1500 > 900
        assert compute_heard_text("Apply button focused", 1500, 900) == "Apply button"

    def test_exact_boundary_three_words(self):
        from sr_verify.interruptions import compute_heard_text
        # "ab cd ef" (8 chars), 800ms, time_per_char=100ms
        # "ab" ends at 2*100=200 <= 500
        # "cd" ends at 5*100=500 <= 500
        # "ef" ends at 8*100=800 > 500
        assert compute_heard_text("ab cd ef", 800, 500) == "ab cd"


# ============================================================
# Reporter tests
# ============================================================

class TestReporter:
    def test_valid_xml_single_pass(self):
        from sr_verify.reporter import generate_junit_xml
        results = [{
            "utterance_id": 0,
            "expected_text": "hello",
            "heard_text": "hello",
            "hypothesis_text": "hello",
            "wer": 0.0,
            "passed": True,
            "threshold": 0.3,
        }]
        xml_str = generate_junit_xml("test_scenario", results)
        root = ET.fromstring(xml_str)
        assert root.tag == "testsuite"
        assert root.attrib["name"] == "test_scenario"
        assert root.attrib["tests"] == "1"
        assert root.attrib["failures"] == "0"
        tc = root.find("testcase")
        assert tc is not None
        assert tc.attrib["name"] == "utterance_0"
        assert tc.find("failure") is None

    def test_failure_element(self):
        from sr_verify.reporter import generate_junit_xml
        results = [{
            "utterance_id": 0,
            "expected_text": "hello",
            "heard_text": "hello",
            "hypothesis_text": "help",
            "wer": 1.0,
            "passed": False,
            "threshold": 0.3,
        }]
        xml_str = generate_junit_xml("fail_test", results)
        root = ET.fromstring(xml_str)
        assert root.attrib["failures"] == "1"
        tc = root.find("testcase")
        failure = tc.find("failure")
        assert failure is not None
        assert "1.000" in failure.attrib["message"]
        assert "0.3" in failure.attrib["message"]

    def test_multiple_testcases(self):
        from sr_verify.reporter import generate_junit_xml
        results = [
            {"utterance_id": 0, "expected_text": "a", "heard_text": "a",
             "hypothesis_text": "a", "wer": 0.0, "passed": True, "threshold": 0.3},
            {"utterance_id": 1, "expected_text": "b", "heard_text": "b",
             "hypothesis_text": "b", "wer": 0.0, "passed": True, "threshold": 0.3},
            {"utterance_id": 2, "expected_text": "c", "heard_text": "c",
             "hypothesis_text": "x", "wer": 1.0, "passed": False, "threshold": 0.5},
        ]
        xml_str = generate_junit_xml("multi_test", results)
        root = ET.fromstring(xml_str)
        assert len(root.findall("testcase")) == 3
        failures = [tc for tc in root.findall("testcase") if tc.find("failure") is not None]
        assert len(failures) == 1

    def test_failure_message_format(self):
        from sr_verify.reporter import generate_junit_xml
        results = [{
            "utterance_id": 5,
            "expected_text": "test",
            "heard_text": "test",
            "hypothesis_text": "toast",
            "wer": 0.45,
            "passed": False,
            "threshold": 0.3,
        }]
        xml_str = generate_junit_xml("format_test", results)
        root = ET.fromstring(xml_str)
        tc = root.find("testcase")
        assert tc.attrib["name"] == "utterance_5"
        failure = tc.find("failure")
        assert "0.450" in failure.attrib["message"]
        assert "0.3" in failure.attrib["message"]
        assert "Expected: test" in failure.text
        assert "Hypothesis: toast" in failure.text


# ============================================================
# Scenario integration tests
# ============================================================

class TestScenarioIntegration:
    def test_simple_scenario_no_interruption(self):
        from sr_verify.interruptions import compute_heard_text
        with open('/app/scenarios/simple.json') as f:
            scenario = json.load(f)
        u = scenario['utterances'][0]
        heard = compute_heard_text(u['text'], u['duration_ms'], u['duration_ms'])
        assert heard == u['text']

    def test_interrupted_scenario_heard_text(self):
        from sr_verify.interruptions import compute_heard_text
        with open('/app/scenarios/interrupted.json') as f:
            scenario = json.load(f)
        utterances = scenario['utterances']
        u0, u1 = utterances[0], utterances[1]
        elapsed = u1['start_ms'] - u0['start_ms']
        heard = compute_heard_text(u0['text'], u0['duration_ms'], elapsed)
        assert heard == "Screen"

    def test_rapid_focus_chained_interrupts(self):
        from sr_verify.interruptions import compute_heard_text
        with open('/app/scenarios/rapid_focus.json') as f:
            scenario = json.load(f)
        utterances = scenario['utterances']
        # Utterance 0 interrupted by utterance 1 at 500ms
        heard0 = compute_heard_text(
            utterances[0]['text'], utterances[0]['duration_ms'],
            utterances[1]['start_ms'] - utterances[0]['start_ms'])
        assert heard0 == "OK"
        # Utterance 1 interrupted by utterance 2 at 600ms relative
        heard1 = compute_heard_text(
            utterances[1]['text'], utterances[1]['duration_ms'],
            utterances[2]['start_ms'] - utterances[1]['start_ms'])
        assert heard1 == "Cancel"

    def test_dialog_mixed_token_normalization(self):
        from sr_verify.normalizer import normalize
        with open('/app/scenarios/dialog_navigation.json') as f:
            scenario = json.load(f)
        # "Press F1 for help" — F1 is alphanumeric, digits inside must not expand
        assert normalize(scenario['utterances'][0]['text']) == "press f1 for help"

    def test_dialog_zero_expansion(self):
        from sr_verify.normalizer import normalize
        with open('/app/scenarios/dialog_navigation.json') as f:
            scenario = json.load(f)
        # "0 items found" — standalone zero must expand to "zero"
        assert normalize(scenario['utterances'][1]['text']) == "zero items found"

    def test_dialog_interrupted_heard(self):
        from sr_verify.interruptions import compute_heard_text
        with open('/app/scenarios/dialog_navigation.json') as f:
            scenario = json.load(f)
        utterances = scenario['utterances']
        # Utterance 0 interrupted by utterance 1 at 1500ms
        elapsed = utterances[1]['start_ms'] - utterances[0]['start_ms']
        heard = compute_heard_text(
            utterances[0]['text'], utterances[0]['duration_ms'], elapsed)
        # "Press F1 for help" (17 chars), 1800ms, at 1500ms
        # time_per_char = 1800/17 ≈ 105.88ms
        # "Press" ends at 5*105.88=529.4 <= 1500
        # "F1" ends at 8*105.88=847.1 <= 1500
        # "for" ends at 12*105.88=1270.6 <= 1500
        # "help" ends at 17*105.88=1800 > 1500
        assert heard == "Press F1 for"
