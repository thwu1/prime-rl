#!/usr/bin/env python3
"""CLI for speech feature extraction.


Usage:
    python3 /app/extract.py <phonation|prosody> <static|dynamic> <wav_path>
"""

import sys
import os
import subprocess
import tempfile
import numpy as np


def preprocess(wav_path):
    """Preprocess audio through SoX pipeline."""
    fd, tmp_path = tempfile.mkstemp(suffix='.wav')
    os.close(fd)
    result = subprocess.run(
        ['bash', '/app/preprocess.sh', wav_path, tmp_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise RuntimeError(f"preprocess.sh failed: {result.stderr}")
    return tmp_path


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 /app/extract.py <phonation|prosody> "
              "<static|dynamic> <wav_path>", file=sys.stderr)
        sys.exit(1)

    module_name = sys.argv[1]
    mode = sys.argv[2]
    wav_path = sys.argv[3]

    # Preprocess through SoX
    preprocessed = preprocess(wav_path)

    try:
        if module_name == 'phonation':
            import phonation
            if mode == 'static':
                features = phonation.extract_static(preprocessed)
            elif mode == 'dynamic':
                features = phonation.extract_dynamic(preprocessed)
            else:
                print(f"Unknown mode: {mode}", file=sys.stderr)
                sys.exit(1)
        elif module_name == 'prosody':
            import prosody
            if mode == 'static':
                features = prosody.extract_static(preprocessed)
            elif mode == 'dynamic':
                features = prosody.extract_dynamic(preprocessed)
            else:
                print(f"Unknown mode: {mode}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Unknown module: {module_name}", file=sys.stderr)
            sys.exit(1)

        if features.ndim == 1:
            print(','.join(f'{v}' for v in features))
        else:
            for row in features:
                print(','.join(f'{v}' for v in row))
    finally:
        if os.path.exists(preprocessed):
            os.unlink(preprocessed)


if __name__ == '__main__':
    main()
