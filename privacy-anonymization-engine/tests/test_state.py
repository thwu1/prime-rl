
import csv
import hashlib
import hmac
import json
import math
import os
import sqlite3
import yaml
from collections import Counter, defaultdict

REMEDIATED_FILE = "/app/output/remediated.csv"
REPORT_FILE = "/app/output/compliance_report.json"
UTILITY_FILE = "/app/output/utility_analysis.json"
CERTIFICATION_FILE = "/app/output/certification.json"
PATIENTS_FILE = "/app/data/patients.csv"
REQUIREMENTS_FILE = "/app/compliance/requirements.yaml"
HIERARCHIES_DIR = "/app/data/hierarchies"
DIAG_HIERARCHY_FILE = "/app/data/diagnosis_hierarchy.json"
DB_FILE = "/app/data/privacy.db"
SIGNING_KEY_FILE = "/app/compliance/signing.key"

# Load compliance configuration
with open(REQUIREMENTS_FILE) as _f:
    _config = yaml.safe_load(_f)
QI_ATTRS = _config["quasi_identifiers"]
SENSITIVE = _config["sensitive_attribute"]
RIC_K = _config["controls"]["RIC"]["parameters"]["minimum_group_size"]
ADR_THRESHOLD = _config["controls"]["ADR"]["parameters"]["minimum_entropy"]
DCR_THRESHOLD = _config["controls"]["DCR"]["parameters"]["maximum_distance"]
DDR_THRESHOLD = _config["controls"]["DDR"]["parameters"]["maximum_frequency"]
SRC_MAX_RATE = _config["controls"]["SRC"]["parameters"]["maximum_suppression_rate"]

# Load utility weights from the SQLite privacy database
_db = sqlite3.connect(DB_FILE)
_cur = _db.execute('SELECT attribute, weight FROM utility_weights')
UTILITY_WEIGHTS = {row[0]: row[1] for row in _cur.fetchall()}
_cur = _db.execute("SELECT value FROM data_provenance WHERE key = 'dataset_id'")
EXPECTED_DATASET_ID = _cur.fetchone()[0]
_db.close()

# Load diagnosis severity ordering for EMD
with open(DIAG_HIERARCHY_FILE) as _f:
    _diag_hier = json.load(_f)
SEVERITY_ORDERING = _diag_hier["severity_ordering"]


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_hierarchy_values(attr):
    """Return (set of all valid values across all levels, max generalization level)."""
    path = os.path.join(HIERARCHIES_DIR, attr + ".csv")
    valid = set()
    max_level = 0
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        max_level = len(header) - 1
        for row in reader:
            valid.update(row)
    return valid, max_level


def get_ecs(data):
    ecs = defaultdict(list)
    for record in data:
        key = tuple(record[a] for a in QI_ATTRS)
        ecs[key].append(record)
    return ecs


def compute_emd(ec_values, all_values, ordering):
    """Compute normalized Earth Mover's Distance (Wasserstein-1) for ordinal data.

    EMD = sum_{i=1}^{n-1} |CDF_ec(i) - CDF_all(i)| / (n - 1)
    """
    n = len(ordering)
    if n <= 1:
        return 0.0
    ec_total = len(ec_values)
    all_total = len(all_values)
    ec_counter = Counter(ec_values)
    all_counter = Counter(all_values)
    cdf_ec = 0.0
    cdf_all = 0.0
    total_diff = 0.0
    for i in range(n - 1):
        cat = ordering[i]
        cdf_ec += ec_counter.get(cat, 0) / ec_total
        cdf_all += all_counter.get(cat, 0) / all_total
        total_diff += abs(cdf_ec - cdf_all)
    return total_diff / (n - 1)


# ---- Output file existence ----

class TestOutputFilesExist:
    def test_remediated_csv_exists(self):
        assert os.path.isfile(REMEDIATED_FILE), "{} does not exist".format(REMEDIATED_FILE)

    def test_compliance_report_exists(self):
        assert os.path.isfile(REPORT_FILE), "{} does not exist".format(REPORT_FILE)

    def test_utility_analysis_exists(self):
        assert os.path.isfile(UTILITY_FILE), "{} does not exist".format(UTILITY_FILE)

    def test_certification_exists(self):
        assert os.path.isfile(CERTIFICATION_FILE), \
            "{} does not exist".format(CERTIFICATION_FILE)


# ---- Data integrity ----

class TestDataIntegrity:
    def test_record_count(self):
        original = load_csv(PATIENTS_FILE)
        remediated = load_csv(REMEDIATED_FILE)
        min_allowed = math.ceil(len(original) * (1 - SRC_MAX_RATE))
        assert min_allowed <= len(remediated) <= len(original), \
            "Expected between {} and {} records, got {}".format(
                min_allowed, len(original), len(remediated))

    def test_columns(self):
        remediated = load_csv(REMEDIATED_FILE)
        expected = set(QI_ATTRS + [SENSITIVE])
        actual = set(remediated[0].keys())
        assert expected == actual, \
            "Expected columns {}, got {}".format(expected, actual)

    def test_sensitive_attribute_preserved(self):
        """Sensitive attribute values must form a subsequence of the original."""
        original = load_csv(PATIENTS_FILE)
        remediated = load_csv(REMEDIATED_FILE)
        orig_vals = [r[SENSITIVE] for r in original]
        rem_vals = [r[SENSITIVE] for r in remediated]
        if len(rem_vals) == len(orig_vals):
            assert rem_vals == orig_vals, \
                "Sensitive attribute values were modified or reordered"
        else:
            # Check subsequence (suppression case)
            it = iter(orig_vals)
            for rv in rem_vals:
                found = False
                for ov in it:
                    if ov == rv:
                        found = True
                        break
                assert found, \
                    "Sensitive attribute not preserved as subsequence of original"


# ---- RIC: Re-identification Control (k-anonymity) ----

class TestReidentificationControl:
    def test_all_ecs_meet_minimum_group_size(self):
        remediated = load_csv(REMEDIATED_FILE)
        ecs = get_ecs(remediated)
        for key, records in ecs.items():
            assert len(records) >= RIC_K, \
                "EC {} has {} records (need >= {})".format(key, len(records), RIC_K)


# ---- ADR: Attribute Diversity Requirement (entropy l-diversity) ----

class TestAttributeDiversity:
    def test_all_ecs_meet_entropy_threshold(self):
        remediated = load_csv(REMEDIATED_FILE)
        ecs = get_ecs(remediated)
        for key, records in ecs.items():
            values = [r[SENSITIVE] for r in records]
            counter = Counter(values)
            total = len(values)
            entropy = 0.0
            for count in counter.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log(p)
            assert entropy >= ADR_THRESHOLD - 1e-9, \
                "EC {} has entropy {:.6f} < threshold {:.6f}".format(
                    key, entropy, ADR_THRESHOLD)


# ---- DCR: Distribution Conformance (Earth Mover's Distance) ----

class TestDistributionConformance:
    def test_all_ecs_within_emd_threshold(self):
        remediated = load_csv(REMEDIATED_FILE)
        all_values = [r[SENSITIVE] for r in remediated]
        ecs = get_ecs(remediated)
        for key, records in ecs.items():
            ec_values = [r[SENSITIVE] for r in records]
            emd = compute_emd(ec_values, all_values, SEVERITY_ORDERING)
            assert emd <= DCR_THRESHOLD + 1e-9, \
                "EC {} has EMD {:.6f} > threshold {}".format(key, emd, DCR_THRESHOLD)


# ---- DDR: Dominance Disclosure Resistance ----

class TestDominanceDisclosure:
    def test_all_ecs_below_dominance_threshold(self):
        remediated = load_csv(REMEDIATED_FILE)
        ecs = get_ecs(remediated)
        for key, records in ecs.items():
            values = [r[SENSITIVE] for r in records]
            counter = Counter(values)
            max_freq = max(counter.values()) / len(values)
            assert max_freq <= DDR_THRESHOLD + 1e-9, \
                "EC {} has max_freq {:.4f} > threshold {}".format(
                    key, max_freq, DDR_THRESHOLD)


# ---- Compliance report structure ----

class TestComplianceReport:
    def test_required_fields_present(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        required = [
            "dataset_id", "generalization_levels", "num_records",
            "num_equivalence_classes", "min_ec_size", "max_ec_size",
            "avg_ec_size", "weighted_ncp", "privacy_checks"
        ]
        for field in required:
            assert field in report, "Missing field '{}' in compliance report".format(field)

    def test_dataset_id_matches_provenance(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        assert report.get("dataset_id") == EXPECTED_DATASET_ID, \
            "dataset_id '{}' does not match provenance '{}'".format(
                report.get("dataset_id"), EXPECTED_DATASET_ID)

    def test_privacy_checks_structure(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        pc = report["privacy_checks"]
        for code in ["RIC", "ADR", "DCR", "DDR"]:
            assert code in pc, "Missing control '{}' in privacy_checks".format(code)
            assert pc[code]["satisfied"] is True, \
                "Control {} not satisfied in report".format(code)

    def test_report_consistency_with_data(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        remediated = load_csv(REMEDIATED_FILE)
        assert report["num_records"] == len(remediated)

        ecs = get_ecs(remediated)
        ec_sizes = [len(records) for records in ecs.values()]
        assert report["num_equivalence_classes"] == len(ecs)
        assert report["min_ec_size"] == min(ec_sizes)
        assert report["max_ec_size"] == max(ec_sizes)

    def test_generalization_levels_present(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        gen_levels = report["generalization_levels"]
        for attr in QI_ATTRS:
            assert attr in gen_levels, \
                "Attribute '{}' missing from generalization_levels".format(attr)
            assert isinstance(gen_levels[attr], int), \
                "Generalization level for '{}' must be an integer".format(attr)
            assert gen_levels[attr] >= 0, \
                "Generalization level for '{}' must be >= 0".format(attr)


# ---- Utility analysis ----

class TestUtilityAnalysis:
    def test_weighted_ncp_in_valid_range(self):
        with open(UTILITY_FILE) as f:
            utility = json.load(f)
        assert "weighted_ncp" in utility, "Missing 'weighted_ncp' in utility analysis"
        wncp = utility["weighted_ncp"]
        assert 0 <= wncp < 1.0, \
            "Weighted NCP {} not in valid range [0, 1.0)".format(wncp)

    def test_per_attribute_ncp_present(self):
        with open(UTILITY_FILE) as f:
            utility = json.load(f)
        assert "per_attribute_ncp" in utility, \
            "Missing 'per_attribute_ncp' in utility analysis"
        pa = utility["per_attribute_ncp"]
        for attr in QI_ATTRS:
            assert attr in pa, \
                "Attribute '{}' missing from per_attribute_ncp".format(attr)

    def test_weighted_ncp_consistency(self):
        """Verify weighted_ncp equals sum of weight_i * per_attr_ncp_i."""
        with open(UTILITY_FILE) as f:
            utility = json.load(f)
        pa = utility["per_attribute_ncp"]
        expected = sum(UTILITY_WEIGHTS[attr] * pa[attr] for attr in QI_ATTRS)
        actual = utility["weighted_ncp"]
        assert abs(expected - actual) < 1e-4, \
            "Weighted NCP {} inconsistent with per-attribute NCPs (expected {})".format(
                actual, expected)

    def test_num_equivalence_classes_present(self):
        with open(UTILITY_FILE) as f:
            utility = json.load(f)
        assert "num_equivalence_classes" in utility, \
            "Missing 'num_equivalence_classes' in utility analysis"
        assert isinstance(utility["num_equivalence_classes"], int)

    def test_report_weighted_ncp_matches_utility(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        with open(UTILITY_FILE) as f:
            utility = json.load(f)
        assert abs(report["weighted_ncp"] - utility["weighted_ncp"]) < 1e-6, \
            "Weighted NCP mismatch between compliance report and utility analysis"


# ---- Generalization validity ----

class TestGeneralizationValidity:
    def test_generalized_values_from_hierarchy(self):
        remediated = load_csv(REMEDIATED_FILE)
        for attr in QI_ATTRS:
            valid_values, _ = load_hierarchy_values(attr)
            for idx, record in enumerate(remediated):
                val = record[attr]
                assert val in valid_values, \
                    "Row {}: value '{}' for '{}' not in hierarchy".format(idx, val, attr)

    def test_not_trivially_fully_generalized(self):
        with open(REPORT_FILE) as f:
            report = json.load(f)
        gen_levels = report["generalization_levels"]
        all_max = True
        for attr in QI_ATTRS:
            _, max_level = load_hierarchy_values(attr)
            if gen_levels[attr] < max_level:
                all_max = False
                break
        assert not all_max, \
            "All quasi-identifiers fully generalized — solution is trivially maximal"


# ---- Compliance certification ----

class TestCertification:
    def test_certification_required_fields(self):
        with open(CERTIFICATION_FILE) as f:
            cert = json.load(f)
        required = [
            "certification_version", "framework", "dataset_hash",
            "signature", "algorithm", "controls_verified",
            "all_controls_satisfied"
        ]
        for field in required:
            assert field in cert, \
                "Missing field '{}' in certification".format(field)

    def test_all_controls_satisfied(self):
        with open(CERTIFICATION_FILE) as f:
            cert = json.load(f)
        assert cert["all_controls_satisfied"] is True, \
            "Certification shows controls not satisfied"

    def test_certification_dataset_id(self):
        with open(CERTIFICATION_FILE) as f:
            cert = json.load(f)
        assert cert.get("dataset_id") == EXPECTED_DATASET_ID, \
            "Certification dataset_id '{}' does not match provenance '{}'".format(
                cert.get("dataset_id"), EXPECTED_DATASET_ID)

    def test_hmac_signature_valid(self):
        """Recompute the HMAC and verify it matches the certification signature."""
        with open(CERTIFICATION_FILE) as f:
            cert = json.load(f)
        with open(REPORT_FILE) as f:
            report = json.load(f)
        with open(SIGNING_KEY_FILE) as f:
            signing_key = f.read().strip()

        # Recompute dataset hash
        h = hashlib.sha256()
        with open(REMEDIATED_FILE, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        dataset_hash = h.hexdigest()
        assert cert["dataset_hash"] == dataset_hash, \
            "Dataset hash mismatch in certification"

        # Recompute HMAC
        canonical_report = json.dumps(report, sort_keys=True, separators=(',', ':'))
        message = "{}|{}".format(canonical_report, dataset_hash)
        expected_sig = hmac.new(
            signing_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        assert cert["signature"] == expected_sig, \
            "HMAC signature mismatch: expected {}, got {}".format(
                expected_sig, cert["signature"])

    def test_controls_verified_list(self):
        with open(CERTIFICATION_FILE) as f:
            cert = json.load(f)
        verified = set(cert["controls_verified"])
        expected = {"RIC", "ADR", "DCR", "DDR"}
        assert expected.issubset(verified), \
            "Missing controls in controls_verified: {}".format(
                expected - verified)


# ---- SQLite database ----

class TestSQLiteDatabase:
    def test_remediated_table_populated(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.execute('SELECT COUNT(*) FROM remediated')
        count = cursor.fetchone()[0]
        conn.close()
        assert count > 0, "remediated table in privacy.db is empty"

    def test_remediated_table_matches_csv(self):
        csv_data = load_csv(REMEDIATED_FILE)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.execute(
            'SELECT age, zipcode, marital_status, education, diagnosis '
            'FROM remediated ORDER BY record_id'
        )
        db_rows = cursor.fetchall()
        conn.close()

        assert len(db_rows) == len(csv_data), \
            "Record count mismatch: CSV has {}, DB has {}".format(
                len(csv_data), len(db_rows))

        for i, (db_row, csv_row) in enumerate(zip(db_rows, csv_data)):
            assert db_row[0] == csv_row['age'], \
                "Row {}: age mismatch".format(i)
            assert db_row[1] == csv_row['zipcode'], \
                "Row {}: zipcode mismatch".format(i)
            assert db_row[2] == csv_row['marital_status'], \
                "Row {}: marital_status mismatch".format(i)
            assert db_row[3] == csv_row['education'], \
                "Row {}: education mismatch".format(i)
            assert db_row[4] == csv_row['diagnosis'], \
                "Row {}: diagnosis mismatch".format(i)

    def test_remediated_count_within_suppression_bounds(self):
        original = load_csv(PATIENTS_FILE)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.execute('SELECT COUNT(*) FROM remediated')
        count = cursor.fetchone()[0]
        conn.close()
        min_allowed = math.ceil(len(original) * (1 - SRC_MAX_RATE))
        assert min_allowed <= count <= len(original), \
            "DB remediated count {} not in allowed range [{}, {}]".format(
                count, min_allowed, len(original))
