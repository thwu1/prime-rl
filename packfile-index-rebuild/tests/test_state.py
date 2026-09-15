
import glob
import json
import os
import re
import subprocess

MANIFEST_PATH = "/app/manifest.json"
REPO_PATH = "/app/repo"
GIT_DIR = os.path.join(REPO_PATH, ".git")


def load_manifest():
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def test_repair_scripts_exist():
    """At least one Python repair script must exist in /app/."""
    py_files = glob.glob("/app/*.py")
    assert len(py_files) >= 1, "No Python repair scripts found in /app/"


def test_no_git_shortcuts():
    """Repair scripts must not use git index-pack or git unpack-objects."""
    all_files = glob.glob("/app/*.py") + glob.glob("/app/*.sh")
    for path in all_files:
        with open(path, "r") as f:
            code = f.read()
        assert "index-pack" not in code, f"{path} must not use git index-pack"
        assert "unpack-objects" not in code, (
            f"{path} must not use git unpack-objects"
        )


def test_head_is_valid_ref():
    """HEAD must be a valid symref or detached hash with no null bytes."""
    head_path = os.path.join(GIT_DIR, "HEAD")
    with open(head_path, "rb") as f:
        data = f.read()
    assert b"\x00" not in data, "HEAD still contains null bytes"
    text = data.decode("utf-8", errors="replace").strip()
    is_symref = text.startswith("ref: refs/")
    is_hash = bool(re.match(r"^[0-9a-f]{40}$", text))
    assert is_symref or is_hash, f"HEAD is not a valid ref: {text[:60]}"


def test_idx_file_exists():
    """A .idx file must exist in the pack directory."""
    pack_dir = os.path.join(GIT_DIR, "objects", "pack")
    idx_files = [f for f in os.listdir(pack_dir) if f.endswith(".idx")]
    assert len(idx_files) == 1, f"Expected 1 .idx file, found {len(idx_files)}"


def test_idx_matches_pack_name():
    """The .idx filename must match the .pack filename (same hash stem)."""
    pack_dir = os.path.join(GIT_DIR, "objects", "pack")
    pack_files = [f for f in os.listdir(pack_dir) if f.endswith(".pack")]
    idx_files = [f for f in os.listdir(pack_dir) if f.endswith(".idx")]
    assert len(pack_files) == 1 and len(idx_files) == 1
    pack_stem = pack_files[0].replace(".pack", "")
    idx_stem = idx_files[0].replace(".idx", "")
    assert pack_stem == idx_stem, (
        f"Pack stem '{pack_stem}' != idx stem '{idx_stem}'"
    )


def test_verify_pack_succeeds():
    """git verify-pack must succeed on the rebuilt index."""
    pack_dir = os.path.join(GIT_DIR, "objects", "pack")
    pack_files = [
        os.path.join(pack_dir, f)
        for f in os.listdir(pack_dir)
        if f.endswith(".pack")
    ]
    assert len(pack_files) == 1
    result = subprocess.run(
        ["git", "verify-pack", "-v", pack_files[0]],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"git verify-pack failed:\n{result.stderr}"


def test_commit_count_matches_manifest():
    """git log must show the expected number of commits."""
    manifest = load_manifest()
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "log", "--oneline", "--all"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git log failed: {result.stderr}"
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    assert len(lines) == manifest["total_commits"], (
        f"Expected {manifest['total_commits']} commits, got {len(lines)}"
    )


def test_branches_match_manifest():
    """All expected branches must exist."""
    manifest = load_manifest()
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "branch", "--format=%(refname:short)"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git branch failed: {result.stderr}"
    branches = sorted(
        [b.strip() for b in result.stdout.strip().split("\n") if b.strip()]
    )
    assert branches == manifest["branches"], (
        f"Expected branches {manifest['branches']}, got {branches}"
    )


def test_merge_commit_parents():
    """HEAD must be a merge commit with the expected number of parents."""
    manifest = load_manifest()
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "cat-file", "-p", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"cat-file HEAD failed: {result.stderr}"
    parents = [
        l for l in result.stdout.split("\n") if l.startswith("parent ")
    ]
    assert len(parents) == manifest["head_merge_parents"], (
        f"Expected {manifest['head_merge_parents']} parents, got {len(parents)}"
    )


def test_head_files_match_manifest():
    """git ls-tree at HEAD must list all expected files."""
    manifest = load_manifest()
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git ls-tree failed: {result.stderr}"
    files = sorted(result.stdout.strip().split("\n"))
    assert files == manifest["head_files"], (
        f"Expected files {manifest['head_files']}, got {files}"
    )


def test_file_content_checks():
    """File contents at HEAD must contain expected substrings from manifest."""
    manifest = load_manifest()
    for filename, checks in manifest["file_checks"].items():
        result = subprocess.run(
            ["git", "-C", REPO_PATH, "show", f"HEAD:{filename}"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Failed to read {filename}: {result.stderr}"
        )
        for substring in checks["contains"]:
            assert substring in result.stdout, (
                f"'{substring}' not found in {filename}"
            )


def test_object_count_matches_manifest():
    """Pack must contain the expected number of objects."""
    manifest = load_manifest()
    pack_dir = os.path.join(GIT_DIR, "objects", "pack")
    pack_files = [
        os.path.join(pack_dir, f)
        for f in os.listdir(pack_dir)
        if f.endswith(".pack")
    ]
    assert len(pack_files) == 1
    result = subprocess.run(
        ["git", "verify-pack", "-v", pack_files[0]],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    obj_lines = [
        l
        for l in result.stdout.split("\n")
        if re.match(r"^[0-9a-f]{40}", l)
    ]
    assert len(obj_lines) == manifest["expected_object_count"], (
        f"Expected {manifest['expected_object_count']} objects, "
        f"got {len(obj_lines)}"
    )


def test_fsck_clean():
    """git fsck must pass with no errors (all corruption resolved)."""
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "fsck", "--no-dangling", "--no-progress"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"git fsck found errors:\n{result.stderr}\n{result.stdout}"
    )


def test_no_corrupt_loose_objects():
    """No corrupt loose object files should remain in the object store."""
    objects_dir = os.path.join(GIT_DIR, "objects")
    for dirname in os.listdir(objects_dir):
        dirpath = os.path.join(objects_dir, dirname)
        if len(dirname) != 2 or not os.path.isdir(dirpath):
            continue
        if dirname in ("pa", "in"):
            # Skip pack/ and info/ prefix matches
            continue
        try:
            int(dirname, 16)
        except ValueError:
            continue
        for filename in os.listdir(dirpath):
            obj_hash = dirname + filename
            if len(obj_hash) != 40:
                continue
            filepath = os.path.join(dirpath, filename)
            # Verify the loose object can be read by git
            result = subprocess.run(
                ["git", "-C", REPO_PATH, "cat-file", "-t", obj_hash],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"Corrupt loose object remains: {obj_hash}"
            )


def test_diff_between_commits():
    """git diff between commits must work (validates tree objects)."""
    result = subprocess.run(
        ["git", "-C", REPO_PATH, "diff", "--stat", "HEAD~1", "HEAD"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git diff failed: {result.stderr}"
    assert len(result.stdout.strip()) > 0, "diff output should not be empty"
