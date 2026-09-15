
import subprocess
import json
import os
import re
import pytest

TRANSPILER = "/app/ddl_transpile.py"
FORMATS = "/app/formats"
INPUTS = "/app/inputs"
RUNTIME = "/app/runtime/runtime.c"
RUNTIME_INC = "/app/runtime"
GEN_DIR = "/app/generated"


def transpile_compile_run(ddl_name, input_name):
    """Transpile a DDL spec to C, compile it, run it, return subprocess result."""
    ddl_file = f"{FORMATS}/{ddl_name}.ddl"
    c_file = f"{GEN_DIR}/{ddl_name}.c"
    bin_out = f"{GEN_DIR}/{ddl_name}"
    bin_input = f"{INPUTS}/{input_name}"

    # Transpile
    r = subprocess.run(
        ["python3", TRANSPILER, ddl_file, c_file],
        capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, f"Transpile failed for {ddl_name}: {r.stderr}"

    # Compile with -Wall -Werror
    r = subprocess.run(
        ["gcc", "-Wall", "-Werror",
         f"-I{RUNTIME_INC}", "-o", bin_out,
         c_file, RUNTIME],
        capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, \
        f"Compilation failed for {ddl_name}.c:\n{r.stderr}"

    # Run compiled parser
    r = subprocess.run(
        [bin_out, bin_input],
        capture_output=True, text=True, timeout=30
    )
    return r


class TestTranspilerExists:
    def test_file_exists(self):
        assert os.path.isfile(TRANSPILER), f"{TRANSPILER} not found"

    def test_is_python(self):
        with open(TRANSPILER) as f:
            content = f.read(200)
        assert "python" in content.lower() or "import" in content, \
            "File should be a Python script"


class TestCompilation:
    """Verify that generated C compiles without warnings under -Wall -Werror."""

    @pytest.mark.parametrize("fmt", ["container", "tagged", "choice", "chunk_stream"])
    def test_compiles_clean(self, fmt):
        ddl_file = f"{FORMATS}/{fmt}.ddl"
        c_file = f"{GEN_DIR}/{fmt}.c"
        bin_out = f"{GEN_DIR}/{fmt}"

        r = subprocess.run(
            ["python3", TRANSPILER, ddl_file, c_file],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, f"Transpile failed: {r.stderr}"

        r = subprocess.run(
            ["gcc", "-Wall", "-Werror",
             f"-I{RUNTIME_INC}", "-o", bin_out,
             c_file, RUNTIME],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, \
            f"Compilation of {fmt}.c failed with warnings/errors:\n{r.stderr}"


class TestContainerFormat:
    """Tests basic struct parsing, multi-byte integers, bounded repetition."""

    def test_parses_successfully(self):
        r = transpile_compile_run("container", "input_container.bin")
        assert r.returncode == 0, f"Parse failed: {r.stderr}"

    def test_version_field(self):
        r = transpile_compile_run("container", "input_container.bin")
        output = json.loads(r.stdout)
        assert output["version"] == 2

    def test_chunk_count(self):
        r = transpile_compile_run("container", "input_container.bin")
        output = json.loads(r.stdout)
        assert output["num_chunks"] == 2
        assert len(output["chunks"]) == 2

    def test_first_chunk(self):
        r = transpile_compile_run("container", "input_container.bin")
        output = json.loads(r.stdout)
        chunk = output["chunks"][0]
        assert chunk["chunk_type"] == 0x48454144
        assert chunk["payload"] == [10, 11, 12]

    def test_second_chunk(self):
        r = transpile_compile_run("container", "input_container.bin")
        output = json.loads(r.stdout)
        chunk = output["chunks"][1]
        assert chunk["chunk_type"] == 0x44415441
        assert chunk["payload"] == [255, 254]

    def test_let_binding_not_in_output(self):
        """The 'let len' binding must NOT appear in chunk output."""
        r = transpile_compile_run("container", "input_container.bin")
        output = json.loads(r.stdout)
        for chunk in output["chunks"]:
            assert "len" not in chunk, \
                "let bindings must not appear in JSON output"


class TestTaggedFormat:
    """Tests case expressions and tagged union results."""

    def test_parses_successfully(self):
        r = transpile_compile_run("tagged", "input_tagged.bin")
        assert r.returncode == 0, f"Parse failed: {r.stderr}"

    def test_record_count(self):
        r = transpile_compile_run("tagged", "input_tagged.bin")
        output = json.loads(r.stdout)
        assert len(output["records"]) == 3

    def test_byte_record(self):
        r = transpile_compile_run("tagged", "input_tagged.bin")
        output = json.loads(r.stdout)
        rec = output["records"][0]["data"]
        assert "byte_rec" in rec
        assert rec["byte_rec"] == 255

    def test_short_record(self):
        r = transpile_compile_run("tagged", "input_tagged.bin")
        output = json.loads(r.stdout)
        rec = output["records"][1]["data"]
        assert "short_rec" in rec
        assert rec["short_rec"] == 256

    def test_int_record(self):
        r = transpile_compile_run("tagged", "input_tagged.bin")
        output = json.loads(r.stdout)
        rec = output["records"][2]["data"]
        assert "int_rec" in rec
        assert rec["int_rec"] == 42

    def test_let_tag_not_in_output(self):
        """The 'let tag' binding must NOT appear in record output."""
        r = transpile_compile_run("tagged", "input_tagged.bin")
        output = json.loads(r.stdout)
        for rec in output["records"]:
            assert "tag" not in rec, \
                "let bindings must not appear in JSON output"


class TestChoiceFormat:
    """Tests First/biased-choice with backtracking."""

    def test_parses_successfully(self):
        r = transpile_compile_run("choice", "input_choice.bin")
        assert r.returncode == 0, f"Parse failed: {r.stderr}"

    def test_item_count(self):
        r = transpile_compile_run("choice", "input_choice.bin")
        output = json.loads(r.stdout)
        assert len(output["items"]) == 3

    def test_first_item_is_pair(self):
        r = transpile_compile_run("choice", "input_choice.bin")
        output = json.loads(r.stdout)
        item = output["items"][0]
        assert "pair" in item
        assert item["pair"]["first"] == 170
        assert item["pair"]["second"] == 187

    def test_second_item_is_single(self):
        r = transpile_compile_run("choice", "input_choice.bin")
        output = json.loads(r.stdout)
        item = output["items"][1]
        assert "single" in item
        assert item["single"]["value"] == 204

    def test_third_item_is_pair(self):
        r = transpile_compile_run("choice", "input_choice.bin")
        output = json.loads(r.stdout)
        item = output["items"][2]
        assert "pair" in item
        assert item["pair"]["first"] == 17
        assert item["pair"]["second"] == 34

    def test_backtracking_correctness(self):
        """Verify that failed PairItem attempt doesn't consume bytes."""
        r = transpile_compile_run("choice", "input_choice.bin")
        output = json.loads(r.stdout)
        items = output["items"]
        tags = [list(it.keys())[0] for it in items]
        assert tags == ["pair", "single", "pair"]


class TestChunkStreamFormat:
    """Tests Chunk (sub-stream) parsing with bounded END."""

    def test_parses_successfully(self):
        r = transpile_compile_run("chunk_stream", "input_chunk.bin")
        assert r.returncode == 0, f"Parse failed: {r.stderr}"

    def test_frame_count(self):
        r = transpile_compile_run("chunk_stream", "input_chunk.bin")
        output = json.loads(r.stdout)
        assert len(output["frames"]) == 2

    def test_first_frame(self):
        r = transpile_compile_run("chunk_stream", "input_chunk.bin")
        output = json.loads(r.stdout)
        frame = output["frames"][0]["content"]
        assert frame["frame_type"] == 1
        assert frame["data"] == [170, 187, 204]

    def test_second_frame(self):
        r = transpile_compile_run("chunk_stream", "input_chunk.bin")
        output = json.loads(r.stdout)
        frame = output["frames"][1]["content"]
        assert frame["frame_type"] == 2
        assert frame["data"] == [221, 238]

    def test_substream_boundary(self):
        """Verify END checks the Chunk boundary, not parent stream."""
        r = transpile_compile_run("chunk_stream", "input_chunk.bin")
        output = json.loads(r.stdout)
        assert len(output["frames"][0]["content"]["data"]) == 3
        assert len(output["frames"][1]["content"]["data"]) == 2


class TestErrorHandling:
    """Tests graceful failure on malformed input."""

    def test_truncated_input_fails(self):
        r = transpile_compile_run("container", "input_truncated.bin")
        assert r.returncode != 0, \
            "Compiled parser should exit non-zero on truncated input"

    def test_wrong_magic_fails(self):
        """Create a temp file with wrong magic and verify failure."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(bytes([0x00, 0x00, 0x00, 0x02, 0x00, 0x00]))
            tmppath = f.name
        try:
            r = transpile_compile_run("container", "input_container.bin")
            # Re-run the already-compiled binary with wrong input
            bin_out = f"{GEN_DIR}/container"
            r = subprocess.run(
                [bin_out, tmppath],
                capture_output=True, text=True, timeout=10
            )
            assert r.returncode != 0, \
                "Compiled parser should fail on wrong magic bytes"
        finally:
            os.unlink(tmppath)


class TestGeneratedCodeQuality:
    """Verify structural properties of the generated C."""

    def test_generated_c_exists(self):
        """After transpilation, the .c file should exist."""
        ddl_file = f"{FORMATS}/container.ddl"
        c_file = f"{GEN_DIR}/container_quality.c"
        r = subprocess.run(
            ["python3", TRANSPILER, ddl_file, c_file],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0
        assert os.path.isfile(c_file)

    def test_generated_c_includes_parser_h(self):
        ddl_file = f"{FORMATS}/container.ddl"
        c_file = f"{GEN_DIR}/container_inc.c"
        subprocess.run(
            ["python3", TRANSPILER, ddl_file, c_file],
            capture_output=True, text=True, timeout=60
        )
        with open(c_file) as f:
            src = f.read()
        assert '#include "parser.h"' in src or "#include <parser.h>" in src \
            or '#include"parser.h"' in src, \
            "Generated C must include parser.h"

    def test_generated_c_has_parse_main(self):
        ddl_file = f"{FORMATS}/container.ddl"
        c_file = f"{GEN_DIR}/container_main.c"
        subprocess.run(
            ["python3", TRANSPILER, ddl_file, c_file],
            capture_output=True, text=True, timeout=60
        )
        with open(c_file) as f:
            src = f.read()
        assert "parse_Main" in src, \
            "Generated C must contain parse_Main function"


class TestValgrind:
    """Tests that compiled parsers have zero memory leaks under valgrind."""

    @pytest.mark.parametrize("fmt,input_file", [
        ("container", "input_container.bin"),
        ("tagged", "input_tagged.bin"),
        ("choice", "input_choice.bin"),
        ("chunk_stream", "input_chunk.bin"),
    ])
    def test_no_memory_errors(self, fmt, input_file):
        ddl_file = f"{FORMATS}/{fmt}.ddl"
        c_file = f"{GEN_DIR}/{fmt}_vg.c"
        bin_out = f"{GEN_DIR}/{fmt}_vg"
        bin_input = f"{INPUTS}/{input_file}"

        r = subprocess.run(
            ["python3", TRANSPILER, ddl_file, c_file],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, f"Transpile failed: {r.stderr}"

        r = subprocess.run(
            ["gcc", "-Wall", "-Werror", "-g",
             f"-I{RUNTIME_INC}", "-o", bin_out,
             c_file, RUNTIME],
            capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, f"Compile failed: {r.stderr}"

        r = subprocess.run(
            ["valgrind", "--leak-check=full", "--error-exitcode=99",
             bin_out, bin_input],
            capture_output=True, text=True, timeout=120
        )
        assert r.returncode != 99, \
            f"Valgrind found memory errors in {fmt}:\n{r.stderr}"
        assert r.returncode == 0, \
            f"Parser {fmt} failed under valgrind (exit {r.returncode}):\n{r.stderr}"


class TestValgrindReport:
    """Tests that the valgrind report file was generated correctly."""

    def test_report_exists(self):
        assert os.path.isfile("/app/valgrind_report.txt"), \
            "/app/valgrind_report.txt not found"

    def test_report_not_empty(self):
        with open("/app/valgrind_report.txt") as f:
            content = f.read()
        assert len(content) > 100, \
            "valgrind_report.txt is too small — should contain valgrind output"

    def test_report_all_clean(self):
        with open("/app/valgrind_report.txt") as f:
            content = f.read()
        summaries = re.findall(r'ERROR SUMMARY: (\d+) errors', content)
        assert len(summaries) >= 4, \
            f"Expected 4 valgrind runs in report, found {len(summaries)}"
        for count in summaries:
            assert count == "0", \
                f"Valgrind report shows {count} errors — expected 0"
