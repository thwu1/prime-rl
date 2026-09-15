
import json
import csv
import math
import os
import pytest
from scipy import stats


# ── helpers to parse source data independently ──────────────────────────


def parse_soft_samples(path):
    """Parse SOFT file and return list of sample dicts with metadata + expression."""
    samples = []
    current = None
    in_table = False
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("^SAMPLE"):
                current = {"id": line.split("=")[1].strip(), "chars": {}, "expr": {}}
                samples.append(current)
                in_table = False
            elif current is not None:
                if line == "!Sample_table_begin":
                    in_table = True
                    continue
                if line == "!Sample_table_end":
                    in_table = False
                    continue
                if in_table:
                    if line.startswith("ID_REF"):
                        continue
                    parts = line.split("\t")
                    if len(parts) == 2:
                        current["expr"][parts[0]] = float(parts[1])
                elif line.startswith("!Sample_title"):
                    current["title"] = line.split("=", 1)[1].strip()
                elif line.startswith("!Sample_organism_ch1"):
                    current["organism"] = line.split("=", 1)[1].strip()
                elif line.startswith("!Sample_platform_id"):
                    current["platform_id"] = line.split("=", 1)[1].strip()
                elif line.startswith("!Sample_characteristics_ch1"):
                    val = line.split("=", 1)[1].strip()
                    if ":" in val:
                        tag, v = val.split(":", 1)
                        current["chars"][tag.strip()] = v.strip()
    return samples


def parse_platform(path):
    """Parse platform annotation TSV. Return dict: probe_id -> list of gene symbols."""
    mapping = {}
    with open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            probe_id = row["ID"]
            gene_sym = row["Gene Symbol"]
            if gene_sym == "---" or probe_id.startswith("AFFX-"):
                mapping[probe_id] = []
            elif " /// " in gene_sym:
                mapping[probe_id] = [g.strip() for g in gene_sym.split(" /// ")]
            else:
                mapping[probe_id] = [gene_sym.strip()]
    return mapping


def parse_sra_runinfo(path):
    """Parse SRA RunInfo CSV. Return list of dicts."""
    with open(path) as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def compute_expected_de(samples, probe_gene_map):
    """Compute expected DE results using paired t-tests + BH correction."""
    # Group samples by patient and type
    patient_map = {}
    for s in samples:
        pid = s["chars"]["patient id"]
        stype = "tumor" if "ccRCC" in s["chars"].get("tissue", "") else "normal"
        patient_map.setdefault(pid, {})[stype] = s

    patients_sorted = sorted(patient_map.keys())
    probe_ids = sorted(samples[0]["expr"].keys())

    results = []
    for probe_id in probe_ids:
        normals = []
        tumors = []
        for pid in patients_sorted:
            if "normal" in patient_map[pid] and "tumor" in patient_map[pid]:
                normals.append(patient_map[pid]["normal"]["expr"][probe_id])
                tumors.append(patient_map[pid]["tumor"]["expr"][probe_id])

        mean_n = sum(normals) / len(normals)
        mean_t = sum(tumors) / len(tumors)
        log2fc = mean_t - mean_n  # already log2 scale

        # Paired t-test
        diffs = [t - n for t, n in zip(tumors, normals)]
        n = len(diffs)
        mean_d = sum(diffs) / n
        var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
        se_d = math.sqrt(var_d / n) if var_d > 0 else 1e-10
        t_stat = mean_d / se_d

        # Two-tailed p-value
        p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)

        genes = probe_gene_map.get(probe_id, [])
        gene_str = " /// ".join(genes) if genes else "---"

        results.append({
            "probe_id": probe_id,
            "gene_symbol": gene_str,
            "mean_normal": mean_n,
            "mean_tumor": mean_t,
            "log2_fold_change": log2fc,
            "t_statistic": t_stat,
            "p_value": p_val,
        })

    # BH correction
    results_sorted = sorted(results, key=lambda x: x["p_value"])
    m = len(results_sorted)
    for i, r in enumerate(results_sorted):
        r["adj_p_value"] = min(1.0, r["p_value"] * m / (i + 1))

    # Enforce monotonicity (from bottom up)
    for i in range(m - 2, -1, -1):
        results_sorted[i]["adj_p_value"] = min(
            results_sorted[i]["adj_p_value"],
            results_sorted[i + 1]["adj_p_value"],
        )

    return sorted(results_sorted, key=lambda x: x["adj_p_value"])


def compute_expected_discrepancies(samples, sra_rows):
    """Find metadata discrepancies between GEO samples and SRA rows."""
    # Build SRA lookup by SampleName
    sra_by_name = {}
    for row in sra_rows:
        sra_by_name[row["SampleName"]] = row

    discrepancies = []
    for s in samples:
        title = s["title"]
        sra_row = sra_by_name.get(title)
        if sra_row is None:
            # Title not found in SRA → discrepancy in sample name
            # Find the SRA row by index position
            idx = samples.index(s)
            if idx < len(sra_rows):
                sra_row_by_idx = sra_rows[idx]
                discrepancies.append({
                    "geo_sample_id": s["id"],
                    "sra_run_id": sra_row_by_idx["Run"],
                    "field": "sample_name",
                    "geo_value": title,
                    "sra_value": sra_row_by_idx["SampleName"],
                })
            continue

        # Check organism
        geo_org = s.get("organism", "")
        sra_org = sra_row.get("ScientificName", "")
        if geo_org != sra_org:
            discrepancies.append({
                "geo_sample_id": s["id"],
                "sra_run_id": sra_row["Run"],
                "field": "organism",
                "geo_value": geo_org,
                "sra_value": sra_org,
            })

        # Check library source (total RNA → TRANSCRIPTOMIC)
        sra_source = sra_row.get("LibrarySource", "")
        if sra_source != "TRANSCRIPTOMIC":
            discrepancies.append({
                "geo_sample_id": s["id"],
                "sra_run_id": sra_row["Run"],
                "field": "library_source",
                "geo_value": "TRANSCRIPTOMIC",
                "sra_value": sra_source,
            })

    return discrepancies


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def soft_samples():
    return parse_soft_samples("/app/data/series.soft")


@pytest.fixture(scope="module")
def probe_gene_map():
    return parse_platform("/app/data/platform_annotation.tsv")


@pytest.fixture(scope="module")
def sra_rows():
    return parse_sra_runinfo("/app/data/sra_runinfo.csv")


@pytest.fixture(scope="module")
def expected_de(soft_samples, probe_gene_map):
    return compute_expected_de(soft_samples, probe_gene_map)


@pytest.fixture(scope="module")
def expected_discrepancies(soft_samples, sra_rows):
    return compute_expected_discrepancies(soft_samples, sra_rows)


# ── tests ───────────────────────────────────────────────────────────────


class TestExperimentalDesign:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/experimental_design.tsv"), \
            "experimental_design.tsv not found"

    def test_header(self):
        with open("/app/output/experimental_design.tsv") as f:
            header = f.readline().strip().split("\t")
        expected_cols = [
            "sample_id", "title", "tissue", "tumor_stage",
            "patient_id", "gender", "age", "platform_id",
        ]
        assert header == expected_cols, f"Header mismatch: {header}"

    def test_row_count(self, soft_samples):
        with open("/app/output/experimental_design.tsv") as f:
            lines = [l for l in f.readlines() if l.strip()]
        # header + 16 data rows
        assert len(lines) == 17, f"Expected 17 lines (header + 16 samples), got {len(lines)}"

    def test_sample_ids(self, soft_samples):
        with open("/app/output/experimental_design.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        output_ids = sorted(r["sample_id"] for r in rows)
        expected_ids = sorted(s["id"] for s in soft_samples)
        assert output_ids == expected_ids, "Sample IDs mismatch"

    def test_sorted_by_sample_id(self):
        with open("/app/output/experimental_design.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        ids = [r["sample_id"] for r in rows]
        assert ids == sorted(ids), "Rows not sorted by sample_id"

    def test_metadata_values(self, soft_samples):
        with open("/app/output/experimental_design.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = {r["sample_id"]: r for r in reader}

        for s in soft_samples:
            row = rows.get(s["id"])
            assert row is not None, f"Missing sample {s['id']}"
            assert row["title"] == s["title"], f"Title mismatch for {s['id']}"
            assert row["patient_id"] == s["chars"]["patient id"], \
                f"Patient ID mismatch for {s['id']}"
            assert row["platform_id"] == "GPL570", \
                f"Platform mismatch for {s['id']}"


class TestProbeGeneMap:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/probe_gene_map.json"), \
            "probe_gene_map.json not found"

    def test_valid_json(self):
        with open("/app/output/probe_gene_map.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_probe_count(self, probe_gene_map):
        with open("/app/output/probe_gene_map.json") as f:
            data = json.load(f)
        assert len(data) == len(probe_gene_map), \
            f"Expected {len(probe_gene_map)} probes, got {len(data)}"

    def test_multi_mapped_probes(self, probe_gene_map):
        """Multi-mapped probes must have multiple gene symbols."""
        with open("/app/output/probe_gene_map.json") as f:
            data = json.load(f)

        multi_mapped = {k: v for k, v in probe_gene_map.items() if len(v) > 1}
        for probe_id, expected_genes in multi_mapped.items():
            assert probe_id in data, f"Missing multi-mapped probe {probe_id}"
            output_genes = sorted(data[probe_id])
            expected_sorted = sorted(expected_genes)
            assert output_genes == expected_sorted, \
                f"Multi-mapped probe {probe_id}: expected {expected_sorted}, got {output_genes}"

    def test_unmapped_probes(self, probe_gene_map):
        """Unmapped and control probes must map to empty list."""
        with open("/app/output/probe_gene_map.json") as f:
            data = json.load(f)

        unmapped = {k: v for k, v in probe_gene_map.items() if len(v) == 0}
        for probe_id in unmapped:
            assert probe_id in data, f"Missing unmapped probe {probe_id}"
            assert data[probe_id] == [], \
                f"Unmapped probe {probe_id} should map to [], got {data[probe_id]}"

    def test_single_mapped_probes(self, probe_gene_map):
        """Single-mapped probes must have exactly one gene symbol."""
        with open("/app/output/probe_gene_map.json") as f:
            data = json.load(f)

        single = {k: v for k, v in probe_gene_map.items() if len(v) == 1}
        for probe_id, expected_genes in single.items():
            assert probe_id in data, f"Missing probe {probe_id}"
            assert data[probe_id] == expected_genes, \
                f"Probe {probe_id}: expected {expected_genes}, got {data[probe_id]}"


class TestReconciliationReport:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/reconciliation_report.json"), \
            "reconciliation_report.json not found"

    def test_valid_json(self):
        with open("/app/output/reconciliation_report.json") as f:
            data = json.load(f)
        assert "discrepancies" in data, "Missing 'discrepancies' key"
        assert isinstance(data["discrepancies"], list)

    def test_discrepancy_count(self, expected_discrepancies):
        with open("/app/output/reconciliation_report.json") as f:
            data = json.load(f)
        assert len(data["discrepancies"]) == len(expected_discrepancies), \
            f"Expected {len(expected_discrepancies)} discrepancies, got {len(data['discrepancies'])}"

    def test_organism_discrepancy(self, expected_discrepancies):
        with open("/app/output/reconciliation_report.json") as f:
            data = json.load(f)

        org_expected = [d for d in expected_discrepancies if d["field"] == "organism"]
        org_found = [d for d in data["discrepancies"] if d["field"] == "organism"]
        assert len(org_found) == len(org_expected), \
            f"Expected {len(org_expected)} organism discrepancies, got {len(org_found)}"

        for exp in org_expected:
            match = [d for d in org_found if d["geo_sample_id"] == exp["geo_sample_id"]]
            assert len(match) == 1, f"Missing organism discrepancy for {exp['geo_sample_id']}"
            assert match[0]["sra_value"] == exp["sra_value"]

    def test_library_source_discrepancy(self, expected_discrepancies):
        with open("/app/output/reconciliation_report.json") as f:
            data = json.load(f)

        lib_expected = [d for d in expected_discrepancies if d["field"] == "library_source"]
        lib_found = [d for d in data["discrepancies"] if d["field"] == "library_source"]
        assert len(lib_found) == len(lib_expected), \
            f"Expected {len(lib_expected)} library_source discrepancies, got {len(lib_found)}"

    def test_sample_name_discrepancy(self, expected_discrepancies):
        with open("/app/output/reconciliation_report.json") as f:
            data = json.load(f)

        name_expected = [d for d in expected_discrepancies if d["field"] == "sample_name"]
        name_found = [d for d in data["discrepancies"] if d["field"] == "sample_name"]
        assert len(name_found) == len(name_expected), \
            f"Expected {len(name_expected)} sample_name discrepancies, got {len(name_found)}"

    def test_discrepancy_structure(self):
        with open("/app/output/reconciliation_report.json") as f:
            data = json.load(f)
        required_keys = {"geo_sample_id", "sra_run_id", "field", "geo_value", "sra_value"}
        for d in data["discrepancies"]:
            assert required_keys.issubset(d.keys()), \
                f"Discrepancy missing keys: {required_keys - set(d.keys())}"


class TestDifferentialExpression:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/de_results.tsv"), \
            "de_results.tsv not found"

    def test_header(self):
        with open("/app/output/de_results.tsv") as f:
            header = f.readline().strip().split("\t")
        expected = [
            "probe_id", "gene_symbol", "mean_normal", "mean_tumor",
            "log2_fold_change", "t_statistic", "p_value", "adj_p_value",
        ]
        assert header == expected, f"Header mismatch: {header}"

    def test_row_count(self, probe_gene_map):
        with open("/app/output/de_results.tsv") as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) == len(probe_gene_map) + 1, \
            f"Expected {len(probe_gene_map) + 1} lines, got {len(lines)}"

    def test_sorted_by_adj_p_value(self):
        with open("/app/output/de_results.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        adj_pvals = [float(r["adj_p_value"]) for r in rows]
        assert adj_pvals == sorted(adj_pvals), \
            "Results not sorted by adj_p_value ascending"

    def test_fold_changes(self, expected_de):
        with open("/app/output/de_results.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            output_rows = {r["probe_id"]: r for r in reader}

        for exp in expected_de:
            probe = exp["probe_id"]
            assert probe in output_rows, f"Missing probe {probe}"
            out_fc = float(output_rows[probe]["log2_fold_change"])
            assert abs(out_fc - exp["log2_fold_change"]) < 0.01, \
                f"Probe {probe} log2FC: expected {exp['log2_fold_change']:.4f}, got {out_fc:.4f}"

    def test_p_values(self, expected_de):
        with open("/app/output/de_results.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            output_rows = {r["probe_id"]: r for r in reader}

        for exp in expected_de:
            probe = exp["probe_id"]
            out_p = float(output_rows[probe]["p_value"])
            # For very small p-values, use relative tolerance
            if exp["p_value"] < 1e-10:
                assert out_p < 1e-6, \
                    f"Probe {probe} p-value should be very small, got {out_p}"
            else:
                rtol = 0.05
                assert abs(out_p - exp["p_value"]) <= rtol * max(abs(exp["p_value"]), 1e-15), \
                    f"Probe {probe} p-value: expected {exp['p_value']:.6e}, got {out_p:.6e}"

    def test_adj_p_values_valid(self, expected_de):
        with open("/app/output/de_results.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        for r in rows:
            adj_p = float(r["adj_p_value"])
            p = float(r["p_value"])
            assert 0 <= adj_p <= 1.0, f"adj_p_value out of [0,1]: {adj_p}"
            assert adj_p >= p - 1e-10, \
                f"adj_p_value ({adj_p}) < p_value ({p}) for probe {r['probe_id']}"

    def test_significant_probes_direction(self, expected_de):
        """Verify that known up-regulated probes have positive fold change."""
        with open("/app/output/de_results.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            output_rows = {r["probe_id"]: r for r in reader}

        # Check a few known up-regulated probes
        up_probes = ["205199_at", "210512_s_at", "200989_at"]  # CA9, VEGFA, HIF1A
        for probe in up_probes:
            if probe in output_rows:
                fc = float(output_rows[probe]["log2_fold_change"])
                assert fc > 0, f"Up-regulated probe {probe} has negative FC: {fc}"

        # Check a few known down-regulated probes
        down_probes = ["205020_s_at", "205352_at"]  # AQP1, SERPINI1
        for probe in down_probes:
            if probe in output_rows:
                fc = float(output_rows[probe]["log2_fold_change"])
                assert fc < 0, f"Down-regulated probe {probe} has positive FC: {fc}"


class TestTopGenes:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/top_genes.txt"), \
            "top_genes.txt not found"

    def test_sorted_alphabetically(self):
        with open("/app/output/top_genes.txt") as f:
            genes = [l.strip() for l in f if l.strip()]
        assert genes == sorted(genes), "Genes not sorted alphabetically"

    def test_no_duplicates(self):
        with open("/app/output/top_genes.txt") as f:
            genes = [l.strip() for l in f if l.strip()]
        assert len(genes) == len(set(genes)), "Duplicate genes found"

    def test_no_unmapped(self):
        with open("/app/output/top_genes.txt") as f:
            genes = [l.strip() for l in f if l.strip()]
        assert "---" not in genes, "Unmapped marker '---' in top genes"

    def test_contains_expected_genes(self, expected_de, probe_gene_map):
        """Known cancer genes should be in the significant list."""
        with open("/app/output/top_genes.txt") as f:
            output_genes = set(l.strip() for l in f if l.strip())

        # Compute expected significant genes
        expected_sig_genes = set()
        for r in expected_de:
            if r["adj_p_value"] < 0.05:
                genes = probe_gene_map.get(r["probe_id"], [])
                for g in genes:
                    expected_sig_genes.add(g)

        assert output_genes == expected_sig_genes, \
            f"Gene list mismatch. Missing: {expected_sig_genes - output_genes}. " \
            f"Extra: {output_genes - expected_sig_genes}"

    def test_known_cancer_genes_present(self):
        """CA9 and VEGFA should definitely be significant in ccRCC."""
        with open("/app/output/top_genes.txt") as f:
            genes = set(l.strip() for l in f if l.strip())
        assert "CA9" in genes, "CA9 (classic ccRCC marker) not in significant genes"
        assert "VEGFA" in genes, "VEGFA not in significant genes"
