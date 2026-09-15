
"""
Tests for ACVP conformance audit task.

Verifies:
1. Audit report correctly identifies failing test groups per vendor
2. Audit report correctly classifies each bug
3. Reference AES-CBC results match independently computed values
4. Reference SHA2-256 results match independently computed values
"""

import json
import hashlib
import os
import pytest
from Crypto.Cipher import AES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path) as f:
        return json.load(f)


def get_result_tg(result_data, tg_id):
    for tg in result_data["testGroups"]:
        if tg["tgId"] == tg_id:
            return tg
    return None


def get_result_tc(tg, tc_id):
    for tc in tg["tests"]:
        if tc["tcId"] == tc_id:
            return tc
    return None


def aes_cbc_encrypt(key_bytes, iv_bytes, pt_bytes):
    return AES.new(key_bytes, AES.MODE_CBC, iv=iv_bytes).encrypt(pt_bytes)


def aes_cbc_decrypt(key_bytes, iv_bytes, ct_bytes):
    return AES.new(key_bytes, AES.MODE_CBC, iv=iv_bytes).decrypt(ct_bytes)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

AUDIT_PATH = "/app/audit_report.json"
AES_PROMPT_PATH = "/app/prompts/aes_cbc_prompt.json"
SHA_PROMPT_PATH = "/app/prompts/sha256_prompt.json"
AES_RESULT_PATH = "/app/results/aes_cbc_results.json"
SHA_RESULT_PATH = "/app/results/sha256_results.json"


# ---------------------------------------------------------------------------
# Expected audit findings
# ---------------------------------------------------------------------------

EXPECTED_AUDIT = {
    "vendor_alpha": {
        "aes_cbc_failing_groups": [38, 41],
        "sha256_failing_groups": [3],
        "bugs": [
            {"affected_algorithm": "AES-CBC", "affected_groups": [38, 41],
             "category": "key_schedule"},
            {"affected_algorithm": "SHA2-256", "affected_groups": [3],
             "category": "ldt_expansion"},
        ],
    },
    "vendor_beta": {
        "aes_cbc_failing_groups": [40, 41, 42],
        "sha256_failing_groups": [2],
        "bugs": [
            {"affected_algorithm": "AES-CBC", "affected_groups": [40, 41, 42],
             "category": "cbc_chain"},
            {"affected_algorithm": "SHA2-256", "affected_groups": [2],
             "category": "mct_algorithm"},
        ],
    },
    "vendor_gamma": {
        "aes_cbc_failing_groups": [39, 42],
        "sha256_failing_groups": [2],
        "bugs": [
            {"affected_algorithm": "AES-CBC", "affected_groups": [39, 42],
             "category": "key_schedule"},
            {"affected_algorithm": "SHA2-256", "affected_groups": [2],
             "category": "mct_state"},
        ],
    },
}


# ---------------------------------------------------------------------------
# AES-CBC MCT checkpoints (correct reference values)
# ---------------------------------------------------------------------------

AES_MCT_CHECKPOINTS = {
    37: {
        "direction": "encrypt", "keyLen": 128,
        0: {"key": "7458F5390D2217BBCC0FD1F93B347D90", "iv": "6392E67EE5616EE1DE96136FF13D25E5",
            "pt": "23AAAA65533958751809211DF108CDF4", "ct": "AC0EA69C1576014789B2F7F9BAF38DA3"},
        1: {"key": "D85653A5185416FC45BD260081C7F033", "iv": "AC0EA69C1576014789B2F7F9BAF38DA3",
            "pt": "954F3A4992290F0345C2239258E4EE70", "ct": "8FB554F1CE95CC4F8170D035A78CC920"},
        49: {"key": "758B49EDFB915841CD2869174E063FBD", "iv": "17EB4B585ED4DD2211012852EEC615BA",
             "pt": "9BC3F4EB99B81047BD2B9E4BDF87C2CB", "ct": "8868CC92CCAE9E6EA267110BCDA28759"},
        99: {"key": "8B77F56EC5D083C1F7B78D1984D1B451", "iv": "363F8F55108FB099C80CE3853A95B14C",
             "pt": "479978F87B257ECFCB27EAACDBDD16C8", "ct": "5BCDB0C8FCB257D9E189A02403C0F39B"},
    },
    38: {
        "direction": "encrypt", "keyLen": 192,
        0: {"key": "DA3103EA1F089EB9E68CBF255306AE220E3CE0499CD83D01", "iv": "856C5428B2F1B5A6A384034E62E9C03D",
            "pt": "D47F7F295854B461A64EF9098C0A9F66", "ct": "01E7EBFB4F4265F0546522A2B6AC6ADD"},
        1: {"key": "8F063ECF70B10C74E76B54DE1C44CBD25A59C2EB2A7457DC", "iv": "01E7EBFB4F4265F0546522A2B6AC6ADD",
            "pt": "DDB14F1B78FD43B355373D256FB992CD", "ct": "C9BA448002725915BB5EC28F37A3E4A2"},
        49: {"key": "71F39FBC24A2A67491908167723568BF3BB64D3597F6FA89", "iv": "16F46B6BD50D43E7E4D99B9756A125E1",
             "pt": "2A7BECB6BCC87F358970EBC9559AA255", "ct": "1C5E6AD086CDA23A7D7037E965389F34"},
        99: {"key": "36E7A606B47E724479F43A494CC3123F93635F1C6A6FF009", "iv": "AC967ED9C4C8A4B95628391C106CA983",
             "pt": "0440D31CBBF57EC53594A5ABDE0F114C", "ct": "F19601359504A624D966446D1648EF74"},
    },
    39: {
        "direction": "encrypt", "keyLen": 256,
        0: {"key": "E5DF90DD32331AED1BF07FF2C3C3BF84D44E2A708A5A56E67CB4B96D406EC500", "iv": "92B2AD6F2DF185C190F55278B8E4E090",
            "pt": "80DEFCFE05363CBD2338C983D802764A", "ct": "B80FFE1C975ADF06CBA97EF5CA24B30E"},
        1: {"key": "D0BF3AF0C2DEB9984A05FF74D1B577BD6C41D46C1D0089E0B71DC7988A4A760E", "iv": "B80FFE1C975ADF06CBA97EF5CA24B30E",
            "pt": "3560AA2DF0EDA37551F580861276C839", "ct": "ED35278BAA057E26CDFFEF66D79AE909"},
        49: {"key": "79EF492524364B7884A0CA52CDFC77D306293FA96A3EE82AECDC602F6D7975A3", "iv": "27171A06105FAAC6B73F1C38708C17DF",
             "pt": "FDE3A6038B5D2622038EA432BE5FB447", "ct": "48AD3C4D7E63D0C9023EE21CA6E2A37C"},
        99: {"key": "955784969C3D3CD00C767BCB4866D80DCA1E2BF969712FCB803AA9A185CF52CC", "iv": "82575308C8872707F9302CA579C0AAD2",
             "pt": "2C668B09AC780B5A42697331D8E4C437", "ct": "6051B534746550CF04E6A5358D1EE638"},
    },
    40: {
        "direction": "decrypt", "keyLen": 128,
        0: {"key": "94B1361992AC20DF6A3EA4A89DE651FD", "iv": "6569A905E10F888F521288C46C5F30AB",
            "pt": "9CAF3972B367B21C35A6A576ACC83B24", "ct": "F45396384730EC31FC9B284321C3A189"},
        1: {"key": "081E0F6B21CB92C35F9801DE312E6AD9", "iv": "9CAF3972B367B21C35A6A576ACC83B24",
            "pt": "3ED24B6CB3E485E62D7C3E5C47108BF7", "ct": "3C522D932829955B367D763BF8F06615"},
        49: {"key": "38DCE04D832D51ED63A825C64FAB3D43", "iv": "3EBE63FB228C43266EEEB8DAE1384637",
             "pt": "54DA8E360CFBBEE5E1E33B1B744BC840", "ct": "FF93F20D662B3A65DE4F10E4B0453D8A"},
        99: {"key": "0B3182614D5ED0290091323284FBE958", "iv": "EB004E04171179B60F4838A2E65FA868",
             "pt": "C3DD5609B254F28B0657D4C98AFD605F", "ct": "123845F7F991F71CCBB9C3B9507BA21A"},
    },
    41: {
        "direction": "decrypt", "keyLen": 192,
        0: {"key": "853843CF85FA46B735655C941F0E933F7430E737079C9C3A", "iv": "B02E620C68A614A586D7EF466B097960",
            "pt": "2C3F873E8B29AEE28CABEA338B2E7A29", "ct": "FBE3087B22425862E5D0255B6D669497"},
        1: {"key": "504F284869CA417C195ADBAA94273DDDF89B0D048CB2E613", "iv": "2C3F873E8B29AEE28CABEA338B2E7A29",
            "pt": "C3A0DE1E6B6E9F9711AD9437239F230A", "ct": "DBC4EF7F6E9092B7D5776B87EC3007CB"},
        49: {"key": "E9CD44C56813B079A0FA0FCF46CE205B00628AFF29A4EFDC", "iv": "252AD7815BF3A530FC0E37EB7435DC9D",
             "pt": "258CCF912D21A0F84CA9052CC2896E0F", "ct": "D1C6EFCB6F78C5D1A08E952389A66285"},
        99: {"key": "B799ED98FE1965827820616452D7C54ABAC10196E11858F0", "iv": "118461A4EC984A1F4C436BE2C4E30AC1",
             "pt": "535306F3423258F9084665686827C3A2", "ct": "DE1C13EAA51AA206AAC525EAE3FBE88A"},
    },
    42: {
        "direction": "decrypt", "keyLen": 256,
        0: {"key": "3A90F4BF6E53ABE77CB2AF79295C7EB1542CB029AC7891C93EED7D033B301355", "iv": "B5F100EFF2892522AE5BA3174B668CD3",
            "pt": "2858891221787270B39A3302A5FB9F14", "ct": "C722660ABCF392651AAC67845363102B"},
        1: {"key": "14AAD7E92E32C398C57109795E1CA4207C74393B8D00E3B98D774E019ECB8C41", "iv": "2858891221787270B39A3302A5FB9F14",
            "pt": "F987AC099DB184CFEF41D20D3107DC00", "ct": "2E3A23564061687FB9C3A6007740DA91"},
        49: {"key": "895051579705F8E9676C50D4C1A96633F5BD350F4D212E81AB15B52B6B10D955", "iv": "AD0EB5EBB49A07FD3E318BE9926A587B",
             "pt": "CC9C772D5E7AA5F1868E731DEF519256", "ct": "5F25562E516FF546370B489F33B80C3C"},
        99: {"key": "F22C753D5D1E5BBBEAAA5E310E3AFCF02DB7A10C0D20D6364474D28554726AB0", "iv": "071BCC62F7449E8F206600F615E7B5B2",
             "pt": "526FCD5A8C3C81233721389C3D9D57CA", "ct": "4F3A60D730C64E8A8742C757F55E7962"},
    },
}

SHA_MCT_CHECKPOINTS = {
    0: "52FC09401E67596F86D751A97E0A4D2D7E8D774DAF326F00BA656B399F291FCC",
    1: "C3DEC68B4FCBE179708EFA53F0DD7AB2DD7A4DAB2C7E2687B0B728ACFF8AE70A",
    49: "38FF40789E841914114EA164BD13B22E7C654A8642FB3A7489BF6366FA2F86E8",
    99: "98B66078E81E35ACAF3543CF2BF3D1F6EED843C592A6BAD2AE07204C2B2C5817",
}

SHA_LDT_EXPECTED = {
    514: "171CBE0FEF605AE836E05A778CDE031E8D475D2F117D121065543ABC89CC76B7",
    515: "1A6A5F72B80A7527EF0A255C7CD5A7E7E63BA04D27C1B9C13A05234AD718E05B",
    516: "1876CD0B75219A81E50F709ABBA8F706F248CD7F872B2B4E4B44252692A97FF9",
    517: "1511CE1866CA94C09DF12DD61B77591CCCDCB0DCC8051AD634AE80BF0360B4D1",
}


# ===========================================================================
# Audit report tests
# ===========================================================================

class TestAuditReportStructure:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.report = load_json(AUDIT_PATH)

    def test_report_exists(self):
        assert os.path.exists(AUDIT_PATH), "audit_report.json not found"

    def test_has_all_vendors(self):
        for v in ["vendor_alpha", "vendor_beta", "vendor_gamma"]:
            assert v in self.report, f"Missing vendor entry: {v}"

    def test_each_vendor_has_required_fields(self):
        for v in ["vendor_alpha", "vendor_beta", "vendor_gamma"]:
            vd = self.report[v]
            assert "aes_cbc_failing_groups" in vd, f"{v}: missing aes_cbc_failing_groups"
            assert "sha256_failing_groups" in vd, f"{v}: missing sha256_failing_groups"
            assert "bugs" in vd, f"{v}: missing bugs"
            assert len(vd["bugs"]) == 2, f"{v}: expected 2 bugs, got {len(vd['bugs'])}"


class TestAuditFailingGroups:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.report = load_json(AUDIT_PATH)

    @pytest.mark.parametrize("vendor", ["vendor_alpha", "vendor_beta", "vendor_gamma"])
    def test_aes_failing_groups(self, vendor):
        actual = sorted(self.report[vendor]["aes_cbc_failing_groups"])
        expected = sorted(EXPECTED_AUDIT[vendor]["aes_cbc_failing_groups"])
        assert actual == expected, \
            f"{vendor} AES failing groups: expected {expected}, got {actual}"

    @pytest.mark.parametrize("vendor", ["vendor_alpha", "vendor_beta", "vendor_gamma"])
    def test_sha_failing_groups(self, vendor):
        actual = sorted(self.report[vendor]["sha256_failing_groups"])
        expected = sorted(EXPECTED_AUDIT[vendor]["sha256_failing_groups"])
        assert actual == expected, \
            f"{vendor} SHA failing groups: expected {expected}, got {actual}"


class TestAuditBugClassification:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.report = load_json(AUDIT_PATH)

    def _find_bug(self, vendor, algorithm):
        bugs = self.report[vendor]["bugs"]
        for b in bugs:
            if b["affected_algorithm"] == algorithm:
                return b
        return None

    @pytest.mark.parametrize("vendor,algo,expected_groups,expected_cat", [
        ("vendor_alpha", "AES-CBC", [38, 41], "key_schedule"),
        ("vendor_alpha", "SHA2-256", [3], "ldt_expansion"),
        ("vendor_beta", "AES-CBC", [40, 41, 42], "cbc_chain"),
        ("vendor_beta", "SHA2-256", [2], "mct_algorithm"),
        ("vendor_gamma", "AES-CBC", [39, 42], "key_schedule"),
        ("vendor_gamma", "SHA2-256", [2], "mct_state"),
    ])
    def test_bug_classification(self, vendor, algo, expected_groups, expected_cat):
        bug = self._find_bug(vendor, algo)
        assert bug is not None, f"{vendor}: no bug for {algo}"
        assert bug["category"] == expected_cat, \
            f"{vendor} {algo}: expected category '{expected_cat}', got '{bug['category']}'"
        assert sorted(bug["affected_groups"]) == sorted(expected_groups), \
            f"{vendor} {algo}: expected groups {expected_groups}, got {bug['affected_groups']}"


# ===========================================================================
# Reference AES-CBC structure tests
# ===========================================================================

class TestAesCbcStructure:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.result = load_json(AES_RESULT_PATH)
        self.prompt = load_json(AES_PROMPT_PATH)

    def test_output_file_exists(self):
        assert os.path.exists(AES_RESULT_PATH)

    def test_top_level_fields(self):
        assert self.result["vsId"] == 42
        assert self.result["algorithm"] == "ACVP-AES-CBC"
        assert self.result["revision"] == "1.0"

    def test_correct_number_of_test_groups(self):
        assert len(self.result["testGroups"]) == 42

    def test_each_group_has_correct_test_count(self):
        for ptg in self.prompt["testGroups"]:
            rtg = get_result_tg(self.result, ptg["tgId"])
            assert rtg is not None, f"Missing tgId={ptg['tgId']}"
            assert len(rtg["tests"]) == len(ptg["tests"]), \
                f"tgId={ptg['tgId']}: expected {len(ptg['tests'])} tests"


# ===========================================================================
# Reference AES-CBC AFT tests (independently recomputed)
# ===========================================================================

class TestAesCbcAft:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.result = load_json(AES_RESULT_PATH)
        self.prompt = load_json(AES_PROMPT_PATH)

    def test_all_aft_encrypt_results(self):
        errors = []
        for ptg in self.prompt["testGroups"]:
            if ptg["testType"] != "AFT" or ptg["direction"] != "encrypt":
                continue
            rtg = get_result_tg(self.result, ptg["tgId"])
            assert rtg is not None
            for pt_tc in ptg["tests"]:
                key = bytes.fromhex(pt_tc["key"])
                iv = bytes.fromhex(pt_tc["iv"])
                pt = bytes.fromhex(pt_tc["pt"])
                expected_ct = aes_cbc_encrypt(key, iv, pt).hex().upper()
                rt = get_result_tc(rtg, pt_tc["tcId"])
                if rt is None:
                    errors.append(f"tgId={ptg['tgId']}, tcId={pt_tc['tcId']}: missing")
                elif rt.get("ct", "").upper() != expected_ct:
                    errors.append(f"tgId={ptg['tgId']}, tcId={pt_tc['tcId']}: wrong ct")
        assert not errors, f"AFT encrypt failures ({len(errors)}):\n" + "\n".join(errors[:10])

    def test_all_aft_decrypt_results(self):
        errors = []
        for ptg in self.prompt["testGroups"]:
            if ptg["testType"] != "AFT" or ptg["direction"] != "decrypt":
                continue
            rtg = get_result_tg(self.result, ptg["tgId"])
            assert rtg is not None
            for pt_tc in ptg["tests"]:
                key = bytes.fromhex(pt_tc["key"])
                iv = bytes.fromhex(pt_tc["iv"])
                ct = bytes.fromhex(pt_tc["ct"])
                expected_pt = aes_cbc_decrypt(key, iv, ct).hex().upper()
                rt = get_result_tc(rtg, pt_tc["tcId"])
                if rt is None:
                    errors.append(f"tgId={ptg['tgId']}, tcId={pt_tc['tcId']}: missing")
                elif rt.get("pt", "").upper() != expected_pt:
                    errors.append(f"tgId={ptg['tgId']}, tcId={pt_tc['tcId']}: wrong pt")
        assert not errors, f"AFT decrypt failures ({len(errors)}):\n" + "\n".join(errors[:10])


# ===========================================================================
# Reference AES-CBC MCT checkpoint tests
# ===========================================================================

class TestAesCbcMct:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.result = load_json(AES_RESULT_PATH)

    @pytest.mark.parametrize("tg_id", [37, 38, 39, 40, 41, 42])
    def test_mct_checkpoints(self, tg_id):
        rtg = get_result_tg(self.result, tg_id)
        assert rtg is not None, f"Missing tgId={tg_id}"
        assert len(rtg["tests"]) == 1
        ra = rtg["tests"][0].get("resultsArray")
        assert ra is not None
        assert len(ra) == 100, f"tgId={tg_id}: expected 100 results, got {len(ra)}"
        checkpoints = AES_MCT_CHECKPOINTS[tg_id]
        for idx in [0, 1, 49, 99]:
            expected = checkpoints[idx]
            actual = ra[idx]
            for field in ["key", "iv", "pt", "ct"]:
                exp_val = expected[field].upper()
                act_val = actual.get(field, "").upper()
                assert act_val == exp_val, \
                    f"MCT tgId={tg_id} idx={idx} {field}: expected {exp_val}, got {act_val}"


# ===========================================================================
# Reference SHA2-256 AFT tests (independently recomputed)
# ===========================================================================

class TestSha256Aft:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.result = load_json(SHA_RESULT_PATH)
        self.prompt = load_json(SHA_PROMPT_PATH)

    def test_all_aft_results(self):
        errors = []
        for ptg in self.prompt["testGroups"]:
            if ptg["testType"] != "AFT":
                continue
            rtg = get_result_tg(self.result, ptg["tgId"])
            assert rtg is not None
            for pt_tc in ptg["tests"]:
                msg_len = pt_tc["len"]
                if msg_len == 0:
                    mb = b""
                else:
                    mb = bytes.fromhex(pt_tc["msg"])[:msg_len // 8]
                expected_md = hashlib.sha256(mb).hexdigest().upper()
                rt = get_result_tc(rtg, pt_tc["tcId"])
                if rt is None:
                    errors.append(f"tcId={pt_tc['tcId']}: missing")
                elif rt.get("md", "").upper() != expected_md:
                    errors.append(f"tcId={pt_tc['tcId']}: wrong md")
        assert not errors, f"SHA AFT failures ({len(errors)}):\n" + "\n".join(errors[:10])


# ===========================================================================
# Reference SHA2-256 MCT checkpoint tests
# ===========================================================================

class TestSha256Mct:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.result = load_json(SHA_RESULT_PATH)

    def test_mct_structure(self):
        rtg = get_result_tg(self.result, 2)
        assert rtg is not None
        assert len(rtg["tests"]) == 1
        ra = rtg["tests"][0].get("resultsArray")
        assert ra is not None
        assert len(ra) == 100

    @pytest.mark.parametrize("idx", [0, 1, 49, 99])
    def test_mct_checkpoint(self, idx):
        rtg = get_result_tg(self.result, 2)
        ra = rtg["tests"][0]["resultsArray"]
        assert ra[idx].get("md", "").upper() == SHA_MCT_CHECKPOINTS[idx]


# ===========================================================================
# Reference SHA2-256 LDT tests
# ===========================================================================

class TestSha256Ldt:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.result = load_json(SHA_RESULT_PATH)

    @pytest.mark.parametrize("tc_id,expected_md", list(SHA_LDT_EXPECTED.items()))
    def test_ldt_result(self, tc_id, expected_md):
        rtg = get_result_tg(self.result, 3)
        assert rtg is not None
        rt = get_result_tc(rtg, tc_id)
        assert rt is not None, f"Missing LDT tcId={tc_id}"
        assert rt.get("md", "").upper() == expected_md
