"""Tests for pack index generator and git repository repair.

Verifies: (1) the solver wrote a working pack_index_gen.py that generates
correct Pack Index v2 files from arbitrary pack files; (2) the original
repository at /app/repo/ is fully functional.

"""

import os
import shutil
import subprocess
import tempfile

import pytest

REPO_DIR = "/app/repo"
PROGRAM = "/app/pack_index_gen.py"
ORIG_IP_BACKUP = "/usr/lib/git-core/.idx-pack-backup"
IP_PATH = "/usr/lib/git-core/git-index-pack"


def _disable_index_pack():
    """Replace git-index-pack with a stub that always fails."""
    with open(IP_PATH, "w") as f:
        f.write('#!/bin/sh\necho "git-index-pack: disabled for anti-cheat test" >&2\nexit 1\n')
    os.chmod(IP_PATH, 0o755)


def _restore_index_pack():
    """Restore the real git-index-pack from the backup."""
    if os.path.isfile(ORIG_IP_BACKUP):
        shutil.copy2(ORIG_IP_BACKUP, IP_PATH)
        os.chmod(IP_PATH, 0o755)


def git(*args, check=True, repo=REPO_DIR):
    """Run a git command against a repo and return CompletedProcess."""
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


# ---------------------------------------------------------------------------
# Module-scoped fixture: independent pack test environment
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def independent_pack_env():
    """Create a fresh git repo, pack it, save reference idx, delete idx,
    temporarily disable git-index-pack, run solver's program, restore
    git-index-pack, yield results for verification tests."""

    test_dir = tempfile.mkdtemp(prefix="packtest_")

    try:
        env_base = os.environ.copy()

        # git-index-pack is available here (restored by test.sh)
        _restore_index_pack()

        # Create test repository with deterministic content
        subprocess.run(["git", "init", test_dir],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", test_dir, "config", "user.name", "Tester"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", test_dir, "config", "user.email", "t@test.com"],
                       check=True, capture_output=True)

        # Commit 1: large file (triggers delta compression later)
        env1 = {**env_base,
                "GIT_AUTHOR_DATE": "2024-06-01T00:00:00+0000",
                "GIT_COMMITTER_DATE": "2024-06-01T00:00:00+0000"}
        with open(os.path.join(test_dir, "data.txt"), "w") as f:
            for i in range(200):
                f.write(f"line {i:04d}: {'x' * 60}\n")
        subprocess.run(["git", "-C", test_dir, "add", "."],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", test_dir, "commit", "-m", "Initial data"],
                       check=True, capture_output=True, env=env1)

        # Commit 2: slight modification (delta target) + new file
        env2 = {**env_base,
                "GIT_AUTHOR_DATE": "2024-06-02T00:00:00+0000",
                "GIT_COMMITTER_DATE": "2024-06-02T00:00:00+0000"}
        with open(os.path.join(test_dir, "data.txt"), "w") as f:
            for i in range(200):
                if i == 100:
                    f.write(f"line {i:04d}: MODIFIED_VALUE {'y' * 50}\n")
                else:
                    f.write(f"line {i:04d}: {'x' * 60}\n")
        with open(os.path.join(test_dir, "extra.txt"), "w") as f:
            f.write("Extra file content\n")
        subprocess.run(["git", "-C", test_dir, "add", "."],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", test_dir, "commit", "-m", "Modify data"],
                       check=True, capture_output=True, env=env2)

        # Commit 3: another file
        env3 = {**env_base,
                "GIT_AUTHOR_DATE": "2024-06-03T00:00:00+0000",
                "GIT_COMMITTER_DATE": "2024-06-03T00:00:00+0000"}
        with open(os.path.join(test_dir, "config.json"), "w") as f:
            f.write('{"key": "value", "number": 42}\n')
        subprocess.run(["git", "-C", test_dir, "add", "."],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", test_dir, "commit", "-m", "Add config"],
                       check=True, capture_output=True, env=env3)

        # Pack everything
        subprocess.run(
            ["git", "-C", test_dir, "gc", "--aggressive", "--prune=now"],
            check=True, capture_output=True, timeout=60,
        )

        # Locate pack file
        pack_dir = os.path.join(test_dir, ".git", "objects", "pack")
        packs = [f for f in os.listdir(pack_dir) if f.endswith(".pack")]
        assert len(packs) == 1, f"Expected 1 pack, found {len(packs)}"
        pack_path = os.path.join(pack_dir, packs[0])
        idx_path = pack_path[:-5] + ".idx"

        # Save reference idx
        with open(idx_path, "rb") as f:
            ref_idx = f.read()

        # Delete idx
        os.remove(idx_path)

        # --- Temporarily disable git-index-pack, run solver, restore ---
        gen_result = None
        try:
            _disable_index_pack()

            gen_result = subprocess.run(
                ["python3", PROGRAM, pack_path],
                capture_output=True, text=True, timeout=120,
            )
        finally:
            # Always restore so verification tests work
            _restore_index_pack()

        yield {
            "test_dir": test_dir,
            "pack_path": pack_path,
            "idx_path": idx_path,
            "ref_idx": ref_idx,
            "gen_result": gen_result,
        }

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Pack index generator program tests
# ---------------------------------------------------------------------------


class TestPackIndexProgram:
    """The solver must have created /app/pack_index_gen.py."""

    def test_program_exists(self):
        assert os.path.isfile(PROGRAM), f"{PROGRAM} not found"

    def test_program_is_valid_python(self):
        result = subprocess.run(
            ["python3", "-c", f"import py_compile; py_compile.compile('{PROGRAM}', doraise=True)"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"pack_index_gen.py has syntax errors:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Independent pack file tests (anti-cheat: unseen pack)
# ---------------------------------------------------------------------------


class TestIndependentPack:
    """Run solver's pack_index_gen.py on a pack file it has never seen."""

    def test_generator_succeeds(self, independent_pack_env):
        r = independent_pack_env["gen_result"]
        assert r is not None, "Generator did not run"
        assert r.returncode == 0, (
            f"pack_index_gen.py failed on independent pack:\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_idx_file_created(self, independent_pack_env):
        assert os.path.isfile(independent_pack_env["idx_path"]), (
            "No .idx file was generated for the independent pack"
        )

    def test_idx_matches_reference(self, independent_pack_env):
        """Generated idx must be byte-identical to git's own idx."""
        idx_path = independent_pack_env["idx_path"]
        if not os.path.isfile(idx_path):
            pytest.skip("idx not generated")
        with open(idx_path, "rb") as f:
            generated = f.read()
        ref = independent_pack_env["ref_idx"]
        assert generated == ref, (
            f"Generated idx ({len(generated)} bytes) differs from reference "
            f"({len(ref)} bytes). First difference at byte "
            f"{next((i for i in range(min(len(generated), len(ref))) if generated[i] != ref[i]), 'N/A')}"
        )

    def test_verify_pack_succeeds(self, independent_pack_env):
        if not os.path.isfile(independent_pack_env["idx_path"]):
            pytest.skip("idx not generated")
        pack_path = independent_pack_env["pack_path"]
        result = subprocess.run(
            ["git", "verify-pack", "-v", pack_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"git verify-pack failed:\n{result.stderr}"
        )

    def test_fsck_passes(self, independent_pack_env):
        if not os.path.isfile(independent_pack_env["idx_path"]):
            pytest.skip("idx not generated")
        result = subprocess.run(
            ["git", "-C", independent_pack_env["test_dir"],
             "fsck", "--full", "--strict"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"fsck failed:\n{result.stderr}"

    def test_log_shows_three_commits(self, independent_pack_env):
        if not os.path.isfile(independent_pack_env["idx_path"]):
            pytest.skip("idx not generated")
        result = subprocess.run(
            ["git", "-C", independent_pack_env["test_dir"],
             "log", "--oneline"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 3, (
            f"Expected 3 commits, got {len(lines)}:\n{result.stdout}"
        )

    def test_file_content_accessible(self, independent_pack_env):
        if not os.path.isfile(independent_pack_env["idx_path"]):
            pytest.skip("idx not generated")
        td = independent_pack_env["test_dir"]
        result = subprocess.run(
            ["git", "-C", td, "show", "HEAD:data.txt"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "MODIFIED_VALUE" in result.stdout


# ---------------------------------------------------------------------------
# Repository health (original repo at /app/repo/)
# ---------------------------------------------------------------------------


class TestFsck:
    """git fsck --full --strict must pass cleanly."""

    def test_fsck_exits_zero(self):
        result = git("fsck", "--full", "--strict")
        assert result.returncode == 0

    def test_fsck_no_errors_on_stderr(self):
        result = git("fsck", "--full", "--strict")
        error_lines = [
            l
            for l in result.stderr.strip().split("\n")
            if l.strip()
            and "dangling" not in l.lower()
            and "notice" not in l.lower()
        ]
        assert len(error_lines) == 0, (
            f"fsck produced error output:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Commit history
# ---------------------------------------------------------------------------


class TestCommitHistory:
    """Complete commit history must be accessible."""

    def test_log_shows_five_commits(self):
        result = git("log", "--oneline")
        commits = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(commits) == 5, (
            f"Expected 5 commits, got {len(commits)}:\n{result.stdout}"
        )

    def test_commit_messages_in_order(self):
        result = git("log", "--format=%s")
        messages = [m for m in result.stdout.strip().split("\n") if m.strip()]
        expected = [
            "Prepare v1.0.0 release",
            "Update record 250 and add engine status method",
            "Add dataset with 500 records",
            "Add engine module with config processing",
            "Initial project setup",
        ]
        assert messages == expected, (
            f"Commit messages don't match.\nExpected: {expected}\nGot: {messages}"
        )

    def test_all_commits_reachable_from_head(self):
        result = git("rev-list", "HEAD")
        shas = [s for s in result.stdout.strip().split("\n") if s.strip()]
        assert len(shas) == 5

    def test_first_commit_accessible(self):
        result = git("log", "--format=%H", "--reverse")
        first_sha = result.stdout.strip().split("\n")[0]
        result = git("show", f"{first_sha}:README.md")
        assert "Project Alpha" in result.stdout


# ---------------------------------------------------------------------------
# File content recovery
# ---------------------------------------------------------------------------


class TestFileContent:
    """All committed files must be recoverable with correct content."""

    def test_readme(self):
        result = git("show", "HEAD:README.md")
        assert result.stdout.strip() == "# Project Alpha"

    def test_main_py(self):
        result = git("show", "HEAD:main.py")
        assert "Project Alpha v0.1" in result.stdout
        assert "def main():" in result.stdout

    def test_engine_module(self):
        result = git("show", "HEAD:src/engine.py")
        assert "class Engine:" in result.stdout
        assert "def _process(self):" in result.stdout
        assert "def status(self):" in result.stdout

    def test_engine_status_method_body(self):
        result = git("show", "HEAD:src/engine.py")
        assert "config_keys" in result.stdout
        assert "self.running" in result.stdout

    def test_version_file(self):
        result = git("show", "HEAD:VERSION")
        assert result.stdout.strip() == "v1.0.0"

    def test_changelog(self):
        result = git("show", "HEAD:CHANGELOG.md")
        assert "Initial release" in result.stdout
        assert "Engine module" in result.stdout

    def test_records_csv_line_count(self):
        result = git("show", "HEAD:data/records.csv")
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 500, f"Expected 500 lines, got {len(lines)}"

    def test_records_csv_modified_line(self):
        result = git("show", "HEAD:data/records.csv")
        lines = result.stdout.strip().split("\n")
        assert "record_0250: MODIFIED_FIELD=999" in lines[250]

    def test_records_csv_unmodified_line(self):
        result = git("show", "HEAD:data/records.csv")
        lines = result.stdout.strip().split("\n")
        assert "record_0100: alpha=1 beta=2" in lines[100]

    def test_records_first_line(self):
        result = git("show", "HEAD:data/records.csv")
        lines = result.stdout.strip().split("\n")
        assert lines[0].startswith("record_0000:")

    def test_records_last_line(self):
        result = git("show", "HEAD:data/records.csv")
        lines = result.stdout.strip().split("\n")
        assert lines[499].startswith("record_0499:")


# ---------------------------------------------------------------------------
# Pack integrity
# ---------------------------------------------------------------------------


class TestPackIntegrity:
    """Pack files must be valid and have matching index files."""

    def test_pack_dir_exists(self):
        pack_dir = os.path.join(REPO_DIR, ".git", "objects", "pack")
        assert os.path.isdir(pack_dir)

    def test_every_pack_has_idx(self):
        pack_dir = os.path.join(REPO_DIR, ".git", "objects", "pack")
        packs = {f[:-5] for f in os.listdir(pack_dir) if f.endswith(".pack")}
        idxs = {f[:-4] for f in os.listdir(pack_dir) if f.endswith(".idx")}
        assert len(packs) > 0, "No pack files found"
        assert packs == idxs, (
            f"Pack/idx mismatch.\nPacks: {packs}\nIdxs: {idxs}"
        )

    def test_verify_pack_succeeds(self):
        pack_dir = os.path.join(REPO_DIR, ".git", "objects", "pack")
        for f in os.listdir(pack_dir):
            if f.endswith(".pack"):
                result = git("verify-pack", "-v", os.path.join(pack_dir, f))
                assert result.returncode == 0, (
                    f"verify-pack failed for {f}:\n{result.stderr}"
                )


# ---------------------------------------------------------------------------
# Tag recovery
# ---------------------------------------------------------------------------


class TestTagRecovery:
    """Annotated tags must be accessible."""

    def test_tag_listed(self):
        result = git("tag", "-l")
        assert "v1.0.0" in result.stdout

    def test_tag_message(self):
        result = git("tag", "-l", "-n1", "v1.0.0")
        assert "Release version 1.0.0" in result.stdout

    def test_tag_points_to_correct_commit(self):
        result = git("log", "-1", "--format=%s", "v1.0.0")
        assert result.stdout.strip() == "Prepare v1.0.0 release"


# ---------------------------------------------------------------------------
# Config sanity
# ---------------------------------------------------------------------------


class TestConfigSanity:
    """Repository config must allow normal git operations."""

    def test_status_works(self):
        result = git("status", check=False)
        assert result.returncode == 0, f"git status failed: {result.stderr}"

    def test_branch_exists(self):
        result = git("branch", "-l")
        assert result.returncode == 0
        branches = [
            l.strip().lstrip("* ")
            for l in result.stdout.strip().split("\n")
            if l.strip()
        ]
        assert len(branches) >= 1
