
import json
import os
import glob
import pytest

RESPONSES_DIR = "/app/responses"


def load_responses_by_algorithm():
    """Load all response JSON files and index by algorithm."""
    results = {}
    files = glob.glob(os.path.join(RESPONSES_DIR, "*.json"))
    for fpath in files:
        with open(fpath) as f:
            data = json.load(f)
        alg = data.get("algorithm", "")
        results[alg] = data
    return results


@pytest.fixture(scope="module")
def responses():
    return load_responses_by_algorithm()


def find_test_case(data, tg_id, tc_id):
    """Find a specific test case by tgId and tcId in response data."""
    for group in data.get("testGroups", []):
        if group.get("tgId") == tg_id:
            for test in group.get("tests", []):
                if test.get("tcId") == tc_id:
                    return test
    return None


def find_test_group(data, tg_id):
    """Find a test group by tgId."""
    for group in data.get("testGroups", []):
        if group.get("tgId") == tg_id:
            return group
    return None


# ============================================================
# Response files existence
# ============================================================

class TestResponseFilesExist:
    def test_responses_directory_exists(self):
        assert os.path.isdir(RESPONSES_DIR), (
            f"Responses directory {RESPONSES_DIR} does not exist"
        )

    def test_at_least_three_response_files(self):
        files = glob.glob(os.path.join(RESPONSES_DIR, "*.json"))
        assert len(files) >= 3, (
            f"Expected at least 3 response files, found {len(files)}"
        )


# ============================================================
# SHA-256 AFT tests
# ============================================================

class TestSHA256AFT:
    """Verify SHA2-256 AFT responses against NIST ACVP expected results."""

    EXPECTED = {
        3: "FB3012839C4D7C7BD36F9BE7194BE7640CE01A7ADE0EC38F00E4CA19F2B318DC",
        6: "FDB5A26B088914D3E312441C13FD57D857297A5E631C93BB3B771A1726AFC1D6",
        7: "C8D7179E5479106102F180DDF452D53F23386C3524EEE99F0E7C0771A3896503",
    }

    def test_sha256_algorithm_present(self, responses):
        assert "SHA2-256" in responses, "No SHA2-256 response file found"

    def test_sha256_vsid(self, responses):
        data = responses["SHA2-256"]
        assert data.get("vsId") == 100

    @pytest.mark.parametrize("tc_id", [3, 6, 7])
    def test_sha256_digest(self, responses, tc_id):
        data = responses["SHA2-256"]
        tc = find_test_case(data, 1, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found"
        actual = tc.get("md", "").upper()
        assert actual == self.EXPECTED[tc_id], (
            f"SHA2-256 tcId={tc_id}: expected {self.EXPECTED[tc_id]}, got {actual}"
        )


# ============================================================
# SHA-256 MCT tests (alternate variant, 100 iterations)
# ============================================================

class TestSHA256MCT:
    """Verify SHA2-256 Monte Carlo Test results."""

    # Expected md values at specific indices in the 100-entry resultsArray
    EXPECTED_MCT = {
        0: "52FC09401E67596F86D751A97E0A4D2D7E8D774DAF326F00BA656B399F291FCC",
        1: "C3DEC68B4FCBE179708EFA53F0DD7AB2DD7A4DAB2C7E2687B0B728ACFF8AE70A",
        2: "6860F5D3E0BA4C342E1F44EF9ADFBAAB921632A23E82D36A67DFA04A154F6723",
        49: "38FF40789E841914114EA164BD13B22E7C654A8642FB3A7489BF6366FA2F86E8",
        97: "E284CEA523BC8FB07AA81BFB01262104979B4791469B7975006017F20F68BBB2",
        98: "A19802D0E666248E4F01CC3A1F15A8486DD4D38907A08ACA4AEA5C0993C53E3D",
        99: "98B66078E81E35ACAF3543CF2BF3D1F6EED843C592A6BAD2AE07204C2B2C5817",
    }

    def test_mct_group_present(self, responses):
        data = responses["SHA2-256"]
        tc = find_test_case(data, 2, 513)
        assert tc is not None, "MCT test case tcId=513 not found in tgId=2"

    def test_mct_results_array_length(self, responses):
        data = responses["SHA2-256"]
        tc = find_test_case(data, 2, 513)
        ra = tc.get("resultsArray", [])
        assert len(ra) == 100, (
            f"MCT resultsArray should have 100 entries, got {len(ra)}"
        )

    @pytest.mark.parametrize("idx", [0, 1, 2, 49, 97, 98, 99])
    def test_mct_result_at_index(self, responses, idx):
        data = responses["SHA2-256"]
        tc = find_test_case(data, 2, 513)
        ra = tc.get("resultsArray", [])
        assert idx < len(ra), f"resultsArray too short for index {idx}"
        actual = ra[idx].get("md", "").upper()
        expected = self.EXPECTED_MCT[idx]
        assert actual == expected, (
            f"MCT index {idx}: expected {expected}, got {actual}"
        )


# ============================================================
# CTR-DRBG tests (AES-256 with derivation function)
# ============================================================

class TestCTRDRBGPredResistance:
    """Verify ctrDRBG with predResistance=true, AES-256, derFunc=true."""

    EXPECTED_FULL = {
        31: "559C9DFBE0F67E3D0DAC34F3D414AD0B0FC27EFA821878DD9C07CB17026604886CF4A613CEA4CB1A7227BE429832D52AABF426E066F1F997B1F3257796A8F8992F3128DF7193B9C1CFF84C2CEBE3AA1E0F711F57EBF70BBF22FDC48B8A4CBCAB3BAD49380A30C05F277381C953D209064588A07C27E233760F6DA780B03908A3482FB9027217BF0CEDD20046F834DD4A4E3DEDCE747A2FB9B68FD803B19B38BC37E9CA95B3684B4479122AE26822C690F7AFCA40E16013C93AACE5B8D58B48875F57533AE631E7BA6F0AA9FDF5FACD8783EBD074BB81427A4E152AB3C26C5D41C3C80692D5019F4690BE73608866A3F41CED69CAFE48323B9AB0014BBF43E73D3F8B08B8D29CD40E58DE721DF924050439BCF67F0D61AE96765D118CD1A60E4B6E35CDB28A943123A30A50DBA510C5ED043979154BC4258213C9E63F24A0E92653A35849F5932321C0B7F6C0BC283FBCC8D66485C45B8EF5E92A3771853575DF1CC2ADB257DF4753460A97078D3DACB53F472DBDB67C0D059AEB416FC16A6BE678ADFFD904FC836033E70211E015AA31FD91116C2E9FC4DAAC9A72C1F5C063D50A700A484C5C70C26F645F541D4DD3C384AE0F427EF6E216C1D881DD3636505562EAA56C684548857A91167268DFAD06F276F0E19A6327F3E234837C281489186B2288F31089C7D765065F90CB958B39C7514A1584157EBDA60710B13C96967C",
        32: "2E30D9998DC33FCF447C60CDF327EAF47C362CD2E2D5E1F76F7C35E65F0325F4EEA5288D521BA061E39AAC87AC8F4A008F738E14090CBDCC044387EAB8CA4FA618650FA22D4EAF97CBBF6EA566027A4A5DF816301613A1919702D9B5C5C40D9FBD097EE1AB99C28211067F2B165D9C5C6427EE36E13AF42BDC68F67577E3DA29810B50BD861FC6195743793E2B829979EA88C3CE0DBBCAA7A1B06F0809F1A5F48198CBD09DB168F35EF6E0C09A3EDB69C2F834D930C583824AB352A35372BDEC9EEB80B451FDE94F55FE4EF0AF8FB1309873E6AF8C58334F733C0746B81264F2719B9D4EBB950D9F48CB5ECDE51B0CCB6225599C8899C8CF477FB1FDD58E86FD10F11BC2981E465B0C749BA00ABA9652C59AACF78302027EF39493183FFC4080533E56E9353B6F731D77DB97E70A68B4D3D54128CAB0889E10FD37F162B9692B59679867CBA2CAC8B3EAC2D90030C4780637103024F8515505B8E57E320E2DF019B45C6AF2972707B490376D7FF5D533BB2D44886FA3BB96BA525B3483371EB70835A904170D72A05203ED931C264A929270AA58EEEB07260FAE0860B97216BCFFE8CABD91DE72BF86505AA5B71427D185EF05D102AA5D130E21AE4E241D3A759E24FBBC586B9E5A1E81308B9D0CB01C8ED737327B10081BC1C194F2B1E1A09D92834BD67073FEF2676BCDE5540C9E90BC78FDB03AD6BF6DCB61A02D709C74EA",
        33: "5FFDAA27AABCE2B6C013EBFDF18F6FF71582571AC5FE256C39C35ACC6590779037F15DFA9855ABA8AE95F9EC96BC3BADD5558CC17A447F78C8950DC13150125965D639C85227A6ED9B2798C64122A6FB4F1EFC02AC57A1323758A462296E3C76D63CBC0CF91C80A728071552A4D16443F75CD650D9DE7BDDF87400C8AAA87B7DD8962BC9380771758986E3CE0A0E891A7802992E074113AD70DF73B4A3E3D6E966A5DFF2D505C476A7E83B786A86B02733725E7411024E4DCA2DF50AE0E2E4920F17BF5227AC4F6982CF6F46A2BFE2DFA54EF02550CA6173AB7F2376B6BCC2ADDD310CB440C6760E26033BBBDAF4D07585B2A21E65307E3BD5EAD8950F8F59799E82EFA6F8188FBD3599530489A7B3374C082BCD90E153125092E607C60ED22ADAF718C46A37E465E84582963F1806806E1D0A8669C918230642FC6ED2B6C872C75A4A77A2F050C6B8CB6A4B954158DCB86C65B64437CBDDB441AA7874B94877762FDCAA8F1B9FFB09741A1511B1DE6AC28771E1F692B3D1E417950A2ADD8664D1ABFCE48E0221DD6303DBD1904F5B7F95A26F6CAAC8B61E64B16136B20D9FFB66394CC66C47E1DB5E3B08681ADE3ED0ABBFBA42CC517D7C7B24D13E493DAE74C596DE8D8C7793222AE3C04D03339BD30B6FBAC41FCAC57AA5F43373388CADC33DCB161A143AC0DB4F9B91154EDE48A42F010FF14C3F31CAD436DA64AF819640",
    }

    def test_ctrdrbg_algorithm_present(self, responses):
        assert "ctrDRBG" in responses, "No ctrDRBG response file found"

    def test_ctrdrbg_vsid(self, responses):
        data = responses["ctrDRBG"]
        assert data.get("vsId") == 200

    @pytest.mark.parametrize("tc_id", [31, 32, 33])
    def test_ctrdrbg_pred_resistance_full(self, responses, tc_id):
        """Full exact match of returnedBits for prediction resistance cases."""
        data = responses["ctrDRBG"]
        tc = find_test_case(data, 1, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found in tgId=1"
        actual = tc.get("returnedBits", "").upper()
        expected = self.EXPECTED_FULL[tc_id]
        assert actual == expected, (
            f"ctrDRBG tcId={tc_id}: returnedBits mismatch\n"
            f"  expected starts: {expected[:60]}...\n"
            f"  actual starts:   {actual[:60]}..."
        )

    @pytest.mark.parametrize("tc_id", [31, 32, 33])
    def test_ctrdrbg_returned_bits_length(self, responses, tc_id):
        """Each returnedBits should be 4096 bits = 1024 hex chars."""
        data = responses["ctrDRBG"]
        tc = find_test_case(data, 1, tc_id)
        assert tc is not None
        rb = tc.get("returnedBits", "")
        assert len(rb) == 1024, (
            f"ctrDRBG tcId={tc_id}: expected 1024 hex chars, got {len(rb)}"
        )


class TestCTRDRBGReseed:
    """Verify ctrDRBG with predResistance=false, reSeed=true, AES-256, derFunc=true."""

    EXPECTED_FULL = {
        151: "818BFA17116B798DC94C4B0F669DE1C0ED1F21DEE4AAB171513C35914027B572452BCA79E306A8AF3181187C64AE779778835136CDF4D02EEC886277C051D34089DF6CEF8D146DE33468744D77DEDEA88FC519BCA02661005F4538E2293BD799BA06B942ACCDCE437FD9143C5A15508BFCA84DED00B91F1812EE84C2DAD3BAB0C2FBFE25BAAE1A25CC93DBA1A76C1E2782BF3014BEBEE63A3C1CE0A6A2BC8EC059627F90AC67A561007F589A6E9D1BA4F62C95B217ED2F44E60DCEE7BDB886E0929B32757A7BB2B3CE044D3A7883CD3372D67870D16BE26A5B486146C09004B99FAEDF2799A42FB345CA9D93A3A3C8E80C4F792876DEDC9D9AA50DD96B691C0B4B1C9AF7AA16FF7CFAA8D7BB65F1D0E3F786B5B8C5EA9230733CE058A55E38BF47444C51B13A662E7866E5540B6CCCE679E52D883D23B0A67A10D5672BF81FC2C66E018B9A9E409DF3A18C5451C4442338037E0D5617C0BF1D775FCC9FAA770D42C6DAD019E4617D6A47F109F2B6CE14C3439186B1A4811188CFFA7EC139E349DC37A434636AB645668743DC86FF2EF29306A1CD5A9F6DEEE6DA13A391760FEE3691557BD5A4BFEE30EEB53033F04FE565B797504FD1259AB2BAC61E09D689D468EF37223FBAE411DBC99A5A6C1507464D4F1DEDBA7989EFEA41DC8B985EEFF219514698FB040A8399ED810A239BE4E36775E0373AF7FF28EA2882856F614381",
        152: "B4D52D1B4298D212B80ED1F434BEFDA98544A655087002338AD9E135DB064DB531257E26A78C8B4C6ECE8A229F50E81491DCE5133D4FF643FF045A30F8E56D4F6B412BD605A30FBDF73E9236B0DF9A3F435407187D046C9A36D0C8EA157451E47D14636F6BD17C3FDA6E69F48B82D1A6EDA97CDD2BB90F3F96E79BA321E30DB68CE1699170B57169F49B20D9A4DD2F1AEFE1E6ABA6B4A7B2C5E42A922DBEBBC696D63043BC0CBA9271F0806BFF8CE8FD4A503D7A2DD6161055879E864A984AFE1CC7D2C091D84A69E60B7DA3CD686E433371B2A16AFADAF2AAFDABE717A1719337AE0062BC05166B4E645F699F253EF92075DA4886FA69A8C4C6447B37FBB1DEA3FAF48B0152AB3FA63E6555BCF49FDC0563BA678ACC16FA23FF8813B062A7DD28A72CBFDD11D7ADB76925A078F1E36FE09BDCCB19D4E4240D8139A9D9D54B4C8A4F12B58B8B8D818D7A08ED8CEE5836AFE4C988D630716612251983F521C9DAAE641AEC3486AA767AA8319168BFD5D9EBE549EC0C5250AA60EDE4437F4BFEB683D57D66A35B1E81D84B9C090EAF122BC28F7EEBC5D7D14870572819A65AC5016DD0EF551E07E70DCB42282B9E7FB762A8E5E9B609F09D697E2CDA27B9A8762A26D13D3B959354D4CD195F6529DE5AD5358FE1FC0F98C274AB4535B60922BF0B56E6CC4CFBE74441CA1F3FE0F5C8C536C5B63C92A3D1B02EAB7C72FF16ACB11E",
    }

    @pytest.mark.parametrize("tc_id", [151, 152])
    def test_ctrdrbg_reseed_full(self, responses, tc_id):
        """Full exact match of returnedBits for explicit reseed cases."""
        data = responses["ctrDRBG"]
        tc = find_test_case(data, 2, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found in tgId=2"
        actual = tc.get("returnedBits", "").upper()
        expected = self.EXPECTED_FULL[tc_id]
        assert actual == expected, (
            f"ctrDRBG tcId={tc_id}: returnedBits mismatch\n"
            f"  expected starts: {expected[:60]}...\n"
            f"  actual starts:   {actual[:60]}..."
        )


# ============================================================
# AES-GCM Encrypt tests
# ============================================================

class TestAESGCMEncrypt:
    """Verify AES-GCM encrypt responses against NIST ACVP expected results."""

    # tgId 1: encrypt, empty payload, tagLen=128
    EXPECTED_TG1 = {
        1: {"ct": "", "tag": "9E557D92647C1510D4101EBEED0C52DD"},
        2: {"ct": "", "tag": "6A7BBCDB4834109B6AA067B5358D94F3"},
        3: {"ct": "", "tag": "72445E31C5DF05DFA2CCBA54AE385DFD"},
    }

    # tgId 2: encrypt, 120-bit payload, tagLen=32, ivLen=120
    EXPECTED_TG2 = {
        4: {"ct": "E8F5854061720508EA3FBCCEB78F4F", "tag": "8AD3515A"},
        5: {"ct": "FFFDB44464A139F960BB98537970BD", "tag": "9BD5F0F7"},
    }

    def test_aes_gcm_algorithm_present(self, responses):
        assert "ACVP-AES-GCM" in responses, "No ACVP-AES-GCM response file found"

    @pytest.mark.parametrize("tc_id", [1, 2, 3])
    def test_aes_gcm_encrypt_empty_payload(self, responses, tc_id):
        data = responses["ACVP-AES-GCM"]
        tc = find_test_case(data, 1, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found in tgId=1"
        expected = self.EXPECTED_TG1[tc_id]
        assert tc.get("ct", "").upper() == expected["ct"], (
            f"AES-GCM encrypt tcId={tc_id}: ct mismatch"
        )
        assert tc.get("tag", "").upper() == expected["tag"], (
            f"AES-GCM encrypt tcId={tc_id}: tag mismatch, "
            f"expected {expected['tag']}, got {tc.get('tag', '')}"
        )

    @pytest.mark.parametrize("tc_id", [4, 5])
    def test_aes_gcm_encrypt_with_payload(self, responses, tc_id):
        data = responses["ACVP-AES-GCM"]
        tc = find_test_case(data, 2, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found in tgId=2"
        expected = self.EXPECTED_TG2[tc_id]
        assert tc.get("ct", "").upper() == expected["ct"], (
            f"AES-GCM encrypt tcId={tc_id}: ct mismatch"
        )
        assert tc.get("tag", "").upper() == expected["tag"], (
            f"AES-GCM encrypt tcId={tc_id}: tag mismatch (32-bit tag)"
        )


# ============================================================
# AES-GCM Decrypt tests
# ============================================================

class TestAESGCMDecrypt:
    """Verify AES-GCM decrypt responses against NIST ACVP expected results."""

    # tgId 3: decrypt, empty payload, tagLen=128
    EXPECTED_TG3 = {
        6: {"pass": True, "pt": ""},
        7: {"pass": False},
        8: {"pass": False},
        9: {"pass": True, "pt": ""},
    }

    # tgId 4: decrypt, 120-bit payload, tagLen=32, ivLen=120
    EXPECTED_TG4 = {
        10: {"pass": True, "pt": "A840015C977767637E951EE79F060F"},
        11: {"pass": False},
        12: {"pass": True, "pt": "1E8BAAFB94BC02C2DED10563ADADAC"},
    }

    @pytest.mark.parametrize("tc_id", [6, 7, 8, 9])
    def test_aes_gcm_decrypt_empty_payload(self, responses, tc_id):
        data = responses["ACVP-AES-GCM"]
        tc = find_test_case(data, 3, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found in tgId=3"
        expected = self.EXPECTED_TG3[tc_id]

        if expected["pass"]:
            assert "pt" in tc, (
                f"AES-GCM decrypt tcId={tc_id}: expected pt field"
            )
            assert tc["pt"].upper() == expected["pt"]
            assert "testPassed" not in tc or tc["testPassed"] is not False
        else:
            assert tc.get("testPassed") is False, (
                f"AES-GCM decrypt tcId={tc_id}: expected testPassed=false, got {tc}"
            )

    @pytest.mark.parametrize("tc_id", [10, 11, 12])
    def test_aes_gcm_decrypt_with_payload(self, responses, tc_id):
        data = responses["ACVP-AES-GCM"]
        tc = find_test_case(data, 4, tc_id)
        assert tc is not None, f"Test case tcId={tc_id} not found in tgId=4"
        expected = self.EXPECTED_TG4[tc_id]

        if expected["pass"]:
            assert "pt" in tc, (
                f"AES-GCM decrypt tcId={tc_id}: expected pt field, got {tc}"
            )
            assert tc["pt"].upper() == expected["pt"]
        else:
            assert tc.get("testPassed") is False, (
                f"AES-GCM decrypt tcId={tc_id}: expected testPassed=false, got {tc}"
            )


# ============================================================
# Response structure compliance
# ============================================================

class TestResponseStructure:
    """Verify ACVP response JSON structure compliance."""

    @pytest.mark.parametrize("algorithm", [
        "SHA2-256", "ctrDRBG", "ACVP-AES-GCM"
    ])
    def test_response_has_required_fields(self, responses, algorithm):
        assert algorithm in responses, f"No response for {algorithm}"
        data = responses[algorithm]
        assert "vsId" in data, f"{algorithm}: missing vsId"
        assert "algorithm" in data, f"{algorithm}: missing algorithm"
        assert "testGroups" in data, f"{algorithm}: missing testGroups"
        assert isinstance(data["testGroups"], list)

    @pytest.mark.parametrize("algorithm", [
        "SHA2-256", "ctrDRBG", "ACVP-AES-GCM"
    ])
    def test_test_groups_have_tgid(self, responses, algorithm):
        data = responses[algorithm]
        for group in data["testGroups"]:
            assert "tgId" in group, f"{algorithm}: test group missing tgId"
            assert "tests" in group, f"{algorithm}: test group missing tests"

    @pytest.mark.parametrize("algorithm", [
        "SHA2-256", "ctrDRBG", "ACVP-AES-GCM"
    ])
    def test_test_cases_have_tcid(self, responses, algorithm):
        data = responses[algorithm]
        for group in data["testGroups"]:
            for test in group["tests"]:
                assert "tcId" in test, (
                    f"{algorithm} tgId={group['tgId']}: test case missing tcId"
                )
