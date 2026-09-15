"""Tests for the Nuitka user plugin task.

Verifies that the agent wrote a correct Nuitka user plugin that handles
dynamic imports, data file inclusion, and native library bundling for
standalone compilation.

"""
import os
import shutil
import subprocess


def test_plugin_file_exists():
    """Verify the user plugin file exists at the expected path."""
    assert os.path.exists("/app/nuitka_plugin.py"), (
        "Plugin file not found at /app/nuitka_plugin.py"
    )


def test_plugin_implements_required_api():
    """Verify the plugin has the correct structure and API elements."""
    with open("/app/nuitka_plugin.py") as f:
        content = f.read()

    assert "NuitkaPluginBase" in content, (
        "Plugin must reference NuitkaPluginBase"
    )
    assert "getImplicitImports" in content, (
        "Plugin must implement getImplicitImports"
    )
    assert "class " in content, (
        "Plugin must define a class"
    )
    assert "from nuitka" in content or "import nuitka" in content, (
        "Plugin must import from the nuitka package"
    )


def test_cpython_baseline():
    """Verify the application runs correctly under CPython with all backends."""
    result = subprocess.run(
        ["python3", "/app/main.py"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"CPython run failed with exit code {result.returncode}: {result.stderr}"
    )
    output = result.stdout.strip()
    assert "Text Processing Report" in output, "Missing report header"
    assert "text_cipher" in output, "Missing text_cipher backend output"
    assert "text_hash" in output, "Missing text_hash backend output"
    assert "text_reverse" in output, "Missing text_reverse backend output"
    assert "text_stats" in output, "Missing text_stats backend output"
    assert "hash=" in output, "Missing hash value from native library backend"
    assert "End of Report" in output, "Missing report footer"


def test_standalone_compilation_and_output():
    """Compile with the user plugin and verify standalone output matches CPython."""
    # Get CPython reference output
    cpython_result = subprocess.run(
        ["python3", "/app/main.py"],
        capture_output=True, text=True, timeout=30
    )
    assert cpython_result.returncode == 0, (
        f"CPython baseline failed: {cpython_result.stderr}"
    )
    expected_output = cpython_result.stdout.strip()

    # Clean any previous compilation artifacts
    for d in ["/app/main.dist", "/app/main.build"]:
        if os.path.exists(d):
            shutil.rmtree(d)

    # Compile with Nuitka standalone mode using the user plugin
    compile_result = subprocess.run(
        [
            "python3", "-m", "nuitka",
            "--mode=standalone",
            "--user-plugin=nuitka_plugin.py",
            "main.py",
        ],
        capture_output=True, text=True, timeout=480,
        cwd="/app",
    )
    assert compile_result.returncode == 0, (
        f"Nuitka compilation failed:\n"
        f"stdout (last 2000 chars): {compile_result.stdout[-2000:]}\n"
        f"stderr (last 2000 chars): {compile_result.stderr[-2000:]}"
    )

    # Find the standalone distribution directory
    dist_dir = "/app/main.dist"
    assert os.path.isdir(dist_dir), (
        f"Standalone dist directory not found at {dist_dir}"
    )

    # Find the executable binary
    binary = None
    for name in ["main.bin", "main"]:
        path = os.path.join(dist_dir, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            binary = path
            break

    if binary is None:
        for f in sorted(os.listdir(dist_dir)):
            path = os.path.join(dist_dir, f)
            if (os.path.isfile(path) and os.access(path, os.X_OK)
                    and not f.endswith(".so") and not f.startswith("lib")):
                binary = path
                break

    assert binary is not None, (
        f"No executable found in {dist_dir}. "
        f"Contents: {sorted(os.listdir(dist_dir))}"
    )

    # Run the standalone binary
    standalone_result = subprocess.run(
        [binary],
        capture_output=True, text=True, timeout=30,
        cwd=dist_dir,
    )
    assert standalone_result.returncode == 0, (
        f"Standalone binary failed with exit code {standalone_result.returncode}:\n"
        f"stdout: {standalone_result.stdout}\n"
        f"stderr: {standalone_result.stderr}"
    )

    # Compare outputs character-for-character
    actual_output = standalone_result.stdout.strip()
    assert actual_output == expected_output, (
        f"Output mismatch!\n"
        f"Expected (CPython):\n{expected_output}\n\n"
        f"Actual (Standalone):\n{actual_output}"
    )
