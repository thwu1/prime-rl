"""Probe the Toolathlon image and hosted task service from one VMVM lease."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from vmvm_backend import run_with_recovery
from vmvm_tb_v2._vacli.backend import VacliVMVMBackend, VacliVMVMConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image",
        default="docker.io/lockon0927/toolathlon-task-image:1016beta",
    )
    parser.add_argument("--lease-ttl", default="10m")
    parser.add_argument("--external-only", action="store_true")
    parser.add_argument("--search-image", action="store_true")
    parser.add_argument("--openapi", action="store_true")
    parser.add_argument("--service-limits", action="store_true")
    parser.add_argument("--service-url", default="http://47.253.57.66:8080")
    parser.add_argument("--fetch-url", action="append", default=[])
    parser.add_argument("--start-only", action="store_true")
    parser.add_argument("--start-task", default="woocommerce-update-cover")
    parser.add_argument("--inspect-task", default="ab-testing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backend = VacliVMVMBackend(
        VacliVMVMConfig(
            image_url=args.image,
            work_dir="/workspace",
            session_timeout=1800,
            lease_ttl=args.lease_ttl,
            max_session_buffer_size=4 * 1024 * 1024,
        )
    )
    try:
        if args.search_image:
            result = run_with_recovery(
                backend,
                r"""
set -u
printf '%s\n' '--- candidate files ---'
find / -xdev -type f \
  \( -name 'global_configs.py' -o -name 'token_key_session.py' \
     -o -name 'google_credentials.json' -o -name 'gcp-service_account.keys.json' \
     -o -name 'snowflake_rsa_key.p8' -o -name 'task_catalog.json' \
     -o -name 'tool_schemas.json' -o -name 'eval_server.py' \) \
  -print 2>/dev/null | sort | head -n 500
printf '%s\n' '--- relevant environment names ---'
env | cut -d= -f1 | grep -Ei \
  'TOOLATHLON|GOOGLE|GCP|SNOWFLAKE|NOTION|GITHUB|HUGGINGFACE|WANDB|CANVAS|WOOCOMMERCE|API_KEY|TOKEN' \
  | sort -u || true
printf '%s\n' '--- workspace tree ---'
find /workspace -maxdepth 3 -printf '%y %p\n' 2>/dev/null | sort | head -n 1000
""".strip(),
                timeout=300,
            )
            print(json.dumps(result, indent=2))
            if result["exit_code"] != 0:
                raise RuntimeError(f"Image search failed: {result}")
            return
        if args.fetch_url:
            urls = " ".join(shlex.quote(url) for url in args.fetch_url)
            result = run_with_recovery(
                backend,
                rf"""
set -u
for url in {urls}; do
  printf '\n--- %s ---\n' "$url"
  curl --location --silent --show-error --max-time 90 --range 0-200000 \
    --write-out '\nHTTP_STATUS=%{{http_code}} SIZE=%{{size_download}}\n' "$url" || true
done
""".strip(),
                timeout=max(120, 120 * len(args.fetch_url)),
            )
            print(json.dumps(result, indent=2))
            if result["exit_code"] != 0:
                raise RuntimeError(f"URL probe failed: {result}")
            return
        if args.openapi:
            result = run_with_recovery(
                backend,
                "curl --fail --location --silent --show-error --max-time 90 "
                f"{shlex.quote(args.service_url.rstrip('/') + '/openapi.json')}",
                timeout=120,
            )
            print(json.dumps(result, indent=2))
            if result["exit_code"] != 0:
                raise RuntimeError(f"OpenAPI probe failed: {result}")
            return
        if args.service_limits:
            endpoint = args.service_url.rstrip("/") + "/submit_evaluation"
            payload = json.dumps(
                {
                    "client_version": "1.3",
                    "mode": "private",
                    "base_url": "http://invalid",
                    "model_name": "capability-probe",
                    "workers": 1_000_000,
                    "ws_client_version": "1.3",
                },
                separators=(",", ":"),
            )
            result = run_with_recovery(
                backend,
                "curl --location --silent --show-error --max-time 90 "
                "--header 'Content-Type: application/json' --request POST "
                f"--data {shlex.quote(payload)} {shlex.quote(endpoint)}",
                timeout=120,
            )
            print(json.dumps(result, indent=2))
            if result["exit_code"] != 0:
                raise RuntimeError(f"Service-limit probe failed: {result}")
            return
        if args.external_only:
            result = run_with_recovery(
                backend,
                r"""
set -u
urls=(
  'https://toolathlon.xyz/docs/leaderboard.md'
  'https://toolathlon.xyz/docs/blog/toolathlon-verified.md'
  'https://huggingface.co/api/datasets/hkust-nlp/Toolathlon-Verified_Trajectories/tree/main?recursive=true&expand=false'
  'https://huggingface.co/datasets/hkust-nlp/Toolathlon-Verified_Trajectories/raw/main/README.md'
  'http://47.253.6.47:8080/check_server_status'
)
for index in "${!urls[@]}"; do
  url="${urls[$index]}"
  output="/tmp/toolathlon_external_${index}"
  printf '\n--- %s ---\n' "$url"
  status=$(curl --location --silent --show-error --max-time 90 \
    --write-out '%{http_code}' --output "$output" "$url" || true)
  printf 'status=%s bytes=' "$status"
  wc -c < "$output" 2>/dev/null || printf '0\n'
  printf '\n--- matches ---\n'
  grep -Ein -A 12 -B 2 \
    'Kimi|50([.]0)?%|original (benchmark|leaderboard|release)|legacy|sampling' \
    "$output" 2>/dev/null | head -n 400 || true
  printf '\n'
done
""".strip(),
                timeout=300,
            )
            print(json.dumps(result, indent=2))
            if result["exit_code"] != 0:
                raise RuntimeError(f"External probe failed: {result}")
            return
        backend.transfer_file(
            Path(__file__).with_name("worker.py").read_bytes(),
            "/opt/toolathlon/worker.py",
        )
        backend.transfer_file(
            Path(__file__).with_name("local_tools.py").read_bytes(),
            "/opt/toolathlon/local_tools.py",
        )
        if args.start_only:
            result = run_with_recovery(
                backend,
                "uv run --project /workspace --no-sync python "
                "/opt/toolathlon/worker.py --probe-start-task "
                f"{shlex.quote(args.start_task)}",
                timeout=240,
            )
            print(json.dumps(result, indent=2))
            if result["exit_code"] != 0:
                raise RuntimeError(f"Start probe failed: {result}")
            return
        command = r"""
set -u
printf 'python='; command -v python3 || command -v python
printf 'uv='; command -v uv
printf 'proxy='; printf '%s\n' "${http_proxy:-unset}"
printf 'workspace_entries='; find /workspace -mindepth 1 -maxdepth 1 -printf '%f,' | sort
printf '\ncredential_files='; find /workspace/configs -maxdepth 2 -type f \
  \( -name 'global_configs.py' -o -name 'token_key_session.py' \
     -o -name 'gcp-oauth.keys.json' -o -name 'google_credentials.json' \) \
  -printf '%P,' 2>/dev/null | sort || true
printf '\n'
uv run --project /workspace --no-sync python \
  /opt/toolathlon/worker.py --inspect-task __TASK_ID__
""".strip().replace("__TASK_ID__", shlex.quote(args.inspect_task))
        result = run_with_recovery(backend, command, timeout=1500)
        print(json.dumps(result, indent=2))
        if result["exit_code"] != 0:
            raise RuntimeError(f"VMVM probe failed: {result}")
    finally:
        backend.destroy()


if __name__ == "__main__":
    main()
