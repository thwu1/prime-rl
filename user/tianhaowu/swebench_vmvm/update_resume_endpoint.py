import argparse
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("base_url")
    parser.add_argument("run_id")
    return parser.parse_args()


def update_client_base_url(config_path: Path, base_url: str, run_id: str) -> Path:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid inference base URL: {base_url!r}")

    text = config_path.read_text()
    config = tomllib.loads(text)
    if not isinstance(config.get("client"), dict) or "base_url" not in config["client"]:
        raise ValueError(f"saved eval config has no client.base_url: {config_path}")

    lines = text.splitlines(keepends=True)
    in_client = False
    replacements = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_client = stripped == "[client]"
        elif in_client and stripped.startswith("base_url ="):
            ending = "\n" if line.endswith("\n") else ""
            lines[index] = f"base_url = {json.dumps(base_url)}{ending}"
            replacements += 1
    if replacements != 1:
        raise ValueError(f"expected one client.base_url in {config_path}, found {replacements}")

    backup = config_path.with_name(f"config.before-resume-{run_id}.toml")
    if backup.exists() and not backup.is_file():
        raise ValueError(f"resume config backup is not a file: {backup}")
    if not backup.exists():
        backup.write_text(text)
        shutil.copymode(config_path, backup)

    descriptor, temporary_name = tempfile.mkstemp(prefix=".config.", suffix=".toml", dir=config_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.writelines(lines)
        updated = tomllib.loads(temporary.read_text())
        if updated["client"]["base_url"] != base_url:
            raise ValueError("updated client.base_url did not round-trip through TOML")
        shutil.copymode(config_path, temporary)
        temporary.replace(config_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


def main() -> None:
    args = parse_args()
    backup = update_client_base_url(args.config.resolve(), args.base_url, args.run_id)
    print(f"saved prior eval config to {backup}")


if __name__ == "__main__":
    main()
