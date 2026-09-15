
import json
import os
import pytest

RESPONSE_PATH = "/app/response.json"


@pytest.fixture(scope="module")
def response():
    assert os.path.exists(RESPONSE_PATH), f"Response file not found at {RESPONSE_PATH}"
    with open(RESPONSE_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def response_lookup(response):
    """Build a lookup: (tgId, tcId) -> test result dict"""
    lookup = {}
    for tg in response["testGroups"]:
        tg_id = tg["tgId"]
        for tc in tg["tests"]:
            tc_id = tc["tcId"]
            lookup[(tg_id, tc_id)] = tc
    return lookup


class TestResponseStructure:
    def test_top_level_fields(self, response):
        assert response["vsId"] == 42
        assert response["algorithm"] == "ACVP-AES-CBC"
        assert response["revision"] == "1.0"

    def test_has_all_test_groups(self, response):
        tg_ids = {tg["tgId"] for tg in response["testGroups"]}
        expected_ids = set(range(1, 19))
        assert tg_ids == expected_ids, f"Missing test groups: {expected_ids - tg_ids}"

    def test_aft_groups_have_correct_test_counts(self, response):
        expected_counts = {
            1: 8, 2: 10, 3: 6, 4: 8, 5: 6, 6: 8,
            7: 8, 8: 10, 9: 6, 10: 8, 11: 6, 12: 8,
        }
        for tg in response["testGroups"]:
            tg_id = tg["tgId"]
            if tg_id in expected_counts:
                assert len(tg["tests"]) == expected_counts[tg_id], (
                    f"tgId={tg_id}: expected {expected_counts[tg_id]} tests, "
                    f"got {len(tg['tests'])}"
                )

    def test_mct_groups_have_results_array(self, response):
        mct_group_ids = {13, 14, 15, 16, 17, 18}
        for tg in response["testGroups"]:
            if tg["tgId"] in mct_group_ids:
                assert len(tg["tests"]) == 1
                tc = tg["tests"][0]
                assert "resultsArray" in tc
                assert len(tc["resultsArray"]) == 100, (
                    f"tgId={tg['tgId']}: expected 100 MCT rounds, "
                    f"got {len(tc['resultsArray'])}"
                )


class TestAFTEncrypt:
    """Verify AFT encrypt results against reference values."""

    AFT_ENCRYPT_CASES = [
        # (tgId, tcId, expected_ct)
        # 128-bit key groups
        (1, 1, "FAFBC741B03C8EA27692F1368DECB097"),
        (1, 3, "DA04BCD08047ADFA52C558BAF3B88D53"),
        (1, 5, "5797DBB89554CA87AFCF9B89F2452850"),
        (1, 8, "DB732EACEFEFE0A87A357AB9021894CC"),
        (2, 9, "F06CEDF90715EC2FB5EAA2E641545325"),
        (2, 12, "E0EC9BFFE28F09D3F1417353A37C7A18"),
        (2, 15, "A5218A83CADA97DCC1F4E1C3BEA8F818"),
        (2, 18, "025D3D47E888766B35637B7B8DD5D0D2"),
        # 192-bit key groups
        (3, 19, "CB02AE839FC34CCA1A0993DEF27FC01E"),
        (3, 22, "90DC76FEEE458D428BEA32ED1DFB7718"),
        (4, 25, "9F6F4F1CDEBD6C15BAB640090BD5B2F9"),
        (4, 30, "0390E7AD4D03997D2D7DC9204A424FC0"),
        # 256-bit key groups
        (5, 33, "C8BE5EE302C9AAD4E112ED3C7C6C67CB"),
        (5, 36, "359ED98FE8697851160DDC60C92A54D5"),
        (6, 39, "79E93326CD5DC29C7527A3CA36CF2D59"),
        (6, 44, "849116D6B4211509C6ECF9E7C57DD52F"),
    ]

    @pytest.mark.parametrize("tg_id,tc_id,expected_ct", AFT_ENCRYPT_CASES)
    def test_aft_encrypt(self, response_lookup, tg_id, tc_id, expected_ct):
        tc = response_lookup.get((tg_id, tc_id))
        assert tc is not None, f"Test case ({tg_id}, {tc_id}) not found"
        assert tc["ct"].upper() == expected_ct, (
            f"tgId={tg_id} tcId={tc_id}: "
            f"expected ct={expected_ct}, got ct={tc.get('ct', 'MISSING')}"
        )


class TestAFTDecrypt:
    """Verify AFT decrypt results against reference values."""

    AFT_DECRYPT_CASES = [
        # (tgId, tcId, expected_pt)
        # 128-bit
        (7, 47, "6F43573A00A3600A309970AE242DAF4D"),
        (7, 50, "C202042480F945AB25722CF81A61CDA6"),
        (7, 54, "76D59BA653EDBDCF75FE87FDD3C2DAC0"),
        (8, 55, "F884933FF23870FC675B5C497D50DEDA"),
        (8, 60, "1E8A35736D2B2DCD10AE056FF3F48E59"),
        (8, 64, "9D126D78626445B00501C8679A4F444C"),
        # 192-bit
        (9, 65, "33802D8D05E392602139182BABE46EFC"),
        (9, 70, "281833612F2622F5921DF85094F50C93"),
        (10, 71, "42CE7329C1B0ADAB3C696585C1782841"),
        (10, 78, "4D405D319CF667F181A8D61E3C816A87"),
        # 256-bit
        (11, 79, "A29DCD9DCE22C218C680E2A6B2E77D73"),
        (11, 84, "5245EC517F2004B49C43266123236835"),
        (12, 85, "A7BBA8E7B4309798D30BD0AAE0611AF9"),
        (12, 92, "F415E190FE89B1484E203F31582C4779"),
    ]

    @pytest.mark.parametrize("tg_id,tc_id,expected_pt", AFT_DECRYPT_CASES)
    def test_aft_decrypt(self, response_lookup, tg_id, tc_id, expected_pt):
        tc = response_lookup.get((tg_id, tc_id))
        assert tc is not None, f"Test case ({tg_id}, {tc_id}) not found"
        assert tc["pt"].upper() == expected_pt, (
            f"tgId={tg_id} tcId={tc_id}: "
            f"expected pt={expected_pt}, got pt={tc.get('pt', 'MISSING')}"
        )


class TestMCTEncrypt:
    """Verify MCT encrypt results for all key sizes with salted key evolution."""

    def _get_mct_results(self, response_lookup, tg_id, tc_id):
        tc = response_lookup.get((tg_id, tc_id))
        assert tc is not None, f"MCT test ({tg_id}, {tc_id}) not found"
        assert "resultsArray" in tc, f"MCT test ({tg_id}, {tc_id}) missing resultsArray"
        return tc["resultsArray"]

    def test_mct_encrypt_128_round_0(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 13, 93)
        r = ra[0]
        assert r["key"].upper() == "2238F9A53A596BCA62E3EC0E80176070"
        assert r["iv"].upper() == "99C6F09B780FA0E679FAB2BECB9C1F18"
        assert r["pt"].upper() == "BFE24F7256D37C9C74B16A181FAD282E"
        assert r["ct"].upper() == "CDB7C783DFEB781E144E33C5C4BF053B"

    def test_mct_encrypt_128_round_49(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 13, 93)
        r = ra[49]
        assert r["key"].upper() == "9F6AB0BF83AEC6FB7008EBB62BC99B1B"
        assert r["ct"].upper() == "AF88F626007632BE887852A5F0D357DF"

    def test_mct_encrypt_128_round_99(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 13, 93)
        r = ra[99]
        assert r["key"].upper() == "3210DC1D106A0F9138B4D64E0B5E4066"
        assert r["iv"].upper() == "48A4976258649266F102DDD9DCFF757F"
        assert r["ct"].upper() == "68BDF02201ADEC6EFD9A4F33E17062F3"

    def test_mct_encrypt_192_round_0(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 14, 94)
        r = ra[0]
        assert r["key"].upper() == "69271E992CD4A8118E26CB51BB340186FDD00DB8730A62C1"
        assert r["ct"].upper() == "F0203FFCA2CCFF0E7912FE36E2034ACF"

    def test_mct_encrypt_192_round_49(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 14, 94)
        r = ra[49]
        assert r["key"].upper() == "DF5BB64EDB5112A6698DB4763631F5E1FE67135426C8A06F"
        assert r["ct"].upper() == "48669221117597855231E2519F30AF64"

    def test_mct_encrypt_192_round_99(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 14, 94)
        r = ra[99]
        assert r["key"].upper() == "E768D989D5A655F20A973B9773523F78FBC7972090AB462A"
        assert r["ct"].upper() == "8FB93A78841DF0CEDE69AF47EE916F0E"

    def test_mct_encrypt_256_round_0(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 15, 95)
        r = ra[0]
        assert r["key"].upper() == "D95C2053875FFEB2778FA8896038C39FBC8E6DEB9CD6A1216BD74A3FBBF26C3E"
        assert r["ct"].upper() == "41F0608877DFB0A60CD8E4C60A411152"

    def test_mct_encrypt_256_round_49(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 15, 95)
        r = ra[49]
        assert r["key"].upper() == "6ADBC529FAA9F25752150355D1934058B142540698322C5F0C0CA1749E233ABB"
        assert r["ct"].upper() == "CE4EC672485D9D9F612D60A555333D93"

    def test_mct_encrypt_256_round_99(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 15, 95)
        r = ra[99]
        assert r["key"].upper() == "410050255E12F00CD66E1BE8DD1A5855431A6889142F259772A742FFD5E0E128"
        assert r["ct"].upper() == "59026403F5A64CACF04F49BB6EFBB14E"


class TestMCTDecrypt:
    """Verify MCT decrypt results for all key sizes with salted key evolution."""

    def _get_mct_results(self, response_lookup, tg_id, tc_id):
        tc = response_lookup.get((tg_id, tc_id))
        assert tc is not None, f"MCT test ({tg_id}, {tc_id}) not found"
        assert "resultsArray" in tc
        return tc["resultsArray"]

    def test_mct_decrypt_128_round_0(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 16, 96)
        r = ra[0]
        assert r["key"].upper() == "A429D6DFAFE8F871F5D89382E162BC24"
        assert r["iv"].upper() == "F97A143681C15002192E2F60B1827A48"
        assert r["ct"].upper() == "AF9035D5ED50C14921D5896257394880"
        assert r["pt"].upper() == "BD63A52D7D27D74B462D0F02174996A2"

    def test_mct_decrypt_128_round_49(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 16, 96)
        r = ra[49]
        assert r["key"].upper() == "1FE2E785BB5B9E4019805A7AC31F4FF7"
        assert r["pt"].upper() == "F10BFDCA09E5E7EC2703406C0C9AF0EF"

    def test_mct_decrypt_128_round_99(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 16, 96)
        r = ra[99]
        assert r["key"].upper() == "E0B561D9C0E0CBD571DDA8D25AC07C85"
        assert r["iv"].upper() == "1142E19E6B3E5275C890B47CB5579F19"
        assert r["pt"].upper() == "971A893E1B16EA848E70CDE17556EC13"
        assert r["ct"].upper() == "866FFACCF5D31D37B730D83BA77589AC"

    def test_mct_decrypt_192_round_0(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 17, 97)
        r = ra[0]
        assert r["key"].upper() == "76E306DF1BF6078FA85B5DC83FFA44F527E795309BB11A10"
        assert r["pt"].upper() == "57DE3E7C4920B08508FB1DF3DF853866"

    def test_mct_decrypt_192_round_49(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 17, 97)
        r = ra[49]
        assert r["key"].upper() == "AC377E6FBAED0F69B92BB9E0D4B0654B75D7FC230554BD18"
        assert r["pt"].upper() == "A4B4120640E7313327DD17BBCBAB01D2"

    def test_mct_decrypt_192_round_99(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 17, 97)
        r = ra[99]
        assert r["key"].upper() == "447C35C0056AC6130C13F7120C661B92F3275A8144E99368"
        assert r["pt"].upper() == "BFEBCE7B571A1F3E9F79E5A95E2027C6"
        assert r["ct"].upper() == "30BDB3B6418B47596C90134C703F9F6A"

    def test_mct_decrypt_256_round_0(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 18, 98)
        r = ra[0]
        assert r["key"].upper() == "74E8DE286DA75FA6195BF92242D2627EB703F9A1D2777FA75F89C203275C7AD8"
        assert r["pt"].upper() == "954E35CAC7A6B26C0552C4BAF5BB7FEE"

    def test_mct_decrypt_256_round_49(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 18, 98)
        r = ra[49]
        assert r["key"].upper() == "6B11D72179E46A1A447CA8DE195E3B39067732CA385140C6F58D7E695C33A439"
        assert r["pt"].upper() == "238D95EEE35006D9A6E95A518C5CC180"

    def test_mct_decrypt_256_round_99(self, response_lookup):
        ra = self._get_mct_results(response_lookup, 18, 98)
        r = ra[99]
        assert r["key"].upper() == "A814568DDC15112A6F0474F8126A50A097FF5CB009E67A7714952926178CB632"
        assert r["iv"].upper() == "41BA7E461FBE25CE8E6DF70237F2FBFB"
        assert r["pt"].upper() == "C325AA870962472E18F961D17A14ED3F"
        assert r["ct"].upper() == "4C71D7272173EADE0E4BF397964DBF3C"
