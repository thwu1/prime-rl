
"""
Tests for Git packfile reading support in gitlib.py and the wyag-cat-file CLI tool.

Uses the git CLI as a ground-truth oracle: every object read through the
library is compared against the output of git cat-file / git ls-tree / etc.
"""

import subprocess
import sys
import os

sys.path.insert(0, '/app')
import gitlib

REPO_PATH = '/app/repo'


def git_cmd(*args):
    """Run a git command in the test repo and return stripped stdout text."""
    result = subprocess.run(
        ['git'] + list(args),
        cwd=REPO_PATH,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def git_cmd_bytes(*args):
    """Run a git command in the test repo and return raw stdout bytes."""
    result = subprocess.run(
        ['git'] + list(args),
        cwd=REPO_PATH,
        capture_output=True,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.decode()}"
    return result.stdout


# --------------------------------------------------------------------------
# Basic object reading
# --------------------------------------------------------------------------

def test_read_head_commit():
    """HEAD commit can be read and has the correct type."""
    repo = gitlib.GitRepository(REPO_PATH)
    head_sha = git_cmd('rev-parse', 'HEAD')
    obj = gitlib.object_read(repo, head_sha)
    assert isinstance(obj, gitlib.GitCommit), f"Expected GitCommit, got {type(obj).__name__}"
    assert obj.fmt == b'commit'


def test_commit_content_matches():
    """Serialized commit matches git cat-file -p output byte-for-byte."""
    repo = gitlib.GitRepository(REPO_PATH)
    head_sha = git_cmd('rev-parse', 'HEAD')
    obj = gitlib.object_read(repo, head_sha)

    expected = git_cmd_bytes('cat-file', '-p', head_sha)
    actual = obj.serialize()
    assert actual == expected, (
        f"Commit content mismatch for {head_sha}\n"
        f"Expected ({len(expected)} bytes): {expected[:200]!r}\n"
        f"Actual   ({len(actual)} bytes): {actual[:200]!r}"
    )


def test_read_tree_object():
    """Root tree of HEAD can be read and has entries."""
    repo = gitlib.GitRepository(REPO_PATH)
    tree_sha = git_cmd('rev-parse', 'HEAD^{tree}')
    obj = gitlib.object_read(repo, tree_sha)
    assert isinstance(obj, gitlib.GitTree), f"Expected GitTree, got {type(obj).__name__}"
    assert len(obj.items) > 0, "Tree should have at least one entry"


def test_tree_entries_match():
    """Tree entries match git ls-tree output."""
    repo = gitlib.GitRepository(REPO_PATH)
    tree_sha = git_cmd('rev-parse', 'HEAD^{tree}')
    obj = gitlib.object_read(repo, tree_sha)

    ls_output = git_cmd('ls-tree', tree_sha)
    lines = [l for l in ls_output.strip().split('\n') if l]

    assert len(obj.items) == len(lines), (
        f"Expected {len(lines)} entries, got {len(obj.items)}"
    )

    # Build a dict from ls-tree for comparison
    expected_entries = {}
    for line in lines:
        parts = line.split('\t')
        meta = parts[0].split()
        expected_entries[parts[1]] = meta[2]  # path -> sha

    for item in obj.items:
        assert item.path in expected_entries, f"Unexpected tree entry: {item.path}"
        assert item.sha == expected_entries[item.path], (
            f"SHA mismatch for {item.path}: {item.sha} != {expected_entries[item.path]}"
        )


# --------------------------------------------------------------------------
# Blob reading
# --------------------------------------------------------------------------

def test_read_blob_object():
    """README.md blob content matches git cat-file -p."""
    repo = gitlib.GitRepository(REPO_PATH)
    blob_sha = git_cmd('rev-parse', 'HEAD:README.md')
    obj = gitlib.object_read(repo, blob_sha)
    assert isinstance(obj, gitlib.GitBlob), f"Expected GitBlob, got {type(obj).__name__}"

    expected = git_cmd_bytes('cat-file', '-p', blob_sha)
    assert obj.blobdata == expected, "Blob content mismatch for README.md"


def test_read_multiple_blobs():
    """Several blobs from different directories can be read correctly."""
    repo = gitlib.GitRepository(REPO_PATH)
    paths = [
        'src/main.py',
        'lib/math_ops.py',
        'src/utils.py',
        'lib/string_ops.py',
        'src/config.py',
        'docs/api.md',
    ]

    for path in paths:
        blob_sha = git_cmd('rev-parse', f'HEAD:{path}')
        obj = gitlib.object_read(repo, blob_sha)
        assert isinstance(obj, gitlib.GitBlob), (
            f"Expected GitBlob for {path}, got {type(obj).__name__}"
        )
        expected = git_cmd_bytes('cat-file', '-p', blob_sha)
        assert obj.blobdata == expected, f"Blob content mismatch for {path}"


# --------------------------------------------------------------------------
# History traversal
# --------------------------------------------------------------------------

def test_traverse_commit_history():
    """Walking parent links visits every commit reachable from HEAD."""
    repo = gitlib.GitRepository(REPO_PATH)
    sha = git_cmd('rev-parse', 'HEAD')

    expected_count = int(git_cmd('rev-list', '--count', 'HEAD'))

    count = 0
    while sha:
        obj = gitlib.object_read(repo, sha)
        assert isinstance(obj, gitlib.GitCommit), (
            f"Expected GitCommit at {sha}, got {type(obj).__name__}"
        )
        count += 1
        if b'parent' in obj.kvlm:
            parent = obj.kvlm[b'parent']
            if isinstance(parent, list):
                sha = parent[0].decode('ascii')
            else:
                sha = parent.decode('ascii')
        else:
            sha = None

    assert count == expected_count, (
        f"Expected {expected_count} commits, traversed {count}"
    )


# --------------------------------------------------------------------------
# Tag reading
# --------------------------------------------------------------------------

def test_read_tag_object():
    """Annotated tag v0.1.0 can be read and its content matches."""
    repo = gitlib.GitRepository(REPO_PATH)
    tag_sha = git_cmd('rev-parse', 'v0.1.0')
    tag_type = git_cmd('cat-file', '-t', tag_sha)

    if tag_type == 'tag':
        obj = gitlib.object_read(repo, tag_sha)
        assert isinstance(obj, gitlib.GitTag), (
            f"Expected GitTag, got {type(obj).__name__}"
        )
        expected = git_cmd_bytes('cat-file', '-p', tag_sha)
        assert obj.serialize() == expected, "Tag content mismatch for v0.1.0"


# --------------------------------------------------------------------------
# Comprehensive object verification
# --------------------------------------------------------------------------

def test_all_reachable_objects():
    """Every reachable object can be read and has the correct type."""
    repo = gitlib.GitRepository(REPO_PATH)

    output = git_cmd('rev-list', '--objects', '--all')
    lines = [l for l in output.strip().split('\n') if l]

    type_map = {
        'commit': gitlib.GitCommit,
        'tree': gitlib.GitTree,
        'blob': gitlib.GitBlob,
        'tag': gitlib.GitTag,
    }

    checked = 0
    for line in lines:
        sha = line.split()[0]
        expected_type = git_cmd('cat-file', '-t', sha)

        obj = gitlib.object_read(repo, sha)
        expected_class = type_map[expected_type]
        assert isinstance(obj, expected_class), (
            f"Object {sha}: expected {expected_type}, got {type(obj).__name__}"
        )
        checked += 1

    assert checked >= 10, (
        f"Expected to check at least 10 objects, only checked {checked}"
    )


def test_object_hash_roundtrip():
    """Reading an object and re-hashing it reproduces the original SHA."""
    repo = gitlib.GitRepository(REPO_PATH)

    # Check several object types
    shas = [
        git_cmd('rev-parse', 'HEAD'),
        git_cmd('rev-parse', 'HEAD^{tree}'),
        git_cmd('rev-parse', 'HEAD:README.md'),
    ]

    for sha in shas:
        obj = gitlib.object_read(repo, sha)
        data = obj.serialize()
        computed = gitlib.object_hash(data, obj.fmt)
        assert computed == sha, (
            f"Hash roundtrip failed: computed {computed} != original {sha}"
        )


# --------------------------------------------------------------------------
# Delta decompression (exercises OFS_DELTA / REF_DELTA paths)
# --------------------------------------------------------------------------

def test_historical_blob_versions():
    """Reading blobs from older commits exercises delta decompression.

    git gc typically stores older versions of files as deltas against
    newer versions, so reading historical blobs forces the packfile
    reader to resolve delta chains.
    """
    repo = gitlib.GitRepository(REPO_PATH)
    commits = git_cmd('rev-list', 'HEAD').strip().split('\n')

    blob_contents = {}
    for commit_sha in commits:
        for path in ['src/main.py', 'README.md', 'lib/math_ops.py']:
            try:
                blob_sha = git_cmd('rev-parse', f'{commit_sha}:{path}')
            except AssertionError:
                continue  # file may not exist in early commits
            if blob_sha not in blob_contents:
                obj = gitlib.object_read(repo, blob_sha)
                expected = git_cmd_bytes('cat-file', '-p', blob_sha)
                assert obj.blobdata == expected, (
                    f"Content mismatch for {path} at {commit_sha[:8]}"
                )
                blob_contents[blob_sha] = True

    # We expect several distinct versions
    assert len(blob_contents) >= 6, (
        f"Expected at least 6 distinct blobs across history, got {len(blob_contents)}"
    )


def test_subtree_objects():
    """Read subtree objects (src/, lib/, docs/) and verify their entries."""
    repo = gitlib.GitRepository(REPO_PATH)
    root_tree_sha = git_cmd('rev-parse', 'HEAD^{tree}')
    root_tree = gitlib.object_read(repo, root_tree_sha)

    subtree_count = 0
    for item in root_tree.items:
        if item.mode.startswith(b'40') or item.mode.startswith(b'04'):
            subtree_count += 1
            sub_obj = gitlib.object_read(repo, item.sha)
            assert isinstance(sub_obj, gitlib.GitTree), (
                f"Subtree {item.path} should be GitTree, got {type(sub_obj).__name__}"
            )
            assert len(sub_obj.items) > 0, (
                f"Subtree {item.path} should have entries"
            )

            expected_ls = git_cmd('ls-tree', item.sha)
            expected_count = len([l for l in expected_ls.strip().split('\n') if l])
            assert len(sub_obj.items) == expected_count, (
                f"Subtree {item.path}: expected {expected_count} entries, "
                f"got {len(sub_obj.items)}"
            )

    assert subtree_count >= 3, (
        f"Expected at least 3 subtrees (src, lib, docs), got {subtree_count}"
    )


# --------------------------------------------------------------------------
# CLI tool tests — wyag-cat-file
# --------------------------------------------------------------------------

def test_cli_tool_exists_and_executable():
    """The wyag-cat-file CLI tool must exist at /app/wyag-cat-file and be executable."""
    assert os.path.isfile('/app/wyag-cat-file'), \
        "CLI tool not found at /app/wyag-cat-file"
    assert os.access('/app/wyag-cat-file', os.X_OK), \
        "/app/wyag-cat-file is not executable (missing chmod +x)"


def test_cli_cat_file_type_commit():
    """wyag-cat-file -t prints 'commit' for the HEAD commit."""
    head_sha = git_cmd('rev-parse', 'HEAD')
    result = subprocess.run(
        ['/app/wyag-cat-file', '-t', head_sha, '--repo', REPO_PATH],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr}"
    assert result.stdout.strip() == 'commit', (
        f"Expected type 'commit', got '{result.stdout.strip()}'"
    )


def test_cli_cat_file_type_blob():
    """wyag-cat-file -t prints 'blob' for a blob object."""
    blob_sha = git_cmd('rev-parse', 'HEAD:README.md')
    result = subprocess.run(
        ['/app/wyag-cat-file', '-t', blob_sha, '--repo', REPO_PATH],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr}"
    assert result.stdout.strip() == 'blob', (
        f"Expected type 'blob', got '{result.stdout.strip()}'"
    )


def test_cli_cat_file_type_tree():
    """wyag-cat-file -t prints 'tree' for a tree object."""
    tree_sha = git_cmd('rev-parse', 'HEAD^{tree}')
    result = subprocess.run(
        ['/app/wyag-cat-file', '-t', tree_sha, '--repo', REPO_PATH],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr}"
    assert result.stdout.strip() == 'tree', (
        f"Expected type 'tree', got '{result.stdout.strip()}'"
    )


def test_cli_cat_file_pretty_commit():
    """wyag-cat-file -p output matches git cat-file -p for commits."""
    head_sha = git_cmd('rev-parse', 'HEAD')
    expected = git_cmd_bytes('cat-file', '-p', head_sha)
    result = subprocess.run(
        ['/app/wyag-cat-file', '-p', head_sha, '--repo', REPO_PATH],
        capture_output=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr.decode()}"
    assert result.stdout == expected, (
        f"CLI commit output differs from git cat-file -p\n"
        f"Expected ({len(expected)} bytes): {expected[:200]!r}\n"
        f"Got      ({len(result.stdout)} bytes): {result.stdout[:200]!r}"
    )


def test_cli_cat_file_pretty_blob():
    """wyag-cat-file -p output matches git cat-file -p for blobs."""
    blob_sha = git_cmd('rev-parse', 'HEAD:README.md')
    expected = git_cmd_bytes('cat-file', '-p', blob_sha)
    result = subprocess.run(
        ['/app/wyag-cat-file', '-p', blob_sha, '--repo', REPO_PATH],
        capture_output=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr.decode()}"
    assert result.stdout == expected, (
        f"CLI blob output differs from git cat-file -p\n"
        f"Expected ({len(expected)} bytes): {expected[:200]!r}\n"
        f"Got      ({len(result.stdout)} bytes): {result.stdout[:200]!r}"
    )


def test_cli_cat_file_pretty_tree():
    """wyag-cat-file -p output matches git cat-file -p for tree objects.

    Tree pretty-printing requires resolving entry types from modes and
    formatting with zero-padded modes, matching git cat-file -p exactly.
    """
    tree_sha = git_cmd('rev-parse', 'HEAD^{tree}')
    expected = git_cmd_bytes('cat-file', '-p', tree_sha)
    result = subprocess.run(
        ['/app/wyag-cat-file', '-p', tree_sha, '--repo', REPO_PATH],
        capture_output=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr.decode()}"
    assert result.stdout == expected, (
        f"CLI tree output differs from git cat-file -p\n"
        f"Expected:\n{expected.decode()}\nGot:\n{result.stdout.decode()}"
    )


def test_cli_cat_file_pretty_subtree():
    """wyag-cat-file -p works for a subtree (e.g. src/) and matches git."""
    subtree_sha = git_cmd('rev-parse', 'HEAD:src')
    expected = git_cmd_bytes('cat-file', '-p', subtree_sha)
    result = subprocess.run(
        ['/app/wyag-cat-file', '-p', subtree_sha, '--repo', REPO_PATH],
        capture_output=True,
    )
    assert result.returncode == 0, f"CLI tool failed: {result.stderr.decode()}"
    assert result.stdout == expected, (
        f"CLI subtree output differs from git cat-file -p\n"
        f"Expected:\n{expected.decode()}\nGot:\n{result.stdout.decode()}"
    )


def test_cli_multiple_object_types():
    """CLI tool correctly handles a sequence of different object types."""
    shas_and_types = [
        (git_cmd('rev-parse', 'HEAD'), 'commit'),
        (git_cmd('rev-parse', 'HEAD^{tree}'), 'tree'),
        (git_cmd('rev-parse', 'HEAD:README.md'), 'blob'),
        (git_cmd('rev-parse', 'HEAD:src/main.py'), 'blob'),
    ]

    for sha, expected_type in shas_and_types:
        # Check -t
        result_t = subprocess.run(
            ['/app/wyag-cat-file', '-t', sha, '--repo', REPO_PATH],
            capture_output=True, text=True,
        )
        assert result_t.returncode == 0, f"CLI -t failed for {sha}: {result_t.stderr}"
        assert result_t.stdout.strip() == expected_type, (
            f"Type mismatch for {sha}: expected {expected_type}, "
            f"got {result_t.stdout.strip()}"
        )

        # Check -p matches git
        expected_content = git_cmd_bytes('cat-file', '-p', sha)
        result_p = subprocess.run(
            ['/app/wyag-cat-file', '-p', sha, '--repo', REPO_PATH],
            capture_output=True,
        )
        assert result_p.returncode == 0, f"CLI -p failed for {sha}: {result_p.stderr.decode()}"
        assert result_p.stdout == expected_content, (
            f"Content mismatch for {sha} (type={expected_type})"
        )
