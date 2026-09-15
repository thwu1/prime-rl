
import json
import os
import hashlib
import subprocess
import pytest

CFS_TOOL = "/app/cfs-tool"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def count_objects(store_dir):
    """Count total object files in the store."""
    count = 0
    objects_dir = os.path.join(store_dir, "objects")
    if os.path.exists(objects_dir):
        for prefix_dir in os.listdir(objects_dir):
            prefix_path = os.path.join(objects_dir, prefix_dir)
            if os.path.isdir(prefix_path):
                count += len([f for f in os.listdir(prefix_path)
                              if os.path.isfile(os.path.join(prefix_path, f))])
    return count


def run_tool(*args, check=True):
    """Run cfs-tool with given arguments."""
    result = subprocess.run(
        [CFS_TOOL] + list(args),
        capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"cfs-tool {' '.join(args)} failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def load_manifest(path):
    with open(path) as f:
        return json.load(f)


# ── Import tests ──────────────────────────────────────────────────────────


class TestImport:
    def test_import_base_layer_manifest_structure(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)

        assert data["version"] == 1
        assert "entries" in data
        assert "whiteouts" in data
        assert "opaque" in data
        assert data["whiteouts"] == []
        assert data["opaque"] == []

        entries = {e["path"]: e for e in data["entries"]}

        # Regular files
        assert "usr/bin/hello" in entries
        assert entries["usr/bin/hello"]["type"] == "file"
        assert entries["usr/bin/hello"]["mode"] == "0755"
        assert entries["usr/bin/hello"]["size"] > 0
        assert "sha256" in entries["usr/bin/hello"]

        assert "usr/bin/tool" in entries
        assert entries["usr/bin/tool"]["type"] == "file"

        # Symlink
        assert "usr/lib/libfoo.so" in entries
        assert entries["usr/lib/libfoo.so"]["type"] == "symlink"
        assert entries["usr/lib/libfoo.so"]["link_target"] == "libfoo.so.1"

        # Directories
        assert "etc" in entries
        assert entries["etc"]["type"] == "directory"
        assert "usr" in entries
        assert entries["usr"]["type"] == "directory"
        assert "etc_backup" in entries
        assert entries["etc_backup"]["type"] == "directory"

        # Empty file (no sha256)
        assert "var/log/.gitkeep" in entries
        assert entries["var/log/.gitkeep"]["type"] == "file"
        assert entries["var/log/.gitkeep"]["size"] == 0
        assert "sha256" not in entries["var/log/.gitkeep"]

    def test_import_entries_sorted(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)

        paths = [e["path"] for e in data["entries"]]
        assert paths == sorted(paths), "Entries must be sorted by path"

    def test_import_creates_object_files(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)

        for entry in data["entries"]:
            if entry["type"] == "file" and entry.get("size", 0) > 0:
                digest = entry["sha256"]
                obj_path = os.path.join(store, "objects", digest[:2], digest)
                assert os.path.exists(obj_path), f"Object missing for {entry['path']}"
                with open(obj_path, "rb") as f:
                    actual_hash = sha256_hex(f.read())
                assert actual_hash == digest, f"Hash mismatch for {entry['path']}"

    def test_import_whiteouts_json(self, tmp_path):
        """Patch layer has .whiteouts.json that populates whiteouts/opaque fields."""
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "patch.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/patch", store, "--manifest", manifest)
        data = load_manifest(manifest)

        assert "usr/lib/libapp.so.1" in data["whiteouts"]
        assert "etc" in data["opaque"]

        # .whiteouts.json itself must NOT appear as an entry
        entry_paths = [e["path"] for e in data["entries"]]
        assert ".whiteouts.json" not in entry_paths

        # Patch layer's own libapp.so.1 IS in entries (separate from whiteout)
        entries = {e["path"]: e for e in data["entries"]}
        assert "usr/lib/libapp.so.1" in entries
        assert entries["usr/lib/libapp.so.1"]["type"] == "file"

    def test_import_mode_format(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)

        for entry in data["entries"]:
            if "mode" in entry:
                mode = entry["mode"]
                assert len(mode) == 4, f"Mode '{mode}' for {entry['path']} must be 4 digits"
                assert all(c in "01234567" for c in mode), \
                    f"Mode '{mode}' for {entry['path']} must be octal digits"

    def test_import_symlink_not_as_file(self, tmp_path):
        """Symlinks must be recorded as type=symlink, not followed as files."""
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)
        entries = {e["path"]: e for e in data["entries"]}

        symlink_entry = entries["usr/lib/libfoo.so"]
        assert symlink_entry["type"] == "symlink", \
            f"Symlink recorded as {symlink_entry['type']} instead of symlink"
        assert "sha256" not in symlink_entry, \
            "Symlink entry should not have sha256"
        assert "size" not in symlink_entry, \
            "Symlink entry should not have size"
        assert symlink_entry["link_target"] == "libfoo.so.1"


# ── Deduplication tests ───────────────────────────────────────────────────


class TestDedup:
    def test_shared_content_deduplicated(self, tmp_path):
        """libfoo.so.1 has identical content in base and app layers."""
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        count_after_base = count_objects(store)

        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)

        base_data = load_manifest(manifest_base)
        app_data = load_manifest(manifest_app)

        base_entries = {e["path"]: e for e in base_data["entries"]}
        app_entries = {e["path"]: e for e in app_data["entries"]}

        # Verify the shared file has the same digest
        assert base_entries["usr/lib/libfoo.so.1"]["sha256"] == \
               app_entries["usr/lib/libfoo.so.1"]["sha256"], \
            "libfoo.so.1 should have identical content in both layers"

        # Count unique new hashes in app layer
        base_hashes = {e["sha256"] for e in base_data["entries"]
                       if e["type"] == "file" and e.get("size", 0) > 0}
        app_hashes = {e["sha256"] for e in app_data["entries"]
                      if e["type"] == "file" and e.get("size", 0) > 0}
        new_hashes = app_hashes - base_hashes

        count_after_app = count_objects(store)
        assert count_after_app == count_after_base + len(new_hashes), \
            "Dedup failed: shared content created duplicate objects"


# ── Checkout tests ────────────────────────────────────────────────────────


class TestCheckout:
    def test_checkout_recreates_files(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        checkout_dir = str(tmp_path / "checkout")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        run_tool("checkout", manifest, store, checkout_dir)

        # Check file content
        with open(os.path.join(checkout_dir, "usr/bin/hello")) as f:
            assert "Hello World" in f.read()

        # Check symlink
        link = os.path.join(checkout_dir, "usr/lib/libfoo.so")
        assert os.path.islink(link)
        assert os.readlink(link) == "libfoo.so.1"

        # Check directory
        assert os.path.isdir(os.path.join(checkout_dir, "etc"))
        assert os.path.isdir(os.path.join(checkout_dir, "etc_backup"))

        # Check empty file
        gitkeep = os.path.join(checkout_dir, "var/log/.gitkeep")
        assert os.path.exists(gitkeep)
        assert os.path.getsize(gitkeep) == 0

    def test_checkout_preserves_permissions(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        checkout_dir = str(tmp_path / "checkout")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        run_tool("checkout", manifest, store, checkout_dir)

        hello_path = os.path.join(checkout_dir, "usr/bin/hello")
        mode = os.stat(hello_path).st_mode
        assert mode & 0o777 == 0o755, f"Expected 0755, got {oct(mode & 0o777)}"

        config_path = os.path.join(checkout_dir, "etc/config.ini")
        mode = os.stat(config_path).st_mode
        assert mode & 0o777 == 0o644, f"Expected 0644, got {oct(mode & 0o777)}"

    def test_checkout_content_matches_original(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        checkout_dir = str(tmp_path / "checkout")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        run_tool("checkout", manifest, store, checkout_dir)

        for root, dirs, files in os.walk("/app/layers/base"):
            for fname in files:
                orig_path = os.path.join(root, fname)
                rel_path = os.path.relpath(orig_path, "/app/layers/base")
                checkout_path = os.path.join(checkout_dir, rel_path)

                if os.path.islink(orig_path):
                    assert os.path.islink(checkout_path), \
                        f"Expected symlink at {rel_path}"
                    assert os.readlink(orig_path) == os.readlink(checkout_path), \
                        f"Symlink target mismatch at {rel_path}"
                else:
                    assert os.path.exists(checkout_path), \
                        f"Missing file at {rel_path}"
                    with open(orig_path, "rb") as f:
                        orig_content = f.read()
                    with open(checkout_path, "rb") as f:
                        checkout_content = f.read()
                    assert orig_content == checkout_content, \
                        f"Content mismatch for {rel_path}"


# ── Verify tests ─────────────────────────────────────────────────────────


class TestVerify:
    def test_verify_passes_on_good_data(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        result = run_tool("verify", manifest, store)
        assert "OK" in result.stdout

    def test_verify_fails_on_corrupted_object(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)

        # Corrupt the first file object
        for entry in data["entries"]:
            if entry["type"] == "file" and entry.get("size", 0) > 0:
                digest = entry["sha256"]
                obj_path = os.path.join(store, "objects", digest[:2], digest)
                with open(obj_path, "wb") as f:
                    f.write(b"CORRUPTED DATA")
                break

        result = run_tool("verify", manifest, store, check=False)
        assert result.returncode != 0
        assert "FAILED" in result.stdout

    def test_verify_fails_on_missing_object(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        data = load_manifest(manifest)

        # Delete the first file object
        for entry in data["entries"]:
            if entry["type"] == "file" and entry.get("size", 0) > 0:
                digest = entry["sha256"]
                obj_path = os.path.join(store, "objects", digest[:2], digest)
                os.remove(obj_path)
                break

        result = run_tool("verify", manifest, store, check=False)
        assert result.returncode != 0
        assert "FAILED" in result.stdout


# ── Diff tests ────────────────────────────────────────────────────────────


class TestDiff:
    def test_diff_base_vs_app(self, tmp_path):
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)

        result = run_tool("diff", manifest_base, manifest_app)
        diff_data = json.loads(result.stdout)

        # hello is modified (different content)
        assert "usr/bin/hello" in diff_data["modified"]

        # app is added in app layer
        assert "usr/bin/app" in diff_data["added"]

        # tool is in base but not in app
        assert "usr/bin/tool" in diff_data["removed"]

        # libfoo.so.1 has identical content -> NOT modified
        assert "usr/lib/libfoo.so.1" not in diff_data["modified"]
        assert "usr/lib/libfoo.so.1" not in diff_data["added"]
        assert "usr/lib/libfoo.so.1" not in diff_data["removed"]

    def test_diff_lists_sorted(self, tmp_path):
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)

        result = run_tool("diff", manifest_base, manifest_app)
        diff_data = json.loads(result.stdout)

        assert diff_data["added"] == sorted(diff_data["added"])
        assert diff_data["removed"] == sorted(diff_data["removed"])
        assert diff_data["modified"] == sorted(diff_data["modified"])

    def test_diff_identical_manifests(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        result = run_tool("diff", manifest, manifest)
        diff_data = json.loads(result.stdout)

        assert diff_data["added"] == []
        assert diff_data["removed"] == []
        assert diff_data["modified"] == []

    def test_diff_detects_modification_attributes(self, tmp_path):
        """Diff must compare entry attributes, not just path presence."""
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)

        result = run_tool("diff", manifest_base, manifest_app)
        diff_data = json.loads(result.stdout)

        # usr/bin/hello exists in both but has different content
        assert "usr/bin/hello" in diff_data["modified"], \
            "Diff must detect entries with same path but different attributes as modified"
        # modified list should not be empty
        assert len(diff_data["modified"]) > 0, \
            "Modified list is empty — diff is not comparing entry attributes"


# ── Merge tests ───────────────────────────────────────────────────────────


class TestMerge:
    def test_merge_base_and_app(self, tmp_path):
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        merged = str(tmp_path / "merged.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)
        run_tool("merge", manifest_base, manifest_app, "--output", merged)

        data = load_manifest(merged)
        entries = {e["path"]: e for e in data["entries"]}
        app_data = load_manifest(manifest_app)
        app_entries = {e["path"]: e for e in app_data["entries"]}

        # App's hello overrides base
        assert entries["usr/bin/hello"]["sha256"] == app_entries["usr/bin/hello"]["sha256"]

        # Base-only entries preserved
        assert "usr/bin/tool" in entries
        assert "usr/share/doc/README" in entries
        assert "usr/lib/libfoo.so" in entries  # symlink from base
        assert "etc_backup" in entries  # base-only directory
        assert "etc_backup/config.ini.bak" in entries

        # App-only entries added
        assert "usr/bin/app" in entries
        assert "usr/lib/libapp.so.1" in entries
        assert "etc/app.conf" in entries

        # Base entries not overridden preserved
        assert "etc/config.ini" in entries
        assert "etc/hosts" in entries

        # Merged manifest has empty whiteout fields
        assert data["whiteouts"] == []
        assert data["opaque"] == []

    def test_merge_whiteout_preserves_overlay(self, tmp_path):
        """Overlay entry at a whiteout path must survive the merge."""
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        manifest_patch = str(tmp_path / "patch.json")
        merged_1 = str(tmp_path / "merged1.json")
        merged_2 = str(tmp_path / "merged2.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)
        run_tool("import", "/app/layers/patch", store, "--manifest", manifest_patch)

        run_tool("merge", manifest_base, manifest_app, "--output", merged_1)
        run_tool("merge", merged_1, manifest_patch, "--output", merged_2)

        data = load_manifest(merged_2)
        entries = {e["path"]: e for e in data["entries"]}

        # Patch has both a whiteout for usr/lib/libapp.so.1 AND its own entry
        # The whiteout removes the base/app version; the overlay entry survives
        assert "usr/lib/libapp.so.1" in entries, \
            "Overlay entry at whiteout path was deleted — whiteouts must only apply to base entries"

        patch_data = load_manifest(manifest_patch)
        patch_entries = {e["path"]: e for e in patch_data["entries"]}
        assert entries["usr/lib/libapp.so.1"]["sha256"] == \
               patch_entries["usr/lib/libapp.so.1"]["sha256"], \
            "Wrong version of libapp.so.1 — should be the overlay (patch) version"

    def test_merge_opaque_scope(self, tmp_path):
        """Opaque whiteout for 'etc' must not affect 'etc_backup'."""
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        manifest_patch = str(tmp_path / "patch.json")
        merged_1 = str(tmp_path / "merged1.json")
        merged_2 = str(tmp_path / "merged2.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)
        run_tool("import", "/app/layers/patch", store, "--manifest", manifest_patch)

        run_tool("merge", manifest_base, manifest_app, "--output", merged_1)
        run_tool("merge", merged_1, manifest_patch, "--output", merged_2)

        data = load_manifest(merged_2)
        entries = {e["path"]: e for e in data["entries"]}

        # etc_backup must survive — opaque 'etc' should not match 'etc_backup'
        assert "etc_backup" in entries, \
            "etc_backup removed — opaque prefix matching is too broad"
        assert "etc_backup/config.ini.bak" in entries, \
            "etc_backup/config.ini.bak removed — opaque prefix matching is too broad"

        # But etc/ from base+app must be removed
        assert "etc/config.ini" not in entries
        assert "etc/hosts" not in entries
        assert "etc/app.conf" not in entries

        # Patch's own etc entries must survive
        assert "etc" in entries
        assert "etc/minimal.conf" in entries

    def test_merge_exact_paths(self, tmp_path):
        """Verify the exact set of paths in the three-layer merge result."""
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        manifest_patch = str(tmp_path / "patch.json")
        merged_1 = str(tmp_path / "merged1.json")
        merged_2 = str(tmp_path / "merged2.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)
        run_tool("import", "/app/layers/patch", store, "--manifest", manifest_patch)

        run_tool("merge", manifest_base, manifest_app, "--output", merged_1)
        run_tool("merge", merged_1, manifest_patch, "--output", merged_2)

        data = load_manifest(merged_2)
        actual_paths = [e["path"] for e in data["entries"]]

        expected_paths = sorted([
            "etc", "etc/minimal.conf",
            "etc_backup", "etc_backup/config.ini.bak",
            "usr", "usr/bin", "usr/bin/app", "usr/bin/hello", "usr/bin/tool",
            "usr/lib", "usr/lib/libapp.so.1", "usr/lib/libfoo.so",
            "usr/lib/libfoo.so.1",
            "usr/share", "usr/share/doc", "usr/share/doc/README",
            "var", "var/log", "var/log/.gitkeep",
        ])

        assert actual_paths == expected_paths, \
            f"Path mismatch.\nExpected: {expected_paths}\nActual:   {actual_paths}"


# ── Stats tests ───────────────────────────────────────────────────────────


class TestStats:
    def test_stats_output_format(self, tmp_path):
        store = str(tmp_path / "store")
        manifest = str(tmp_path / "base.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest)
        result = run_tool("stats", store)

        stats = json.loads(result.stdout)
        assert "total_objects" in stats
        assert "total_size_bytes" in stats
        assert isinstance(stats["total_objects"], int)
        assert isinstance(stats["total_size_bytes"], int)
        assert stats["total_objects"] > 0
        assert stats["total_size_bytes"] > 0

    def test_stats_reflects_dedup(self, tmp_path):
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        os.makedirs(store)

        run_tool("import", "/app/layers/base", store, "--manifest", manifest_base)
        result1 = run_tool("stats", store)
        stats1 = json.loads(result1.stdout)

        run_tool("import", "/app/layers/app", store, "--manifest", manifest_app)
        result2 = run_tool("stats", store)
        stats2 = json.loads(result2.stdout)

        app_data = load_manifest(manifest_app)
        app_file_count = sum(1 for e in app_data["entries"]
                             if e["type"] == "file" and e.get("size", 0) > 0)

        new_objects = stats2["total_objects"] - stats1["total_objects"]
        assert new_objects < app_file_count, \
            "Dedup not working: all app files created new objects"


# ── GC tests ─────────────────────────────────────────────────────────────


class TestGC:
    def test_gc_removes_unreferenced_objects(self, tmp_path):
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        # Import all three layers
        for layer in ["base", "app", "patch"]:
            run_tool("import", f"/app/layers/{layer}", store,
                     "--manifest", os.path.join(manifests_dir, f"{layer}.json"))

        initial_count = count_objects(store)

        # Remove app manifest — its unique objects become unreferenced
        os.remove(os.path.join(manifests_dir, "app.json"))

        result = run_tool("gc", store, manifests_dir)
        gc_data = json.loads(result.stdout)

        assert gc_data["removed_objects"] > 0, "GC should have removed some objects"
        assert gc_data["remaining_objects"] > 0, "GC should have kept some objects"
        assert gc_data["remaining_objects"] < initial_count, \
            "Remaining objects should be fewer than initial"
        assert "freed_bytes" in gc_data
        assert gc_data["freed_bytes"] > 0

    def test_gc_preserves_referenced_objects(self, tmp_path):
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        manifest = os.path.join(manifests_dir, "base.json")
        run_tool("import", "/app/layers/base", store, "--manifest", manifest)

        # GC with all objects referenced — nothing should be removed
        result = run_tool("gc", store, manifests_dir)
        gc_data = json.loads(result.stdout)

        assert gc_data["removed_objects"] == 0
        assert gc_data["freed_bytes"] == 0

        # Verify still passes
        verify_result = run_tool("verify", manifest, store)
        assert "OK" in verify_result.stdout

    def test_gc_verify_after_cleanup(self, tmp_path):
        """After GC, remaining manifests must still verify successfully."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        for layer in ["base", "app", "patch"]:
            run_tool("import", f"/app/layers/{layer}", store,
                     "--manifest", os.path.join(manifests_dir, f"{layer}.json"))

        # Remove app manifest
        os.remove(os.path.join(manifests_dir, "app.json"))

        run_tool("gc", store, manifests_dir)

        # Remaining manifests must still verify
        for mf in ["base.json", "patch.json"]:
            result = run_tool("verify", os.path.join(manifests_dir, mf), store)
            assert "OK" in result.stdout, f"Verify failed for {mf} after GC"


# ── Fsck tests ───────────────────────────────────────────────────────────


class TestFsck:
    def test_fsck_clean_store(self, tmp_path):
        """fsck reports clean on a valid store with no errors or orphans."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        run_tool("import", "/app/layers/base", store,
                 "--manifest", os.path.join(manifests_dir, "base.json"))

        result = run_tool("fsck", store, manifests_dir)
        data = json.loads(result.stdout)

        assert data["status"] == "clean"
        assert data["manifests_checked"] == 1
        assert data["objects_checked"] > 0
        assert data["orphaned_objects"] == 0
        assert data["errors"] == []

    def test_fsck_detects_hash_mismatch(self, tmp_path):
        """fsck detects corrupted objects with hash mismatches."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        manifest = os.path.join(manifests_dir, "base.json")
        run_tool("import", "/app/layers/base", store, "--manifest", manifest)

        mf_data = load_manifest(manifest)
        for entry in mf_data["entries"]:
            if entry["type"] == "file" and entry.get("size", 0) > 0:
                digest = entry["sha256"]
                obj_path = os.path.join(store, "objects", digest[:2], digest)
                with open(obj_path, "wb") as f:
                    f.write(b"CORRUPTED DATA")
                break

        result = run_tool("fsck", store, manifests_dir, check=False)
        fsck_data = json.loads(result.stdout)

        assert fsck_data["status"] == "dirty"
        assert result.returncode != 0
        assert any(e["type"] == "hash_mismatch" for e in fsck_data["errors"])

    def test_fsck_detects_missing_object(self, tmp_path):
        """fsck detects objects referenced by manifests but missing from store."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        manifest = os.path.join(manifests_dir, "base.json")
        run_tool("import", "/app/layers/base", store, "--manifest", manifest)

        mf_data = load_manifest(manifest)
        for entry in mf_data["entries"]:
            if entry["type"] == "file" and entry.get("size", 0) > 0:
                digest = entry["sha256"]
                obj_path = os.path.join(store, "objects", digest[:2], digest)
                os.remove(obj_path)
                break

        result = run_tool("fsck", store, manifests_dir, check=False)
        fsck_data = json.loads(result.stdout)

        assert fsck_data["status"] == "dirty"
        assert any(e["type"] == "missing_object" for e in fsck_data["errors"])

    def test_fsck_reports_orphaned_objects(self, tmp_path):
        """fsck counts orphaned objects without marking store as dirty."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        # Import base into manifests_dir
        run_tool("import", "/app/layers/base", store,
                 "--manifest", os.path.join(manifests_dir, "base.json"))
        # Import app into same store but manifest goes OUTSIDE manifests_dir
        run_tool("import", "/app/layers/app", store,
                 "--manifest", str(tmp_path / "app.json"))

        result = run_tool("fsck", store, manifests_dir)
        fsck_data = json.loads(result.stdout)

        assert fsck_data["status"] == "clean", \
            "Orphans should not make status dirty"
        assert fsck_data["orphaned_objects"] > 0, \
            "Should detect orphaned objects from unreferenced app layer"

    def test_fsck_output_schema(self, tmp_path):
        """fsck output conforms to the documented JSON schema."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        run_tool("import", "/app/layers/base", store,
                 "--manifest", os.path.join(manifests_dir, "base.json"))

        result = run_tool("fsck", store, manifests_dir)
        data = json.loads(result.stdout)

        assert isinstance(data["status"], str)
        assert data["status"] in ("clean", "dirty")
        assert isinstance(data["manifests_checked"], int)
        assert isinstance(data["objects_checked"], int)
        assert isinstance(data["orphaned_objects"], int)
        assert isinstance(data["errors"], list)

    def test_fsck_multiple_manifests(self, tmp_path):
        """fsck checks all manifests in the directory."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        for layer in ["base", "app", "patch"]:
            run_tool("import", f"/app/layers/{layer}", store,
                     "--manifest", os.path.join(manifests_dir, f"{layer}.json"))

        result = run_tool("fsck", store, manifests_dir)
        data = json.loads(result.stdout)

        assert data["status"] == "clean"
        assert data["manifests_checked"] == 3
        assert data["orphaned_objects"] == 0


# ── Store Audit tests ────────────────────────────────────────────────────


class TestStoreAudit:
    AUDIT_SCRIPT = "/app/store-audit.sh"

    def run_audit(self, *args, check=True):
        result = subprocess.run(
            [self.AUDIT_SCRIPT] + list(args),
            capture_output=True, text=True
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"store-audit.sh failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result

    def test_audit_implementation(self):
        """store-audit.sh must be a shell script using jq, find, sha256sum."""
        assert os.path.isfile(self.AUDIT_SCRIPT), "store-audit.sh not found"
        assert os.access(self.AUDIT_SCRIPT, os.X_OK), \
            "store-audit.sh not executable"

        with open(self.AUDIT_SCRIPT) as f:
            content = f.read()

        first_line = content.split('\n')[0].strip()
        assert first_line.startswith("#!/bin/"), \
            f"Expected shell shebang, got: {first_line}"
        assert "jq" in content, "store-audit.sh must use jq"
        assert "find" in content, "store-audit.sh must use find"
        assert "sha256sum" in content, "store-audit.sh must use sha256sum"

    def test_audit_clean_store(self, tmp_path):
        """store-audit.sh reports ok on a valid store."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        run_tool("import", "/app/layers/base", store,
                 "--manifest", os.path.join(manifests_dir, "base.json"))

        result = self.run_audit(store, manifests_dir)
        data = json.loads(result.stdout)

        assert data["status"] == "ok"
        assert data["total_objects"] > 0
        assert data["referenced_objects"] > 0
        assert data["orphaned_objects"] == 0
        assert data["integrity_errors"] == 0

    def test_audit_output_schema(self, tmp_path):
        """store-audit.sh output conforms to documented JSON schema."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        run_tool("import", "/app/layers/base", store,
                 "--manifest", os.path.join(manifests_dir, "base.json"))

        result = self.run_audit(store, manifests_dir)
        data = json.loads(result.stdout)

        assert isinstance(data["total_objects"], int)
        assert isinstance(data["referenced_objects"], int)
        assert isinstance(data["orphaned_objects"], int)
        assert isinstance(data["integrity_errors"], int)
        assert data["status"] in ("ok", "errors_found")

    def test_audit_detects_orphans(self, tmp_path):
        """store-audit.sh detects orphaned objects."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        run_tool("import", "/app/layers/base", store,
                 "--manifest", os.path.join(manifests_dir, "base.json"))
        # Import app into same store but manifest goes outside manifests_dir
        run_tool("import", "/app/layers/app", store,
                 "--manifest", str(tmp_path / "app.json"))

        result = self.run_audit(store, manifests_dir)
        data = json.loads(result.stdout)

        assert data["orphaned_objects"] > 0

    def test_audit_detects_integrity_errors(self, tmp_path):
        """store-audit.sh detects corrupted objects via sha256sum."""
        store = str(tmp_path / "store")
        manifests_dir = str(tmp_path / "manifests")
        os.makedirs(store)
        os.makedirs(manifests_dir)

        manifest = os.path.join(manifests_dir, "base.json")
        run_tool("import", "/app/layers/base", store, "--manifest", manifest)

        mf_data = load_manifest(manifest)
        for entry in mf_data["entries"]:
            if entry["type"] == "file" and entry.get("size", 0) > 0:
                digest = entry["sha256"]
                obj_path = os.path.join(store, "objects", digest[:2], digest)
                with open(obj_path, "wb") as f:
                    f.write(b"CORRUPTED DATA")
                break

        result = self.run_audit(store, manifests_dir, check=False)
        data = json.loads(result.stdout)

        assert result.returncode != 0
        assert data["status"] == "errors_found"
        assert data["integrity_errors"] > 0


# ── End-to-end test ──────────────────────────────────────────────────────


class TestEndToEnd:
    def test_merge_checkout_correctness(self, tmp_path):
        """Import three layers, merge them, checkout, verify content."""
        store = str(tmp_path / "store")
        manifest_base = str(tmp_path / "base.json")
        manifest_app = str(tmp_path / "app.json")
        manifest_patch = str(tmp_path / "patch.json")
        merged_1 = str(tmp_path / "merged1.json")
        merged_2 = str(tmp_path / "merged2.json")
        checkout_dir = str(tmp_path / "checkout")
        os.makedirs(store)

        # Import all layers
        for layer, mf in [("base", manifest_base),
                          ("app", manifest_app),
                          ("patch", manifest_patch)]:
            run_tool("import", f"/app/layers/{layer}", store, "--manifest", mf)

        # Merge: base + app + patch
        run_tool("merge", manifest_base, manifest_app, "--output", merged_1)
        run_tool("merge", merged_1, manifest_patch, "--output", merged_2)

        # Checkout merged result
        run_tool("checkout", merged_2, store, checkout_dir)

        # Patched app content
        with open(os.path.join(checkout_dir, "usr/bin/app")) as f:
            assert "App v2 patched" in f.read()

        # Overlay entry at whiteout path preserved (patch's libapp.so.1)
        assert os.path.exists(os.path.join(checkout_dir, "usr/lib/libapp.so.1"))

        # Opaque whiteout replaced etc/ - only minimal.conf remains
        etc_files = os.listdir(os.path.join(checkout_dir, "etc"))
        assert "minimal.conf" in etc_files
        assert "config.ini" not in etc_files
        assert "hosts" not in etc_files
        assert "app.conf" not in etc_files

        # etc_backup preserved (not affected by opaque 'etc')
        assert os.path.exists(os.path.join(checkout_dir, "etc_backup/config.ini.bak"))

        # Unaffected base content preserved
        with open(os.path.join(checkout_dir, "usr/bin/tool")) as f:
            assert "Tool v1" in f.read()

        # Symlink preserved
        link = os.path.join(checkout_dir, "usr/lib/libfoo.so")
        assert os.path.islink(link)
        assert os.readlink(link) == "libfoo.so.1"

        # Verify integrity of merged manifest
        result = run_tool("verify", merged_2, store)
        assert "OK" in result.stdout
