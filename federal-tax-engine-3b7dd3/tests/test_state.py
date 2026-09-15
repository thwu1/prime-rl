
import json
import os
import subprocess
import glob
import xml.etree.ElementTree as ElementTree
import pytest


RESULTS_DIR = "/app/results"
XML_DIR = "/app/xml_returns"
NS = {"t": "urn:irs:form1040:ty2025"}


@pytest.fixture(scope="session", autouse=True)
def run_computation():
    """Run the tax computation engine before tests."""
    result = subprocess.run(
        ["python3", "/app/compute_tax.py"],
        capture_output=True, text=True, cwd="/app"
    )
    assert result.returncode == 0, (
        f"compute_tax.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def load_result(scenario_name):
    path = os.path.join(RESULTS_DIR, f"{scenario_name}.json")
    assert os.path.exists(path), f"Result file not found: {path}"
    with open(path) as f:
        return json.load(f)


def load_xml(scenario_name):
    path = os.path.join(XML_DIR, f"{scenario_name}.xml")
    assert os.path.exists(path), f"XML file not found: {path}"
    tree = ElementTree.parse(path)
    return tree.getroot()


def xml_int(root, xpath):
    el = root.find(xpath, NS)
    assert el is not None, f"XML element not found: {xpath}"
    return int(el.text)


def xml_text(root, xpath):
    el = root.find(xpath, NS)
    assert el is not None, f"XML element not found: {xpath}"
    return el.text


# ---------------------------------------------------------------------------
# Schema Validation
# ---------------------------------------------------------------------------
class TestSchemaValidation:

    def test_json_schema_all_scenarios(self):
        import jsonschema
        with open("/app/output_schema.json") as f:
            schema = json.load(f)
        for i in range(1, 6):
            result = load_result(f"scenario_{i}")
            jsonschema.validate(result, schema)

    def test_xml_files_exist(self):
        for i in range(1, 6):
            path = os.path.join(XML_DIR, f"scenario_{i}.xml")
            assert os.path.exists(path), f"Missing XML: {path}"

    def test_xmllint_validates_all(self):
        xml_files = sorted(glob.glob(os.path.join(XML_DIR, "scenario_*.xml")))
        assert len(xml_files) >= 5, f"Expected >= 5 XML files, found {len(xml_files)}"
        result = subprocess.run(
            ["xmllint", "--schema", "/app/mef_schema.xsd", "--noout"] + xml_files,
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"xmllint validation failed:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# XML Content Verification -- Scenario 1
# ---------------------------------------------------------------------------
class TestXmlScenario1:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.root = load_xml("scenario_1")

    def test_filing_status(self):
        assert xml_text(self.root, ".//t:Header/t:FilingStatus") == "single"

    def test_tax_year(self):
        assert xml_int(self.root, ".//t:Header/t:TaxYear") == 2025

    def test_wages(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line1a") == 42470

    def test_total_tax(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line24") == 2926

    def test_amount_owed(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line37") == 213

    def test_refund_zero(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line34") == 0

    def test_schedule_h_total(self):
        assert xml_int(self.root, ".//t:ScheduleH/t:Line8") == 474

    def test_energy_credit(self):
        assert xml_int(self.root, ".//t:Form5695/t:Line32") == 516

    def test_schedule_2(self):
        assert xml_int(self.root, ".//t:Schedule2/t:Line21") == 474

    def test_schedule_3(self):
        assert xml_int(self.root, ".//t:Schedule3/t:Line8") == 516


# ---------------------------------------------------------------------------
# XML Content Verification -- Scenario 2
# ---------------------------------------------------------------------------
class TestXmlScenario2:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.root = load_xml("scenario_2")

    def test_filing_status(self):
        assert xml_text(self.root, ".//t:Header/t:FilingStatus") == "mfj"

    def test_qdcgtw_tax(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line16") == 11120

    def test_capital_gain(self):
        assert xml_int(self.root, ".//t:ScheduleD/t:Line16") == 10105

    def test_refund(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line34") == 880

    def test_no_energy(self):
        assert xml_int(self.root, ".//t:Form5695/t:Line32") == 0


# ---------------------------------------------------------------------------
# XML Content Verification -- Scenario 3
# ---------------------------------------------------------------------------
class TestXmlScenario3:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.root = load_xml("scenario_3")

    def test_filing_status(self):
        assert xml_text(self.root, ".//t:Header/t:FilingStatus") == "hoh"

    def test_credit_limited(self):
        assert xml_int(self.root, ".//t:Form5695/t:Line32") == 488

    def test_credit_limit_value(self):
        assert xml_int(self.root, ".//t:Form5695/t:Line31") == 488

    def test_schedule_h_total(self):
        assert xml_int(self.root, ".//t:ScheduleH/t:Line8") == 689

    def test_refund(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line34") == 511


# ---------------------------------------------------------------------------
# XML Content Verification -- Scenario 4
# ---------------------------------------------------------------------------
class TestXmlScenario4:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.root = load_xml("scenario_4")

    def test_filing_status(self):
        assert xml_text(self.root, ".//t:Header/t:FilingStatus") == "single"

    def test_negative_stcg(self):
        assert xml_int(self.root, ".//t:ScheduleD/t:Line7") == -2400

    def test_total_tax(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line24") == 13749

    def test_energy_credit(self):
        assert xml_int(self.root, ".//t:Form5695/t:Line32") == 3200

    def test_non_hp_aggregate(self):
        assert xml_int(self.root, ".//t:Form5695/t:Line28") == 1200

    def test_amount_owed(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line37") == 3849


# ---------------------------------------------------------------------------
# XML Content Verification -- Scenario 5
# ---------------------------------------------------------------------------
class TestXmlScenario5:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.root = load_xml("scenario_5")

    def test_filing_status(self):
        assert xml_text(self.root, ".//t:Header/t:FilingStatus") == "qss"

    def test_dividends_at_zero_rate(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line16") == 2943

    def test_refund(self):
        assert xml_int(self.root, ".//t:Form1040/t:Line34") == 1274

    def test_schedule_h_fit(self):
        assert xml_int(self.root, ".//t:ScheduleH/t:Line7") == 200

    def test_schedule_h_total(self):
        assert xml_int(self.root, ".//t:ScheduleH/t:Line8") == 583


# ---------------------------------------------------------------------------
# Scenario 1: Single filer, 2 W-2s, Schedule H, Form 5695 energy credits
# ---------------------------------------------------------------------------
class TestScenario1:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = load_result("scenario_1")

    def test_wages(self):
        assert self.r["form_1040"]["line_1a"] == 42470

    def test_total_wages(self):
        assert self.r["form_1040"]["line_1z"] == 42470

    def test_total_income(self):
        assert self.r["form_1040"]["line_9"] == 42470

    def test_agi(self):
        assert self.r["form_1040"]["line_11a"] == 42470

    def test_standard_deduction(self):
        assert self.r["form_1040"]["line_12e"] == 15750

    def test_taxable_income(self):
        assert self.r["form_1040"]["line_15"] == 26720

    def test_tax(self):
        assert self.r["form_1040"]["line_16"] == 2968

    def test_line_18(self):
        assert self.r["form_1040"]["line_18"] == 2968

    def test_credits_from_schedule_3(self):
        assert self.r["form_1040"]["line_20"] == 516

    def test_tax_after_credits(self):
        assert self.r["form_1040"]["line_22"] == 2452

    def test_other_taxes(self):
        assert self.r["form_1040"]["line_23"] == 474

    def test_total_tax(self):
        assert self.r["form_1040"]["line_24"] == 2926

    def test_withholding(self):
        assert self.r["form_1040"]["line_25a"] == 2713
        assert self.r["form_1040"]["line_25d"] == 2713

    def test_total_payments(self):
        assert self.r["form_1040"]["line_33"] == 2713

    def test_amount_owed(self):
        assert self.r["form_1040"]["line_37"] == 213

    def test_not_overpaid(self):
        assert self.r["form_1040"]["line_34"] == 0

    def test_sch_h_ss_tax(self):
        assert self.r["schedule_h"]["line_2"] == 384

    def test_sch_h_medicare_tax(self):
        assert self.r["schedule_h"]["line_4"] == 90

    def test_sch_h_total(self):
        assert self.r["schedule_h"]["line_8"] == 474

    def test_5695_door_credit(self):
        assert self.r["form_5695"]["line_19h"] == 240

    def test_5695_window_credit(self):
        assert self.r["form_5695"]["line_20d"] == 276

    def test_5695_non_hp_aggregate(self):
        assert self.r["form_5695"]["line_28"] == 516

    def test_5695_total_credit(self):
        assert self.r["form_5695"]["line_30"] == 516

    def test_5695_credit_allowed(self):
        assert self.r["form_5695"]["line_32"] == 516

    def test_sch2_household(self):
        assert self.r["schedule_2"]["line_9"] == 474

    def test_sch2_total_other(self):
        assert self.r["schedule_2"]["line_21"] == 474

    def test_sch3_energy_credit(self):
        assert self.r["schedule_3"]["line_5b"] == 516

    def test_sch3_total(self):
        assert self.r["schedule_3"]["line_8"] == 516


# ---------------------------------------------------------------------------
# Scenario 2: MFJ, qualified dividends + capital gains
# ---------------------------------------------------------------------------
class TestScenario2:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = load_result("scenario_2")

    def test_wages(self):
        assert self.r["form_1040"]["line_1a"] == 120000

    def test_qualified_dividends(self):
        assert self.r["form_1040"]["line_3a"] == 3000

    def test_ordinary_dividends(self):
        assert self.r["form_1040"]["line_3b"] == 3000

    def test_capital_gain(self):
        assert self.r["form_1040"]["line_7"] == 10105

    def test_total_income(self):
        assert self.r["form_1040"]["line_9"] == 133105

    def test_agi(self):
        assert self.r["form_1040"]["line_11a"] == 133105

    def test_standard_deduction(self):
        assert self.r["form_1040"]["line_12e"] == 31500

    def test_taxable_income(self):
        assert self.r["form_1040"]["line_15"] == 101605

    def test_tax_qdcgtw(self):
        assert self.r["form_1040"]["line_16"] == 11120

    def test_line_18(self):
        assert self.r["form_1040"]["line_18"] == 11120

    def test_no_credits(self):
        assert self.r["form_1040"]["line_20"] == 0

    def test_total_tax(self):
        assert self.r["form_1040"]["line_24"] == 11120

    def test_withholding(self):
        assert self.r["form_1040"]["line_25d"] == 12000

    def test_refund(self):
        assert self.r["form_1040"]["line_34"] == 880

    def test_not_owed(self):
        assert self.r["form_1040"]["line_37"] == 0

    def test_sch_d_stcg(self):
        assert self.r["schedule_d"]["line_7"] == 2006

    def test_sch_d_ltcg(self):
        assert self.r["schedule_d"]["line_15"] == 8099

    def test_sch_d_combined(self):
        assert self.r["schedule_d"]["line_16"] == 10105

    def test_no_sch_h(self):
        assert self.r["schedule_h"]["line_8"] == 0

    def test_sch2_zero(self):
        assert self.r["schedule_2"]["line_9"] == 0
        assert self.r["schedule_2"]["line_21"] == 0

    def test_no_energy(self):
        assert self.r["schedule_3"]["line_5b"] == 0
        assert self.r["form_5695"]["line_32"] == 0


# ---------------------------------------------------------------------------
# Scenario 3: HOH, credit limitation binding (credit > tax liability)
# ---------------------------------------------------------------------------
class TestScenario3:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = load_result("scenario_3")

    def test_wages(self):
        assert self.r["form_1040"]["line_1a"] == 28500

    def test_standard_deduction(self):
        assert self.r["form_1040"]["line_12e"] == 23625

    def test_taxable_income(self):
        assert self.r["form_1040"]["line_15"] == 4875

    def test_tax(self):
        assert self.r["form_1040"]["line_16"] == 488

    def test_credits_limited_by_tax(self):
        assert self.r["form_1040"]["line_20"] == 488

    def test_tax_after_credits_zero(self):
        assert self.r["form_1040"]["line_22"] == 0

    def test_other_taxes(self):
        assert self.r["form_1040"]["line_23"] == 689

    def test_total_tax(self):
        assert self.r["form_1040"]["line_24"] == 689

    def test_total_payments(self):
        assert self.r["form_1040"]["line_33"] == 1200

    def test_refund(self):
        assert self.r["form_1040"]["line_34"] == 511

    def test_not_owed(self):
        assert self.r["form_1040"]["line_37"] == 0

    def test_sch_h_ss_tax(self):
        assert self.r["schedule_h"]["line_2"] == 558

    def test_sch_h_medicare_tax(self):
        assert self.r["schedule_h"]["line_4"] == 131

    def test_sch_h_total(self):
        assert self.r["schedule_h"]["line_8"] == 689

    def test_5695_window_credit(self):
        assert self.r["form_5695"]["line_20d"] == 600

    def test_5695_heat_pump_credit(self):
        assert self.r["form_5695"]["line_29h"] == 1800

    def test_5695_non_hp_aggregate(self):
        assert self.r["form_5695"]["line_28"] == 600

    def test_5695_total_before_limit(self):
        assert self.r["form_5695"]["line_30"] == 2400

    def test_5695_credit_limit(self):
        assert self.r["form_5695"]["line_31"] == 488

    def test_5695_credit_allowed(self):
        assert self.r["form_5695"]["line_32"] == 488

    def test_sch2_household(self):
        assert self.r["schedule_2"]["line_9"] == 689

    def test_sch2_total_other(self):
        assert self.r["schedule_2"]["line_21"] == 689

    def test_sch3_energy_credit(self):
        assert self.r["schedule_3"]["line_5b"] == 488


# ---------------------------------------------------------------------------
# Scenario 4: Single, 3 W-2s, dividends + mixed cap gains (ST loss / LT gain),
#   all forms active. Tests QDCGTW where ordinary income exceeds 0% breakpoint,
#   non-HP aggregate cap binding, heat pump cap binding.
# ---------------------------------------------------------------------------
class TestScenario4:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = load_result("scenario_4")

    def test_wages(self):
        assert self.r["form_1040"]["line_1a"] == 95000

    def test_qualified_dividends(self):
        assert self.r["form_1040"]["line_3a"] == 8500

    def test_ordinary_dividends(self):
        assert self.r["form_1040"]["line_3b"] == 11200

    def test_capital_gain(self):
        assert self.r["form_1040"]["line_7"] == 12900

    def test_total_income(self):
        assert self.r["form_1040"]["line_9"] == 119100

    def test_agi(self):
        assert self.r["form_1040"]["line_11a"] == 119100

    def test_standard_deduction(self):
        assert self.r["form_1040"]["line_12e"] == 15750

    def test_taxable_income(self):
        assert self.r["form_1040"]["line_15"] == 103350

    def test_tax(self):
        assert self.r["form_1040"]["line_16"] == 16153

    def test_line_18(self):
        assert self.r["form_1040"]["line_18"] == 16153

    def test_credits(self):
        assert self.r["form_1040"]["line_20"] == 3200

    def test_tax_after_credits(self):
        assert self.r["form_1040"]["line_22"] == 12953

    def test_other_taxes(self):
        assert self.r["form_1040"]["line_23"] == 796

    def test_total_tax(self):
        assert self.r["form_1040"]["line_24"] == 13749

    def test_withholding(self):
        assert self.r["form_1040"]["line_25a"] == 9900
        assert self.r["form_1040"]["line_25d"] == 9900

    def test_total_payments(self):
        assert self.r["form_1040"]["line_33"] == 9900

    def test_amount_owed(self):
        assert self.r["form_1040"]["line_37"] == 3849

    def test_not_overpaid(self):
        assert self.r["form_1040"]["line_34"] == 0

    def test_sch_d_stcg_negative(self):
        assert self.r["schedule_d"]["line_7"] == -2400

    def test_sch_d_ltcg(self):
        assert self.r["schedule_d"]["line_15"] == 15300

    def test_sch_d_combined(self):
        assert self.r["schedule_d"]["line_16"] == 12900

    def test_sch_h_ss_tax(self):
        assert self.r["schedule_h"]["line_2"] == 645

    def test_sch_h_medicare_tax(self):
        assert self.r["schedule_h"]["line_4"] == 151

    def test_sch_h_total(self):
        assert self.r["schedule_h"]["line_8"] == 796

    def test_5695_insulation(self):
        assert self.r["form_5695"]["line_18b"] == 1200

    def test_5695_door(self):
        assert self.r["form_5695"]["line_19h"] == 360

    def test_5695_audit(self):
        assert self.r["form_5695"]["line_26c"] == 150

    def test_5695_non_hp_aggregate(self):
        assert self.r["form_5695"]["line_28"] == 1200

    def test_5695_heat_pump(self):
        assert self.r["form_5695"]["line_29h"] == 2000

    def test_5695_total(self):
        assert self.r["form_5695"]["line_30"] == 3200

    def test_5695_credit_not_limited(self):
        assert self.r["form_5695"]["line_32"] == 3200

    def test_sch2_household(self):
        assert self.r["schedule_2"]["line_9"] == 796

    def test_sch2_total_other(self):
        assert self.r["schedule_2"]["line_21"] == 796

    def test_sch3_energy(self):
        assert self.r["schedule_3"]["line_5b"] == 3200

    def test_sch3_total(self):
        assert self.r["schedule_3"]["line_8"] == 3200


# ---------------------------------------------------------------------------
# Scenario 5: QSS filer, qualified dividends only (no Schedule D triggers),
#   Schedule H with FIT withholding. Tests QDCGTW with dividends only where
#   all preferential income falls in 0% bracket, ROUND_HALF_UP on 72.50.
# ---------------------------------------------------------------------------
class TestScenario5:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = load_result("scenario_5")

    def test_wages(self):
        assert self.r["form_1040"]["line_1a"] == 55000

    def test_qualified_dividends(self):
        assert self.r["form_1040"]["line_3a"] == 20000

    def test_ordinary_dividends(self):
        assert self.r["form_1040"]["line_3b"] == 25000

    def test_no_capital_gain(self):
        assert self.r["form_1040"]["line_7"] == 0

    def test_total_income(self):
        assert self.r["form_1040"]["line_9"] == 80000

    def test_agi(self):
        assert self.r["form_1040"]["line_11a"] == 80000

    def test_standard_deduction(self):
        assert self.r["form_1040"]["line_12e"] == 31500

    def test_taxable_income(self):
        assert self.r["form_1040"]["line_15"] == 48500

    def test_tax(self):
        assert self.r["form_1040"]["line_16"] == 2943

    def test_line_18(self):
        assert self.r["form_1040"]["line_18"] == 2943

    def test_no_credits(self):
        assert self.r["form_1040"]["line_20"] == 0

    def test_tax_after_credits(self):
        assert self.r["form_1040"]["line_22"] == 2943

    def test_other_taxes(self):
        assert self.r["form_1040"]["line_23"] == 583

    def test_total_tax(self):
        assert self.r["form_1040"]["line_24"] == 3526

    def test_withholding(self):
        assert self.r["form_1040"]["line_25a"] == 4800
        assert self.r["form_1040"]["line_25d"] == 4800

    def test_total_payments(self):
        assert self.r["form_1040"]["line_33"] == 4800

    def test_refund(self):
        assert self.r["form_1040"]["line_34"] == 1274

    def test_not_owed(self):
        assert self.r["form_1040"]["line_37"] == 0

    def test_sch_h_ss_tax(self):
        assert self.r["schedule_h"]["line_2"] == 310

    def test_sch_h_medicare_tax(self):
        assert self.r["schedule_h"]["line_4"] == 73

    def test_sch_h_fit_withheld(self):
        assert self.r["schedule_h"]["line_7"] == 200

    def test_sch_h_total(self):
        assert self.r["schedule_h"]["line_8"] == 583

    def test_sch_d_zero(self):
        assert self.r["schedule_d"]["line_7"] == 0
        assert self.r["schedule_d"]["line_15"] == 0
        assert self.r["schedule_d"]["line_16"] == 0

    def test_no_energy(self):
        assert self.r["form_5695"]["line_32"] == 0
        assert self.r["schedule_3"]["line_5b"] == 0

    def test_sch2_household(self):
        assert self.r["schedule_2"]["line_9"] == 583

    def test_sch2_total_other(self):
        assert self.r["schedule_2"]["line_21"] == 583

    def test_sch3_no_credits(self):
        assert self.r["schedule_3"]["line_8"] == 0
