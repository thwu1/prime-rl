
import os
import subprocess
import tempfile
import struct
import stat
import pytest

BINARY = "/app/arkv"
SCRIPT = "/app/arkv.py"
FIXED_TIME = 1705276800  # 2024-01-15T00:00:00 UTC


def run_ref(args, cwd=None, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        [BINARY] + args, capture_output=True, text=True, timeout=30, cwd=cwd, env=env
    )
    return r.stdout, r.stderr, r.returncode


def run_impl(args, cwd=None, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        ["python3", SCRIPT] + args,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
        env=env,
    )
    return r.stdout, r.stderr, r.returncode


def make_file(dirpath, name, content, mode=0o644):
    path = os.path.join(dirpath, name)
    if isinstance(content, str):
        content = content.encode()
    with open(path, "wb") as f:
        f.write(content)
    os.chmod(path, mode)
    os.utime(path, (FIXED_TIME, FIXED_TIME))
    return path


def make_dir(dirpath, name, mode=0o755):
    path = os.path.join(dirpath, name)
    os.makedirs(path, exist_ok=True)
    os.chmod(path, mode)
    os.utime(path, (FIXED_TIME, FIXED_TIME))
    return path


@pytest.fixture
def workdir():
    with tempfile.TemporaryDirectory() as d:
        make_file(d, "hello.txt", "Hello, World!")
        make_file(d, "data.bin", bytes(range(256)), mode=0o600)
        make_file(d, "empty.txt", b"")
        make_dir(d, "subdir")
        yield d


def read_bytes(workdir, name):
    with open(os.path.join(workdir, name), "rb") as f:
        return f.read()


# ===== Format compatibility: byte-identical archives =====


class TestFormatCompat:
    def test_single_file(self, workdir):
        run_ref(["create", "ref.arkv", "hello.txt"], cwd=workdir)
        run_impl(["create", "impl.arkv", "hello.txt"], cwd=workdir)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_multi_file(self, workdir):
        run_ref(["create", "ref.arkv", "hello.txt", "data.bin"], cwd=workdir)
        run_impl(["create", "impl.arkv", "hello.txt", "data.bin"], cwd=workdir)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_with_directory(self, workdir):
        run_ref(["create", "ref.arkv", "hello.txt", "subdir"], cwd=workdir)
        run_impl(["create", "impl.arkv", "hello.txt", "subdir"], cwd=workdir)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_empty_file(self, workdir):
        run_ref(["create", "ref.arkv", "empty.txt"], cwd=workdir)
        run_impl(["create", "impl.arkv", "empty.txt"], cwd=workdir)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_with_checksum(self, workdir):
        env = {"ARKV_CHECKSUM": "1"}
        run_ref(["create", "ref.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env)
        run_impl(["create", "impl.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_with_scramble(self, workdir):
        env = {"ARKV_SCRAMBLE": "1"}
        run_ref(["create", "ref.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env)
        run_impl(["create", "impl.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_with_both_flags(self, workdir):
        env = {"ARKV_CHECKSUM": "1", "ARKV_SCRAMBLE": "1"}
        run_ref(["create", "ref.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env)
        run_impl(["create", "impl.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env)
        assert read_bytes(workdir, "ref.arkv") == read_bytes(workdir, "impl.arkv")

    def test_binary_header(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir)
        data = read_bytes(workdir, "test.arkv")
        assert data[:4] == b"ARKV"
        assert data[4] == 2  # version
        assert data[-8:] == b"ARKV_END"


# ===== Command output comparison =====


class TestListCommand:
    def test_list_output(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt", "data.bin", "subdir"], cwd=workdir)
        out_c, _, rc_c = run_ref(["list", "test.arkv"], cwd=workdir)
        out_py, _, rc_py = run_impl(["list", "test.arkv"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py

    def test_list_checksum_archive(self, workdir):
        env = {"ARKV_CHECKSUM": "1"}
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir, env_extra=env)
        out_c, _, _ = run_ref(["list", "test.arkv"], cwd=workdir)
        out_py, _, _ = run_impl(["list", "test.arkv"], cwd=workdir)
        assert out_c == out_py


class TestCreateOutput:
    def test_create_stdout(self, workdir):
        out_c, _, rc_c = run_ref(["create", "ref.arkv", "hello.txt"], cwd=workdir)
        out_py, _, rc_py = run_impl(["create", "impl.arkv", "hello.txt"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        # Normalize archive name in output for comparison
        assert out_c.replace("ref.arkv", "X") == out_py.replace("impl.arkv", "X")

    def test_create_stdout_with_flags(self, workdir):
        env = {"ARKV_CHECKSUM": "1", "ARKV_SCRAMBLE": "1"}
        out_c, _, _ = run_ref(
            ["create", "ref.arkv", "hello.txt"], cwd=workdir, env_extra=env
        )
        out_py, _, _ = run_impl(
            ["create", "impl.arkv", "hello.txt"], cwd=workdir, env_extra=env
        )
        assert "[checksum]" in out_c
        assert "[scrambled]" in out_c
        assert out_c.replace("ref.arkv", "X") == out_py.replace("impl.arkv", "X")


# ===== Hidden commands =====


class TestInfoCommand:
    def test_info_output(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt", "subdir"], cwd=workdir)
        out_c, _, rc_c = run_ref(["info", "test.arkv"], cwd=workdir)
        out_py, _, rc_py = run_impl(["info", "test.arkv"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py

    def test_info_with_flags(self, workdir):
        env = {"ARKV_CHECKSUM": "1", "ARKV_SCRAMBLE": "1"}
        run_ref(
            ["create", "test.arkv", "hello.txt"], cwd=workdir, env_extra=env
        )
        out_c, _, _ = run_ref(["info", "test.arkv"], cwd=workdir)
        out_py, _, _ = run_impl(["info", "test.arkv"], cwd=workdir)
        assert out_c == out_py
        assert "checksum" in out_c
        assert "scramble" in out_c


class TestVerifyCommand:
    def test_verify_valid(self, workdir):
        env = {"ARKV_CHECKSUM": "1"}
        run_ref(
            ["create", "test.arkv", "hello.txt", "data.bin"], cwd=workdir, env_extra=env
        )
        out_c, _, rc_c = run_ref(["verify", "test.arkv"], cwd=workdir)
        out_py, _, rc_py = run_impl(["verify", "test.arkv"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py
        assert "OK" in out_c

    def test_verify_no_checksums(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir)
        out_c, _, rc_c = run_ref(["verify", "test.arkv"], cwd=workdir)
        out_py, _, rc_py = run_impl(["verify", "test.arkv"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py

    def test_verify_corrupt(self, workdir):
        env = {"ARKV_CHECKSUM": "1"}
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir, env_extra=env)
        arcpath = os.path.join(workdir, "test.arkv")
        data = bytearray(open(arcpath, "rb").read())
        # Corrupt a byte in the file data section (after header + path + metadata)
        # Header=10, pathlen=2, path=9, type=1, mode=2, mtime=8, size=4 = 36
        # Data starts at offset 36 for file "hello.txt"
        if len(data) > 40:
            data[40] ^= 0xFF
        corrupt_path = os.path.join(workdir, "corrupt.arkv")
        with open(corrupt_path, "wb") as f:
            f.write(data)
        _, _, rc_c = run_ref(["verify", "corrupt.arkv"], cwd=workdir)
        _, _, rc_py = run_impl(["verify", "corrupt.arkv"], cwd=workdir)
        assert rc_c != 0
        assert rc_py != 0
        assert rc_c == rc_py

    def test_verify_scrambled_valid(self, workdir):
        env = {"ARKV_CHECKSUM": "1", "ARKV_SCRAMBLE": "1"}
        run_ref(
            ["create", "test.arkv", "hello.txt"], cwd=workdir, env_extra=env
        )
        out_c, _, rc_c = run_ref(["verify", "test.arkv"], cwd=workdir)
        out_py, _, rc_py = run_impl(["verify", "test.arkv"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py


class TestDumpCommand:
    def test_dump_output(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt", "subdir"], cwd=workdir)
        out_c, _, rc_c = run_ref(["dump", "test.arkv"], cwd=workdir)
        out_py, _, rc_py = run_impl(["dump", "test.arkv"], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py

    def test_dump_with_checksum(self, workdir):
        env = {"ARKV_CHECKSUM": "1"}
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir, env_extra=env)
        out_c, _, _ = run_ref(["dump", "test.arkv"], cwd=workdir)
        out_py, _, _ = run_impl(["dump", "test.arkv"], cwd=workdir)
        assert out_c == out_py
        assert "cksum=" in out_c


# ===== Extraction =====


class TestExtract:
    def test_extract_basic(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt", "data.bin"], cwd=workdir)
        ext_c = os.path.join(workdir, "ext_c")
        ext_py = os.path.join(workdir, "ext_py")

        out_c, _, rc_c = run_ref(["extract", "test.arkv", ext_c], cwd=workdir)
        out_py, _, rc_py = run_impl(["extract", "test.arkv", ext_py], cwd=workdir)
        assert rc_c == 0
        assert rc_py == 0

        for fname in ["hello.txt", "data.bin"]:
            with open(os.path.join(ext_c, fname), "rb") as f:
                c_data = f.read()
            with open(os.path.join(ext_py, fname), "rb") as f:
                py_data = f.read()
            orig = open(os.path.join(workdir, fname), "rb").read()
            assert c_data == orig, f"{fname} content mismatch in C extract"
            assert py_data == orig, f"{fname} content mismatch in Python extract"

    def test_extract_scrambled(self, workdir):
        env = {"ARKV_SCRAMBLE": "1", "ARKV_CHECKSUM": "1"}
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir, env_extra=env)
        ext_c = os.path.join(workdir, "ext_c")
        ext_py = os.path.join(workdir, "ext_py")

        run_ref(["extract", "test.arkv", ext_c], cwd=workdir)
        run_impl(["extract", "test.arkv", ext_py], cwd=workdir)

        orig = open(os.path.join(workdir, "hello.txt"), "rb").read()
        c_data = open(os.path.join(ext_c, "hello.txt"), "rb").read()
        py_data = open(os.path.join(ext_py, "hello.txt"), "rb").read()
        assert c_data == orig
        assert py_data == orig

    def test_cross_compat_py_archive(self, workdir):
        """Python creates archive, C binary extracts it."""
        run_impl(["create", "py.arkv", "hello.txt"], cwd=workdir)
        ext = os.path.join(workdir, "ext_cross")
        out, _, rc = run_ref(["extract", "py.arkv", ext], cwd=workdir)
        assert rc == 0
        orig = open(os.path.join(workdir, "hello.txt"), "rb").read()
        extracted = open(os.path.join(ext, "hello.txt"), "rb").read()
        assert extracted == orig

    def test_cross_compat_c_archive(self, workdir):
        """C binary creates archive, Python extracts it."""
        run_ref(["create", "c.arkv", "hello.txt"], cwd=workdir)
        ext = os.path.join(workdir, "ext_cross")
        out, _, rc = run_impl(["extract", "c.arkv", ext], cwd=workdir)
        assert rc == 0
        orig = open(os.path.join(workdir, "hello.txt"), "rb").read()
        extracted = open(os.path.join(ext, "hello.txt"), "rb").read()
        assert extracted == orig

    def test_extract_directory_entry(self, workdir):
        run_ref(["create", "test.arkv", "subdir"], cwd=workdir)
        ext = os.path.join(workdir, "ext_dir")
        run_impl(["extract", "test.arkv", ext], cwd=workdir)
        assert os.path.isdir(os.path.join(ext, "subdir"))

    def test_extract_output(self, workdir):
        run_ref(["create", "test.arkv", "hello.txt"], cwd=workdir)
        ext_c = os.path.join(workdir, "ec")
        ext_py = os.path.join(workdir, "ep")
        out_c, _, _ = run_ref(["extract", "test.arkv", ext_c], cwd=workdir)
        out_py, _, _ = run_impl(["extract", "test.arkv", ext_py], cwd=workdir)
        assert out_c.replace(ext_c, "DIR") == out_py.replace(ext_py, "DIR")


# ===== Error handling =====


class TestErrors:
    def test_missing_file_create(self, workdir):
        _, err_c, rc_c = run_ref(
            ["create", "bad.arkv", "nonexistent_file.xyz"], cwd=workdir
        )
        _, err_py, rc_py = run_impl(
            ["create", "bad.arkv", "nonexistent_file.xyz"], cwd=workdir
        )
        assert rc_c != 0
        assert rc_py != 0

    def test_bad_archive_list(self, workdir):
        bad_path = os.path.join(workdir, "bad.arkv")
        with open(bad_path, "wb") as f:
            f.write(b"NOT_AN_ARCHIVE_DATA")
        _, err_c, rc_c = run_ref(["list", "bad.arkv"], cwd=workdir)
        _, err_py, rc_py = run_impl(["list", "bad.arkv"], cwd=workdir)
        assert rc_c != 0
        assert rc_py != 0

    def test_unknown_command(self):
        _, err_c, rc_c = run_ref(["boguscmd"])
        _, err_py, rc_py = run_impl(["boguscmd"])
        assert rc_c != 0
        assert rc_py != 0

    def test_no_args(self):
        _, _, rc_c = run_ref([])
        _, _, rc_py = run_impl([])
        assert rc_c != 0
        assert rc_py != 0


# ===== Help and version =====


class TestHelpVersion:
    def test_help_output(self):
        out_c, _, rc_c = run_ref(["--help"])
        out_py, _, rc_py = run_impl(["--help"])
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py

    def test_version_output(self):
        out_c, _, rc_c = run_ref(["--version"])
        out_py, _, rc_py = run_impl(["--version"])
        assert rc_c == 0
        assert rc_py == 0
        assert out_c == out_py


# ===== Scramble correctness =====


class TestScramble:
    def test_scramble_changes_data(self, workdir):
        """Scrambled archive should have different data bytes than plain."""
        run_ref(["create", "plain.arkv", "hello.txt"], cwd=workdir)
        run_ref(
            ["create", "scram.arkv", "hello.txt"],
            cwd=workdir,
            env_extra={"ARKV_SCRAMBLE": "1"},
        )
        plain = read_bytes(workdir, "plain.arkv")
        scram = read_bytes(workdir, "scram.arkv")
        # Same header and path, but data section should differ
        assert plain != scram
        # Both should have same header magic and footer
        assert plain[:4] == scram[:4] == b"ARKV"
        assert plain[-8:] == scram[-8:] == b"ARKV_END"

    def test_scramble_roundtrip(self, workdir):
        """Create scrambled archive, extract, verify content matches original."""
        env = {"ARKV_SCRAMBLE": "1"}
        run_ref(["create", "test.arkv", "data.bin"], cwd=workdir, env_extra=env)
        ext = os.path.join(workdir, "ext_scram")
        run_impl(["extract", "test.arkv", ext], cwd=workdir)
        orig = open(os.path.join(workdir, "data.bin"), "rb").read()
        extracted = open(os.path.join(ext, "data.bin"), "rb").read()
        assert extracted == orig
