
"""Verify Noise Protocol handshake results against cacophony test vectors."""

import json
import os
import pytest

EXPECTED = {
    "Noise_XX_25519_ChaChaPoly_SHA256": {
        "handshake_hash": "c8e5f64e846193be2a834104c2a009868d6c9f3bd3c186299888b488b2f1f58e",
        "ciphertexts": [
            "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c79444c756477696720766f6e204d69736573",
            "95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f14480884381cbad1f276e038c48378ffce2b65285e08d6b68aaa3629a5a8639392490e5b9bd5269c2f1e4f488ed8831161f19b7815528f8982ffe09be9b5c412f8a0db50f8814c7194e83f23dbd8d162c9326ad",
            "c7195ffacac1307ff99046f219750fc47693e23c3cb08b89c2af808b444850a80ae475b9df0f169ae80a89be0865b57f58c9fea0d4ec82a286427402f113e4b6ae769a1d95941d49b25030",
            "96763ed773f8e47bb3712f0e29b3060ffc956ffc146cee53d5e1df",
            "3e40f15f6f3a46ae446b253bf8b1d9ffb6ed9b174d272328ff91a7e2e5c79c07f5",
            "eb3f3515110702e047a6c9da4478b6ead94873c11c0f2d710ddb3f09fce024b3a58502ae3f",
        ],
    },
    "Noise_IK_25519_AESGCM_BLAKE2s": {
        "handshake_hash": "af51ccef548b5277ae7120c78750de6ad146ead3565b67ae43551ca4dfa962a3",
        "ciphertexts": [
            "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c7944fc16af5edc066c93c77be147f8e6785cd6bd7b27e0f660d02a6a566ceb61b22af4d0dcc8560bce79b2a1fb55f68bc34017319936516ae9ce0862fe172c77a883f241700cb26d145dc8f8c9fe80a29008",
            "95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f14480884319679a2f2fae0ee3700b9d1f532eb77fcf485567e810eaf95b2f9eeca858fe",
            "daf849a4f4bd8b0276f120b017b9dfdbc9ed667ee98316e95de1cc",
            "cdf2321b9584498d0ce313cb0c995c3ee2d679c1f3c22576ff1e90",
            "abc41aa7b17f5d7c5b8454c203668718a15020b72729f1243490ab54150338293a",
            "59bafe529215e376187e06fcfb6772d6ca7f0946877e77aafb4a90a5fc6c4cf82344d5c949",
        ],
    },
    "Noise_NK_25519_ChaChaPoly_BLAKE2b": {
        "handshake_hash": "f87aa4eb6416e5b0d2b6e6f0b7bc41f3c5986a5d32d55c08d67cbd412f3ec2fa04d8e358ab95b3bbfab054a140a98eccf4284bb6309b600981d451ecac484932",
        "ciphertexts": [
            "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c7944f3041e39b0c8ba56008f2d1183fea6ac83564ead0267b0842ec4c521ed1e1407",
            "95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f1448088432281dcc1835131f305dca14525e15e27d1f32294aa835e40fc18be480c1db9",
            "357e24e9f28ba22080666f7efacc01b2a0a4e358e742aeeff2aaf5",
            "8b23b34ff3169de06a39551e969ca7876cc5122a4acff74bf2ec29",
            "5c104779b6f36e59fca73ed94b0ae092eae1d76dd109caf5060aaaedba385d7076",
            "34ae0518d0cd3aa641ed372ea94935ceecd87f8c4b422ce21a33d3f6f5493891e3e915d83f",
        ],
    },
    "Noise_KK_25519_AESGCM_SHA256": {
        "handshake_hash": "c03693acd830588fac76dd414c9e100e8c601d27511de855100239f7705fa3f2",
        "ciphertexts": [
            "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c79448564738a841228e693caeec4c497a8bd562231c3e51a1f03c4fd45dfe3a67870",
            "95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f144808843b94504c4d83506f5dd2568b68490eba8ed6f9cf2cca194a273c56d7ae3c558",
            "6a5c10a201d4e3a08f79f64949e55731f774913a4d949bda3fcebf",
            "4e8a1bf06926fdd74e2f516e2b0c11cc1dc3387fadeb75389d4342",
            "c1df7194ca8ea51d4dd99059bc9b90288112d47237d8481f1773fb26a31629a05c",
            "3edba4feaf590ee88dd8f5fba51db4bee651cf41afd410fe476c524ac9b1db24252fc55ff8",
        ],
    },
    "Noise_NNpsk0_25519_ChaChaPoly_SHA256": {
        "handshake_hash": "f4d03dc34495c95729ea6de9e1b59004b59733102488b3e24bc441e0be208eaf",
        "ciphertexts": [
            "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c794479b962b8aff8485742ac32f905ba45369e2465fb59e138a93d67a0d1266b6a54",
            "95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f144808843d6062704d5a9c422a8e834423f8c1feada7e8d0d910a1a2cd030fb584221e3",
            "e632c3763d7669067383433197a3baddf146e9e70ad4b4e9e59e0f",
            "64c6bee32ea91c8474bb4c21d7a700109ad45af77b29764ba5eb1e",
            "e2fa0bed0603b62d3ccac2ecabbf3fe33f3e86514909b323361626266cb2471cc8",
            "0c01dc9cec1fe4ddd692e8dd32188aa351088dc91183639a53b57aa4692b5ebdef8b8ca111",
        ],
    },
    "Noise_N_25519_AESGCM_SHA512": {
        "handshake_hash": "f11ef2519ad3e11f7f86402d4ccfbcca16e594eb7b5b8e96da4ef57682cb4b284e2535dbb564d798a1817ab3afc1be4b0dac90108a6d2d7e731f0f4b7396ee64",
        "ciphertexts": [
            "ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c79442e342fc24bc3e384f0d6bc351f9d3b64235953d3ceb030acdced0d3d1f92f11d",
            "134dbd942584fc54217bba66d70e7956d6f049bab00e880191572991e1fb56",
            "f347f4cc451cf99f4f2e3fce2564c7c86c05d4365418f4a3350ad4",
            "8ce5a7d70ef7e0e37293e4589f85202319f4c99de4c7fb37d774b3",
            "849639e55808f64fefc8f941e9af6f5f7d2ffe170db389aec129a723c37f7e4454",
            "f160e889105be3b13893f012b208d2a603b3b87524fdc47aa031f98ee48f001f521850c7ca",
        ],
    },
}


def load_results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), f"results.json not found at {results_path}"
    with open(results_path) as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json must exist at /app/results.json"

    def test_results_is_list(self):
        results = load_results()
        assert isinstance(results, list), "results.json must contain a JSON array"

    def test_correct_number_of_results(self):
        results = load_results()
        assert len(results) == 6, f"Expected 6 results, got {len(results)}"

    def test_all_protocols_present(self):
        results = load_results()
        result_names = {r["protocol_name"] for r in results}
        expected_names = set(EXPECTED.keys())
        assert result_names == expected_names, (
            f"Missing protocols: {expected_names - result_names}, "
            f"Extra protocols: {result_names - expected_names}"
        )


class TestNoiseXX_ChaChaPoly_SHA256:
    PROTO = "Noise_XX_25519_ChaChaPoly_SHA256"

    def _get_result(self):
        results = load_results()
        for r in results:
            if r["protocol_name"] == self.PROTO:
                return r
        pytest.fail(f"No result for {self.PROTO}")

    def test_handshake_hash(self):
        r = self._get_result()
        assert r["handshake_hash"] == EXPECTED[self.PROTO]["handshake_hash"]

    def test_message_count(self):
        r = self._get_result()
        assert len(r["messages"]) == 6

    @pytest.mark.parametrize("msg_idx", range(6))
    def test_ciphertext(self, msg_idx):
        r = self._get_result()
        actual = r["messages"][msg_idx]["ciphertext"]
        expected = EXPECTED[self.PROTO]["ciphertexts"][msg_idx]
        assert actual == expected, (
            f"Message {msg_idx} mismatch:\n  got:    {actual[:80]}...\n  expect: {expected[:80]}..."
        )


class TestNoiseIK_AESGCM_BLAKE2s:
    PROTO = "Noise_IK_25519_AESGCM_BLAKE2s"

    def _get_result(self):
        results = load_results()
        for r in results:
            if r["protocol_name"] == self.PROTO:
                return r
        pytest.fail(f"No result for {self.PROTO}")

    def test_handshake_hash(self):
        r = self._get_result()
        assert r["handshake_hash"] == EXPECTED[self.PROTO]["handshake_hash"]

    def test_message_count(self):
        r = self._get_result()
        assert len(r["messages"]) == 6

    @pytest.mark.parametrize("msg_idx", range(6))
    def test_ciphertext(self, msg_idx):
        r = self._get_result()
        actual = r["messages"][msg_idx]["ciphertext"]
        expected = EXPECTED[self.PROTO]["ciphertexts"][msg_idx]
        assert actual == expected


class TestNoiseNK_ChaChaPoly_BLAKE2b:
    PROTO = "Noise_NK_25519_ChaChaPoly_BLAKE2b"

    def _get_result(self):
        results = load_results()
        for r in results:
            if r["protocol_name"] == self.PROTO:
                return r
        pytest.fail(f"No result for {self.PROTO}")

    def test_handshake_hash(self):
        r = self._get_result()
        assert r["handshake_hash"] == EXPECTED[self.PROTO]["handshake_hash"]

    def test_message_count(self):
        r = self._get_result()
        assert len(r["messages"]) == 6

    @pytest.mark.parametrize("msg_idx", range(6))
    def test_ciphertext(self, msg_idx):
        r = self._get_result()
        actual = r["messages"][msg_idx]["ciphertext"]
        expected = EXPECTED[self.PROTO]["ciphertexts"][msg_idx]
        assert actual == expected


class TestNoiseKK_AESGCM_SHA256:
    PROTO = "Noise_KK_25519_AESGCM_SHA256"

    def _get_result(self):
        results = load_results()
        for r in results:
            if r["protocol_name"] == self.PROTO:
                return r
        pytest.fail(f"No result for {self.PROTO}")

    def test_handshake_hash(self):
        r = self._get_result()
        assert r["handshake_hash"] == EXPECTED[self.PROTO]["handshake_hash"]

    def test_message_count(self):
        r = self._get_result()
        assert len(r["messages"]) == 6

    @pytest.mark.parametrize("msg_idx", range(6))
    def test_ciphertext(self, msg_idx):
        r = self._get_result()
        actual = r["messages"][msg_idx]["ciphertext"]
        expected = EXPECTED[self.PROTO]["ciphertexts"][msg_idx]
        assert actual == expected


class TestNoiseNNpsk0_ChaChaPoly_SHA256:
    PROTO = "Noise_NNpsk0_25519_ChaChaPoly_SHA256"

    def _get_result(self):
        results = load_results()
        for r in results:
            if r["protocol_name"] == self.PROTO:
                return r
        pytest.fail(f"No result for {self.PROTO}")

    def test_handshake_hash(self):
        r = self._get_result()
        assert r["handshake_hash"] == EXPECTED[self.PROTO]["handshake_hash"]

    def test_message_count(self):
        r = self._get_result()
        assert len(r["messages"]) == 6

    @pytest.mark.parametrize("msg_idx", range(6))
    def test_ciphertext(self, msg_idx):
        r = self._get_result()
        actual = r["messages"][msg_idx]["ciphertext"]
        expected = EXPECTED[self.PROTO]["ciphertexts"][msg_idx]
        assert actual == expected


class TestNoiseN_AESGCM_SHA512:
    PROTO = "Noise_N_25519_AESGCM_SHA512"

    def _get_result(self):
        results = load_results()
        for r in results:
            if r["protocol_name"] == self.PROTO:
                return r
        pytest.fail(f"No result for {self.PROTO}")

    def test_handshake_hash(self):
        r = self._get_result()
        assert r["handshake_hash"] == EXPECTED[self.PROTO]["handshake_hash"]

    def test_message_count(self):
        r = self._get_result()
        assert len(r["messages"]) == 6

    @pytest.mark.parametrize("msg_idx", range(6))
    def test_ciphertext(self, msg_idx):
        r = self._get_result()
        actual = r["messages"][msg_idx]["ciphertext"]
        expected = EXPECTED[self.PROTO]["ciphertexts"][msg_idx]
        assert actual == expected
