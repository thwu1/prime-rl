"""
CAVP CTR_DRBG Conformance Pipeline Tests.

Verifies that the solver produced a correct reference implementation,
a working CAVS parser, a functional harness, and accurate conformance report.

"""

import json
import os
import sys
import importlib.util
import pytest

sys.path.insert(0, "/app")

# ---------------------------------------------------------------------------
# CAVP intermediate states (Key, V) from CAVS 14.3 response files.
# ---------------------------------------------------------------------------

INTERMEDIATE_STATES = {
    "aes256_df_basic": [
        {
            "count": 0,
            "inst_key": "3363d9000e6db47c16d3fc65f2872c08a35f99b2d174afa537a66ec153052d98",
            "inst_v": "9ee8d2e9c618ccbb8e66b5eb5333dce1",
            "gen1_key": "b1dff09c816af6d4b2111fe63c4507cb196154f8c59957a94a2b641a7c16cc01",
            "gen1_v": "69eec01b2dd4ff3aab5fac9467f54485",
            "gen2_key": "33a1f160b0bde1dd55fc314c3d1620c0581ace8b32f062fb1ed54cdecdc17694",
            "gen2_v": "f537c07f36573a26b3f55c8b9f7246d1",
        },
        {
            "count": 1,
            "inst_key": "b474f2ede9bebc8d3d7fd931e5cf594b0f83776c47a2bf7c28cf7b732bdfeae9",
            "inst_v": "a88c1eb5f4c8dda2a2737dee244ed1a5",
            "gen1_key": "921d51310a9cef4048c7833a0a3dc295791298a514b137d1b1b3b4191ae46625",
            "gen1_v": "36f88057e49a3805011c18b4c59b9b96",
            "gen2_key": "5adab58f7832ff002946d93f7026a80778414276a53573735dccb186b63dbc75",
            "gen2_v": "12b11118ef5e85ec1b6a22d0eccf1a15",
        },
        {
            "count": 2,
            "inst_key": "1ab4e9b152a99f90f2f9cd59091e4ef39c22bb66677ede0b67bccb012f4756ac",
            "inst_v": "1e93cbee86575faeb7856f5f71996f33",
            "gen1_key": "436f7282e60ec61b718a53f8d3ba84f9b34bf30a17054fe043f43193835f08c1",
            "gen1_v": "b4c187b741a0c87b7d9ed8cd6f5e94ff",
            "gen2_key": "f149827b53f9d804d8ad2d9a468f197daa08ba6148443378d4fd5100a359cd8a",
            "gen2_v": "87c9f8d47cebfa738acd2ba1cf7ee429",
        },
    ],
    "aes256_df_addl_input": [
        {
            "count": 0,
            "inst_key": "fe96784a3968b04aca2079e4bc1b7674e59d0bcb9d1168fb26cacd830ffde509",
            "inst_v": "24274380ee9aa72b730efae01987a16e",
            "gen1_key": "ec013aa81ec90251e399774516481a22736bd89b5a5a6a7198da7cfceb741c59",
            "gen1_v": "9e34cdda08a3c193231647953c73a8db",
            "gen2_key": "c13f343817bf7fcaafc49023e633f3222a16f3ae3c608880aa8e7e0f6b67b05a",
            "gen2_v": "a644cb76114072fa7fdd5715746ee41a",
        },
        {
            "count": 1,
            "inst_key": "3742b0a4b3b5eb1c9dfafe61d79ebc8a2d1cb44543c3a935631d758859253d54",
            "inst_v": "278ab18d16365223469e7a3ada9a5ac8",
            "gen1_key": "9441cfee7b599157d5abed8ffcd99e97a82a43107bf11060b149140dac78867d",
            "gen1_v": "0d86e2e104265fb42ce3924a7314001d",
            "gen2_key": "866d9d9b9826a13d1ad3d422f6fe162b20cd55dddad7f30a995cc55d70b90891",
            "gen2_v": "b8e568d819fa434e8a5d1ec926d4e087",
        },
        {
            "count": 2,
            "inst_key": "e0ff04bc0dd9fe56e994fb28f0695d32ad1c6b89b51f87eec51cdd0b2fe5aa25",
            "inst_v": "bb18f50b3a18c2dc6a577c0c71f7c7e6",
            "gen1_key": "54f8dbea108e2489d29f21bccba28fe77f3c67d9139cb7cc6a1890e78e2f7cbf",
            "gen1_v": "f4b89010857051688731199ad6589fc4",
            "gen2_key": "85a0e65aad05ab063e92ed53a121abc5e54f961248b1e718248a01e6ea20db5d",
            "gen2_v": "aa58988f6ca15834c1b16963eff05de5",
        },
    ],
    "aes256_df_perso": [
        {
            "count": 0,
            "inst_key": "7c0d39f9032f89229e8ec342c31eb451305ff52ffd751b68b7b07f067134100f",
            "inst_v": "a7e1ccbc0558fb3f7471f695bc1e38cc",
            "gen1_key": "0b20cf7229e0ec73c95af113106652026a3ce4a2b970cde54ea59ea4c80d5d73",
            "gen1_v": "0720050c7e09f23989c8e8c39416ee47",
            "gen2_key": "2f31f36a8aa08c825e58e5c2f514db39a21456db9c2156bfa81d5de3d1d805d3",
            "gen2_v": "c0c855c3035381aa8ce38ca390a38451",
        },
        {
            "count": 1,
            "inst_key": "cc310662550f9070432d7ecd2d1dc1203694400edb61b7bce29c01722f020df8",
            "inst_v": "fe2487387ae2200c5eab01a79be8b332",
            "gen1_key": "aaaed2a0018a461c6937a0dd7990536f0dba93e48e0794989999b3df97b19514",
            "gen1_v": "146b38684571f0391445449be977872b",
            "gen2_key": "8129c4e3ac375d8b867d348845314c589bfbcf4fbef496860c242119397d1891",
            "gen2_v": "0cd0c1613bc201c112ca678d1a267d25",
        },
        {
            "count": 2,
            "inst_key": "26ee6d146dd7b8df081378d9e573dbb0c4d591a6d322e23c68d35ae166422cad",
            "inst_v": "569bc37274643d959c3e942b226f6445",
            "gen1_key": "48ec5a157f848a5a7d7054e46c150661a811f00c856027c8f0950c0f60fa4f49",
            "gen1_v": "8d1ba79316c1d7d47f4d192effdaf0aa",
            "gen2_key": "e00450b294d41812575ff5ec8e976a82ce9857b669d99891ef5d427aa8958ae9",
            "gen2_v": "36a7929fe0f6459082c524760328320f",
        },
    ],
    "aes256_nodf_basic": [
        {
            "count": 0,
            "inst_key": "8c52f901632d522774c08fad0eb2c33b98a701a1861aecf3d8a25860941709fd",
            "inst_v": "217b52142105250243c0b2c206b8f59e",
            "gen1_key": "72f4af5c93258eb3eeec8c0cacea6c1d1978a4fad44312725f1ac43b167f2d52",
            "gen1_v": "e86f6d07dfb551cebad80e6bf6830ac4",
            "gen2_key": "1a1c6e5f1cccc6974436e5fd3f015bc8e9dc0f90053b73e3c19d4dfd66d1b85a",
            "gen2_v": "53c78ac61a0bac9d7d2e92b1e73e3392",
        },
        {
            "count": 1,
            "inst_key": "68603ccf141e853f3b10c008550ab842345ce399712346aa16f977292c3c51f0",
            "inst_v": "a165e2ffc83dee140a654fb7e5b9b5ee",
            "gen1_key": "0f3ae40b109548d29a30a56c848a2ee97c09706efdd2760fcd85c1f6b0386ec9",
            "gen1_v": "85cbbdd3d168a48fdf485b5ee8fec428",
            "gen2_key": "fb63a736069acd25a9ba49865d167e8c506e787c999e5509faa75129c2c26625",
            "gen2_v": "3bccc6785beb8d11ace6816d0378ad1e",
        },
        {
            "count": 2,
            "inst_key": "5118225735bdd47d02186824625fcf2943a4c025cbfda08c1143d9330e3413b5",
            "inst_v": "27f2ec27afc005592e2506a13d33f3f9",
            "gen1_key": "8921a58fe74ebbaf81c0e2441bf56a110e74bf47339badbf68791467bf24a2c9",
            "gen1_v": "ec255695174809d82bc333993fe38856",
            "gen2_key": "29a7babeda561bc30e8eaad7071efde51aa611ab42e9676afef6ad25851c4b82",
            "gen2_v": "981f260a2e69d260d0ddcd941af035fa",
        },
    ],
    "aes256_df_reseed": [
        {
            "count": 0,
            "inst_key": "d64160c3e965f377caef625c7eb21dd37728bcf84bfc23b92e267611feaffda8",
            "inst_v": "446ce986bd722ad1a514ebb7d274ec99",
            "reseed_key": "50d9feb33fc77303b83232b7deded04f1bfa4afaa937712f88458d6b64c046c5",
            "reseed_v": "0b8e38a54036f1ba80a2880d4f17bb09",
            "gen1_key": "a2203a6f082ecdc0cd38f0b3b19f1a8cd6a5f110a13bb488c1e70f9f95a93024",
            "gen1_v": "84b0a849c5459e27fe7f8c5db26fa13d",
            "gen2_key": "de721178a341a85eb54a2f7e2b3cd4bcc201417e739eb183fa958f9af8535b2c",
            "gen2_v": "de67dd5f9a431fc46dd1825cd1a2bff3",
        },
        {
            "count": 1,
            "inst_key": "7536744c7884f4fdcaad8a4c0d7a0fcefae9b8a2f6b25fc58695fc105b5f89cf",
            "inst_v": "277f8013d3736c9042086bc6bcac849a",
            "reseed_key": "a844429f03e836098374b7ce4a745f946f6813abd0bd3937935cb1fd16872100",
            "reseed_v": "697e7b06fac7ade93f93b74b87ada432",
            "gen1_key": "9a528ae33c4fb8621b6f7a461457f163c2d1223b8101ffea60d831f251188fd1",
            "gen1_v": "0b0ecbb77b576b030776599181b52ae8",
            "gen2_key": "ce47dc772482b4f116a1f07edd3df7c0ef3623934bc210e7083827563a720263",
            "gen2_v": "2693e839470384cd98db50df67bcaf61",
        },
        {
            "count": 2,
            "inst_key": "fb5d817284c1e8cbc87ce8139b161bcfc1e60b7c86d5b4406a08381aca80ed61",
            "inst_v": "0dd44d48218a34f2a98f61a99f03b6d4",
            "reseed_key": "84b278789ea405c3b13e7da4f4f2e9b75eadd3bd3ff3586bcd294980cd9f23f9",
            "reseed_v": "f139065e248bb86f328994553c12ad35",
            "gen1_key": "2274598253ff7fc91df184cc95af221f97212106664606056063c9ee88d0d6ea",
            "gen1_v": "a5f20bf9b989e86e9179029cd8144fe6",
            "gen2_key": "4754fb21f0510855ca9ad5ffb2602a1be6bf8a9c90d0a1d8ffa5b7e0149bc4ad",
            "gen2_v": "3bdff5e02d954c2d1481db75401703ff",
        },
    ],
}


@pytest.fixture(scope="module")
def cavp_data():
    with open("/tests/cavp_vectors.json") as f:
        return json.load(f)


def _get_group(cavp_data, group_id):
    for g in cavp_data["test_groups"]:
        if g["id"] == group_id:
            return g
    raise ValueError(f"Test group {group_id} not found")


def _hex_to_bytes(h):
    return bytes.fromhex(h) if h else b""


def _run_vector(drbg_class, use_df, tv, states, rbits_len, has_reseed=False):
    """Execute a single CAVP test vector and verify all states + output."""
    drbg = drbg_class(use_df=use_df)

    entropy = _hex_to_bytes(tv["entropy_input"])
    nonce = _hex_to_bytes(tv["nonce"])
    pers = _hex_to_bytes(tv["personalization_string"])

    drbg.instantiate(entropy, nonce, pers)
    assert drbg.key.hex() == states["inst_key"], (
        f"Instantiate Key mismatch (COUNT={tv['count']})"
    )
    assert drbg.v.hex() == states["inst_v"], (
        f"Instantiate V mismatch (COUNT={tv['count']})"
    )

    if has_reseed:
        reseed_entropy = _hex_to_bytes(tv["entropy_input_reseed"])
        reseed_ai = _hex_to_bytes(tv.get("additional_input_reseed", ""))
        drbg.reseed(reseed_entropy, reseed_ai)
        assert drbg.key.hex() == states["reseed_key"], (
            f"Reseed Key mismatch (COUNT={tv['count']})"
        )
        assert drbg.v.hex() == states["reseed_v"], (
            f"Reseed V mismatch (COUNT={tv['count']})"
        )

    ai1 = _hex_to_bytes(tv["additional_input_1"])
    drbg.generate(rbits_len, ai1)
    assert drbg.key.hex() == states["gen1_key"], (
        f"Generate1 Key mismatch (COUNT={tv['count']})"
    )
    assert drbg.v.hex() == states["gen1_v"], (
        f"Generate1 V mismatch (COUNT={tv['count']})"
    )

    ai2 = _hex_to_bytes(tv["additional_input_2"])
    result = drbg.generate(rbits_len, ai2)
    assert result.hex() == tv["returned_bits"], (
        f"ReturnedBits mismatch (COUNT={tv['count']})"
    )
    assert drbg.key.hex() == states["gen2_key"], (
        f"Generate2 Key mismatch (COUNT={tv['count']})"
    )
    assert drbg.v.hex() == states["gen2_v"], (
        f"Generate2 V mismatch (COUNT={tv['count']})"
    )


# ===========================================================================
# Test Group 1: Reference implementation correctness
# ===========================================================================

class TestReferenceImplDFBasic:
    GROUP_ID = "aes256_df_basic"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_vector(self, cavp_data, idx):
        from reference_impl import CTR_DRBG
        group = _get_group(cavp_data, self.GROUP_ID)
        tv = group["tests"][idx]
        states = INTERMEDIATE_STATES[self.GROUP_ID][idx]
        _run_vector(CTR_DRBG, True, tv, states, group["returned_bits_len"])


class TestReferenceImplDFAddl:
    GROUP_ID = "aes256_df_addl_input"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_vector(self, cavp_data, idx):
        from reference_impl import CTR_DRBG
        group = _get_group(cavp_data, self.GROUP_ID)
        tv = group["tests"][idx]
        states = INTERMEDIATE_STATES[self.GROUP_ID][idx]
        _run_vector(CTR_DRBG, True, tv, states, group["returned_bits_len"])


class TestReferenceImplDFPerso:
    GROUP_ID = "aes256_df_perso"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_vector(self, cavp_data, idx):
        from reference_impl import CTR_DRBG
        group = _get_group(cavp_data, self.GROUP_ID)
        tv = group["tests"][idx]
        states = INTERMEDIATE_STATES[self.GROUP_ID][idx]
        _run_vector(CTR_DRBG, True, tv, states, group["returned_bits_len"])


class TestReferenceImplNoDFBasic:
    GROUP_ID = "aes256_nodf_basic"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_vector(self, cavp_data, idx):
        from reference_impl import CTR_DRBG
        group = _get_group(cavp_data, self.GROUP_ID)
        tv = group["tests"][idx]
        states = INTERMEDIATE_STATES[self.GROUP_ID][idx]
        _run_vector(CTR_DRBG, False, tv, states, group["returned_bits_len"])


class TestReferenceImplDFReseed:
    GROUP_ID = "aes256_df_reseed"

    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_vector(self, cavp_data, idx):
        from reference_impl import CTR_DRBG
        group = _get_group(cavp_data, self.GROUP_ID)
        tv = group["tests"][idx]
        states = INTERMEDIATE_STATES[self.GROUP_ID][idx]
        _run_vector(CTR_DRBG, True, tv, states, group["returned_bits_len"],
                    has_reseed=True)


# ===========================================================================
# Test Group 2: Reference implementation interface
# ===========================================================================

class TestReferenceInterface:
    def test_class_exists(self):
        from reference_impl import CTR_DRBG
        assert hasattr(CTR_DRBG, "__init__")

    def test_use_df_parameter(self):
        from reference_impl import CTR_DRBG
        drbg_df = CTR_DRBG(use_df=True)
        drbg_nodf = CTR_DRBG(use_df=False)
        assert drbg_df.use_df is True
        assert drbg_nodf.use_df is False

    def test_methods_exist(self):
        from reference_impl import CTR_DRBG
        drbg = CTR_DRBG()
        assert callable(getattr(drbg, "instantiate", None))
        assert callable(getattr(drbg, "generate", None))
        assert callable(getattr(drbg, "reseed", None))

    def test_state_attributes(self):
        from reference_impl import CTR_DRBG
        drbg = CTR_DRBG(use_df=True)
        entropy = bytes.fromhex(
            "36401940fa8b1fba91a1661f211d78a0"
            "b9389a74e5bccfece8d766af1a6d3b14"
        )
        nonce = bytes.fromhex("496f25b0f1301b4f501be30380a137eb")
        drbg.instantiate(entropy, nonce)
        assert isinstance(drbg.key, bytes) and len(drbg.key) == 32
        assert isinstance(drbg.v, bytes) and len(drbg.v) == 16


# ===========================================================================
# Test Group 3: Conformance report
# ===========================================================================

class TestConformanceReport:
    @pytest.fixture(scope="class")
    def report(self):
        with open("/app/conformance_report.json") as f:
            return json.load(f)

    def test_report_exists(self):
        assert os.path.isfile("/app/conformance_report.json")

    def test_has_all_implementations(self, report):
        assert "impl_A" in report
        assert "impl_B" in report
        assert "impl_C" in report

    def test_has_recommendation(self, report):
        assert "recommendation" in report
        assert report["recommendation"] == "impl_B"

    def test_impl_a_overall_fail(self, report):
        assert report["impl_A"]["overall_status"] == "fail"

    def test_impl_a_nodf_passes(self, report):
        configs = report["impl_A"]["configurations"]
        assert configs["nodf_basic"]["status"] == "pass"

    def test_impl_a_df_configs_fail(self, report):
        configs = report["impl_A"]["configurations"]
        for cfg in ["df_basic", "df_addl", "df_pers", "df_reseed"]:
            assert configs[cfg]["status"] == "fail", (
                f"impl_A {cfg} should fail"
            )

    def test_impl_b_overall_fail(self, report):
        assert report["impl_B"]["overall_status"] == "fail"

    def test_impl_b_non_reseed_pass(self, report):
        configs = report["impl_B"]["configurations"]
        for cfg in ["df_basic", "df_addl", "df_pers", "nodf_basic"]:
            assert configs[cfg]["status"] == "pass", (
                f"impl_B {cfg} should pass"
            )

    def test_impl_b_reseed_fails(self, report):
        configs = report["impl_B"]["configurations"]
        assert configs["df_reseed"]["status"] == "fail"

    def test_impl_c_overall_fail(self, report):
        assert report["impl_C"]["overall_status"] == "fail"

    def test_impl_c_all_fail(self, report):
        configs = report["impl_C"]["configurations"]
        for cfg in ["df_basic", "df_addl", "df_pers", "nodf_basic", "df_reseed"]:
            assert configs[cfg]["status"] == "fail", (
                f"impl_C {cfg} should fail"
            )

    def test_defects_present(self, report):
        for impl_name in ["impl_A", "impl_B", "impl_C"]:
            defects = report[impl_name]["defects"]
            assert len(defects) >= 1, (
                f"{impl_name} should have at least 1 defect"
            )
            for d in defects:
                assert "component" in d
                assert "description" in d

    def test_bcc_verifications_present(self, report):
        found_any = False
        for impl_name in ["impl_A", "impl_B", "impl_C"]:
            bcc = report[impl_name].get("bcc_verifications", [])
            if len(bcc) >= 1:
                found_any = True
                for sample in bcc:
                    assert "key_hex" in sample
                    assert "match" in sample
        assert found_any, "At least one implementation must have BCC verifications"

    def test_vector_counts(self, report):
        for impl_name in ["impl_A", "impl_B", "impl_C"]:
            configs = report[impl_name]["configurations"]
            for cfg_id, cfg_data in configs.items():
                assert "vectors_passed" in cfg_data
                assert "vectors_total" in cfg_data
                assert cfg_data["vectors_total"] > 0


# ===========================================================================
# Test Group 4: CAVS parser
# ===========================================================================

class TestCavsParser:
    def test_module_exists(self):
        assert os.path.isfile("/app/cavs_parser.py")

    def test_parse_returns_groups(self):
        from cavs_parser import parse_cavs_file
        groups = parse_cavs_file("/app/cavs_raw/CTR_DRBG_AES256.txt")
        assert isinstance(groups, list)
        assert len(groups) == 5, f"Expected 5 test groups, got {len(groups)}"

    def test_groups_have_vectors(self):
        from cavs_parser import parse_cavs_file
        groups = parse_cavs_file("/app/cavs_raw/CTR_DRBG_AES256.txt")
        for i, group in enumerate(groups):
            vecs = group.get("vectors", group.get("tests", []))
            assert len(vecs) >= 3, (
                f"Group {i} should have at least 3 vectors, got {len(vecs)}"
            )

    def test_intermediate_states_extracted(self):
        from cavs_parser import parse_cavs_file
        groups = parse_cavs_file("/app/cavs_raw/CTR_DRBG_AES256.txt")
        first_group = groups[0]
        data_str = json.dumps(first_group)
        expected_key = "3363d9000e6db47c16d3fc65f2872c08a35f99b2d174afa537a66ec153052d98"
        assert expected_key in data_str, (
            "Parser must extract intermediate Key values from ** INSTANTIATE blocks"
        )


# ===========================================================================
# Test Group 5: Harness module
# ===========================================================================

class TestHarness:
    def test_module_exists(self):
        assert os.path.isfile("/app/harness.py")

    def test_evaluate_function_exists(self):
        spec = importlib.util.spec_from_file_location("harness", "/app/harness.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "evaluate_implementation")
        assert callable(mod.evaluate_implementation)
