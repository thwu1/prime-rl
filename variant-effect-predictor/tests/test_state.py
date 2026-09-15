"""
Tests for variant annotation pipeline output.

Verifies QC report, variant effect annotations, and summary statistics.
Tests cover: REF mismatch exclusion, multi-allelic splitting, indel
left-alignment, effect classification across positive and negative strand
genes with multi-exon CDS, and summary statistics.

"""
import json
import os
import pytest


def load_results():
    """Load variant_effects.tsv keyed by (CHROM, POS, ALT)."""
    path = "/app/results/variant_effects.tsv"
    assert os.path.isfile(path), f"Output file {path} does not exist"

    results = {}
    with open(path) as f:
        header = f.readline().strip().split("\t")
        assert len(header) >= 11, f"Expected at least 11 columns, got {len(header)}"
        for line in f:
            if not line.strip():
                continue
            fields = line.strip().split("\t")
            row = {h: v for h, v in zip(header, fields)}
            key = (row["CHROM"], int(row["POS"]), row["ALT"])
            results[key] = row
    return results


@pytest.fixture(scope="module")
def results():
    return load_results()


@pytest.fixture(scope="module")
def qc_report():
    path = "/app/results/qc_report.json"
    assert os.path.isfile(path), f"QC report {path} does not exist"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def summary():
    path = "/app/results/summary.json"
    assert os.path.isfile(path), f"Summary {path} does not exist"
    with open(path) as f:
        return json.load(f)


# ==== Output file existence ====

def test_output_files_exist():
    assert os.path.isfile("/app/results/variant_effects.tsv"), \
        "variant_effects.tsv not found"
    assert os.path.isfile("/app/results/qc_report.json"), \
        "qc_report.json not found"
    assert os.path.isfile("/app/results/summary.json"), \
        "summary.json not found"


# ==== QC Report verification ====

def test_qc_ref_mismatches(qc_report):
    """Two variants had REF alleles not matching the genome."""
    assert qc_report["ref_mismatches"] == 2, \
        f"Expected 2 REF mismatches, got {qc_report['ref_mismatches']}"


def test_qc_multiallelic(qc_report):
    """One multi-allelic record should have been decomposed."""
    assert qc_report["multiallelic_split"] == 1, \
        f"Expected 1 multi-allelic split, got {qc_report['multiallelic_split']}"


def test_qc_indels_realigned(qc_report):
    """One indel should have been left-aligned to a different position."""
    assert qc_report["indels_realigned"] == 1, \
        f"Expected 1 indel realigned, got {qc_report['indels_realigned']}"


def test_qc_input_count(qc_report):
    """Raw VCF has 15 data lines."""
    assert qc_report["total_input_variants"] == 15, \
        f"Expected 15 input variants, got {qc_report['total_input_variants']}"


def test_qc_clean_count(qc_report):
    """After QC: 15 - 2 mismatches + 1 split = 14 clean variants."""
    assert qc_report["total_clean_variants"] == 14, \
        f"Expected 14 clean variants, got {qc_report['total_clean_variants']}"


# ==== Variant count and data quality handling ====

def test_clean_variant_count(results):
    """Should have exactly 14 annotated variants after QC."""
    assert len(results) == 14, f"Expected 14 clean variants, got {len(results)}"


def test_ref_mismatch_750_excluded(results):
    """Position 750 had wrong REF allele (G vs genome T) — must be excluded."""
    matching = [k for k in results if k[1] == 750]
    assert len(matching) == 0, \
        "REF-mismatch variant at pos 750 should be excluded"


def test_ref_mismatch_1450_excluded(results):
    """Position 1450 had wrong REF allele (A vs genome C) — must be excluded."""
    matching = [k for k in results if k[1] == 1450]
    assert len(matching) == 0, \
        "REF-mismatch variant at pos 1450 should be excluded"


def test_multiallelic_split_at_1604(results):
    """Position 1604 was multi-allelic (G,T) — must yield two biallelic records."""
    at_1604 = [k for k in results if k[1] == 1604]
    assert len(at_1604) == 2, \
        f"Expected 2 records at pos 1604 after multi-allelic split, got {len(at_1604)}"
    alts = sorted(k[2] for k in at_1604)
    assert alts == ["G", "T"], \
        f"Expected ALTs G and T at pos 1604, got {alts}"


def test_indel_left_aligned_to_1614(results):
    """Insertion at pos 1615 must be left-aligned to pos 1614."""
    at_1615 = [k for k in results if k[1] == 1615]
    assert len(at_1615) == 0, \
        "Non-normalized indel at pos 1615 should be realigned to 1614"
    at_1614 = [k for k in results if k[1] == 1614]
    assert len(at_1614) == 1, \
        "Left-aligned indel should appear at pos 1614"


def test_variants_sorted_by_position(results):
    """All variants must be sorted by genomic position."""
    positions = [k[1] for k in results]
    assert positions == sorted(positions), \
        "Variants must be sorted by position"


# ==== Individual variant effect annotations ====

def test_intergenic_variant(results):
    """Position 50: intergenic region, no gene overlap."""
    r = results[("chr1", 50, "A")]
    assert r["EFFECT"] == "intergenic_variant"
    assert r["GENE"] == "."


def test_synonymous_geneA(results):
    """Position 109: 3rd codon position in geneA exon1, GAT->GAC, D->D."""
    r = results[("chr1", 109, "C")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "synonymous_variant"
    assert r["AA_REF"] == "D"
    assert r["AA_ALT"] == "D"
    assert r["CODON_REF"] == "GAT"
    assert r["CODON_ALT"] == "GAC"


def test_missense_geneA(results):
    """Position 122: 1st codon position in geneA exon1, CAC->TAC, H->Y."""
    r = results[("chr1", 122, "T")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "missense_variant"
    assert r["AA_REF"] == "H"
    assert r["AA_ALT"] == "Y"
    assert r["CODON_REF"] == "CAC"
    assert r["CODON_ALT"] == "TAC"


def test_frameshift_insertion_geneA(results):
    """Position 130: 1bp insertion in geneA exon1 -> frameshift."""
    r = results[("chr1", 130, "AT")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "frameshift_variant"


def test_splice_donor_variant(results):
    """Position 251: first base of intron (GT donor site)."""
    r = results[("chr1", 251, "A")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "splice_donor_variant"


def test_intron_variant(results):
    """Position 300: middle of intron in geneA."""
    r = results[("chr1", 300, "G")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "intron_variant"


def test_splice_acceptor_variant(results):
    """Position 400: last base of intron (AG acceptor site)."""
    r = results[("chr1", 400, "T")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "splice_acceptor_variant"


def test_stop_gained_geneA(results):
    """Position 407: in geneA exon2, AAA->TAA, K->*."""
    r = results[("chr1", 407, "T")]
    assert r["GENE"] == "geneA"
    assert r["EFFECT"] == "stop_gained"
    assert r["AA_REF"] == "K"
    assert r["AA_ALT"] == "*"
    assert r["CODON_REF"] == "AAA"
    assert r["CODON_ALT"] == "TAA"


def test_multi_exon_codon_position(results):
    """Position 407 is in exon 2 of geneA. CDS offset includes 150bp from
    exon 1, so this should be codon/amino acid position 53."""
    r = results[("chr1", 407, "T")]
    if "AA_POS" in r and r["AA_POS"] != ".":
        assert int(r["AA_POS"]) == 53, \
            f"Multi-exon CDS offset not handled: expected AA_POS=53, got {r['AA_POS']}"


def test_frameshift_deletion_geneB(results):
    """Position 1256: 2bp deletion in geneB (- strand) -> frameshift."""
    r = results[("chr1", 1256, "G")]
    assert r["GENE"] == "geneB"
    assert r["EFFECT"] == "frameshift_variant"


def test_synonymous_geneB_negative_strand(results):
    """Position 1271: synonymous in geneB (- strand), ATT->ATC, I->I.

    Tests negative-strand annotation: + strand REF=A (complement=T on mRNA),
    ALT=G (complement=C). mRNA codon changes from ATT to ATC, both Isoleucine.
    """
    r = results[("chr1", 1271, "G")]
    assert r["GENE"] == "geneB"
    assert r["EFFECT"] == "synonymous_variant"
    assert r["AA_REF"] == "I"
    assert r["AA_ALT"] == "I"


def test_missense_geneB_negative_strand(results):
    """Position 1287: missense in geneB (- strand), GCA->GTA, A->V.

    Tests reverse-complement codon determination: + strand G->A at pos 1287.
    On mRNA (- strand) this changes codon 5 from GCA (Ala) to GTA (Val).
    """
    r = results[("chr1", 1287, "A")]
    assert r["GENE"] == "geneB"
    assert r["EFFECT"] == "missense_variant"
    assert r["AA_REF"] == "A"
    assert r["AA_ALT"] == "V"
    assert r["CODON_REF"] == "GCA"
    assert r["CODON_ALT"] == "GTA"


def test_missense_geneC_alt_G(results):
    """Position 1604 ALT=G (from multi-allelic split): AAC->GAC, N->D."""
    r = results[("chr1", 1604, "G")]
    assert r["GENE"] == "geneC"
    assert r["EFFECT"] == "missense_variant"
    assert r["AA_REF"] == "N"
    assert r["AA_ALT"] == "D"
    assert r["CODON_REF"] == "AAC"
    assert r["CODON_ALT"] == "GAC"


def test_missense_geneC_alt_T(results):
    """Position 1604 ALT=T (from multi-allelic split): AAC->TAC, N->Y."""
    r = results[("chr1", 1604, "T")]
    assert r["GENE"] == "geneC"
    assert r["EFFECT"] == "missense_variant"
    assert r["AA_REF"] == "N"
    assert r["AA_ALT"] == "Y"
    assert r["CODON_REF"] == "AAC"
    assert r["CODON_ALT"] == "TAC"


def test_frameshift_geneC_left_aligned(results):
    """Left-aligned 1bp insertion at pos 1614 in geneC -> frameshift."""
    r = results[("chr1", 1614, "GG")]
    assert r["GENE"] == "geneC"
    assert r["EFFECT"] == "frameshift_variant"


# ==== Summary statistics ====

def test_titv_ratio(summary):
    """Ti/Tv ratio: 6 transitions / 5 transversions = 1.20."""
    ratio = summary["titv_ratio"]
    assert abs(ratio - 1.20) < 0.05, \
        f"Ti/Tv ratio should be ~1.20, got {ratio}"


def test_effect_counts(summary):
    """Verify effect type counts across all 14 clean variants."""
    counts = summary["effect_counts"]
    assert counts.get("intergenic_variant") == 1, \
        f"intergenic_variant: expected 1, got {counts.get('intergenic_variant')}"
    assert counts.get("synonymous_variant") == 2, \
        f"synonymous_variant: expected 2, got {counts.get('synonymous_variant')}"
    assert counts.get("missense_variant") == 4, \
        f"missense_variant: expected 4, got {counts.get('missense_variant')}"
    assert counts.get("frameshift_variant") == 3, \
        f"frameshift_variant: expected 3, got {counts.get('frameshift_variant')}"
    assert counts.get("splice_donor_variant") == 1, \
        f"splice_donor_variant: expected 1, got {counts.get('splice_donor_variant')}"
    assert counts.get("splice_acceptor_variant") == 1, \
        f"splice_acceptor_variant: expected 1, got {counts.get('splice_acceptor_variant')}"
    assert counts.get("intron_variant") == 1, \
        f"intron_variant: expected 1, got {counts.get('intron_variant')}"
    assert counts.get("stop_gained") == 1, \
        f"stop_gained: expected 1, got {counts.get('stop_gained')}"


def test_genes_affected(summary):
    """All three genes should have CDS-level variants."""
    genes = sorted(summary["genes_affected"])
    assert genes == ["geneA", "geneB", "geneC"], \
        f"Expected ['geneA', 'geneB', 'geneC'], got {genes}"


def test_summary_json_structure(summary):
    """Summary JSON must have all required keys."""
    assert "effect_counts" in summary, "Missing effect_counts"
    assert "titv_ratio" in summary, "Missing titv_ratio"
    assert "genes_affected" in summary, "Missing genes_affected"
    assert isinstance(summary["effect_counts"], dict)
    assert isinstance(summary["titv_ratio"], (int, float))
    assert isinstance(summary["genes_affected"], list)
