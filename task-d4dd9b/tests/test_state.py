import subprocess
import os
import pytest



@pytest.fixture(scope="module")
def build_result():
    """Build the project from scratch and return results."""
    subprocess.run(["rm", "-rf", "/app/build"], check=False)

    configure = subprocess.run(
        ["cmake", "-B", "/app/build", "-S", "/app"],
        capture_output=True, text=True, timeout=120
    )

    build = None
    if configure.returncode == 0:
        build = subprocess.run(
            ["cmake", "--build", "/app/build", "-j", "2"],
            capture_output=True, text=True, timeout=300
        )

    return {"configure": configure, "build": build}


def test_cmake_config_created():
    """CMake package configuration files must exist in the expected directory."""
    config_dir = "/usr/local/lib/cmake/DataFlow"
    assert os.path.isdir(config_dir), f"Config directory not found: {config_dir}"
    files = os.listdir(config_dir)
    cmake_files = [f for f in files if f.endswith(".cmake")]
    assert len(cmake_files) >= 2, \
        f"Expected at least 2 CMake config files (config + version), found: {cmake_files}"


def test_cmake_configure(build_result):
    """CMake configuration must complete without errors."""
    r = build_result["configure"]
    assert r.returncode == 0, f"CMake configure failed:\n{r.stderr[-2000:]}"


def test_build_succeeds(build_result):
    """Project must compile and link without errors."""
    assert build_result["build"] is not None, "Build skipped (configure failed)"
    r = build_result["build"]
    assert r.returncode == 0, f"Build failed:\n{r.stderr[-2000:]}"


def test_binary_exists(build_result):
    """The sigframe binary must exist after building."""
    assert os.path.isfile("/app/build/sigframe"), \
        "Binary /app/build/sigframe not found"


def test_binary_runs(build_result):
    """The binary must execute and produce expected output."""
    assert os.path.isfile("/app/build/sigframe"), "Binary not found"
    r = subprocess.run(["/app/build/sigframe"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"Runtime error:\n{r.stderr}"
    assert "Pipeline complete" in r.stdout, \
        f"Expected 'Pipeline complete' in output:\n{r.stdout}"
    assert "5 values" in r.stdout, \
        f"Expected '5 values' in output:\n{r.stdout}"
    assert "encoded" in r.stdout, \
        f"Expected 'encoded' in output:\n{r.stdout}"


def test_find_package_preserved():
    """Both libraries must still use find_package(DataFlow)."""
    with open("/app/src/parser/CMakeLists.txt") as f:
        assert "find_package(DataFlow" in f.read(), \
            "Parser must use find_package(DataFlow)"
    with open("/app/src/executor/CMakeLists.txt") as f:
        assert "find_package(DataFlow" in f.read(), \
            "Executor must use find_package(DataFlow)"


def test_codec_replaces_compress():
    """Executor must reference Codec component, not deprecated Compress."""
    with open("/app/src/executor/CMakeLists.txt") as f:
        c = f.read()
    assert "Codec" in c, "Executor must use Codec component"
    assert "Compress" not in c, "Deprecated Compress must be replaced with Codec"


def test_v2_include_paths():
    """Source files must use dataflow/v2/ include paths."""
    for p in ["/app/src/parser/parser.h",
              "/app/src/parser/parser.cpp",
              "/app/src/executor/executor.h"]:
        with open(p) as f:
            c = f.read()
        for bad in ["<dataflow/pipeline.h>", "<dataflow/core.h>",
                     "<dataflow/compress.h>"]:
            assert bad not in c, f"{p} still has old include: {bad}"
