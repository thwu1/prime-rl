from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_HEADER = r"# task_id\tcatalog_path\tmirror_path\tstorage\tsize\tsha256\tgit_blob_oid"
PUBLIC_ASSET_KEYS = (
    "path",
    "mirror_path",
    "storage",
    "size",
    "sha256",
    "git_blob_oid",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_OID_RE = re.compile(r"[0-9a-f]{40}")


class AssetManifestError(ValueError):
    pass


class PermanentDownloadError(RuntimeError):
    pass


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise AssetManifestError(f"Unsafe asset path: {value!r}")
    return Path(*path.parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_oid(path: Path, size: int) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {size}\0".encode())
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_oid_bytes(content: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(content)}\0".encode())
    digest.update(content)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_path(source: dict[str, Any]) -> Path:
    name = str(source["asset_manifest_file"])
    relative = _safe_relative(name)
    if len(relative.parts) != 1:
        raise AssetManifestError("source.asset_manifest_file must name a file beside asset_fetch.py")
    return Path(__file__).with_name(relative.name)


def mirror_provenance(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "repository": str(source["asset_mirror_repository"]),
        "commit": str(source["asset_mirror_commit"]),
        "tasks_tree": str(source["asset_mirror_tasks_tree"]),
        "manifest_file": str(source["asset_manifest_file"]),
        "manifest_sha256": str(source["asset_manifest_sha256"]),
    }


def load_asset_manifest(config: dict[str, Any]) -> list[dict[str, Any]]:
    source = config["source"]
    path = _manifest_path(source)
    expected_manifest_sha256 = str(source["asset_manifest_sha256"])
    actual_manifest_sha256 = _sha256(path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise AssetManifestError(
            "GDPval asset manifest checksum mismatch: "
            f"expected {expected_manifest_sha256}, got {actual_manifest_sha256}"
        )

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != MANIFEST_HEADER:
        raise AssetManifestError(f"Unexpected GDPval asset manifest header: {path}")
    entries: list[dict[str, Any]] = []
    keys: set[tuple[str, str]] = set()
    catalog_paths: set[str] = set()
    mirror_paths: set[str] = set()
    for line_number, line in enumerate(lines[1:], 2):
        values = line.split("\t")
        if len(values) != 7:
            raise AssetManifestError(f"Expected seven TSV fields in {path}:{line_number}")
        task_id, catalog_path, mirror_path, storage, size_text, sha256, git_blob_oid = values
        if not task_id:
            raise AssetManifestError(f"Missing task ID in {path}:{line_number}")
        catalog_relative = _safe_relative(catalog_path).as_posix()
        mirror_relative = _safe_relative(mirror_path).as_posix()
        if storage not in {"git", "git-lfs"}:
            raise AssetManifestError(f"Unknown storage type in {path}:{line_number}: {storage!r}")
        try:
            size = int(size_text)
        except ValueError as error:
            raise AssetManifestError(f"Invalid asset size in {path}:{line_number}: {size_text!r}") from error
        if size <= 0:
            raise AssetManifestError(f"Asset size must be positive in {path}:{line_number}")
        if SHA256_RE.fullmatch(sha256) is None or GIT_OID_RE.fullmatch(git_blob_oid) is None:
            raise AssetManifestError(f"Invalid asset digest in {path}:{line_number}")
        if catalog_relative.startswith("reference_files/"):
            expected_folder = "refs"
        elif catalog_relative.startswith("deliverable_files/"):
            expected_folder = "gold"
        else:
            raise AssetManifestError(f"Unexpected catalog path in {path}:{line_number}: {catalog_path!r}")
        mirror_parts = PurePosixPath(mirror_relative).parts
        if (
            len(mirror_parts) < 5
            or mirror_parts[:2] != ("gdpval-bench", "tasks")
            or not mirror_parts[2].isdigit()
            or mirror_parts[3] != expected_folder
            or PurePosixPath(catalog_relative).name != PurePosixPath(mirror_relative).name
        ):
            raise AssetManifestError(f"Catalog/mirror path mismatch in {path}:{line_number}")
        if storage == "git-lfs":
            pointer = (f"version https://git-lfs.github.com/spec/v1\noid sha256:{sha256}\nsize {size}\n").encode()
            if _git_blob_oid_bytes(pointer) != git_blob_oid:
                raise AssetManifestError(f"Git LFS pointer digest mismatch in {path}:{line_number}")
        key = task_id, catalog_relative
        if key in keys or catalog_relative in catalog_paths or mirror_relative in mirror_paths:
            raise AssetManifestError(f"Duplicate asset in {path}:{line_number}")
        keys.add(key)
        catalog_paths.add(catalog_relative)
        mirror_paths.add(mirror_relative)
        entries.append(
            {
                "task_id": task_id,
                "catalog_path": catalog_relative,
                "mirror_path": mirror_relative,
                "storage": storage,
                "size": size,
                "sha256": sha256,
                "git_blob_oid": git_blob_oid,
            }
        )
    if len(entries) != 509:
        raise AssetManifestError(f"Expected 509 GDPval assets, found {len(entries)}")
    return entries


def bind_manifest_to_catalog(
    manifest: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    expected: list[tuple[str, str, str]] = []
    for task_index, task in enumerate(catalog):
        task_id = str(task["task_id"])
        for key, folder in (("reference_files", "refs"), ("deliverable_files", "gold")):
            for value in task.get(key) or []:
                catalog_path = _safe_relative(str(value)).as_posix()
                mirror_path = (
                    PurePosixPath("gdpval-bench", "tasks", str(task_index), folder) / PurePosixPath(catalog_path).name
                ).as_posix()
                expected.append((task_id, catalog_path, mirror_path))
    actual = [(item["task_id"], item["catalog_path"], item["mirror_path"]) for item in manifest]
    if actual != expected:
        for index, (observed, wanted) in enumerate(zip(actual, expected)):
            if observed != wanted:
                raise AssetManifestError(
                    f"GDPval asset manifest/catalog mismatch at entry {index}: expected {wanted}, got {observed}"
                )
        raise AssetManifestError(
            f"GDPval asset manifest/catalog length mismatch: expected {len(expected)}, got {len(actual)}"
        )
    return {
        "entries": len(manifest),
        "reference_files": sum(item["catalog_path"].startswith("reference_files/") for item in manifest),
        "deliverable_files": sum(item["catalog_path"].startswith("deliverable_files/") for item in manifest),
        "git_blobs": sum(item["storage"] == "git" for item in manifest),
        "git_lfs_objects": sum(item["storage"] == "git-lfs" for item in manifest),
        "logical_bytes": sum(int(item["size"]) for item in manifest),
    }


def select_manifest_entries(
    manifest: list[dict[str, Any]],
    required: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    by_key = {(item["task_id"], item["catalog_path"]): item for item in manifest}
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for task_id, catalog_path in required:
        key = str(task_id), _safe_relative(catalog_path).as_posix()
        if key in seen:
            continue
        seen.add(key)
        try:
            selected.append(dict(by_key[key]))
        except KeyError as error:
            raise AssetManifestError(f"Asset is missing from the pinned mirror manifest: {key}") from error
    return selected


def asset_specs(
    task: dict[str, Any],
    config: dict[str, Any],
    *,
    catalog_key: str,
) -> list[dict[str, Any]]:
    manifest = load_asset_manifest(config)
    required = [(str(task["task_id"]), str(path)) for path in task.get(catalog_key) or []]
    return [
        {
            "path": item["catalog_path"],
            **{key: item[key] for key in PUBLIC_ASSET_KEYS if key != "path"},
        }
        for item in select_manifest_entries(manifest, required)
    ]


def _selected_manifest_sha256(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _cache_provenance(config: dict[str, Any], manifest: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        **mirror_provenance(config["source"]),
        "manifest_entries": len(manifest),
    }


def _cache_root(config: dict[str, Any]) -> Path:
    return Path(config["source"]["asset_cache_dir"]).expanduser().resolve()


def _cache_file(config: dict[str, Any], entry: dict[str, Any]) -> Path:
    root = _cache_root(config)
    path = (root / _safe_relative(str(entry["catalog_path"]))).resolve()
    if not path.is_relative_to(root):
        raise AssetManifestError(f"Asset cache path escapes its root: {entry['catalog_path']}")
    return path


def asset_selection_provenance(
    config: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **mirror_provenance(config["source"]),
        "selected_manifest_sha256": _selected_manifest_sha256(entries),
        "selected_assets": len(entries),
        "selected_bytes": sum(int(item["size"]) for item in entries),
        "selected_git_blobs": sum(item["storage"] == "git" for item in entries),
        "selected_git_lfs_objects": sum(item["storage"] == "git-lfs" for item in entries),
    }


def _validate_cached_file(path: Path, entry: dict[str, Any], *, verify_hash: bool) -> str | None:
    if not path.is_file():
        return "missing"
    if path.stat().st_size != int(entry["size"]):
        return "size"
    if verify_hash and _sha256(path) != entry["sha256"]:
        return "sha256"
    if verify_hash and entry["storage"] == "git" and _git_blob_oid(path, int(entry["size"])) != entry["git_blob_oid"]:
        return "git_blob_oid"
    logical_path = entry.get("catalog_path", entry.get("path", path.name))
    if Path(str(logical_path)).suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                archive.infolist()
                if archive.testzip() is not None:
                    return "zip_crc"
        except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
            return "zip_structure"
    return None


def asset_cache_status(
    config: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    root = _cache_root(config)
    manifest = load_asset_manifest(config)
    expected_provenance = _cache_provenance(config, manifest)
    provenance_path = root / ".gdpval-asset-mirror.json"
    provenance_ok = False
    provenance_error: str | None = None
    if provenance_path.is_file():
        try:
            provenance_ok = json.loads(provenance_path.read_text(encoding="utf-8")) == expected_provenance
            if not provenance_ok:
                provenance_error = "cache provenance differs from the configured mirror"
        except (OSError, json.JSONDecodeError) as error:
            provenance_error = f"{type(error).__name__}: {error}"
    else:
        provenance_error = "cache provenance is missing"

    missing: list[str] = []
    corrupt: list[dict[str, str]] = []
    cached = 0
    for entry in entries:
        issue = _validate_cached_file(_cache_file(config, entry), entry, verify_hash=verify_hashes)
        if issue == "missing":
            missing.append(str(entry["catalog_path"]))
        elif issue:
            corrupt.append({"path": str(entry["catalog_path"]), "reason": issue})
        else:
            cached += 1
    return {
        **asset_selection_provenance(config, entries),
        "cache_dir": str(root),
        "cached_assets": cached,
        "missing_assets": len(missing),
        "missing_asset_sample": missing[:10],
        "corrupt_assets": len(corrupt),
        "corrupt_asset_sample": corrupt[:10],
        "provenance_ok": provenance_ok,
        "provenance_error": provenance_error,
        "hashes_verified": verify_hashes,
        "ready": provenance_ok and not missing and not corrupt,
    }


def _request_bytes(request: urllib.request.Request, *, timeout: float = 300) -> bytes:
    last_error: BaseException | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in {408, 409, 429} and error.code < 500:
                raise PermanentDownloadError(f"HTTP {error.code} for {request.full_url}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt < 5:
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"Request failed after 6 attempts for {request.full_url}: {last_error}")


def _lfs_download_actions(config: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not entries:
        return {}
    source = config["source"]
    repository = str(source["asset_mirror_repository"])
    endpoint = f"https://github.com/{repository}.git/info/lfs/objects/batch"
    request_payload = {
        "operation": "download",
        "transfers": ["basic"],
        "ref": {"name": str(source["asset_mirror_commit"])},
        "objects": [{"oid": item["sha256"], "size": int(item["size"])} for item in entries],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_payload, separators=(",", ":")).encode(),
        headers={
            "Accept": "application/vnd.git-lfs+json",
            "Content-Type": "application/vnd.git-lfs+json",
            "User-Agent": "gdpval-vmvm/1",
        },
        method="POST",
    )
    payload = json.loads(_request_bytes(request).decode())
    objects = payload.get("objects")
    if not isinstance(objects, list):
        raise PermanentDownloadError("Git LFS batch response has no objects list")
    actions: dict[str, dict[str, Any]] = {}
    requested = {str(item["sha256"]): int(item["size"]) for item in entries}
    for item in objects:
        if not isinstance(item, dict):
            raise PermanentDownloadError("Git LFS batch response contains a non-object entry")
        oid = str(item.get("oid", ""))
        if oid not in requested or int(item.get("size", -1)) != requested[oid]:
            raise PermanentDownloadError(f"Git LFS batch response changed object identity: {item}")
        if item.get("error"):
            raise PermanentDownloadError(f"Git LFS object {oid} is unavailable: {item['error']}")
        download = item.get("actions", {}).get("download")
        if not isinstance(download, dict) or not download.get("href"):
            raise PermanentDownloadError(f"Git LFS object {oid} has no download action")
        parsed = urllib.parse.urlparse(str(download["href"]))
        if parsed.scheme != "https" or not (
            parsed.hostname == "githubusercontent.com" or (parsed.hostname or "").endswith(".githubusercontent.com")
        ):
            raise PermanentDownloadError(f"Unexpected Git LFS download host for {oid}: {parsed.hostname}")
        headers = download.get("header") or {}
        if not isinstance(headers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()
        ):
            raise PermanentDownloadError(f"Invalid Git LFS download headers for {oid}")
        actions[oid] = {"href": str(download["href"]), "headers": headers}
    if set(actions) != set(requested):
        raise PermanentDownloadError("Git LFS batch response omitted requested objects")
    return actions


def _download_to_file(
    url: str,
    destination: Path,
    headers: dict[str, str] | None = None,
    *,
    description: str,
) -> None:
    request_headers = {"User-Agent": "gdpval-vmvm/1", **(headers or {})}
    request = urllib.request.Request(url, headers=request_headers)
    last_error: BaseException | None = None
    for attempt in range(6):
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(request, timeout=300) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            return
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in {408, 409, 429} and error.code < 500:
                raise PermanentDownloadError(f"HTTP {error.code} while downloading {description}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
        if attempt < 5:
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"Download failed after 6 attempts for {description}: {last_error}")


def prepare_asset_cache(
    config: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    workers: int = 8,
) -> dict[str, Any]:
    root = _cache_root(config)
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_asset_manifest(config)
    provenance = _cache_provenance(config, manifest)
    provenance_path = root / ".gdpval-asset-mirror.json"
    lock_path = root / ".prepare.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if provenance_path.exists():
            observed = json.loads(provenance_path.read_text(encoding="utf-8"))
            if observed != provenance:
                raise AssetManifestError(
                    f"GDPval asset cache belongs to a different mirror or manifest: {provenance_path}"
                )
        else:
            _atomic_write_json(provenance_path, provenance)

        pending = [
            item
            for item in entries
            if _validate_cached_file(_cache_file(config, item), item, verify_hash=True) is not None
        ]
        lfs_actions = _lfs_download_actions(
            config,
            [item for item in pending if item["storage"] == "git-lfs"],
        )
        source = config["source"]
        raw_base = (
            f"https://raw.githubusercontent.com/{source['asset_mirror_repository']}/{source['asset_mirror_commit']}/"
        )

        def fetch(entry: dict[str, Any]) -> None:
            destination = _cache_file(config, entry)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if entry["storage"] == "git":
                url = raw_base + urllib.parse.quote(str(entry["mirror_path"]), safe="/")
                headers: dict[str, str] = {}
            else:
                action = lfs_actions[str(entry["sha256"])]
                url = str(action["href"])
                headers = dict(action["headers"])
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.verified.", dir=destination.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            temporary.unlink()
            try:
                issue: str | None = None
                for verification_attempt in range(3):
                    _download_to_file(
                        url,
                        temporary,
                        headers,
                        description=str(entry["catalog_path"]),
                    )
                    issue = _validate_cached_file(temporary, entry, verify_hash=True)
                    if issue is None:
                        break
                    temporary.unlink(missing_ok=True)
                    if verification_attempt < 2:
                        time.sleep(2**verification_attempt)
                if issue is not None:
                    raise PermanentDownloadError(
                        f"Downloaded asset failed {issue} verification after 3 attempts: {entry['catalog_path']}"
                    )
                os.chmod(temporary, 0o644)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

        if pending:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
                futures = [executor.submit(fetch, item) for item in pending]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
        os.chmod(provenance_path, 0o644)
        for item in entries:
            os.chmod(_cache_file(config, item), 0o644)
        status = asset_cache_status(config, entries, verify_hashes=True)
        if not status["ready"]:
            raise AssetManifestError("GDPval asset cache failed post-download verification")
        return status | {"downloaded_assets": len(pending)}


def public_asset_record(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in PUBLIC_ASSET_KEYS}


def verify_staged_assets(manifest: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    resolved_root = root.resolve()
    for item in manifest:
        relative = _safe_relative(str(item["path"]))
        destination = (resolved_root / relative).resolve()
        if not destination.is_relative_to(resolved_root):
            raise AssetManifestError(f"Staged path escapes destination: {relative}")
        issue = _validate_cached_file(destination, item, verify_hash=True)
        if issue is not None:
            raise AssetManifestError(f"Staged asset failed {issue} verification: {relative}")
        output.append(public_asset_record(item))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["verify"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise AssetManifestError("Asset manifest must be a JSON list")
    try:
        assets = verify_staged_assets(manifest, args.root)
    except (AssetManifestError, OSError) as error:
        print(json.dumps({"status": "fatal", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "ok", "assets": assets}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
