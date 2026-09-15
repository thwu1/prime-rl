
import os
import subprocess
import pytest

RESULTS_DIR = "/app/results"


def read_result(filename):
    """Read a result file and return stripped content."""
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.exists(path), f"Result file {filename} does not exist in {RESULTS_DIR}"
    with open(path) as f:
        return f.read().strip()


class TestResultsExist:
    def test_results_directory_exists(self):
        assert os.path.isdir(RESULTS_DIR), f"Results directory {RESULTS_DIR} does not exist"

    def test_denovo_count_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "denovo_count.txt"))

    def test_recessive_count_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "recessive_count.txt"))

    def test_compound_het_genes_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "compound_het_genes.txt"))

    def test_top_candidate_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "top_candidate.txt"))


class TestAnnotationIntegrity:
    def test_annotated_vcf_has_pop_af_field(self):
        """Verify the annotation pipeline correctly maps population frequency
        to the expected INFO field name used by downstream filters."""
        result = subprocess.run(
            ["bcftools", "view", "-h", "/app/annotated.vcf.gz"],
            capture_output=True, text=True,
        )
        assert "pop_af" in result.stdout, (
            "Annotated VCF does not contain 'pop_af' INFO field. "
            "Review annotation configuration for field naming consistency "
            "with downstream filter expressions."
        )


class TestDenovo:
    def test_denovo_count(self):
        """Verify de novo variant count reflects correct application of all
        clinical-grade quality, evidence, and frequency criteria."""
        content = read_result("denovo_count.txt")
        assert content == "3", (
            f"Expected 3 de novo variants, got '{content}'. "
            "Verify that population frequency thresholds, genotype quality, "
            "read depth, and parental evidence filters are all correctly applied."
        )


class TestRecessive:
    def test_recessive_count(self):
        """Verify autosomal recessive variant count after all required filters."""
        content = read_result("recessive_count.txt")
        assert content == "2", (
            f"Expected 2 autosomal recessive variants, got '{content}'. "
            "Ensure frequency-based filtering is consistently applied "
            "across all inheritance models."
        )


class TestCompoundHet:
    def test_compound_het_genes(self):
        """Verify compound heterozygous gene identification with correct
        phase-by-inheritance pairing."""
        content = read_result("compound_het_genes.txt")
        genes = sorted([g.strip() for g in content.splitlines() if g.strip()])
        assert genes == ["COMT"], (
            f"Expected compound het gene ['COMT'], got {genes}."
        )


class TestTopCandidate:
    def test_top_candidate(self):
        """Verify the top candidate reflects correct clinical variant
        prioritization methodology."""
        content = read_result("top_candidate.txt")
        assert content == "chr22:16150000:C:T", (
            f"Expected top candidate 'chr22:16150000:C:T', got '{content}'. "
            "Review variant ranking methodology and the relative weight of "
            "consequence type versus computational prediction scores."
        )
