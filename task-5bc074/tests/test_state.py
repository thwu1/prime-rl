
import os
import csv
import pytest

OUTPUT_FILE = "/app/output/variant_effects.tsv"

EXPECTED = [
    {"chrom": "chr1", "pos": 50, "ref": "A", "alt": "T", "gene": ".", "feature": "intergenic", "effect": "intergenic_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 101, "ref": "A", "alt": "G", "gene": "ALPHA", "feature": "CDS", "effect": "start_lost", "aa_change": "p.Met1Val"},
    {"chrom": "chr1", "pos": 104, "ref": "A", "alt": "G", "gene": "ALPHA", "feature": "CDS", "effect": "missense_variant", "aa_change": "p.Thr2Ala"},
    {"chrom": "chr1", "pos": 122, "ref": "GC", "alt": "G", "gene": "ALPHA", "feature": "CDS", "effect": "frameshift_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 151, "ref": "C", "alt": "T", "gene": "ALPHA", "feature": "CDS", "effect": "synonymous_variant", "aa_change": "p.His17His"},
    {"chrom": "chr1", "pos": 218, "ref": "TT", "alt": "T", "gene": "ALPHA", "feature": "CDS", "effect": "frameshift_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 226, "ref": "GGTC", "alt": "G", "gene": "ALPHA", "feature": "CDS", "effect": "inframe_deletion", "aa_change": "p.Val43del"},
    {"chrom": "chr1", "pos": 263, "ref": "A", "alt": "T", "gene": "ALPHA", "feature": "CDS", "effect": "stop_gained", "aa_change": "p.Lys55Ter"},
    {"chrom": "chr1", "pos": 299, "ref": "C", "alt": "CACG", "gene": "ALPHA", "feature": "CDS", "effect": "inframe_insertion", "aa_change": "p.67_68insThr"},
    {"chrom": "chr1", "pos": 450, "ref": "G", "alt": "A", "gene": ".", "feature": "intergenic", "effect": "intergenic_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 530, "ref": "C", "alt": "T", "gene": "BETA", "feature": "CDS", "effect": "synonymous_variant", "aa_change": "p.Cys10Cys"},
    {"chrom": "chr1", "pos": 651, "ref": "A", "alt": "T", "gene": "BETA", "feature": "splice_site", "effect": "splice_donor_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 700, "ref": "A", "alt": "C", "gene": "BETA", "feature": "intron", "effect": "intron_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 770, "ref": "G", "alt": "GA", "gene": "BETA", "feature": "CDS", "effect": "frameshift_variant", "aa_change": "."},
    {"chrom": "chr1", "pos": 800, "ref": "T", "alt": "A", "gene": "BETA", "feature": "CDS", "effect": "missense_variant", "aa_change": "p.Ile67Asn"},
    {"chrom": "chr1", "pos": 1200, "ref": "C", "alt": "T", "gene": "GAMMA", "feature": "CDS", "effect": "missense_variant", "aa_change": "p.Ala51Thr"},
    {"chrom": "chr1", "pos": 1300, "ref": "T", "alt": "G", "gene": "GAMMA", "feature": "CDS", "effect": "synonymous_variant", "aa_change": "p.Leu17Leu"},
    {"chrom": "chr1", "pos": 1400, "ref": "A", "alt": "G", "gene": ".", "feature": "intergenic", "effect": "intergenic_variant", "aa_change": "."},
]


def load_output():
    """Load the output TSV file."""
    assert os.path.exists(OUTPUT_FILE), f"Output file {OUTPUT_FILE} does not exist"
    rows = []
    with open(OUTPUT_FILE) as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            row['pos'] = int(row['POS'])
            row['chrom'] = row['CHROM']
            row['ref'] = row['REF']
            row['alt'] = row['ALT']
            row['gene'] = row['GENE']
            row['feature'] = row['FEATURE']
            row['effect'] = row['EFFECT']
            row['aa_change'] = row['AA_CHANGE']
            rows.append(row)
    return rows


class TestOutputExists:
    def test_output_file_exists(self):
        assert os.path.exists(OUTPUT_FILE), "Output file variant_effects.tsv not found"

    def test_correct_number_of_rows(self):
        rows = load_output()
        assert len(rows) == 18, f"Expected 18 variant rows, got {len(rows)}"

    def test_has_header(self):
        with open(OUTPUT_FILE) as f:
            header = f.readline().strip()
        for col in ["CHROM", "POS", "REF", "ALT", "GENE", "FEATURE", "EFFECT", "AA_CHANGE"]:
            assert col in header, f"Header missing column: {col}"


class TestIntergenicVariants:
    def test_intergenic_before_genes(self):
        rows = load_output()
        row = [r for r in rows if r['pos'] == 50]
        assert len(row) == 1, "Missing variant at position 50"
        row = row[0]
        assert row['gene'] == '.', f"Variant at 50 should be intergenic, got gene={row['gene']}"
        assert row['effect'] == 'intergenic_variant'

    def test_intergenic_between_genes(self):
        rows = load_output()
        row = [r for r in rows if r['pos'] == 450]
        assert len(row) == 1, "Missing variant at position 450"
        row = row[0]
        assert row['gene'] == '.', f"Variant at 450 should be intergenic"
        assert row['effect'] == 'intergenic_variant'

    def test_intergenic_after_genes(self):
        rows = load_output()
        row = [r for r in rows if r['pos'] == 1400]
        assert len(row) == 1, "Missing variant at position 1400"
        row = row[0]
        assert row['gene'] == '.', f"Variant at 1400 should be intergenic"
        assert row['effect'] == 'intergenic_variant'


class TestAlphaSNPs:
    def test_start_lost(self):
        """Variant at position 101 disrupts ATG start codon (ATG->GTG)."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 101][0]
        assert row['gene'] == 'ALPHA'
        assert row['effect'] == 'start_lost', f"Expected start_lost, got {row['effect']}"
        assert row['aa_change'] == 'p.Met1Val', f"Expected p.Met1Val, got {row['aa_change']}"

    def test_missense(self):
        """Variant at position 104: ACA->GCA (Thr->Ala)."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 104][0]
        assert row['gene'] == 'ALPHA'
        assert row['effect'] == 'missense_variant', f"Expected missense, got {row['effect']}"
        assert row['aa_change'] == 'p.Thr2Ala', f"Expected p.Thr2Ala, got {row['aa_change']}"

    def test_synonymous(self):
        """Variant at position 151: CAC->CAT (His->His)."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 151][0]
        assert row['gene'] == 'ALPHA'
        assert row['effect'] == 'synonymous_variant', f"Expected synonymous, got {row['effect']}"
        assert row['aa_change'] == 'p.His17His', f"Expected p.His17His, got {row['aa_change']}"

    def test_stop_gained(self):
        """Variant at position 263: AAG->TAG creates premature stop."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 263][0]
        assert row['gene'] == 'ALPHA'
        assert row['effect'] == 'stop_gained', f"Expected stop_gained, got {row['effect']}"
        assert row['aa_change'] == 'p.Lys55Ter', f"Expected p.Lys55Ter, got {row['aa_change']}"


class TestAlphaIndels:
    def test_already_normalized_deletion(self):
        """Deletion at input pos 122 (GC>G) is already left-normalized."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 122]
        assert len(row) == 1, "Variant at position 122 not found"
        row = row[0]
        assert row['ref'] == 'GC', f"Expected REF=GC, got {row['ref']}"
        assert row['alt'] == 'G', f"Expected ALT=G, got {row['alt']}"
        assert row['effect'] == 'frameshift_variant'

    def test_left_normalized_frameshift(self):
        """Deletion at input pos 220 (TT>T) must be left-normalized to pos 218 (TT>T).

        Reference has TTTT at positions 218-221. A deletion in this homopolymer
        run must be left-shifted to the leftmost equivalent position.
        """
        rows = load_output()
        row = [r for r in rows if r['pos'] == 218]
        assert len(row) == 1, "Left-normalized variant at position 218 not found (was pos 220 in VCF, should be left-shifted through TTTT run)"
        row = row[0]
        assert row['ref'] == 'TT', f"Expected left-normalized REF=TT, got {row['ref']}"
        assert row['alt'] == 'T', f"Expected left-normalized ALT=T, got {row['alt']}"
        assert row['effect'] == 'frameshift_variant'
        assert row['gene'] == 'ALPHA'

    def test_inframe_deletion(self):
        """3bp deletion at position 226 (GGTC>G) removes one codon."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 226][0]
        assert row['effect'] == 'inframe_deletion', f"Expected inframe_deletion, got {row['effect']}"
        assert row['aa_change'] == 'p.Val43del', f"Expected p.Val43del, got {row['aa_change']}"

    def test_inframe_insertion(self):
        """3bp insertion at position 299 (C>CACG) inserts one codon."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 299][0]
        assert row['effect'] == 'inframe_insertion', f"Expected inframe_insertion, got {row['effect']}"
        assert row['aa_change'] == 'p.67_68insThr', f"Expected p.67_68insThr, got {row['aa_change']}"


class TestBetaGene:
    def test_exon1_synonymous(self):
        """SNP in BETA exon1 at position 530."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 530][0]
        assert row['gene'] == 'BETA'
        assert row['feature'] == 'CDS'
        assert row['effect'] == 'synonymous_variant'
        assert row['aa_change'] == 'p.Cys10Cys'

    def test_splice_donor(self):
        """Variant at position 651 is the first base of BETA intron (splice donor)."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 651][0]
        assert row['gene'] == 'BETA'
        assert row['feature'] == 'splice_site', f"Expected splice_site, got {row['feature']}"
        assert row['effect'] == 'splice_donor_variant', f"Expected splice_donor_variant, got {row['effect']}"

    def test_intron_variant(self):
        """Variant at position 700 is in BETA intron."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 700][0]
        assert row['gene'] == 'BETA'
        assert row['feature'] == 'intron'
        assert row['effect'] == 'intron_variant'

    def test_exon2_frameshift(self):
        """1bp insertion in BETA exon2 at position 770."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 770][0]
        assert row['gene'] == 'BETA'
        assert row['feature'] == 'CDS'
        assert row['effect'] == 'frameshift_variant'

    def test_exon2_missense(self):
        """SNP in BETA exon2 at position 800: codon 67 across the splice junction."""
        rows = load_output()
        row = [r for r in rows if r['pos'] == 800][0]
        assert row['gene'] == 'BETA'
        assert row['feature'] == 'CDS'
        assert row['effect'] == 'missense_variant', f"Expected missense, got {row['effect']}"
        assert row['aa_change'] == 'p.Ile67Asn', f"Expected p.Ile67Asn, got {row['aa_change']}"


class TestGammaReverseStrand:
    def test_gamma_missense(self):
        """SNP at position 1200 in reverse-strand gene GAMMA.

        On the + strand, C>T at pos 1200.
        On the - strand CDS, this complements to G>A.
        The offset in the CDS is 1350-1200=150 (codon 51, position 1).
        Reference codon GCT (Ala) -> ACT (Thr): missense.
        """
        rows = load_output()
        row = [r for r in rows if r['pos'] == 1200][0]
        assert row['gene'] == 'GAMMA', f"Expected GAMMA, got {row['gene']}"
        assert row['feature'] == 'CDS'
        assert row['effect'] == 'missense_variant', f"Expected missense, got {row['effect']}"
        assert row['aa_change'] == 'p.Ala51Thr', f"Expected p.Ala51Thr, got {row['aa_change']}"

    def test_gamma_synonymous(self):
        """SNP at position 1300 in reverse-strand gene GAMMA.

        On the + strand, T>G at pos 1300.
        On the - strand CDS, this complements to A>C.
        The offset in CDS is 1350-1300=50 (codon 17, position 3).
        Reference codon CTA (Leu) -> CTC (Leu): synonymous.
        """
        rows = load_output()
        row = [r for r in rows if r['pos'] == 1300][0]
        assert row['gene'] == 'GAMMA', f"Expected GAMMA, got {row['gene']}"
        assert row['feature'] == 'CDS'
        assert row['effect'] == 'synonymous_variant', f"Expected synonymous, got {row['effect']}"
        assert row['aa_change'] == 'p.Leu17Leu', f"Expected p.Leu17Leu, got {row['aa_change']}"


class TestFullOutput:
    """Verify every row matches exactly."""

    def test_all_variants_match(self):
        rows = load_output()
        assert len(rows) == len(EXPECTED), f"Expected {len(EXPECTED)} rows, got {len(rows)}"

        for i, exp in enumerate(EXPECTED):
            row = rows[i]
            for key in ['chrom', 'pos', 'ref', 'alt', 'gene', 'feature', 'effect', 'aa_change']:
                actual = row[key]
                expected_val = exp[key]
                if key == 'pos':
                    actual = int(actual)
                assert actual == expected_val, (
                    f"Row {i+1} (pos={exp['pos']}): {key} mismatch: "
                    f"expected '{expected_val}', got '{actual}'"
                )
