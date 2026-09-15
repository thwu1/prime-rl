"""Run all experiments and collect results into results.json."""
import subprocess
import json
import os


def main():
    experiments_dir = '/app/lab/experiments'
    results = {}

    for exp in sorted(os.listdir(experiments_dir)):
        exp_dir = os.path.join(experiments_dir, exp)
        script = os.path.join(exp_dir, 'compute.py')
        if os.path.isdir(exp_dir) and os.path.exists(script):
            print(f"Running {exp}...")
            proc = subprocess.run(
                ['python3', 'compute.py'],
                cwd=exp_dir,
                capture_output=True,
                text=True,
                timeout=300
            )
            if proc.returncode != 0:
                print(f"  ERROR: {proc.stderr}")
                continue
            for line in proc.stdout.strip().split('\n'):
                if line.startswith('RESULT:'):
                    val_str = line.split('RESULT:')[1].strip()
                    try:
                        val = int(val_str)
                    except ValueError:
                        val = float(val_str)
                    results[exp] = val
                    print(f"  -> {val}")

    out_path = '/app/lab/results.json'
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {len(results)} results to {out_path}")


if __name__ == "__main__":
    main()
