"""End-to-end screen reader verification pipeline CLI."""
import argparse
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(
        description='Screen reader audio verification pipeline',
    )
    parser.add_argument('--spec', required=True, help='Path to YAML test specification')
    parser.add_argument('--output', required=True, help='Path for JUnit XML output')
    args = parser.parse_args()

    # Lazy imports so --help works without heavy deps
    import yaml
    from stt_verifier.synthesize import create_interrupted_audio
    from stt_verifier.transcribe import transcribe_audio
    from stt_verifier.matcher import match_sequence
    from stt_verifier.junit import generate_junit_xml

    with open(args.spec) as f:
        spec = yaml.safe_load(f)

    results = []
    all_pass = True

    for test in spec.get('tests', []):
        name = test['name']
        start_time = time.time()

        try:
            utterances = test['utterances']
            for u in utterances:
                if 'speech_rate' not in u:
                    u['speech_rate'] = test.get('speech_rate', 175)

            audio_path = f'/tmp/stt_test_{name}.wav'
            create_interrupted_audio(
                utterances, audio_path,
                silence_gap_ms=test.get('silence_gap_ms', 500),
            )

            transcription = transcribe_audio(audio_path)

            expected = test['expected_fragments']
            max_wer = test.get('max_wer', 0.5)
            match_result = match_sequence(expected, transcription, threshold=max_wer)

            passed = all(m['status'] == 'full' for m in match_result['matches'])
            message = f"Overall score: {match_result['overall_score']:.3f}"
            if not passed:
                all_pass = False
                details = []
                for m in match_result['matches']:
                    if m['status'] != 'full':
                        details.append(
                            f"{m['expected']}: {m['status']} (score={m['score']:.3f})"
                        )
                message += ' | ' + '; '.join(details)

            elapsed = time.time() - start_time
            results.append({
                'name': name,
                'passed': passed,
                'message': message,
                'time': elapsed,
            })

        except Exception as e:
            elapsed = time.time() - start_time
            results.append({
                'name': name,
                'passed': False,
                'message': str(e),
                'time': elapsed,
            })
            all_pass = False

    generate_junit_xml(results, args.output)
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
