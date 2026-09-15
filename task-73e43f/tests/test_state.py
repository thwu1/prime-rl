
import os
import json
import math
import shutil
import subprocess
import pytest

RESULTS_DIR = "/app/results"


@pytest.fixture(scope="session", autouse=True)
def pipeline_run():
    """Clean up any previous runs and execute the Nextflow pipeline."""
    for d in ["/app/.nextflow", "/app/work", "/app/results", "/app/null"]:
        shutil.rmtree(d, ignore_errors=True)
    for f in ["/app/.nextflow.log", "/app/.nextflow.log.1"]:
        if os.path.exists(f):
            os.remove(f)

    try:
        result = subprocess.run(
            ["nextflow", "run", "main.nf", "-ansi-log", "false"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Pipeline timed out after 300 seconds")
    except FileNotFoundError:
        pytest.fail("nextflow command not found - is Nextflow installed?")
    return result


def _read_freq_file(filepath):
    """Read a tab-separated word frequency file into dict {word: count}."""
    counts = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                counts[parts[0]] = int(parts[1])
    return counts


def _read_tf_file(filepath):
    """Read a tab-separated TF file into dict {word: float}."""
    tfs = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                tfs[parts[0]] = float(parts[1])
    return tfs


def _read_idf_file(filepath):
    """Read a tab-separated IDF file into dict {word: (df, idf)}."""
    entries = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 3:
                entries[parts[0]] = (int(parts[1]), float(parts[2]))
    return entries


def _read_summary():
    """Read and parse summary.json."""
    with open(f"{RESULTS_DIR}/summary.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------
class TestPipelineExecution:
    def test_pipeline_exits_zero(self, pipeline_run):
        assert pipeline_run.returncode == 0, (
            f"Pipeline failed with exit code {pipeline_run.returncode}\n"
            f"STDOUT (last 3000 chars):\n{pipeline_run.stdout[-3000:]}\n"
            f"STDERR (last 3000 chars):\n{pipeline_run.stderr[-3000:]}"
        )


# ---------------------------------------------------------------------------
# Output file existence
# ---------------------------------------------------------------------------
class TestOutputFilesExist:
    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_wordcount_file_exists(self, pipeline_run, sample):
        path = f"{RESULTS_DIR}/per_sample/{sample}_wordcounts.txt"
        assert os.path.isfile(path), f"{sample}_wordcounts.txt not found at {path}"

    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_filtered_file_exists(self, pipeline_run, sample):
        path = f"{RESULTS_DIR}/filtered/{sample}_filtered.txt"
        assert os.path.isfile(path), f"{sample}_filtered.txt not found at {path}"

    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_tf_file_exists(self, pipeline_run, sample):
        path = f"{RESULTS_DIR}/normalized/{sample}_tf.txt"
        assert os.path.isfile(path), f"{sample}_tf.txt not found at {path}"

    def test_idf_file_exists(self, pipeline_run):
        path = f"{RESULTS_DIR}/doc_freq/idf.tsv"
        assert os.path.isfile(path), f"idf.tsv not found at {path}"

    def test_summary_file_exists(self, pipeline_run):
        path = f"{RESULTS_DIR}/summary.json"
        assert os.path.isfile(path), f"summary.json not found at {path}"


# ---------------------------------------------------------------------------
# Word count correctness
# ---------------------------------------------------------------------------
class TestWordCounts:
    def test_doc_alpha_the_count(self, pipeline_run):
        counts = _read_freq_file(
            f"{RESULTS_DIR}/per_sample/doc_alpha_wordcounts.txt"
        )
        assert counts.get("the") == 4, (
            f"Expected 'the'=4 in doc_alpha, got {counts.get('the')}"
        )

    def test_doc_alpha_fox_count(self, pipeline_run):
        counts = _read_freq_file(
            f"{RESULTS_DIR}/per_sample/doc_alpha_wordcounts.txt"
        )
        assert counts.get("fox") == 1

    def test_doc_beta_the_count(self, pipeline_run):
        counts = _read_freq_file(
            f"{RESULTS_DIR}/per_sample/doc_beta_wordcounts.txt"
        )
        assert counts.get("the") == 3, (
            f"Expected 'the'=3 in doc_beta, got {counts.get('the')}"
        )

    def test_doc_beta_to_count(self, pipeline_run):
        counts = _read_freq_file(
            f"{RESULTS_DIR}/per_sample/doc_beta_wordcounts.txt"
        )
        assert counts.get("to") == 3, (
            f"Expected 'to'=3 in doc_beta, got {counts.get('to')}"
        )

    def test_doc_gamma_not_count(self, pipeline_run):
        counts = _read_freq_file(
            f"{RESULTS_DIR}/per_sample/doc_gamma_wordcounts.txt"
        )
        assert counts.get("not") == 1


# ---------------------------------------------------------------------------
# Filtering correctness
# ---------------------------------------------------------------------------
class TestFiltering:
    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_no_short_words_in_filtered(self, pipeline_run, sample):
        counts = _read_freq_file(f"{RESULTS_DIR}/filtered/{sample}_filtered.txt")
        found_short = [w for w in counts if len(w) < 3]
        assert not found_short, (
            f"Short words found in {sample}_filtered.txt: {found_short}"
        )

    def test_doc_alpha_filtered_has_fox(self, pipeline_run):
        counts = _read_freq_file(f"{RESULTS_DIR}/filtered/doc_alpha_filtered.txt")
        assert "fox" in counts, "Expected 'fox' in doc_alpha filtered output"

    def test_doc_alpha_filtered_no_a(self, pipeline_run):
        counts = _read_freq_file(f"{RESULTS_DIR}/filtered/doc_alpha_filtered.txt")
        assert "a" not in counts, "'a' (length 1) should be filtered from doc_alpha"

    def test_doc_beta_filtered_no_to(self, pipeline_run):
        counts = _read_freq_file(f"{RESULTS_DIR}/filtered/doc_beta_filtered.txt")
        assert "to" not in counts, "'to' (length 2) should be filtered from doc_beta"

    def test_doc_gamma_filtered_no_is(self, pipeline_run):
        counts = _read_freq_file(f"{RESULTS_DIR}/filtered/doc_gamma_filtered.txt")
        assert "is" not in counts, "'is' (length 2) should be filtered from doc_gamma"


# ---------------------------------------------------------------------------
# TF normalization correctness
# ---------------------------------------------------------------------------
class TestNormalization:
    def test_doc_alpha_the_tf(self, pipeline_run):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_alpha_tf.txt")
        expected = 4.0 / 19.0
        assert abs(tfs.get("the", 0) - expected) < 1e-5, (
            f"Expected the TF ~{expected:.6f}, got {tfs.get('the')}"
        )

    def test_doc_alpha_fox_tf(self, pipeline_run):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_alpha_tf.txt")
        expected = 1.0 / 19.0
        assert abs(tfs.get("fox", 0) - expected) < 1e-5

    def test_doc_alpha_unique_count(self, pipeline_run):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_alpha_tf.txt")
        assert len(tfs) == 16, f"Expected 16 unique words in doc_alpha TF, got {len(tfs)}"

    def test_doc_beta_the_tf(self, pipeline_run):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_beta_tf.txt")
        expected = 3.0 / 15.0
        assert abs(tfs.get("the", 0) - expected) < 1e-5

    def test_doc_beta_unique_count(self, pipeline_run):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_beta_tf.txt")
        assert len(tfs) == 13, f"Expected 13 unique words in doc_beta TF, got {len(tfs)}"

    def test_doc_gamma_uniform_tf(self, pipeline_run):
        """doc_gamma has 14 unique filtered words, all with count=1, so each TF=1/14."""
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_gamma_tf.txt")
        expected = 1.0 / 14.0
        for word, tf in tfs.items():
            assert abs(tf - expected) < 1e-5, (
                f"doc_gamma '{word}': expected TF ~{expected:.6f}, got {tf}"
            )

    def test_doc_gamma_unique_count(self, pipeline_run):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/doc_gamma_tf.txt")
        assert len(tfs) == 14, f"Expected 14 unique words in doc_gamma TF, got {len(tfs)}"

    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_tf_values_sum_to_one(self, pipeline_run, sample):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/{sample}_tf.txt")
        total = sum(tfs.values())
        assert abs(total - 1.0) < 1e-4, (
            f"{sample} TF sum = {total}, expected ~1.0"
        )

    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_no_short_words_in_tf(self, pipeline_run, sample):
        tfs = _read_tf_file(f"{RESULTS_DIR}/normalized/{sample}_tf.txt")
        found_short = [w for w in tfs if len(w) < 3]
        assert not found_short, (
            f"Short words found in {sample}_tf.txt: {found_short}"
        )

    @pytest.mark.parametrize("sample", ["doc_alpha", "doc_beta", "doc_gamma"])
    def test_tf_sorted_correctly(self, pipeline_run, sample):
        """TF file must be sorted by tf descending, then word ascending for ties."""
        with open(f"{RESULTS_DIR}/normalized/{sample}_tf.txt") as f:
            lines = [l.strip() for l in f if l.strip()]
        entries = [(l.split("\t")[0], float(l.split("\t")[1])) for l in lines]
        for i in range(len(entries) - 1):
            word_a, tf_a = entries[i]
            word_b, tf_b = entries[i + 1]
            if abs(tf_a - tf_b) > 1e-6:
                assert tf_a > tf_b, (
                    f"TF not sorted descending: {word_a}({tf_a:.6f}) "
                    f"before {word_b}({tf_b:.6f})"
                )
            else:
                assert word_a < word_b, (
                    f"Tied TFs not sorted alphabetically: "
                    f"'{word_a}' before '{word_b}'"
                )


# ---------------------------------------------------------------------------
# IDF correctness
# ---------------------------------------------------------------------------
class TestIDF:
    def test_idf_entry_count(self, pipeline_run):
        """There are 40 unique filtered words across all 3 documents."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        assert len(entries) == 40, (
            f"Expected 40 entries in idf.tsv, got {len(entries)}"
        )

    def test_idf_the_df(self, pipeline_run):
        """'the' appears in doc_alpha and doc_beta: df=2."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        assert entries["the"][0] == 2, (
            f"Expected df=2 for 'the', got {entries['the'][0]}"
        )

    def test_idf_the_idf_value(self, pipeline_run):
        """IDF('the') = ln(3/2) ≈ 0.405465."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        expected = math.log(3.0 / 2.0)
        assert abs(entries["the"][1] - expected) < 1e-5, (
            f"Expected IDF ~{expected:.6f} for 'the', got {entries['the'][1]}"
        )

    def test_idf_not_df(self, pipeline_run):
        """'not' appears in doc_beta and doc_gamma: df=2."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        assert entries["not"][0] == 2

    def test_idf_that_df(self, pipeline_run):
        """'that' appears in doc_beta and doc_gamma: df=2."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        assert entries["that"][0] == 2

    def test_idf_fox_df(self, pipeline_run):
        """'fox' appears only in doc_alpha: df=1."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        assert entries["fox"][0] == 1

    def test_idf_fox_idf_value(self, pipeline_run):
        """IDF('fox') = ln(3/1) ≈ 1.098612."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        expected = math.log(3.0)
        assert abs(entries["fox"][1] - expected) < 1e-5, (
            f"Expected IDF ~{expected:.6f} for 'fox', got {entries['fox'][1]}"
        )

    def test_idf_actions_idf_value(self, pipeline_run):
        """IDF('actions') = ln(3/1) ≈ 1.098612 (only in doc_gamma)."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        expected = math.log(3.0)
        assert abs(entries["actions"][1] - expected) < 1e-5

    def test_idf_no_short_words(self, pipeline_run):
        """IDF file should contain no words shorter than min_length=3."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        found_short = [w for w in entries if len(w) < 3]
        assert not found_short, f"Short words in idf.tsv: {found_short}"

    def test_idf_sorted_correctly(self, pipeline_run):
        """IDF file must be sorted by idf descending, then word ascending for ties."""
        with open(f"{RESULTS_DIR}/doc_freq/idf.tsv") as f:
            lines = [l.strip() for l in f if l.strip()]
        entries = []
        for line in lines:
            parts = line.split("\t")
            entries.append((parts[0], int(parts[1]), float(parts[2])))
        for i in range(len(entries) - 1):
            word_a, _, idf_a = entries[i]
            word_b, _, idf_b = entries[i + 1]
            if abs(idf_a - idf_b) > 1e-6:
                assert idf_a > idf_b, (
                    f"IDF not sorted descending: {word_a}({idf_a:.6f}) "
                    f"before {word_b}({idf_b:.6f})"
                )
            else:
                assert word_a < word_b, (
                    f"Tied IDFs not sorted alphabetically: "
                    f"'{word_a}' before '{word_b}'"
                )

    def test_idf_df1_count(self, pipeline_run):
        """37 words appear in exactly one document."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        df1_count = sum(1 for _, (df, _) in entries.items() if df == 1)
        assert df1_count == 37, (
            f"Expected 37 words with df=1, got {df1_count}"
        )

    def test_idf_df2_count(self, pipeline_run):
        """3 words appear in exactly two documents: the, not, that."""
        entries = _read_idf_file(f"{RESULTS_DIR}/doc_freq/idf.tsv")
        df2_words = sorted(w for w, (df, _) in entries.items() if df == 2)
        assert df2_words == ["not", "that", "the"], (
            f"Expected df=2 words ['not', 'that', 'the'], got {df2_words}"
        )


# ---------------------------------------------------------------------------
# Summary JSON correctness (TF-IDF)
# ---------------------------------------------------------------------------
class TestSummary:
    def test_summary_has_all_samples(self, pipeline_run):
        data = _read_summary()
        assert "samples" in data, "summary.json missing 'samples' key"
        for s in ["doc_alpha", "doc_beta", "doc_gamma"]:
            assert s in data["samples"], f"'{s}' missing from summary samples"

    def test_summary_has_num_documents(self, pipeline_run):
        data = _read_summary()
        assert "num_documents" in data, "summary.json missing 'num_documents' key"

    def test_summary_num_documents_value(self, pipeline_run):
        data = _read_summary()
        assert data["num_documents"] == 3, (
            f"Expected num_documents=3, got {data['num_documents']}"
        )

    def test_summary_has_global_field(self, pipeline_run):
        data = _read_summary()
        assert "global_top_tfidf_word" in data, (
            "summary.json missing 'global_top_tfidf_word' key"
        )

    def test_alpha_unique_words(self, pipeline_run):
        data = _read_summary()
        assert data["samples"]["doc_alpha"]["unique_words"] == 16

    def test_beta_unique_words(self, pipeline_run):
        data = _read_summary()
        assert data["samples"]["doc_beta"]["unique_words"] == 13

    def test_gamma_unique_words(self, pipeline_run):
        data = _read_summary()
        assert data["samples"]["doc_gamma"]["unique_words"] == 14

    def test_alpha_top_tfidf_word(self, pipeline_run):
        """doc_alpha: 'the' has TF=4/19, IDF=ln(3/2), TF-IDF≈0.0854 — highest."""
        data = _read_summary()
        assert data["samples"]["doc_alpha"]["top_tfidf_word"] == "the"

    def test_beta_top_tfidf_word(self, pipeline_run):
        """doc_beta: 'the' has TF=3/15, IDF=ln(3/2), TF-IDF≈0.0811 — highest."""
        data = _read_summary()
        assert data["samples"]["doc_beta"]["top_tfidf_word"] == "the"

    def test_gamma_top_tfidf_word(self, pipeline_run):
        """doc_gamma: all df=1 words have equal TF-IDF; 'actions' is alphabetically first."""
        data = _read_summary()
        assert data["samples"]["doc_gamma"]["top_tfidf_word"] == "actions", (
            f"Expected 'actions' (alphabetically first among tied TF-IDF), "
            f"got '{data['samples']['doc_gamma']['top_tfidf_word']}'"
        )

    def test_alpha_top_tfidf_score(self, pipeline_run):
        """TF-IDF('the', alpha) = (4/19) * ln(3/2) ≈ 0.085361."""
        data = _read_summary()
        expected = (4.0 / 19.0) * math.log(3.0 / 2.0)
        assert abs(data["samples"]["doc_alpha"]["top_tfidf_score"] - expected) < 1e-4, (
            f"Expected ~{expected:.6f}, got {data['samples']['doc_alpha']['top_tfidf_score']}"
        )

    def test_beta_top_tfidf_score(self, pipeline_run):
        """TF-IDF('the', beta) = (3/15) * ln(3/2) ≈ 0.081093."""
        data = _read_summary()
        expected = (3.0 / 15.0) * math.log(3.0 / 2.0)
        assert abs(data["samples"]["doc_beta"]["top_tfidf_score"] - expected) < 1e-4, (
            f"Expected ~{expected:.6f}, got {data['samples']['doc_beta']['top_tfidf_score']}"
        )

    def test_gamma_top_tfidf_score(self, pipeline_run):
        """TF-IDF for df=1 words in gamma = (1/14) * ln(3) ≈ 0.078472."""
        data = _read_summary()
        expected = (1.0 / 14.0) * math.log(3.0)
        assert abs(data["samples"]["doc_gamma"]["top_tfidf_score"] - expected) < 1e-4, (
            f"Expected ~{expected:.6f}, got {data['samples']['doc_gamma']['top_tfidf_score']}"
        )

    def test_global_top_tfidf_word(self, pipeline_run):
        """'the' in doc_alpha has the highest TF-IDF (≈0.0854) across all docs."""
        data = _read_summary()
        assert data["global_top_tfidf_word"] == "the", (
            f"Expected global top TF-IDF word 'the', "
            f"got '{data['global_top_tfidf_word']}'"
        )
