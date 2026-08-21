import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("instance_id")
    parser.add_argument("instance_path", type=Path)
    parser.add_argument("status_path", type=Path)
    return parser.parse_args()


def find_patch(output_dir: Path, instance_id: str) -> str:
    for output_path in sorted(output_dir.rglob("output.jsonl")):
        for line in output_path.read_text().splitlines():
            result = json.loads(line)
            if result.get("instance_id") == instance_id:
                return result.get("test_result", {}).get("git_patch", "")
    raise FileNotFoundError(f"No OpenHands result found for {instance_id} in {output_dir}")


def workspace_patch(instance: dict) -> str:
    workspace_name = f"{instance['repo']}__{instance['version']}".replace("/", "__")
    workspace = Path("/workspace") / workspace_name
    result = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "diff",
            "--no-color",
            "--binary",
            "--full-index",
            "--cached",
            instance["base_commit"],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def normalize_patch(patch: str) -> str:
    if not patch.strip():
        return ""
    lines = patch.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if line.startswith("diff --git"):
            return "\n".join(lines[index:]).rstrip() + "\n"
    return ""


def main() -> None:
    args = parse_args()
    instance = json.loads(args.instance_path.read_text().splitlines()[0])
    serialized_patch = normalize_patch(find_patch(args.output_dir, args.instance_id))
    patch = normalize_patch(workspace_patch(instance))
    status = {
        "applied": False,
        "bytes": len(patch.encode()),
        "mode": "empty",
        "patch": patch,
        "sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "serialized_matches_workspace": serialized_patch == patch,
        "serialized_sha256": hashlib.sha256(serialized_patch.encode()).hexdigest(),
        "source": "workspace",
    }
    subprocess.run(
        ["git", "-C", "/testbed", "reset", "--hard", instance["base_commit"]],
        check=True,
    )
    if not patch.strip():
        args.status_path.write_text(json.dumps(status))
        return
    patch_path = Path("/tmp/openhands.patch")
    patch_path.write_text(patch)
    applied = subprocess.run(
        [
            "git",
            "-C",
            "/testbed",
            "apply",
            "--index",
            "--whitespace=nowarn",
            str(patch_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if applied.returncode == 0:
        status.update(applied=True, mode="direct")
        args.status_path.write_text(json.dumps(status))
        return
    subprocess.run(
        ["git", "-C", "/testbed", "reset", "--hard", instance["base_commit"]],
        check=True,
    )
    recounted = subprocess.run(
        [
            "git",
            "-C",
            "/testbed",
            "apply",
            "--index",
            "--recount",
            "--whitespace=nowarn",
            str(patch_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if recounted.returncode == 0:
        status.update(applied=True, mode="recount")
        args.status_path.write_text(json.dumps(status))
        return
    subprocess.run(
        ["git", "-C", "/testbed", "reset", "--hard", instance["base_commit"]],
        check=True,
    )
    status.update(mode="invalid", error=recounted.stderr.strip())
    args.status_path.write_text(json.dumps(status))
    print(f"OpenHands returned an invalid patch; scoring the unchanged repository:\n{recounted.stderr.strip()}")


if __name__ == "__main__":
    main()
