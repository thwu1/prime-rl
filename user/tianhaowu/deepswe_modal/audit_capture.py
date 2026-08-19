import argparse
from pathlib import Path

from request_capture import audit_captured_requests
from run_deepswe_modal import inference_router


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("driver_dir", type=Path)
    parser.add_argument("--inference-job-id", required=True)
    parser.add_argument("--latest-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    driver_dir = args.driver_dir.resolve()
    latest_dir = args.latest_dir.resolve() if args.latest_dir else driver_dir / "latest_requests"
    output_path = args.output.resolve() if args.output else driver_dir / "thinking_trajectory_audit.json"
    audit_captured_requests(
        inference_router(args.inference_job_id),
        latest_dir,
        driver_dir / "request_capture.jsonl",
        output_path,
    )
    print(f"Thinking trajectory audit passed: {output_path}", flush=True)


if __name__ == "__main__":
    main()
