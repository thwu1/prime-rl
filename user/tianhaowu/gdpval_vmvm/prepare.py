from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from asset_fetch import bind_manifest_to_catalog, load_asset_manifest, mirror_provenance
from common import atomic_write_json, load_jsonl, sha256_file

PARQUET_FILE = "data/train-00000-of-00001.parquet"


def _json_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _pin_asset_urls(urls: Any, *, dataset: str, revision: str) -> list[str]:
    values = _json_value(urls)
    if not isinstance(values, list):
        return []
    prefix = f"https://huggingface.co/datasets/{dataset}/resolve/"
    pinned: list[str] = []
    for value in values:
        url = str(value)
        if not url.startswith(prefix):
            raise ValueError(f"Unexpected GDPval asset URL: {url}")
        _, separator, filename = url[len(prefix) :].partition("/")
        if not separator:
            raise ValueError(f"Malformed GDPval asset URL: {url}")
        pinned.append(f"{prefix}{revision}/{filename}")
    return pinned


def _pin_hf_uris(uris: Any, *, dataset: str, revision: str) -> list[str]:
    values = _json_value(uris)
    if not isinstance(values, list):
        return []
    prefix = f"hf://datasets/{dataset}@"
    pinned: list[str] = []
    for value in values:
        uri = str(value)
        if not uri.startswith(prefix):
            raise ValueError(f"Unexpected GDPval asset URI: {uri}")
        _, separator, filename = uri[len(prefix) :].partition("/")
        if not separator:
            raise ValueError(f"Malformed GDPval asset URI: {uri}")
        pinned.append(f"{prefix}{revision}/{filename}")
    return pinned


def prepare(config: dict[str, Any]) -> Path:
    from datasets import load_dataset
    from huggingface_hub import hf_hub_download

    source = config["source"]
    dataset_name = str(source["dataset"])
    dataset_revision = str(source["dataset_revision"])
    catalog_path = Path(source["catalog_file"]).expanduser().resolve()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_url = source.get("dataset_mirror_url")
    if mirror_url:
        descriptor, temporary_name = tempfile.mkstemp(prefix="gdpval-parquet-", suffix=".parquet")
        os.close(descriptor)
        parquet_path = Path(temporary_name)
        try:
            with urllib.request.urlopen(str(mirror_url), timeout=120) as response, parquet_path.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        except Exception:
            parquet_path.unlink(missing_ok=True)
            raise
        transport = {"type": "sha256-verified-github-mirror", "url": mirror_url}
    else:
        parquet_path = Path(
            hf_hub_download(
                repo_id=str(source["dataset"]),
                repo_type="dataset",
                filename=PARQUET_FILE,
                revision=str(source["dataset_revision"]),
                token=os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"),
            )
        )
        transport = {"type": "huggingface_hub", "path": str(parquet_path)}
    actual_sha256 = sha256_file(parquet_path)
    expected_sha256 = str(source["dataset_parquet_sha256"])
    if actual_sha256 != expected_sha256:
        raise ValueError(f"GDPval parquet checksum mismatch: expected {expected_sha256}, got {actual_sha256}")

    dataset = load_dataset("parquet", data_files=str(parquet_path), split="train")
    expected_tasks = int(config["benchmark"]["expected_tasks"])
    if len(dataset) != expected_tasks:
        raise ValueError(f"Expected {expected_tasks} GDPval tasks, found {len(dataset)}")

    temporary = catalog_path.with_suffix(catalog_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        seen: set[str] = set()
        sectors: set[str] = set()
        occupations: set[str] = set()
        reference_count = 0
        deliverable_count = 0
        rubric_count = 0
        for raw in dataset:
            task_id = str(raw["task_id"])
            if task_id in seen:
                raise ValueError(f"Duplicate GDPval task_id: {task_id}")
            seen.add(task_id)
            sectors.add(str(raw.get("sector", "")))
            occupations.add(str(raw.get("occupation", "")))
            references = _json_value(raw.get("reference_files", []))
            deliverables = _json_value(raw.get("deliverable_files", []))
            rubric_json = _json_value(raw.get("rubric_json", {}))
            parsed_rubric = json.loads(rubric_json) if isinstance(rubric_json, str) else rubric_json
            reference_count += len(references)
            deliverable_count += len(deliverables)
            rubric_count += (
                len(parsed_rubric) if isinstance(parsed_rubric, list) else len(parsed_rubric.get("criteria", []))
            )
            row = {
                "task_id": task_id,
                "sector": raw.get("sector", ""),
                "occupation": raw.get("occupation", ""),
                "prompt": raw["prompt"],
                "reference_files": references,
                "reference_file_urls": _pin_asset_urls(
                    raw.get("reference_file_urls", []),
                    dataset=dataset_name,
                    revision=dataset_revision,
                ),
                "reference_file_hf_uris": _pin_hf_uris(
                    raw.get("reference_file_hf_uris", []),
                    dataset=dataset_name,
                    revision=dataset_revision,
                ),
                "deliverable_files": deliverables,
                "deliverable_file_urls": _pin_asset_urls(
                    raw.get("deliverable_file_urls", []),
                    dataset=dataset_name,
                    revision=dataset_revision,
                ),
                "deliverable_file_hf_uris": _pin_hf_uris(
                    raw.get("deliverable_file_hf_uris", []),
                    dataset=dataset_name,
                    revision=dataset_revision,
                ),
                "rubric_json": rubric_json,
                "rubric_pretty": raw.get("rubric_pretty", ""),
            }
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    observed = {
        "tasks": len(seen),
        "sectors": len(sectors),
        "occupations": len(occupations),
        "reference_files": reference_count,
        "deliverable_files": deliverable_count,
        "rubric_items": rubric_count,
    }
    expected = {
        "tasks": 220,
        "sectors": 9,
        "occupations": 44,
        "reference_files": 261,
        "deliverable_files": 248,
        "rubric_items": 10_453,
    }
    if observed != expected:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"Pinned GDPval release shape mismatch: expected {expected}, got {observed}")
    asset_manifest = load_asset_manifest(config)
    try:
        asset_shape = bind_manifest_to_catalog(asset_manifest, load_jsonl(temporary))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, catalog_path)
    atomic_write_json(
        catalog_path.with_suffix(catalog_path.suffix + ".provenance.json"),
        {
            "dataset": source["dataset"],
            "revision": source["dataset_revision"],
            "parquet_file": PARQUET_FILE,
            "parquet_sha256": actual_sha256,
            "catalog_sha256": sha256_file(catalog_path),
            "tasks": len(dataset),
            "shape": observed,
            "transport": transport,
            "asset_mirror": mirror_provenance(source) | {"shape": asset_shape},
        },
    )
    if mirror_url:
        parquet_path.unlink(missing_ok=True)
    return catalog_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    import tomllib

    path = prepare(tomllib.loads(args.config.read_text(encoding="utf-8")))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
