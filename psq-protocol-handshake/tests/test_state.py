
"""Tests for PSQ protocol implementation.

Verifies the agent's output.json against pre-computed test vectors
for the X25519_NONE_X25519_CHACHA20POLY1305_HKDFSHA256 ciphersuite.
"""

import json
import os
import pytest

# Pre-computed test vectors (generated from independently verified reference implementation)
EXPECTED_INTERMEDIATE = {
    "ss_dh_outer": "f16e5d75638ee10b0f775fb39d0bb79f20617d5d042f25d25085b6ac571d6517",
    "ss_dh_inner": "da2811b2c1c3b2a70efada3b3eddf8877fa8d9657461f723f1eb010d0c733d7c",
    "ss_dh_response_1": "097a97332b1b3aaf94ca151a42dbfc6e51c767eccad71e9b2c680bb4d45c9d0e",
    "ss_dh_response_2": "506a11312430c4ced6f887ea1ed9f784e1ee4e1de2c1270c853c8896ef4c8862",
    "tx0": "98684e1a099021768150b26661a1448a99bc237f80aaa9b4d3add60ab0b70852",
    "tx1": "49c0b2f6a969dd6de701278b4c04eddee93978f6a6507e820e311bdc9f6fdb52",
    "tx2": "b9373cbc49b7fff08f515d7a552b3458fee56fda8913757419ea04f3ecd52722",
    "K_0": "0bf8f9fc620ea198c44df75b32607d44b41e8fa6adf5ef2ccc9bf9034b804b15",
    "K_1": "386e6b9781908c9adbdc43178598bac518f2f7c4e4ac235751384c0a00664f14",
    "K_2": "cfeeb62413bb29b8050d46fb56fa5cce55502b1867f96a30532c5746d3be74e6",
    "ctxt_inner": "2889f1161cc9989c18d203c6062e8e791d5e3de74091959da5e112ea39a8995ab8edfdd86e41472f0934805e593b44b4f1c048693a143b44",
}

EXPECTED_SESSION = {
    "K_S": "7a45d2c4c74e7100bf422f09a92e19b70752f50ea9e633301987a08f0ed8f5d7",
    "session_ID": "90360cdf39d99f4ee133cdfcbb56a7e8e7b3456127b3b41e24d21ec4cd5ab681",
    "pk_binder": "9cf42b700ebfaf244fe7ef98aeb8dcbf370d805e14d63898eefa1a384746ac56",
    "K_i2r_0": "496eede175c07e67b8e6e2d99ee0011a08ef3944dc837a7bbfd0cb313e16f9b5",
    "K_r2i_0": "a63ac44e9d569b9d1e638e01805a6f8f9cc0105b5f4e0a1595b91ceb079a293e",
    "K_i2r_1": "05ff00eb29641299dbd2c78e1e0412c5f0893539b5487aa5091c0663aba25b69",
    "K_r2i_1": "fcb9efe59e2ff584a184691762ce63db7656095770a880b13ab7eeb0336ba7bc",
    "K_export": "c2b6f96e0f99f82a7c96bbdb30ac006e8425f9fdefea80c2dfd21594d4e68bf7",
}

EXPECTED_REKEY = {
    "K_import": "4c90261b3407e92b492e5534a1e2c45a27d7025d37aba6785202c132f903f16a",
    "tx_prime": "7a2f8c6b84ebfa765157a026d6cd5cfae546b3c6f0bdb69308b57ee00622cee8",
    "K_S_prime": "472042c77ca16edb25cefab69bb0b776758989c5b6292f7df9ead14bf0ed69c8",
    "session_ID_prime": "c9735fdfdcf99b56924cf8beab25095f470eea6b545c2fb3d5785e69e74ba35d",
}


@pytest.fixture
def output():
    """Load the agent's output.json."""
    output_path = "/app/output.json"
    assert os.path.exists(output_path), (
        f"output.json not found at {output_path}. "
        "The implementation must write results to /app/output.json."
    )
    with open(output_path, "r") as f:
        data = json.load(f)
    return data


def test_output_has_required_sections(output):
    """Verify output.json has all required top-level sections."""
    assert "intermediate" in output, "Missing 'intermediate' section"
    assert "session" in output, "Missing 'session' section"
    assert "rekey" in output, "Missing 'rekey' section"


def test_intermediate_has_required_keys(output):
    """Verify intermediate section has all required keys."""
    intermediate = output["intermediate"]
    for key in EXPECTED_INTERMEDIATE:
        assert key in intermediate, f"Missing intermediate key: {key}"


def test_session_has_required_keys(output):
    """Verify session section has all required keys."""
    session = output["session"]
    for key in EXPECTED_SESSION:
        assert key in session, f"Missing session key: {key}"


def test_rekey_has_required_keys(output):
    """Verify rekey section has all required keys."""
    rekey = output["rekey"]
    for key in EXPECTED_REKEY:
        assert key in rekey, f"Missing rekey key: {key}"


# --- X25519 DH shared secrets ---

def test_ss_dh_outer(output):
    """Verify outer DH shared secret: DH.Derive(epriv_I, pub_R)."""
    assert output["intermediate"]["ss_dh_outer"] == EXPECTED_INTERMEDIATE["ss_dh_outer"]


def test_ss_dh_inner(output):
    """Verify inner DH shared secret: DH.Derive(priv_I, pub_R)."""
    assert output["intermediate"]["ss_dh_inner"] == EXPECTED_INTERMEDIATE["ss_dh_inner"]


def test_ss_dh_response_1(output):
    """Verify response DH shared secret 1: DH.Derive(epriv_R, pub_I)."""
    assert output["intermediate"]["ss_dh_response_1"] == EXPECTED_INTERMEDIATE["ss_dh_response_1"]


def test_ss_dh_response_2(output):
    """Verify response DH shared secret 2: DH.Derive(epriv_R, epub_I)."""
    assert output["intermediate"]["ss_dh_response_2"] == EXPECTED_INTERMEDIATE["ss_dh_response_2"]


# --- Transcript hashes ---

def test_tx0(output):
    """Verify transcript hash tx0 = hash(0x00 || len_prefix(context) || pub_R || epub_I)."""
    assert output["intermediate"]["tx0"] == EXPECTED_INTERMEDIATE["tx0"]


def test_tx1(output):
    """Verify transcript hash tx1 = hash(0x01 || tx0 || pub_I || optional(None) || optional(None))."""
    assert output["intermediate"]["tx1"] == EXPECTED_INTERMEDIATE["tx1"]


def test_tx2(output):
    """Verify transcript hash tx2 = hash(0x02 || tx1 || epub_R)."""
    assert output["intermediate"]["tx2"] == EXPECTED_INTERMEDIATE["tx2"]


# --- Derived keys ---

def test_K_0(output):
    """Verify K_0 = KDF(ss_dh_outer, tx0)."""
    assert output["intermediate"]["K_0"] == EXPECTED_INTERMEDIATE["K_0"]


def test_K_1(output):
    """Verify K_1 = KDF(K_0 || ss_dh_inner, tx1)."""
    assert output["intermediate"]["K_1"] == EXPECTED_INTERMEDIATE["K_1"]


def test_K_2(output):
    """Verify K_2 = KDF(K_1 || ss_dh_response_1 || ss_dh_response_2, tx2)."""
    assert output["intermediate"]["K_2"] == EXPECTED_INTERMEDIATE["K_2"]


# --- AEAD ciphertexts ---

def test_ctxt_inner(output):
    """Verify inner ciphertext = AEAD.Encrypt(K_1, registration_payload, inner_aad)."""
    assert output["intermediate"]["ctxt_inner"] == EXPECTED_INTERMEDIATE["ctxt_inner"]


# --- Session keys ---

def test_K_S(output):
    """Verify session key K_S = KDF(K_2, 'session key' || tx2)."""
    assert output["session"]["K_S"] == EXPECTED_SESSION["K_S"]


def test_session_ID(output):
    """Verify session_ID = KDF(K_S, 'shared key id')."""
    assert output["session"]["session_ID"] == EXPECTED_SESSION["session_ID"]


def test_pk_binder(output):
    """Verify pk_binder = KDF(K_S, pub_I || pub_R)."""
    assert output["session"]["pk_binder"] == EXPECTED_SESSION["pk_binder"]


def test_K_i2r_0(output):
    """Verify channel key K_i2r for channel 0."""
    assert output["session"]["K_i2r_0"] == EXPECTED_SESSION["K_i2r_0"]


def test_K_r2i_0(output):
    """Verify channel key K_r2i for channel 0."""
    assert output["session"]["K_r2i_0"] == EXPECTED_SESSION["K_r2i_0"]


def test_K_i2r_1(output):
    """Verify channel key K_i2r for channel 1."""
    assert output["session"]["K_i2r_1"] == EXPECTED_SESSION["K_i2r_1"]


def test_K_r2i_1(output):
    """Verify channel key K_r2i for channel 1."""
    assert output["session"]["K_r2i_1"] == EXPECTED_SESSION["K_r2i_1"]


def test_K_export(output):
    """Verify exported secret K_export = KDF(K_S, export_context || 'PSQ secret export')."""
    assert output["session"]["K_export"] == EXPECTED_SESSION["K_export"]


# --- Rekey ---

def test_K_import(output):
    """Verify K_import = KDF(K_S || psk, 'secret import')."""
    assert output["rekey"]["K_import"] == EXPECTED_REKEY["K_import"]


def test_tx_prime(output):
    """Verify tx' = hash(tx2 || session_ID)."""
    assert output["rekey"]["tx_prime"] == EXPECTED_REKEY["tx_prime"]


def test_K_S_prime(output):
    """Verify rekeyed session key K_S' = KDF(K_import, 'session secret' || tx')."""
    assert output["rekey"]["K_S_prime"] == EXPECTED_REKEY["K_S_prime"]


def test_session_ID_prime(output):
    """Verify rekeyed session_ID' = KDF(K_S', 'shared key id')."""
    assert output["rekey"]["session_ID_prime"] == EXPECTED_REKEY["session_ID_prime"]
