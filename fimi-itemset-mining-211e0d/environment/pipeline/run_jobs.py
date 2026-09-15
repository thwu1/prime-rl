#!/usr/bin/env python3
"""Run all mining jobs specified in the configuration."""


import json
import subprocess
import sys
import os


def main():
    config_path = '/app/config/jobs.json'
    with open(config_path) as f:
        config = json.load(f)

    for job in config['jobs']:
        dataset = job['dataset']
        mode = job['mode']
        min_sup = job['min_support']
        output = job.get('output', '')

        # Normalize raw datasets before mining
        if '/raw/' in dataset:
            norm_dir = '/app/data/normalized'
            os.makedirs(norm_dir, exist_ok=True)
            basename = os.path.basename(dataset).rsplit('.', 1)[0] + '.dat'
            norm_path = os.path.join(norm_dir, basename)
            subprocess.run(
                ['python3', '/app/pipeline/normalizer.py', dataset, norm_path],
                check=True
            )
            dataset = norm_path

        if output:
            os.makedirs(os.path.dirname(output), exist_ok=True)

        cmd = ['python3', '/app/pipeline/miner.py', mode, dataset, str(min_sup)]
        if output:
            cmd.append(output)

        print(f"=== Job: {job['id']} ===")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout, end='')
        else:
            print(f"FAILED: {result.stderr}", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
