"""End-to-end speech verification pipeline."""
import json
import os
import subprocess
import tempfile

from .interruptions import compute_heard_text
from .metrics import segmented_wer
from .normalizer import normalize
from .reporter import generate_junit_xml


def run_scenario(scenario_path, output_path=None, whisper_model="tiny"):
    """Run full verification pipeline on a scenario JSON file.

    Loads scenario, computes heard texts from interruption metadata,
    synthesizes audio via espeak-ng, transcribes with openai-whisper,
    runs segmented alignment, and optionally writes JUnit XML.
    """
    with open(scenario_path) as f:
        scenario = json.load(f)

    name = scenario['name']
    utterances = scenario['utterances']

    # Map utterance IDs to their data
    utt_by_id = {u['id']: u for u in utterances}

    # Build interruption map: which utterances are interrupted and by whom
    interrupted_by = {}
    for u in utterances:
        target = u.get('interrupts')
        if target is not None:
            interrupted_by[target] = u

    # Compute heard text for each utterance
    segments = []
    for u in utterances:
        if u['id'] in interrupted_by:
            interruptor = interrupted_by[u['id']]
            actual_duration = interruptor['start_ms'] - u['start_ms']
            heard = compute_heard_text(u['text'], u['duration_ms'], actual_duration)
            is_interrupted = True
        else:
            heard = u['text']
            is_interrupted = False

        threshold = 0.5 if is_interrupted else 0.3
        segments.append({
            'id': u['id'],
            'text': u['text'],
            'heard': heard,
            'interrupted': is_interrupted,
            'threshold': threshold,
        })

    active_segments = [s for s in segments if s['heard']]

    if not active_segments:
        results = [{
            'utterance_id': s['id'],
            'expected_text': s['text'],
            'heard_text': '',
            'hypothesis_text': '',
            'wer': 0.0,
            'passed': True,
            'threshold': s['threshold'],
        } for s in segments]
        if output_path:
            with open(output_path, 'w') as f:
                f.write(generate_junit_xml(name, results))
        return {'name': name, 'results': results, 'overall_wer': 0.0}

    # Synthesize each heard segment with espeak-ng
    wav_files = []
    for seg in active_segments:
        fd, path = tempfile.mkstemp(suffix='.wav')
        os.close(fd)
        subprocess.run(
            ['espeak-ng', '-w', path, seg['heard']],
            check=True, capture_output=True,
        )
        wav_files.append(path)

    # Concatenate WAV files
    if len(wav_files) == 1:
        combined_wav = wav_files[0]
    else:
        fd, combined_wav = tempfile.mkstemp(suffix='.wav')
        os.close(fd)
        fd, concat_list = tempfile.mkstemp(suffix='.txt')
        with os.fdopen(fd, 'w') as f:
            for wf in wav_files:
                f.write(f"file '{wf}'\n")
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
             '-i', concat_list, '-c', 'copy', combined_wav],
            check=True, capture_output=True,
        )
        os.unlink(concat_list)

    # Transcribe with Whisper
    import whisper
    model = whisper.load_model(whisper_model)
    result = model.transcribe(combined_wav)
    transcription = result['text'].strip()

    # Run segmented alignment
    hyp_words = normalize(transcription).split()
    ref_segments_norm = [normalize(s['heard']).split() for s in active_segments]

    overall_wer_val, seg_results = segmented_wer(hyp_words, ref_segments_norm)

    # Build results
    results = []
    seg_idx = 0
    for s in segments:
        if s['heard']:
            sr = seg_results[seg_idx]
            seg_wer = sr.wer
            hyp_text = ' '.join(sr.hyp_words)
            seg_idx += 1
        else:
            seg_wer = 0.0
            hyp_text = ''

        passed = seg_wer <= s['threshold']
        results.append({
            'utterance_id': s['id'],
            'expected_text': s['text'],
            'heard_text': s['heard'],
            'hypothesis_text': hyp_text,
            'wer': seg_wer,
            'passed': passed,
            'threshold': s['threshold'],
        })

    if output_path:
        with open(output_path, 'w') as f:
            f.write(generate_junit_xml(name, results))

    # Cleanup
    for wf in wav_files:
        if os.path.exists(wf):
            os.unlink(wf)
    if len(wav_files) > 1 and os.path.exists(combined_wav):
        os.unlink(combined_wav)

    return {'name': name, 'results': results, 'overall_wer': overall_wer_val}
