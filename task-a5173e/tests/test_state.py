
import subprocess
import pytest


@pytest.fixture(scope="module")
def sim_output():
    """Compile and simulate the AES-128 design with iverilog."""
    compile_result = subprocess.run(
        ["iverilog", "-o", "/tmp/decrypt_test",
         "/app/aes128_encrypt.v", "/app/aes128_decrypt.v",
         "/app/tb_aes128_decrypt.v"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compile_result.returncode == 0, (
        f"Verilog compilation failed:\n{compile_result.stderr}"
    )

    sim_result = subprocess.run(
        ["vvp", "/tmp/decrypt_test"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return sim_result.stdout


def test_no_failures(sim_output):
    """No test vector should produce a FAIL."""
    assert "[FAIL]" not in sim_output, f"Test failures detected:\n{sim_output}"


def test_all_five_vectors_pass(sim_output):
    """All 5 test vectors must pass."""
    count = sim_output.count("[PASS]")
    assert count == 5, (
        f"Expected 5 passing vectors, got {count}:\n{sim_output}"
    )


def test_fips197_appendix_b_decrypt(sim_output):
    """FIPS 197 Appendix B decryption test vector must pass."""
    assert "[PASS] Test 0" in sim_output


def test_sp800_38a_ecb_decrypt(sim_output):
    """NIST SP 800-38A ECB Block 1 decryption test vector must pass."""
    assert "[PASS] Test 1" in sim_output


def test_fips197_kat_decrypt(sim_output):
    """FIPS 197 Appendix A (KAT) decryption test vector must pass."""
    assert "[PASS] Test 2" in sim_output


def test_allzeros_decrypt(sim_output):
    """All-zeros decryption test vector must pass."""
    assert "[PASS] Test 3" in sim_output


def test_encrypt_decrypt_roundtrip(sim_output):
    """Encrypt-then-decrypt round-trip must match original plaintext."""
    assert "[PASS] Test 4" in sim_output
