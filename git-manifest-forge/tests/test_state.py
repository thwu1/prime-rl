
import hashlib
import os
import re
import struct
import subprocess
import zlib

import pytest

REPO_DIR = "/app/repo"
GIT_DIR = os.path.join(REPO_DIR, ".git")


def run_git(*args, cwd=REPO_DIR):
    """Run a git command in the repo."""
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ── repair.py constraints ───────────────────────────────────────────────


class TestRepairConstraints:
    def test_repair_script_exists(self):
        assert os.path.exists("/app/repair.py"), "repair.py must exist at /app/"

    def test_no_git_library_imports(self):
        with open("/app/repair.py", "r") as f:
            content = f.read().lower()
        for lib in ["dulwich", "gitpython", "pygit2"]:
            assert lib not in content, f"Must not use library: {lib}"

    def test_no_subprocess_git(self):
        with open("/app/repair.py", "r") as f:
            content = f.read()
        git_calls = re.findall(
            r"subprocess.*[\"']git[\"']|os\.system.*git|os\.popen.*git", content
        )
        assert len(git_calls) == 0, f"repair.py must not call git: {git_calls}"


# ── Repository structure ─────────────────────────────────────────────────


class TestRepoStructure:
    def test_repo_exists(self):
        assert os.path.isdir(REPO_DIR), "Repo directory must exist"
        assert os.path.isdir(GIT_DIR), ".git directory must exist"

    def test_git_dir_contents(self):
        assert os.path.isdir(os.path.join(GIT_DIR, "objects"))
        assert os.path.isdir(os.path.join(GIT_DIR, "refs", "heads"))
        assert os.path.isfile(os.path.join(GIT_DIR, "HEAD"))

    def test_head_ref(self):
        with open(os.path.join(GIT_DIR, "HEAD"), "r") as f:
            head = f.read().strip()
        assert head == "ref: refs/heads/main"

    def test_branch_ref_exists(self):
        ref_path = os.path.join(GIT_DIR, "refs", "heads", "main")
        assert os.path.isfile(ref_path), "refs/heads/main must exist"
        with open(ref_path) as f:
            sha = f.read().strip()
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), (
            f"Branch ref must contain a 40-char hex SHA, got: {sha}"
        )


# ── git fsck ─────────────────────────────────────────────────────────────


class TestGitFsck:
    def test_fsck_passes(self):
        result = run_git("fsck", "--full", "--strict")
        assert result.returncode == 0, f"git fsck failed:\n{result.stderr}"

    def test_fsck_no_errors_in_stderr(self):
        result = run_git("fsck", "--full", "--strict")
        stderr = result.stderr.lower()
        assert "error" not in stderr, (
            f"git fsck stderr contains errors:\n{result.stderr}"
        )


# ── Commit history ───────────────────────────────────────────────────────


class TestCommits:
    def test_commit_count(self):
        result = run_git("rev-list", "--count", "HEAD")
        assert result.returncode == 0
        assert result.stdout.strip() == "2", (
            f"Expected 2 commits, got {result.stdout.strip()}"
        )

    def test_head_commit_subject(self):
        result = run_git("log", "-1", "--format=%s", "HEAD")
        assert result.stdout.strip() == "Add sorting edge cases and expand modules"

    def test_head_commit_author(self):
        result = run_git("log", "-1", "--format=%an <%ae>", "HEAD")
        assert result.stdout.strip() == "Charles Babbage <charles@example.com>"

    def test_head_commit_timestamp(self):
        result = run_git("log", "-1", "--format=%at", "HEAD")
        assert result.stdout.strip() == "1700100000"

    def test_head_commit_timezone(self):
        result = run_git("log", "-1", "--format=%ai", "HEAD")
        assert "+0000" in result.stdout

    def test_parent_commit_subject(self):
        result = run_git("log", "-1", "--format=%s", "HEAD~1")
        assert result.returncode == 0
        assert result.stdout.strip() == "Initial project setup"

    def test_parent_commit_author(self):
        result = run_git("log", "-1", "--format=%an <%ae>", "HEAD~1")
        assert result.stdout.strip() == "Ada Lovelace <ada@example.com>"

    def test_parent_commit_timestamp(self):
        result = run_git("log", "-1", "--format=%at", "HEAD~1")
        assert result.stdout.strip() == "1700000000"

    def test_parent_commit_timezone(self):
        result = run_git("log", "-1", "--format=%ai", "HEAD~1")
        assert "+0100" in result.stdout

    def test_parent_commit_multiline_body(self):
        result = run_git("log", "-1", "--format=%b", "HEAD~1")
        body = result.stdout.strip()
        assert "Establish the basic project structure" in body
        assert "source code and configuration files" in body

    def test_first_commit_has_no_parent(self):
        result = run_git("cat-file", "-p", "HEAD~1")
        assert result.returncode == 0
        for line in result.stdout.split("\n"):
            if line == "":
                break
            assert not line.startswith("parent"), (
                "First commit must have no parent"
            )

    def test_second_commit_has_one_parent(self):
        result = run_git("cat-file", "-p", "HEAD")
        assert result.returncode == 0
        parents = [
            l for l in result.stdout.split("\n") if l.startswith("parent ")
        ]
        assert len(parents) == 1, (
            f"HEAD should have exactly 1 parent, got {len(parents)}"
        )


# ── Tree structure and sorting ───────────────────────────────────────────


class TestTreeStructure:
    def test_head_file_list(self):
        result = run_git("ls-tree", "-r", "--name-only", "HEAD")
        assert result.returncode == 0
        files = sorted(result.stdout.strip().split("\n"))
        expected = sorted(
            [
                "LICENSE",
                "README.md",
                "data.txt",
                "data/config.json",
                "src/lib.py",
                "src/lib/io.py",
                "src/lib/utils.py",
                "src/lib0.py",
                "src/main.py",
            ]
        )
        assert files == expected, f"File list mismatch: {files}"

    def test_file_modes(self):
        result = run_git("ls-tree", "-r", "HEAD")
        assert result.returncode == 0
        entries = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split("\t")
            meta = parts[0].split()
            entries[parts[1]] = meta[0]

        assert entries["src/main.py"] == "100755", "main.py should be executable"
        assert entries["README.md"] == "100644", "README.md should be regular"
        assert entries["LICENSE"] == "100644", "LICENSE should be regular"
        assert entries["data.txt"] == "100644", "data.txt should be regular"

    def test_root_tree_sort_order(self):
        """data.txt (file) must sort BEFORE data/ (dir).

        '.' (0x2E) < '/' (0x2F) in the directory-suffix comparison.
        """
        result = run_git("ls-tree", "HEAD")
        assert result.returncode == 0
        names = [line.split("\t")[1] for line in result.stdout.strip().split("\n")]

        data_txt_idx = names.index("data.txt")
        data_dir_idx = names.index("data")
        assert data_txt_idx < data_dir_idx, (
            f"data.txt (idx {data_txt_idx}) must sort before data/ (idx {data_dir_idx}). "
            f"Full order: {names}"
        )

    def test_src_tree_sort_order(self):
        """In src/: lib.py < lib/ < lib0.py.

        '.' (0x2E) < '/' (0x2F) < '0' (0x30).
        """
        result = run_git("ls-tree", "HEAD:src")
        assert result.returncode == 0
        names = [line.split("\t")[1] for line in result.stdout.strip().split("\n")]

        lib_py_idx = names.index("lib.py")
        lib_dir_idx = names.index("lib")
        lib0_py_idx = names.index("lib0.py")
        main_py_idx = names.index("main.py")

        assert lib_py_idx < lib_dir_idx, "lib.py must sort before lib/"
        assert lib_dir_idx < lib0_py_idx, "lib/ must sort before lib0.py"
        assert lib0_py_idx < main_py_idx, "lib0.py must sort before main.py"

    def test_first_commit_file_list(self):
        result = run_git("ls-tree", "-r", "--name-only", "HEAD~1")
        assert result.returncode == 0
        files = sorted(result.stdout.strip().split("\n"))
        expected = sorted(
            [
                "LICENSE",
                "README.md",
                "data/config.json",
                "src/lib/io.py",
                "src/lib/utils.py",
                "src/main.py",
            ]
        )
        assert files == expected, f"First commit file list mismatch: {files}"


# ── Index file ───────────────────────────────────────────────────────────


class TestIndex:
    def test_index_exists(self):
        assert os.path.isfile(os.path.join(GIT_DIR, "index")), (
            ".git/index must exist"
        )

    def test_index_file_count(self):
        result = run_git("ls-files")
        assert result.returncode == 0
        files = result.stdout.strip().split("\n")
        assert len(files) == 9, f"Expected 9 files in index, got {len(files)}"

    def test_index_matches_head_tree(self):
        tree_result = run_git("ls-tree", "-r", "--name-only", "HEAD")
        index_result = run_git("ls-files")
        tree_files = sorted(tree_result.stdout.strip().split("\n"))
        index_files = sorted(index_result.stdout.strip().split("\n"))
        assert tree_files == index_files, (
            f"Index files must match HEAD tree: {index_files} != {tree_files}"
        )

    def test_index_shas_match_tree(self):
        tree_result = run_git("ls-tree", "-r", "HEAD")
        index_result = run_git("ls-files", "--stage")

        tree_shas = {}
        for line in tree_result.stdout.strip().split("\n"):
            parts = line.split("\t")
            meta = parts[0].split()
            tree_shas[parts[1]] = meta[2]

        index_shas = {}
        for line in index_result.stdout.strip().split("\n"):
            parts = line.split("\t")
            meta = parts[0].split()
            index_shas[parts[1]] = meta[1]

        for path, tree_sha in tree_shas.items():
            assert path in index_shas, f"{path} missing from index"
            assert tree_sha == index_shas[path], (
                f"SHA mismatch for {path}: tree={tree_sha}, index={index_shas[path]}"
            )

    def test_index_binary_header(self):
        with open(os.path.join(GIT_DIR, "index"), "rb") as f:
            raw = f.read()

        assert raw[:4] == b"DIRC", "Index must start with DIRC signature"
        version = struct.unpack(">I", raw[4:8])[0]
        assert version == 2, f"Index version must be 2, got {version}"
        count = struct.unpack(">I", raw[8:12])[0]
        assert count == 9, f"Index entry count must be 9, got {count}"

    def test_index_sha1_checksum(self):
        with open(os.path.join(GIT_DIR, "index"), "rb") as f:
            raw = f.read()

        stored_checksum = raw[-20:]
        computed_checksum = hashlib.sha1(raw[:-20]).digest()
        assert stored_checksum == computed_checksum, (
            "Index SHA-1 trailer checksum is incorrect"
        )


# ── Object store ─────────────────────────────────────────────────────────


class TestObjectStore:
    def test_blob_content_readme(self):
        result = run_git("show", "HEAD:README.md")
        assert result.returncode == 0
        assert "# Forge Project" in result.stdout
        assert "Updated with new modules" in result.stdout

    def test_blob_content_data_txt(self):
        result = run_git("show", "HEAD:data.txt")
        assert result.returncode == 0
        assert "Flat data file at root level." in result.stdout

    def test_blob_content_lib_py(self):
        result = run_git("show", "HEAD:src/lib.py")
        assert result.returncode == 0
        assert "Namespace package marker" in result.stdout

    def test_blob_content_config_json(self):
        """Verify the config blob is accessible (tests misplaced-blob fix)."""
        result = run_git("show", "HEAD:data/config.json")
        assert result.returncode == 0
        assert '"version": 2' in result.stdout

    def test_object_zlib_and_header(self):
        """Verify a raw object has correct zlib + header format."""
        result = run_git("rev-parse", "HEAD:LICENSE")
        assert result.returncode == 0
        sha = result.stdout.strip()

        obj_path = os.path.join(GIT_DIR, "objects", sha[:2], sha[2:])
        assert os.path.exists(obj_path), f"Object file missing: {obj_path}"

        with open(obj_path, "rb") as f:
            compressed = f.read()

        decompressed = zlib.decompress(compressed)
        null_idx = decompressed.index(b"\x00")
        header = decompressed[:null_idx].decode("ascii")
        parts = header.split(" ")
        assert parts[0] == "blob", f"Expected blob, got {parts[0]}"
        content = decompressed[null_idx + 1:]
        assert int(parts[1]) == len(content), (
            f"Header size {parts[1]} != content length {len(content)}"
        )

    def test_object_sha_matches_path(self):
        """The object's path must be derived from its SHA-1 hash."""
        result = run_git("rev-parse", "HEAD:data.txt")
        sha = result.stdout.strip()

        obj_path = os.path.join(GIT_DIR, "objects", sha[:2], sha[2:])
        with open(obj_path, "rb") as f:
            compressed = f.read()

        decompressed = zlib.decompress(compressed)
        computed_sha = hashlib.sha1(decompressed).hexdigest()
        assert computed_sha == sha, (
            f"Object path implies SHA {sha}, but content hashes to {computed_sha}"
        )

    def test_all_loose_objects_valid(self):
        """Every loose object's SHA must match its path."""
        objects_dir = os.path.join(GIT_DIR, "objects")
        for prefix in os.listdir(objects_dir):
            pdir = os.path.join(objects_dir, prefix)
            if not os.path.isdir(pdir) or prefix in ("info", "pack"):
                continue
            for fname in os.listdir(pdir):
                fpath = os.path.join(pdir, fname)
                path_sha = prefix + fname
                with open(fpath, "rb") as f:
                    compressed = f.read()
                raw = zlib.decompress(compressed)
                actual_sha = hashlib.sha1(raw).hexdigest()
                assert actual_sha == path_sha, (
                    f"Object at {prefix}/{fname} has SHA {actual_sha}, "
                    f"expected {path_sha}"
                )


# ── Working tree ─────────────────────────────────────────────────────────


class TestWorkingTree:
    def test_all_files_exist(self):
        result = run_git("ls-tree", "-r", "--name-only", "HEAD")
        for path in result.stdout.strip().split("\n"):
            full = os.path.join(REPO_DIR, path)
            assert os.path.exists(full), f"Working tree file missing: {path}"

    def test_working_tree_content_matches_blobs(self):
        result = run_git("ls-tree", "-r", "--name-only", "HEAD")
        for path in result.stdout.strip().split("\n"):
            with open(os.path.join(REPO_DIR, path), "r") as f:
                wt = f.read()
            show = run_git("show", f"HEAD:{path}")
            assert show.stdout == wt, (
                f"Content mismatch for {path}: "
                f"worktree={wt!r}, blob={show.stdout!r}"
            )

    def test_lib0_py_content_complete(self):
        """src/lib0.py must have full content (tests truncation fix)."""
        with open(os.path.join(REPO_DIR, "src", "lib0.py")) as f:
            content = f.read()
        assert "# Additional module" in content
        assert "VERSION = '0.1'" in content

    def test_git_status_clean(self):
        """After repair, git status should show a clean working tree."""
        result = run_git("status", "--porcelain")
        assert result.returncode == 0
        output = result.stdout.strip()
        assert output == "", (
            f"Working tree should be clean, but git status shows:\n{output}"
        )
