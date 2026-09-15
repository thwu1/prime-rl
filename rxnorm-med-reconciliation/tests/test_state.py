
import json
import pytest

REPORT_PATH = "/app/reconciliation_report.json"
FORMULARY_PATH = "/app/formulary.json"


@pytest.fixture(scope="module")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def formulary():
    with open(FORMULARY_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def formulary_rxcuis(formulary):
    return {m["rxcui"] for m in formulary["preferred_medications"]}


@pytest.fixture(scope="module")
def meds_by_id(report):
    return {m["id"]: m for m in report["medications"]}


@pytest.fixture(scope="module")
def duplications(report):
    return report["therapeutic_duplications"]


# ─── Structural tests ───────────────────────────────────────────────────────


class TestReportStructure:
    def test_report_exists_and_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_patient_id(self, report):
        assert report["patient_id"] == "RECON-2024-001"

    def test_medication_count(self, report):
        assert len(report["medications"]) == 8

    def test_has_therapeutic_duplications_key(self, report):
        assert "therapeutic_duplications" in report
        assert isinstance(report["therapeutic_duplications"], list)

    def test_schema_completeness(self, meds_by_id):
        required = {"id", "rxcui", "name", "tty", "ingredients",
                     "generic_equivalent", "atc_classes",
                     "on_formulary", "formulary_alternatives"}
        for med_id, med in meds_by_id.items():
            assert required.issubset(set(med.keys())), \
                f"{med_id} missing fields: {required - set(med.keys())}"

    def test_rxcui_are_strings(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            assert isinstance(med["rxcui"], str), \
                f"{med_id} rxcui should be string, got {type(med['rxcui'])}"

    def test_ingredient_structure(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            assert isinstance(med["ingredients"], list), \
                f"{med_id} ingredients should be list"
            assert len(med["ingredients"]) >= 1, \
                f"{med_id} should have at least 1 ingredient"
            for ing in med["ingredients"]:
                assert "rxcui" in ing, f"{med_id} ingredient missing rxcui"
                assert "name" in ing, f"{med_id} ingredient missing name"
                assert isinstance(ing["rxcui"], str)
                assert len(ing["rxcui"]) > 0

    def test_atc_class_structure(self, meds_by_id):
        """Check that atc_classes field is a list with valid structure."""
        for med_id, med in meds_by_id.items():
            assert isinstance(med["atc_classes"], list), \
                f"{med_id} atc_classes should be list"
            for c in med["atc_classes"]:
                assert "class_id" in c
                assert "class_name" in c
                assert len(c["class_id"]) > 0
                assert len(c["class_name"]) > 0

    def test_on_formulary_is_bool(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            assert isinstance(med["on_formulary"], bool), \
                f"{med_id} on_formulary should be bool"

    def test_formulary_alternatives_is_list(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            assert isinstance(med["formulary_alternatives"], list), \
                f"{med_id} formulary_alternatives should be list"


# ─── Individual medication resolution tests ──────────────────────────────────


class TestM1NdcResolution:
    """M1: NDC 0069-3150-83 → azithromycin 500 MG Injection [Zithromax]"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M1"]["rxcui"] == "1668240"

    def test_tty_is_sbd(self, meds_by_id):
        assert meds_by_id["M1"]["tty"] == "SBD"

    def test_ingredient_azithromycin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M1"]["ingredients"]]
        assert any("azithromycin" in n for n in names)

    def test_has_generic_equivalent(self, meds_by_id):
        ge = meds_by_id["M1"]["generic_equivalent"]
        assert ge is not None, "SBD should have generic equivalent"
        assert "rxcui" in ge
        assert "name" in ge
        assert "azithromycin" in ge["name"].lower()


class TestM2BrandAtorvastatin:
    """M2: Lipitor 20 MG Oral Tablet → atorvastatin"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M2"]["rxcui"] == "617318"

    def test_tty_is_sbd(self, meds_by_id):
        assert meds_by_id["M2"]["tty"] == "SBD"

    def test_ingredient_atorvastatin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M2"]["ingredients"]]
        assert any("atorvastatin" in n for n in names)

    def test_name_contains_lipitor(self, meds_by_id):
        # Canonical name is "atorvastatin 20 MG Oral Tablet [Lipitor]"
        name_lower = meds_by_id["M2"]["name"].lower()
        assert "atorvastatin" in name_lower or "lipitor" in name_lower

    def test_branded_has_generic_equivalent(self, meds_by_id):
        ge = meds_by_id["M2"]["generic_equivalent"]
        assert ge is not None, "SBD should have generic equivalent"
        assert "atorvastatin" in ge["name"].lower()


class TestM3GenericMetformin:
    """M3: metformin hydrochloride 500 MG Oral Tablet"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M3"]["rxcui"] == "861007"

    def test_tty_is_scd(self, meds_by_id):
        assert meds_by_id["M3"]["tty"] == "SCD"

    def test_ingredient_metformin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M3"]["ingredients"]]
        assert any("metformin" in n for n in names)

    def test_no_generic_equivalent(self, meds_by_id):
        assert meds_by_id["M3"]["generic_equivalent"] is None, \
            "SCD should have null generic_equivalent"


class TestM4GenericAtorvastatin:
    """M4: atorvastatin 40 MG Oral Tablet"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M4"]["rxcui"] == "617311"

    def test_tty_is_scd(self, meds_by_id):
        assert meds_by_id["M4"]["tty"] == "SCD"

    def test_ingredient_atorvastatin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M4"]["ingredients"]]
        assert any("atorvastatin" in n for n in names)

    def test_no_generic_equivalent(self, meds_by_id):
        assert meds_by_id["M4"]["generic_equivalent"] is None


class TestM5MultiIngredient:
    """M5: amlodipine 5 MG / atorvastatin 20 MG Oral Tablet"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M5"]["rxcui"] == "597980"

    def test_tty_is_scd(self, meds_by_id):
        assert meds_by_id["M5"]["tty"] == "SCD"

    def test_exactly_two_ingredients(self, meds_by_id):
        assert len(meds_by_id["M5"]["ingredients"]) == 2

    def test_has_amlodipine(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M5"]["ingredients"]]
        assert any("amlodipine" in n for n in names)

    def test_has_atorvastatin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M5"]["ingredients"]]
        assert any("atorvastatin" in n for n in names)


class TestM6Warfarin:
    """M6: warfarin sodium 5 MG Oral Tablet"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M6"]["rxcui"] == "855332"

    def test_tty_is_scd(self, meds_by_id):
        assert meds_by_id["M6"]["tty"] == "SCD"

    def test_ingredient_warfarin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M6"]["ingredients"]]
        assert any("warfarin" in n for n in names)

    def test_no_generic_equivalent(self, meds_by_id):
        assert meds_by_id["M6"]["generic_equivalent"] is None


class TestM7ApproximateMatch:
    """M7: 'lisinoprl 10mg tabs' → lisinopril via fuzzy matching"""

    def test_rxcui_resolved(self, meds_by_id):
        assert meds_by_id["M7"]["rxcui"] is not None
        assert len(meds_by_id["M7"]["rxcui"]) > 0

    def test_ingredient_lisinopril(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M7"]["ingredients"]]
        assert any("lisinopril" in n for n in names)

    def test_name_contains_lisinopril(self, meds_by_id):
        assert "lisinopril" in meds_by_id["M7"]["name"].lower()


class TestM8MultiIngredientMetformin:
    """M8: metformin hydrochloride 500 MG / sitagliptin 50 MG Oral Tablet"""

    def test_rxcui(self, meds_by_id):
        assert meds_by_id["M8"]["rxcui"] == "861819"

    def test_tty_is_scd(self, meds_by_id):
        assert meds_by_id["M8"]["tty"] == "SCD"

    def test_at_least_two_ingredients(self, meds_by_id):
        assert len(meds_by_id["M8"]["ingredients"]) >= 2

    def test_has_metformin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M8"]["ingredients"]]
        assert any("metformin" in n for n in names)

    def test_has_sitagliptin(self, meds_by_id):
        names = [i["name"].lower() for i in meds_by_id["M8"]["ingredients"]]
        assert any("sitagliptin" in n for n in names)


# ─── Therapeutic duplication detection ───────────────────────────────────────


class TestTherapeuticDuplications:
    def _find_group(self, duplications, ingredient_name):
        """Find a duplication group by ingredient name (case-insensitive)."""
        return [d for d in duplications
                if ingredient_name.lower() in d["ingredient_name"].lower()]

    def test_atorvastatin_duplication_exists(self, duplications):
        groups = self._find_group(duplications, "atorvastatin")
        assert len(groups) == 1, \
            f"Expected exactly 1 atorvastatin duplication group, found {len(groups)}"

    def test_atorvastatin_duplication_members(self, duplications):
        groups = self._find_group(duplications, "atorvastatin")
        group = groups[0]
        assert set(group["medication_ids"]) == {"M2", "M4", "M5"}, \
            f"Expected M2,M4,M5 but got {group['medication_ids']}"

    def test_metformin_duplication_exists(self, duplications):
        groups = self._find_group(duplications, "metformin")
        assert len(groups) == 1, \
            f"Expected exactly 1 metformin duplication group, found {len(groups)}"

    def test_metformin_duplication_members(self, duplications):
        groups = self._find_group(duplications, "metformin")
        group = groups[0]
        assert set(group["medication_ids"]) == {"M3", "M8"}, \
            f"Expected M3,M8 but got {group['medication_ids']}"

    def test_no_singleton_duplications(self, duplications):
        for d in duplications:
            assert len(d["medication_ids"]) >= 2, \
                f"Duplication group for {d['ingredient_name']} has fewer than 2 members"

    def test_duplication_group_structure(self, duplications):
        for d in duplications:
            assert "ingredient_rxcui" in d
            assert "ingredient_name" in d
            assert "medication_ids" in d
            assert isinstance(d["ingredient_rxcui"], str)
            assert len(d["ingredient_rxcui"]) > 0
            assert isinstance(d["medication_ids"], list)

    def test_medication_ids_sorted(self, duplications):
        for d in duplications:
            assert d["medication_ids"] == sorted(d["medication_ids"]), \
                f"medication_ids for {d['ingredient_name']} not sorted"


# ─── Generic equivalent consistency ─────────────────────────────────────────


class TestGenericEquivalents:
    def test_sbd_entries_have_generic_equivalent(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            if med["tty"] == "SBD":
                assert med["generic_equivalent"] is not None, \
                    f"{med_id} (SBD) should have generic_equivalent"
                ge = med["generic_equivalent"]
                assert "rxcui" in ge
                assert "name" in ge
                assert isinstance(ge["rxcui"], str)
                assert len(ge["rxcui"]) > 0

    def test_scd_entries_have_null_generic_equivalent(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            if med["tty"] == "SCD":
                assert med["generic_equivalent"] is None, \
                    f"{med_id} (SCD) should have null generic_equivalent"


# ─── ATC classification ─────────────────────────────────────────────────────


class TestATCClassification:
    def test_most_medications_have_atc_classes(self, meds_by_id):
        """At least 6 of 8 medications should have ATC class data."""
        count_with_atc = sum(
            1 for med in meds_by_id.values()
            if len(med["atc_classes"]) >= 1
        )
        assert count_with_atc >= 6, \
            f"Only {count_with_atc}/8 medications have ATC classes, expected >= 6"


# ─── Formulary cross-referencing ─────────────────────────────────────────────


class TestFormularyMembership:
    """Verify on_formulary flag matches expected values."""

    def test_m1_not_on_formulary(self, meds_by_id):
        assert meds_by_id["M1"]["on_formulary"] is False

    def test_m2_not_on_formulary(self, meds_by_id):
        assert meds_by_id["M2"]["on_formulary"] is False

    def test_m3_on_formulary(self, meds_by_id):
        assert meds_by_id["M3"]["on_formulary"] is True

    def test_m4_on_formulary(self, meds_by_id):
        assert meds_by_id["M4"]["on_formulary"] is True

    def test_m5_on_formulary(self, meds_by_id):
        assert meds_by_id["M5"]["on_formulary"] is True

    def test_m6_on_formulary(self, meds_by_id):
        assert meds_by_id["M6"]["on_formulary"] is True

    def test_m8_on_formulary(self, meds_by_id):
        assert meds_by_id["M8"]["on_formulary"] is True


class TestFormularyAlternatives:
    """Verify formulary alternatives logic."""

    def test_on_formulary_items_have_empty_alternatives(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            if med["on_formulary"]:
                assert med["formulary_alternatives"] == [], \
                    f"{med_id} is on formulary but has non-empty alternatives"

    def test_m1_no_formulary_alternatives(self, meds_by_id):
        alts = meds_by_id["M1"]["formulary_alternatives"]
        assert len(alts) == 0, \
            f"No azithromycin in formulary, but got alternatives: {alts}"

    def test_m2_has_atorvastatin_alternatives(self, meds_by_id):
        alts = meds_by_id["M2"]["formulary_alternatives"]
        assert len(alts) >= 2, \
            "M2 should have atorvastatin formulary alternatives"
        alt_rxcuis = {a["rxcui"] for a in alts}
        # Formulary has atorvastatin 20 MG (617310) and 40 MG (617311)
        assert "617310" in alt_rxcuis or "617311" in alt_rxcuis, \
            "M2 should have generic atorvastatin alternatives from formulary"

    def test_alternatives_only_contain_formulary_items(self, meds_by_id,
                                                       formulary_rxcuis):
        """All listed alternatives must actually be in the formulary."""
        for med_id, med in meds_by_id.items():
            for alt in med["formulary_alternatives"]:
                assert alt["rxcui"] in formulary_rxcuis, \
                    f"{med_id} lists alternative {alt['rxcui']} not in formulary"

    def test_alternative_structure(self, meds_by_id):
        for med_id, med in meds_by_id.items():
            for alt in med["formulary_alternatives"]:
                assert "rxcui" in alt, f"{med_id} alternative missing rxcui"
                assert "name" in alt, f"{med_id} alternative missing name"
                assert isinstance(alt["rxcui"], str)
                assert len(alt["rxcui"]) > 0
                assert len(alt["name"]) > 0

    def test_m7_formulary_consistency(self, meds_by_id):
        """M7 resolves to lisinopril which is in formulary."""
        m7 = meds_by_id["M7"]
        if m7["on_formulary"]:
            assert m7["formulary_alternatives"] == []
        else:
            alt_rxcuis = {a["rxcui"] for a in m7["formulary_alternatives"]}
            assert "314076" in alt_rxcuis, \
                "lisinopril 10 MG (314076) should be alternative if M7 not on formulary"
