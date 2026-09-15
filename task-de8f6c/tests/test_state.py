"""
Tests for screen reader audio verification framework.

"""
import sys
import os
import subprocess
import tempfile
import pytest

sys.path.insert(0, '/app')


# ============================================================
# WER: text normalization
# ============================================================

class TestNormalizeText:
    def test_lowercase(self):
        from stt_verifier.wer import normalize_text
        assert normalize_text("Hello World") == "hello world"

    def test_strip_punctuation(self):
        from stt_verifier.wer import normalize_text
        result = normalize_text("Hello, world!")
        assert "," not in result
        assert "!" not in result
        assert "hello" in result
        assert "world" in result

    def test_number_single_digit(self):
        from stt_verifier.wer import normalize_text
        result = normalize_text("item 5")
        assert "five" in result
        assert "5" not in result

    def test_number_two_digit(self):
        from stt_verifier.wer import normalize_text
        result = normalize_text("page 29")
        assert "twenty" in result
        assert "nine" in result

    def test_number_hundred(self):
        from stt_verifier.wer import normalize_text
        result = normalize_text("error 404")
        assert "four hundred" in result

    def test_number_three_digit_with_teens(self):
        from stt_verifier.wer import normalize_text
        result = normalize_text("status 213")
        assert "two hundred" in result
        assert "thirteen" in result

    def test_collapse_whitespace(self):
        from stt_verifier.wer import normalize_text
        result = normalize_text("  hello   world  ")
        assert result == "hello world"


# ============================================================
# WER: compute_wer
# ============================================================

class TestComputeWER:
    def test_identical_strings(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("hello world", "hello world")
        assert r['wer'] == 0.0
        assert r['substitutions'] == 0
        assert r['insertions'] == 0
        assert r['deletions'] == 0

    def test_one_substitution(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("the cat sat", "the bat sat")
        assert abs(r['wer'] - 1 / 3) < 0.01
        assert r['substitutions'] == 1

    def test_one_deletion(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("screen reader on", "screen reader")
        assert r['deletions'] == 1
        assert r['insertions'] == 0
        assert abs(r['wer'] - 1 / 3) < 0.01

    def test_one_insertion(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("hello world", "hello beautiful world")
        assert r['insertions'] == 1
        assert r['deletions'] == 0
        assert abs(r['wer'] - 0.5) < 0.01

    def test_empty_ref_nonempty_hyp(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("", "hello")
        assert r['wer'] == float('inf')

    def test_both_empty(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("", "")
        assert r['wer'] == 0.0

    def test_case_insensitive_by_default(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("Hello World", "hello world")
        assert r['wer'] == 0.0

    def test_ref_len_field(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("one two three four", "one two three four")
        assert r['ref_len'] == 4

    def test_all_substitutions(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("cat dog bird", "red blue green")
        assert r['wer'] == 1.0
        assert r['substitutions'] == 3

    def test_multiple_deletions(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("one two three four five", "one five")
        assert r['deletions'] == 3
        assert r['insertions'] == 0

    def test_multiple_insertions(self):
        from stt_verifier.wer import compute_wer
        r = compute_wer("start end", "start middle extra words end")
        assert r['insertions'] == 3
        assert r['deletions'] == 0


# ============================================================
# Matcher: match_sequence
# ============================================================

class TestMatchSequence:
    def test_single_full_match(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(["screen reader on"], "screen reader on")
        assert len(r['matches']) == 1
        assert r['matches'][0]['status'] == 'full'
        assert r['matches'][0]['score'] > 0.9

    def test_two_full_matches(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(
            ["hello world", "good morning"],
            "hello world good morning",
        )
        assert len(r['matches']) == 2
        assert r['matches'][0]['status'] == 'full'
        assert r['matches'][1]['status'] == 'full'

    def test_partial_then_full(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(
            ["screen reader on", "twenty nine push button"],
            "screen reader twenty nine push button",
        )
        assert len(r['matches']) == 2
        # Second message must be a full match
        assert r['matches'][1]['status'] == 'full'
        # Overall score should be high
        assert r['overall_score'] > 0.5

    def test_clearly_partial(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(
            ["the quick brown fox jumps over the lazy dog", "hello world"],
            "the quick hello world",
        )
        assert len(r['matches']) == 2
        assert r['matches'][0]['status'] == 'partial'
        assert r['matches'][1]['status'] == 'full'

    def test_missing_message(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(["hello", "goodbye"], "hello")
        assert len(r['matches']) == 2
        assert r['matches'][0]['status'] == 'full'
        assert r['matches'][1]['status'] == 'missing'

    def test_overall_score_present(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(["hello world"], "hello world")
        assert 'overall_score' in r
        assert r['overall_score'] > 0.9

    def test_empty_transcription(self):
        from stt_verifier.matcher import match_sequence
        r = match_sequence(["hello"], "")
        assert r['matches'][0]['status'] == 'missing'

    def test_full_vs_partial_threshold(self):
        from stt_verifier.matcher import match_sequence
        r_strict = match_sequence(["hello world"], "hello world", threshold=0.0)
        assert r_strict['matches'][0]['status'] == 'full'
        r_strict2 = match_sequence(["hello world test"], "hello world", threshold=0.1)
        assert r_strict2['matches'][0]['status'] != 'full'


# ============================================================
# VAD: segment_utterances
# ============================================================

class TestVAD:
    @pytest.fixture
    def two_utterance_audio(self, tmp_path):
        """Generate audio with two utterances separated by silence."""
        import numpy as np
        import soundfile as sf

        utt1_path = str(tmp_path / "utt1.wav")
        utt2_path = str(tmp_path / "utt2.wav")
        combined_path = str(tmp_path / "combined.wav")

        subprocess.run(
            ['espeak-ng', '-w', utt1_path, '-s', '175', 'hello world'],
            check=True, capture_output=True,
        )
        subprocess.run(
            ['espeak-ng', '-w', utt2_path, '-s', '175', 'good morning'],
            check=True, capture_output=True,
        )

        audio1, sr1 = sf.read(utt1_path)
        audio2, sr2 = sf.read(utt2_path)
        assert sr1 == sr2

        silence = np.zeros(int(sr1 * 1.0))  # 1 second silence gap
        combined = np.concatenate([
            np.zeros(int(sr1 * 0.5)),
            audio1,
            silence,
            audio2,
            np.zeros(int(sr1 * 0.5)),
        ])
        sf.write(combined_path, combined, sr1)
        return combined_path

    def test_detects_two_segments(self, two_utterance_audio):
        from stt_verifier.vad import segment_utterances
        segments = segment_utterances(two_utterance_audio, min_silence_ms=500)
        assert len(segments) == 2

    def test_segment_timestamps(self, two_utterance_audio):
        from stt_verifier.vad import segment_utterances
        segments = segment_utterances(two_utterance_audio, min_silence_ms=500)
        for seg in segments:
            assert 'start' in seg
            assert 'end' in seg
            assert seg['end'] > seg['start']
            assert seg['start'] >= 0

    def test_segments_ordered(self, two_utterance_audio):
        from stt_verifier.vad import segment_utterances
        segments = segment_utterances(two_utterance_audio, min_silence_ms=500)
        if len(segments) >= 2:
            assert segments[1]['start'] > segments[0]['end']

    def test_silence_only(self, tmp_path):
        import numpy as np
        import soundfile as sf

        silence_path = str(tmp_path / "silence.wav")
        sf.write(silence_path, np.zeros(16000), 16000)

        from stt_verifier.vad import segment_utterances
        segments = segment_utterances(silence_path)
        assert len(segments) == 0

    def test_segment_duration_reasonable(self, two_utterance_audio):
        from stt_verifier.vad import segment_utterances
        segments = segment_utterances(two_utterance_audio, min_silence_ms=500)
        assert len(segments) == 2
        for seg in segments:
            duration = seg['end'] - seg['start']
            assert 0.2 < duration < 3.0, f"Segment duration {duration}s outside expected range"


# ============================================================
# JUnit XML generation
# ============================================================

class TestJUnitXML:
    def test_generates_valid_xml(self, tmp_path):
        from stt_verifier.junit import generate_junit_xml
        from lxml import etree

        results = [
            {'name': 'test_pass', 'passed': True, 'message': 'OK', 'time': 1.0},
            {'name': 'test_fail', 'passed': False, 'message': 'WER too high', 'time': 2.0},
        ]
        output = str(tmp_path / "results.xml")
        generate_junit_xml(results, output)

        assert os.path.exists(output)
        tree = etree.parse(output)
        testcases = tree.findall('.//testcase')
        assert len(testcases) == 2

    def test_failure_elements(self, tmp_path):
        from stt_verifier.junit import generate_junit_xml
        from lxml import etree

        results = [
            {'name': 'test_fail', 'passed': False, 'message': 'error msg', 'time': 1.0},
        ]
        output = str(tmp_path / "results.xml")
        generate_junit_xml(results, output)

        tree = etree.parse(output)
        failures = tree.findall('.//failure')
        assert len(failures) == 1

    def test_all_pass_no_failures(self, tmp_path):
        from stt_verifier.junit import generate_junit_xml
        from lxml import etree

        results = [
            {'name': 't1', 'passed': True, 'message': 'OK', 'time': 0.5},
            {'name': 't2', 'passed': True, 'message': 'OK', 'time': 0.5},
        ]
        output = str(tmp_path / "results.xml")
        generate_junit_xml(results, output)

        tree = etree.parse(output)
        failures = tree.findall('.//failure')
        assert len(failures) == 0


# ============================================================
# Pipeline CLI
# ============================================================

class TestPipelineCLI:
    def test_module_importable(self):
        from stt_verifier import pipeline  # noqa: F401

    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, '-m', 'stt_verifier.pipeline', '--help'],
            capture_output=True, text=True, cwd='/app',
        )
        assert result.returncode == 0
        assert '--spec' in result.stdout
        assert '--output' in result.stdout


# ============================================================
# Synthesize
# ============================================================

class TestSynthesize:
    def test_basic_synthesis(self, tmp_path):
        from stt_verifier.synthesize import synthesize_speech
        output = str(tmp_path / "output.wav")
        synthesize_speech("hello world", output)
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0

    def test_custom_rate(self, tmp_path):
        from stt_verifier.synthesize import synthesize_speech
        slow = str(tmp_path / "slow.wav")
        fast = str(tmp_path / "fast.wav")
        synthesize_speech("hello world good morning", slow, rate=100)
        synthesize_speech("hello world good morning", fast, rate=300)
        assert os.path.getsize(slow) > os.path.getsize(fast)

    def test_interrupted_audio(self, tmp_path):
        import soundfile as sf
        from stt_verifier.synthesize import create_interrupted_audio

        output = str(tmp_path / "interrupted.wav")
        utterances = [
            {'text': 'screen reader on', 'interrupt_after_ms': 600},
            {'text': 'push button'},
        ]
        create_interrupted_audio(utterances, output)
        assert os.path.exists(output)
        audio, sr = sf.read(output)
        assert len(audio) > 0


# ============================================================
# Integration
# ============================================================

class TestIntegration:
    def test_synthesize_then_vad(self, tmp_path):
        from stt_verifier.synthesize import synthesize_speech
        from stt_verifier.vad import segment_utterances

        output = str(tmp_path / "speech.wav")
        synthesize_speech("hello world this is a test", output)

        segments = segment_utterances(output, min_silence_ms=300)
        assert len(segments) >= 1
        assert segments[0]['end'] - segments[0]['start'] > 0.1
