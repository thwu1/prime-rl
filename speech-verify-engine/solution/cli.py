"""CLI entry point for sr_verify."""
import sys
import argparse

from .normalizer import normalize
from .metrics import wer


def main():
    parser = argparse.ArgumentParser(prog='sr_verify',
                                     description='Screen reader speech verification engine')
    subparsers = parser.add_subparsers(dest='command')

    verify_p = subparsers.add_parser('verify', help='Run verification on a scenario')
    verify_p.add_argument('scenario', help='Path to scenario JSON file')
    verify_p.add_argument('--output', '-o', help='Output JUnit XML path')
    verify_p.add_argument('--model', default='tiny', help='Whisper model name')

    norm_p = subparsers.add_parser('normalize', help='Normalize text')
    norm_p.add_argument('text', help='Text to normalize')

    wer_p = subparsers.add_parser('wer', help='Compute WER')
    wer_p.add_argument('reference', help='Reference text')
    wer_p.add_argument('hypothesis', help='Hypothesis text')

    args = parser.parse_args()

    if args.command == 'verify':
        from .pipeline import run_scenario
        result = run_scenario(args.scenario, args.output, args.model)
        for r in result['results']:
            status = 'PASS' if r['passed'] else 'FAIL'
            print(f"[{status}] utterance_{r['utterance_id']}: WER={r['wer']:.3f}")
        print(f"\nOverall WER: {result['overall_wer']:.3f}")
    elif args.command == 'normalize':
        print(normalize(args.text))
    elif args.command == 'wer':
        score = wer(args.reference, args.hypothesis)
        print(f"{score:.4f}")
    else:
        parser.print_help()
        sys.exit(1)
