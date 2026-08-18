import argparse
from pathlib import Path

from request_capture import audit_captured_requests
from run_deepswe_modal import inference_router


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("driver_dir", type=Path)
    parser.add_argument("--inference-job-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    driver_dir = args.driver_dir.resolve()
    audit_captured_requests(
        inference_router(args.inference_job_id),
        driver_dir / "latest_requests",
        driver_dir / "request_capture.jsonl",
        driver_dir / "thinking_trajectory_audit.json",
    )
    print(f"Thinking trajectory audit passed: {driver_dir}", flush=True)


if __name__ == "__main__":
    main()
