
"""
Tests for firmware security hardening task.
Verifies that:
1. Fixed code compiles at -O2 and is functionally correct
2. Dead-store-eliminated memset calls have been replaced with wipe operations
   that survive compiler optimization
3. Timing-vulnerable memcmp calls have been replaced with constant-time comparisons
4. An automated verification tool correctly identifies vulnerabilities in the
   original binary and confirms their absence in the fixed binary
5. A design rationale evaluates multiple mitigation strategies with justification
"""

import subprocess
import os
import re
import json
import shutil
import pytest


# Functions that originally had dead-store memset calls (optimized away at -O2)
# and MUST have wipe operations after fixing
FUNCTIONS_NEEDING_WIPE = [
    "secure_encrypt",
    "secure_decrypt",
    "verify_auth_token",
    "generate_keypair",
    "hmac_sign",
    "process_subscription",
    "derive_session_key",
]

# Functions that must NOT use memcmp for security-critical comparison
FUNCTIONS_NEEDING_CONSTANT_TIME = [
    "verify_auth_token",
    "process_subscription",
]


@pytest.fixture(scope="session")
def compiled_binary():
    """Compile the project and return path to binary."""
    result = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Compilation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    binary_path = "/app/build/secure_firmware"
    assert os.path.exists(binary_path), "Binary not found after compilation"
    return binary_path


@pytest.fixture(scope="session")
def objdump_output(compiled_binary):
    """Get disassembly of the compiled binary."""
    result = subprocess.run(
        ["objdump", "-d", compiled_binary],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, "objdump failed"
    return result.stdout


@pytest.fixture(scope="session")
def functional_test_result(compiled_binary):
    """Run the binary's built-in functional tests."""
    result = subprocess.run(
        [compiled_binary],
        capture_output=True, text=True, timeout=30
    )
    return result


@pytest.fixture(scope="session")
def vulnerable_binary():
    """Build the original vulnerable binary in a temporary directory."""
    ref_path = "/app/reference/secure_ops_vulnerable.c"
    assert os.path.exists(ref_path), (
        f"Reference vulnerable source not found at {ref_path}"
    )

    tmpdir = "/tmp/vuln_build"
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)
    shutil.copytree("/app", tmpdir)
    shutil.copy(
        ref_path,
        os.path.join(tmpdir, "src", "secure_ops.c")
    )
    result = subprocess.run(
        ["make", "-C", tmpdir, "clean", "all"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Failed to build vulnerable binary:\n{result.stderr}"
    )
    binary = os.path.join(tmpdir, "build", "secure_firmware")
    assert os.path.exists(binary), "Vulnerable binary not found after build"
    return binary


def get_function_asm(objdump_text, func_name):
    """Extract disassembly for a specific function from objdump output."""
    pattern = rf'^([0-9a-f]+ <{re.escape(func_name)}>:.*?)(?=\n[0-9a-f]+ <|\Z)'
    match = re.search(pattern, objdump_text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def has_wipe_operation(func_asm):
    """
    Check if a function's disassembly contains a wipe operation that
    survived -O2 optimization. Accepts multiple valid fix approaches.
    """
    if not func_asm:
        return False

    lower = func_asm.lower()

    # Pattern 1: Call to explicit_bzero (the standard fix)
    if "explicit_bzero" in lower:
        return True

    # Pattern 2: Call to memset_explicit (C23 standard)
    if "memset_explicit" in lower:
        return True

    # Pattern 3: Call to well-known wipe functions
    wipe_names = [
        "openssl_cleanse", "sodium_memzero", "crypto_wipe",
        "zeroize", "cleanse", "scrub", "purge", "burn",
    ]
    for name in wipe_names:
        if name in lower:
            return True

    # Pattern 4: Call to a custom wipe/zero function
    if re.search(r'(?:secure|safe|const)[_]?(?:wipe|zero|clear|erase|clean)', lower):
        return True

    # Pattern 5: memset call preserved via compiler barrier
    if "memset" in lower:
        return True

    # Pattern 6: rep stosb/stosd (from volatile loop or inline memset)
    if "rep stos" in lower:
        return True

    # Pattern 7: Multiple zero stores (from unrolled volatile loop)
    zero_stores = len(re.findall(r'mov\w*\s+\$0x0', func_asm))
    if zero_stores >= 4:
        return True

    return False


def has_no_memcmp(func_asm):
    """Check that a function does NOT use memcmp for its comparison."""
    if not func_asm:
        return True
    lower = func_asm.lower()
    return "memcmp" not in lower and "strcmp" not in lower


class TestCompilation:
    """Verify the fixed code compiles and works correctly."""

    def test_compilation_succeeds(self, compiled_binary):
        """The fixed code must compile successfully with -O2."""
        assert os.path.exists(compiled_binary)

    def test_functional_correctness(self, functional_test_result):
        """The fixed code must still produce correct results."""
        assert functional_test_result.returncode == 0, (
            f"Functional test failed:\n"
            f"stdout: {functional_test_result.stdout}\n"
            f"stderr: {functional_test_result.stderr}"
        )


class TestDeadStoreElimination:
    """
    Verify that dead-store-eliminated memset calls have been properly fixed.
    In the original code, memset() calls on local buffers before function
    return are removed by GCC's Dead Store Elimination at -O2. The fix
    must use a technique that prevents the compiler from removing the wipe.
    """

    @pytest.mark.parametrize("func_name", FUNCTIONS_NEEDING_WIPE)
    def test_wipe_operation_present(self, objdump_output, func_name):
        """Each vulnerable function must have a wipe operation that survives -O2."""
        func_asm = get_function_asm(objdump_output, func_name)
        assert func_asm, f"Function {func_name} not found in binary disassembly"
        assert has_wipe_operation(func_asm), (
            f"Function '{func_name}' does not contain a wipe operation in the "
            f"compiled binary. The memset was likely still optimized away by "
            f"Dead Store Elimination. Use explicit_bzero(), a volatile-based "
            f"wipe, or a compiler barrier to prevent optimization."
        )


class TestTimingSideChannel:
    """
    Verify that timing-vulnerable comparisons have been replaced with
    constant-time alternatives. memcmp() exits early on the first byte
    difference, enabling byte-by-byte brute-force via timing measurement.
    """

    @pytest.mark.parametrize("func_name", FUNCTIONS_NEEDING_CONSTANT_TIME)
    def test_no_memcmp(self, objdump_output, func_name):
        """Security comparison functions must not use memcmp (timing side channel)."""
        func_asm = get_function_asm(objdump_output, func_name)
        assert func_asm, f"Function {func_name} not found in binary disassembly"
        assert has_no_memcmp(func_asm), (
            f"Function '{func_name}' still uses memcmp/strcmp for security-"
            f"critical comparison. This enables timing side-channel attacks "
            f"where an attacker brute-forces the correct value byte-by-byte "
            f"by measuring response time. Replace with a constant-time "
            f"comparison (XOR accumulation with volatile result)."
        )


class TestVerificationTool:
    """
    Verify the automated security verification tool correctly identifies
    compiler-defeated security operations in compiled binaries.
    """

    def test_tool_exists_and_executable(self):
        """Verification tool must exist at /app/verify_security.sh."""
        assert os.path.exists("/app/verify_security.sh"), (
            "Verification tool not found at /app/verify_security.sh"
        )
        assert os.access("/app/verify_security.sh", os.X_OK), (
            "/app/verify_security.sh is not executable"
        )

    def test_output_is_valid_json_with_schema(self, compiled_binary):
        """Tool output must be valid JSON with required schema fields."""
        result = subprocess.run(
            ["/app/verify_security.sh", compiled_binary],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Tool exited with code {result.returncode}: {result.stderr}"
        )
        try:
            output = json.loads(result.stdout.strip())
        except json.JSONDecodeError as e:
            pytest.fail(f"Tool output is not valid JSON: {e}\nOutput: {result.stdout[:500]}")

        assert "binary" in output, "JSON missing 'binary' field"
        assert "vulnerabilities_found" in output, "JSON missing 'vulnerabilities_found' field"
        assert "vulnerabilities" in output, "JSON missing 'vulnerabilities' field"
        assert "secure" in output, "JSON missing 'secure' field"
        assert isinstance(output["vulnerabilities"], list), "'vulnerabilities' must be a list"
        assert isinstance(output["vulnerabilities_found"], int), "'vulnerabilities_found' must be int"
        assert isinstance(output["secure"], bool), "'secure' must be bool"

    def test_detects_vulnerabilities_in_original(self, vulnerable_binary):
        """Tool must detect vulnerabilities in the original unpatched binary."""
        result = subprocess.run(
            ["/app/verify_security.sh", vulnerable_binary],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Tool failed on vulnerable binary: {result.stderr}"
        )
        output = json.loads(result.stdout.strip())
        assert output["vulnerabilities_found"] > 0, (
            "Tool failed to detect any vulnerabilities in the original binary"
        )
        assert not output["secure"], (
            "Tool incorrectly reports vulnerable binary as secure"
        )
        # Must detect issues in at least 2 distinct functions
        funcs = set(v["function"] for v in output["vulnerabilities"])
        assert len(funcs) >= 2, (
            f"Tool only detected issues in {len(funcs)} function(s): {funcs}. "
            f"Expected at least 2 vulnerable functions."
        )

    def test_reports_clean_on_fixed(self, compiled_binary):
        """Tool must report zero vulnerabilities in the fixed binary."""
        result = subprocess.run(
            ["/app/verify_security.sh", compiled_binary],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Tool failed on fixed binary: {result.stderr}"
        )
        output = json.loads(result.stdout.strip())
        assert output["vulnerabilities_found"] == 0, (
            f"Tool reports {output['vulnerabilities_found']} vulnerabilities "
            f"in fixed binary: {output.get('vulnerabilities', [])}"
        )
        assert output["secure"], (
            "Tool does not report fixed binary as secure"
        )


class TestDesignRationale:
    """
    Verify the design rationale evaluates multiple mitigation strategies
    with justified trade-off analysis.
    """

    def test_rationale_exists(self):
        """Design rationale must exist at /app/design_rationale.md."""
        assert os.path.exists("/app/design_rationale.md"), (
            "Design rationale not found at /app/design_rationale.md"
        )

    def test_rationale_substantial(self):
        """Design rationale must contain substantial analysis."""
        with open("/app/design_rationale.md") as f:
            content = f.read()
        assert len(content) > 500, (
            f"Design rationale is too short ({len(content)} chars). "
            f"Expected substantial comparative analysis."
        )

    def test_rationale_evaluates_at_least_four_strategies(self):
        """Must evaluate at least 4 distinct mitigation strategies."""
        with open("/app/design_rationale.md") as f:
            content = f.read().lower()

        strategies = {
            "explicit_bzero": ["explicit_bzero"],
            "memset_s": ["memset_s"],
            "volatile": ["volatile"],
            "compiler_barrier": [
                "compiler barrier", "memory barrier",
                "__asm__", "asm volatile", "clobber",
            ],
            "pragma": ["pragma"],
            "platform_api": [
                "securezeromemory", "openssl_cleanse", "sodium_memzero",
            ],
        }

        found = [
            name for name, keywords in strategies.items()
            if any(kw in content for kw in keywords)
        ]

        assert len(found) >= 4, (
            f"Only found {len(found)} distinct strategy groups discussed: {found}. "
            f"Need at least 4 strategies evaluated."
        )

    def test_rationale_discusses_dead_store_elimination(self):
        """Must discuss Dead Store Elimination as compiler optimization."""
        with open("/app/design_rationale.md") as f:
            content = f.read().lower()
        assert any(term in content for term in [
            "dead store", "dse", "store elimination", "optimized away",
            "dead-store", "eliminated by the compiler",
        ]), "Rationale does not discuss Dead Store Elimination"

    def test_rationale_discusses_timing_attack(self):
        """Must discuss timing side-channel vulnerability and mitigation."""
        with open("/app/design_rationale.md") as f:
            content = f.read().lower()
        assert any(term in content for term in [
            "timing", "side-channel", "side channel",
            "constant-time", "constant time",
        ]), "Rationale does not discuss timing side-channel attacks"

    def test_rationale_justifies_chosen_approach(self):
        """Must contain justification for the chosen mitigation approach."""
        with open("/app/design_rationale.md") as f:
            content = f.read().lower()
        assert any(term in content for term in [
            "chosen", "selected", "recommend", "prefer",
            "decided", "our approach", "we use", "i chose",
            "chosen approach", "justif", "best option",
            "final choice", "we chose",
        ]), "Rationale does not justify the chosen approach"
