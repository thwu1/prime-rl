
import subprocess
import json
import os
import shutil


def run_cmd(cmd, cwd=None, timeout=180):
    """Run a command and return the result."""
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout,
    )


def clean_dist(path):
    """Remove dist directory if it exists."""
    dist = os.path.join(path, "dist")
    if os.path.isdir(dist):
        shutil.rmtree(dist)


# ── Build once at module level (runs when pytest imports this file) ──────────
clean_dist("/app/lib")
clean_dist("/app/consumer")

LIB_BUILD = run_cmd(["tsc", "-p", "/app/lib/tsconfig.json"])
CON_BUILD = run_cmd(["tsc", "-p", "/app/consumer/tsconfig.json"])

CONSUMER_RUN = None
if LIB_BUILD.returncode == 0 and CON_BUILD.returncode == 0:
    CONSUMER_RUN = run_cmd(["node", "/app/consumer/dist/main.js"])


# ── Library compilation ─────────────────────────────────────────────────────

class TestLibraryCompilation:

    def test_library_compiles_without_errors(self):
        assert LIB_BUILD.returncode == 0, (
            f"Library tsc failed (exit {LIB_BUILD.returncode}):\n"
            f"stdout: {LIB_BUILD.stdout}\nstderr: {LIB_BUILD.stderr}"
        )

    def test_declaration_files_generated(self):
        expected_dts = [
            "/app/lib/dist/index.d.ts",
            "/app/lib/dist/vector.d.ts",
            "/app/lib/dist/matrix.d.ts",
            "/app/lib/dist/types.d.ts",
            "/app/lib/dist/plugins/transform.d.ts",
            "/app/lib/dist/plugins/interpolate.d.ts",
            "/app/lib/dist/plugins/statistics.d.ts",
        ]
        for dts in expected_dts:
            assert os.path.isfile(dts), f"Missing declaration file: {dts}"

    def test_types_module_js_output_exists(self):
        assert os.path.isfile("/app/lib/dist/types.js"), (
            "Missing compiled output: /app/lib/dist/types.js"
        )

    def test_statistics_module_compiled(self):
        assert os.path.isfile("/app/lib/dist/plugins/statistics.js"), (
            "Missing compiled output: /app/lib/dist/plugins/statistics.js"
        )


# ── Consumer compilation ─────────────────────────────────────────────────────

class TestConsumerCompilation:

    def test_consumer_compiles_without_errors(self):
        assert CON_BUILD.returncode == 0, (
            f"Consumer tsc failed (exit {CON_BUILD.returncode}):\n"
            f"stdout: {CON_BUILD.stdout}\nstderr: {CON_BUILD.stderr}"
        )

    def test_consumer_tsconfig_uses_nodenext(self):
        with open("/app/consumer/tsconfig.json") as f:
            config = json.load(f)
        opts = config.get("compilerOptions", {})
        mod = opts.get("module", "").lower()
        res = opts.get("moduleResolution", "").lower()
        assert mod in ("nodenext", "node16"), (
            f"Consumer module should be nodenext or node16, got '{mod}'"
        )
        assert res in ("nodenext", "node16"), (
            f"Consumer moduleResolution should be nodenext or node16, got '{res}'"
        )


# ── Consumer execution ───────────────────────────────────────────────────────

class TestConsumerExecution:

    def _stdout(self):
        assert CONSUMER_RUN is not None, (
            "Consumer did not run (build failed).\n"
            f"Lib: exit={LIB_BUILD.returncode} err={LIB_BUILD.stderr}\n"
            f"Con: exit={CON_BUILD.returncode} err={CON_BUILD.stderr}"
        )
        return CONSUMER_RUN.stdout

    def test_consumer_runs_without_errors(self):
        out = self._stdout()
        assert CONSUMER_RUN.returncode == 0, (
            f"Consumer execution failed (exit {CONSUMER_RUN.returncode}):\n"
            f"stdout: {out}\nstderr: {CONSUMER_RUN.stderr}"
        )

    def test_cross_product_output(self):
        assert "cross: [0.00, 0.00, 1.00]" in self._stdout()

    def test_determinant_output(self):
        assert "det: -2" in self._stdout()

    def test_trace_output(self):
        out = self._stdout()
        assert "trace: 5" in out, (
            f"Expected 'trace: 5' in output, got:\n{out}"
        )

    def test_dimension_output(self):
        assert "dim: 3" in self._stdout()

    def test_from_interface_output(self):
        assert "from-interface: [1.00, 2.00, 3.00]" in self._stdout()

    def test_rotation_output(self):
        assert "rotated: [0.00, 1.00]" in self._stdout()

    def test_interpolation_output(self):
        assert "lerp: [5.00, 5.00]" in self._stdout()

    def test_mean_output(self):
        assert "mean: [3.00, 4.00]" in self._stdout()

    def test_cov_trace_output(self):
        assert "cov-trace: 8" in self._stdout()

    def test_platform_output(self):
        assert "platform: node-optimized" in self._stdout()


# ── Configuration correctness ─────────────────────────────────────────────────

class TestConfigurationCorrectness:

    def test_exports_no_mjs_extension(self):
        with open("/app/lib/package.json") as f:
            pkg = json.load(f)
        exports_str = json.dumps(pkg.get("exports", {}))
        assert ".mjs" not in exports_str, (
            "Exports map should not contain .mjs paths (type:module emits .js)"
        )

    def test_exports_has_vector_subpath(self):
        with open("/app/lib/package.json") as f:
            pkg = json.load(f)
        exports = pkg.get("exports", {})
        assert "./vector" in exports, (
            "Exports must include './vector' subpath (not './vector.js')"
        )
        assert "./vector.js" not in exports, (
            "Exports key should be './vector' not './vector.js'"
        )

    def test_exports_types_subpath_targets_exist(self):
        with open("/app/lib/package.json") as f:
            pkg = json.load(f)
        exports = pkg.get("exports", {})
        types_export = exports.get("./types", {})
        assert types_export, "Exports must include './types' subpath"
        default_path = types_export.get("default", "")
        assert default_path, "./types export must have a 'default' condition"
        full_path = os.path.join("/app/lib", default_path)
        assert os.path.isfile(full_path), (
            f"./types export default target does not exist: {full_path}"
        )
        types_path = types_export.get("types", "")
        if types_path:
            full_types = os.path.join("/app/lib", types_path)
            assert os.path.isfile(full_types), (
                f"./types export types target does not exist: {full_types}"
            )

    def test_imports_platform_uses_dist(self):
        with open("/app/lib/package.json") as f:
            pkg = json.load(f)
        imports = pkg.get("imports", {})
        platform = imports.get("#platform", {})
        node_path = platform.get("node", "")
        assert node_path.startswith("./dist/"), (
            f"#platform node path should start with ./dist/, got '{node_path}'"
        )
        assert node_path.endswith(".js"), (
            f"#platform node path should end with .js, got '{node_path}'"
        )
        default_path = platform.get("default", "")
        assert default_path.startswith("./dist/"), (
            f"#platform default path should start with ./dist/, got '{default_path}'"
        )
        assert default_path.endswith(".js"), (
            f"#platform default path should end with .js, got '{default_path}'"
        )

    def test_imports_platform_targets_exist(self):
        with open("/app/lib/package.json") as f:
            pkg = json.load(f)
        imports = pkg.get("imports", {})
        platform = imports.get("#platform", {})
        for cond in ("node", "default"):
            target = platform.get(cond, "")
            if target:
                full = os.path.join("/app/lib", target)
                assert os.path.isfile(full), (
                    f"#platform {cond} target does not exist: {full}"
                )

    def test_library_declaration_enabled(self):
        with open("/app/lib/tsconfig.json") as f:
            config = json.load(f)
        opts = config.get("compilerOptions", {})
        assert opts.get("declaration") is True, (
            "Library tsconfig must have declaration: true"
        )

    def test_library_isolated_modules_enabled(self):
        with open("/app/lib/tsconfig.json") as f:
            config = json.load(f)
        opts = config.get("compilerOptions", {})
        assert opts.get("isolatedModules") is True, (
            "Library tsconfig must retain isolatedModules: true"
        )


# ── Anti-cheat: trace method ─────────────────────────────────────────────────

class TestAntiCheatTraceMethod:

    def test_trace_with_different_matrix(self):
        """Run trace() on matrices the consumer doesn't use."""
        script = '/tmp/test_trace_anti.mjs'
        with open(script, 'w') as f:
            f.write(
                'import { Matrix } from "/app/lib/dist/matrix.js";\n'
                'const m1 = new Matrix([[5, 0], [0, 3]]);\n'
                'if (m1.trace() !== 8) {\n'
                '  console.error("trace [[5,0],[0,3]] should be 8, got", m1.trace());\n'
                '  process.exit(1);\n'
                '}\n'
                'const m2 = new Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]]);\n'
                'if (m2.trace() !== 15) {\n'
                '  console.error("trace 3x3 should be 15, got", m2.trace());\n'
                '  process.exit(1);\n'
                '}\n'
                'const m3 = new Matrix([[10]]);\n'
                'if (m3.trace() !== 10) {\n'
                '  console.error("trace 1x1 should be 10, got", m3.trace());\n'
                '  process.exit(1);\n'
                '}\n'
                'console.log("TRACE_OK");\n'
            )
        result = run_cmd(["node", script])
        assert result.returncode == 0 and "TRACE_OK" in result.stdout, (
            f"Trace anti-cheat test failed:\n{result.stdout}\n{result.stderr}"
        )


# ── Anti-cheat: statistics functions ──────────────────────────────────────────

class TestAntiCheatStatistics:

    def test_mean_with_different_data(self):
        """Verify mean() is not hardcoded to return [3, 4]."""
        script = '/tmp/test_mean_anti.mjs'
        with open(script, 'w') as f:
            f.write(
                'import { Vector } from "/app/lib/dist/vector.js";\n'
                'import { mean } from "/app/lib/dist/plugins/statistics.js";\n'
                'const vecs = [new Vector([10, 20, 30]), new Vector([30, 40, 60])];\n'
                'const m = mean(vecs);\n'
                'const expected = [20, 30, 45];\n'
                'for (let i = 0; i < 3; i++) {\n'
                '  if (Math.abs(m.components[i] - expected[i]) > 0.001) {\n'
                '    console.error("mean mismatch at", i, ":", m.components[i], "!=", expected[i]);\n'
                '    process.exit(1);\n'
                '  }\n'
                '}\n'
                'console.log("MEAN_OK");\n'
            )
        result = run_cmd(["node", script])
        assert result.returncode == 0 and "MEAN_OK" in result.stdout, (
            f"Mean anti-cheat test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_covariance_with_different_data(self):
        """Verify covarianceMatrix() uses sample covariance (N-1) and is not hardcoded."""
        script = '/tmp/test_cov_anti.mjs'
        with open(script, 'w') as f:
            f.write(
                'import { Vector } from "/app/lib/dist/vector.js";\n'
                'import { covarianceMatrix } from "/app/lib/dist/plugins/statistics.js";\n'
                '// Dataset: [[10,20],[30,40],[50,60]]\n'
                '// Mean: [30, 40]\n'
                '// Sample var(x) = ((10-30)^2+(30-30)^2+(50-30)^2)/2 = 800/2 = 400\n'
                '// Sample var(y) = ((20-40)^2+(40-40)^2+(60-40)^2)/2 = 800/2 = 400\n'
                '// Trace = 800\n'
                'const vecs = [new Vector([10, 20]), new Vector([30, 40]), new Vector([50, 60])];\n'
                'const cov = covarianceMatrix(vecs);\n'
                'if (Math.abs(cov.trace() - 800) > 0.001) {\n'
                '  console.error("cov trace should be 800, got", cov.trace());\n'
                '  process.exit(1);\n'
                '}\n'
                '// Check off-diagonal: cov(x,y) = ((10-30)(20-40)+0+(50-30)(60-40))/2 = (400+0+400)/2 = 400\n'
                'if (Math.abs(cov.rows[0][1] - 400) > 0.001) {\n'
                '  console.error("cov[0][1] should be 400, got", cov.rows[0][1]);\n'
                '  process.exit(1);\n'
                '}\n'
                'console.log("COV_OK");\n'
            )
        result = run_cmd(["node", script])
        assert result.returncode == 0 and "COV_OK" in result.stdout, (
            f"Covariance anti-cheat test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_mean_returns_vector_instance(self):
        """Verify mean returns a proper Vector with .dimension property."""
        script = '/tmp/test_mean_type.mjs'
        with open(script, 'w') as f:
            f.write(
                'import { Vector } from "/app/lib/dist/vector.js";\n'
                'import { mean } from "/app/lib/dist/plugins/statistics.js";\n'
                'const vecs = [new Vector([1, 2]), new Vector([3, 4])];\n'
                'const m = mean(vecs);\n'
                'if (m.dimension !== 2) {\n'
                '  console.error("mean should return Vector with dimension 2, got", m.dimension);\n'
                '  process.exit(1);\n'
                '}\n'
                'if (typeof m.add !== "function") {\n'
                '  console.error("mean result should be a Vector instance with add method");\n'
                '  process.exit(1);\n'
                '}\n'
                'console.log("MEAN_TYPE_OK");\n'
            )
        result = run_cmd(["node", script])
        assert result.returncode == 0 and "MEAN_TYPE_OK" in result.stdout, (
            f"Mean type anti-cheat test failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_covariance_returns_matrix_instance(self):
        """Verify covarianceMatrix returns a proper Matrix with .determinant()."""
        script = '/tmp/test_cov_type.mjs'
        with open(script, 'w') as f:
            f.write(
                'import { Vector } from "/app/lib/dist/vector.js";\n'
                'import { covarianceMatrix } from "/app/lib/dist/plugins/statistics.js";\n'
                'const vecs = [new Vector([1, 2]), new Vector([3, 4]), new Vector([5, 6])];\n'
                'const cov = covarianceMatrix(vecs);\n'
                'if (typeof cov.determinant !== "function") {\n'
                '  console.error("cov should be a Matrix instance with determinant method");\n'
                '  process.exit(1);\n'
                '}\n'
                '// Cov = [[4,4],[4,4]], det = 16 - 16 = 0\n'
                'if (Math.abs(cov.determinant()) > 0.001) {\n'
                '  console.error("cov det should be 0, got", cov.determinant());\n'
                '  process.exit(1);\n'
                '}\n'
                'console.log("COV_TYPE_OK");\n'
            )
        result = run_cmd(["node", script])
        assert result.returncode == 0 and "COV_TYPE_OK" in result.stdout, (
            f"Covariance type anti-cheat test failed:\n{result.stdout}\n{result.stderr}"
        )
