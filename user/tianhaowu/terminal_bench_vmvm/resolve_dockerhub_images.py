#!/usr/bin/env python3
"""Resolve Harbor task slugs to immutable Docker Hub image digests."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _json_request(url: str, headers: dict[str, str] | None = None, retries: int = 8) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "prime-rl-terminal-bench/1", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"request failed after {retries} attempts: {url}") from last_error


def _registry_token(repository: str) -> str:
    query = urllib.parse.urlencode({"service": "registry.docker.io", "scope": f"repository:{repository}:pull"})
    token = _json_request(f"https://auth.docker.io/token?{query}").get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Docker registry did not issue an anonymous pull token")
    return token


def _registry_tags(repository: str, token: str) -> set[str]:
    url = f"https://registry-1.docker.io/v2/{repository}/tags/list?n=30000"
    payload = _json_request(url, {"Authorization": f"Bearer {token}"})
    return {str(tag) for tag in payload.get("tags", [])}


def _manifest_digest(repository: str, tag: str, token: str, retries: int = 8) -> str:
    quoted_tag = urllib.parse.quote(tag, safe="")
    url = f"https://registry-1.docker.io/v2/{repository}/manifests/{quoted_tag}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": ", ".join(
            (
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            )
        ),
        "User-Agent": "prime-rl-terminal-bench/1",
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers, method="HEAD")
            with urllib.request.urlopen(request, timeout=60) as response:
                digest = response.headers.get("Docker-Content-Digest")
            if isinstance(digest, str) and digest.startswith("sha256:"):
                return digest
            raise RuntimeError(f"manifest response omitted Docker-Content-Digest for {tag}")
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"failed to resolve manifest digest for {tag}") from last_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--repository", default="tianhao0122/optimbench-tb")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--max-workers", type=int, default=16)
    args = parser.parse_args()

    task_dirs = [
        path
        for path in sorted(args.dataset_dir.resolve().iterdir())
        if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
    ]
    expected = {path.name for path in task_dirs}
    if not expected:
        raise SystemExit("dataset has no immediate-child Harbor tasks")

    # Assert directory slugs and declared Harbor names still correspond before
    # trusting a tag lookup keyed by the directory name.
    for task_dir in task_dirs:
        config = tomllib.loads((task_dir / "task.toml").read_text())
        declared = config.get("task", {}).get("name", "")
        if declared.rsplit("/", 1)[-1] != task_dir.name:
            raise SystemExit(f"task slug/name mismatch: {task_dir.name} vs {declared}")

    token = _registry_token(args.repository)
    published = _registry_tags(args.repository, token)
    missing_tags = sorted(expected - published)
    resolvable = sorted(expected & published)
    partial_path = args.output.with_suffix(".partial.json")
    found: dict[str, dict[str, str]] = {}
    if partial_path.is_file():
        partial = json.loads(partial_path.read_text())
        if partial.get("repository") == args.repository:
            found = {
                slug: entry
                for slug, entry in partial.get("found", {}).items()
                if slug in expected and isinstance(entry, dict) and "agent" in entry
            }

    pending = [slug for slug in resolvable if slug not in found]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(_manifest_digest, args.repository, slug, token): slug for slug in pending}
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            slug = futures[future]
            digest = future.result()
            found[slug] = {
                "agent": f"docker.io/{args.repository}:{slug}@{digest}",
                "tag": slug,
                "digest": digest,
            }
            if completed == 1 or completed % 100 == 0 or completed == len(pending):
                _atomic_json(
                    partial_path,
                    {"repository": args.repository, "found": found},
                )
                print(f"digests={len(found)}/{len(resolvable)}", flush=True)

    missing = sorted(expected - found.keys())
    output = {
        "schema_version": 1,
        "repository": args.repository,
        "tasks": len(expected),
        "published_tags": len(published),
        "resolved": len(found),
        "missing_tags": missing_tags,
        "missing": missing,
        "images": {slug: found[slug] for slug in sorted(found)},
    }
    _atomic_json(args.output, output)
    print(
        json.dumps(
            {key: output[key] for key in ("repository", "tasks", "published_tags", "resolved", "missing")},
            indent=2,
        )
    )
    if args.require_all and missing:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
