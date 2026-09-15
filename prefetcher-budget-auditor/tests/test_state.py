
import json
import subprocess
import pytest

TOOL = "/app/storage_pipeline.py"
FNLMMA = "/app/prefetchers/FNLMMA_prefetcher.cc"
PIPS = "/app/prefetchers/PIPS_prefetcher.cc"
BASELINE = "/app/prefetchers/no_l1i_pref.cc"
EIP = "/app/prefetchers/entangling_EPI_l1i_pref.cc"


def run_tool(*args):
    """Run the storage pipeline and return parsed JSON output."""
    result = subprocess.run(
        ["python3", TOOL] + list(args),
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Tool failed with stderr: {result.stderr}"
    return json.loads(result.stdout)


class TestPreprocess:
    """Tests requiring gcc -E -dM for cross-file macro resolution."""

    def test_champsim_macros_present(self):
        """Cross-file macros from ChampSim headers must appear in output.

        These macros are defined in cache.h and champsim.h, NOT in the
        prefetcher file itself. They can only be resolved by processing
        the full #include chain: prefetcher.cc -> ooo_cpu.h -> cache.h -> champsim.h.
        """
        out = run_tool("preprocess", FNLMMA)
        macros = out["macros"]
        assert macros["L1I_SET"] == 64
        assert macros["L1I_WAY"] == 8
        assert macros["NUM_CPUS"] == 1
        assert macros["BLOCK_SIZE"] == 64
        assert macros["LOG2_BLOCK_SIZE"] == 6
        assert macros["L1I_PQ_SIZE"] == 32
        assert macros["L1I_MSHR_SIZE"] == 8

    def test_entangling_cross_file_dependencies(self):
        """Macros depending on ChampSim header values must be resolved.

        L1I_TIMING_MSHR_SIZE = L1I_PQ_SIZE + L1I_MSHR_SIZE + 2 = 32 + 8 + 2 = 42
        L1I_TIMING_CACHE_TAG_BITS = L1I_TIMING_MSHR_TAG_BITS - L1I_SET_BITS = 42 - 6 = 36

        These require L1I_PQ_SIZE and L1I_MSHR_SIZE from cache.h.
        """
        out = run_tool("preprocess", EIP)
        macros = out["macros"]
        assert macros["L1I_TIMING_MSHR_SIZE"] == 42
        assert macros["L1I_TIMING_CACHE_TAG_BITS"] == 36

    def test_conditional_compilation(self):
        """Conditional compilation must be handled correctly.

        ooo_cpu.h defines STAT_PRINTING_PERIOD differently depending on
        whether CRC2_COMPILE is defined. Since champsim.h defines
        NO_CRC2_COMPILE (not CRC2_COMPILE), the value is 10000000.
        """
        out = run_tool("preprocess", EIP)
        macros = out["macros"]
        assert macros["STAT_PRINTING_PERIOD"] == 10000000

    def test_entangling_prefetcher_macros(self):
        """Prefetcher-specific macros must be correctly resolved."""
        out = run_tool("preprocess", EIP)
        macros = out["macros"]
        assert macros["L1I_HIST_TABLE_ENTRIES"] == 1072
        assert macros["L1I_ENTANGLED_TABLE_SETS"] == 256
        assert macros["L1I_ENTANGLED_TABLE_WAYS"] == 34
        assert macros["L1I_TAG_BITS"] == 34
        assert macros["L1I_XPQ_ENTRIES"] == 32
        assert macros["L1I_CONFIDENCE_COUNTER_BITS"] == 2
        assert macros["L1I_ENTANGLED_NUM_FORMATS"] == 6

    def test_fnlmma_macro_expressions(self):
        """Macro expressions with arithmetic and bit shifts must resolve."""
        out = run_tool("preprocess", FNLMMA)
        macros = out["macros"]
        assert macros["DISTAHEAD"] == 8
        assert macros["LOGMULTSIZE"] == 0
        assert macros["MMA_FILT_SIZE"] == 17
        # FNL_NBENTRIES = (1 << (16 + LOGMULTSIZE)) = 65536
        assert macros["FNL_NBENTRIES"] == 65536
        # SIZESHADOWICACHE = (64 * NBWAYISHADOW) = 192
        assert macros["SIZESHADOWICACHE"] == 192
        # SIZEFILTERFNL = (SIZEWAYFILTERFNL * NBWAYFILTERFNL) = 128
        assert macros["SIZEFILTERFNL"] == 128

    def test_pips_macros(self):
        """PIPS prefetcher macros including dependent CMAX."""
        out = run_tool("preprocess", PIPS)
        macros = out["macros"]
        assert macros["LHT_LOGSETS"] == 10
        assert macros["LHT_NUMWAYS"] == 10
        assert macros["NTARGETS"] == 3
        assert macros["CBITS"] == 4
        assert macros["OFFSETBITS"] == 22
        # CMAX = ((1 << CBITS) - 1) = 15
        assert macros["CMAX"] == 15

    def test_no_system_macros(self):
        """System/compiler macros (starting with _) must be filtered out."""
        out = run_tool("preprocess", BASELINE)
        macros = out["macros"]
        for name in macros:
            assert not name.startswith("_"), f"System macro '{name}' should be filtered"


class TestStructureAnalysis:
    """Tests requiring ctags + source parsing for struct bit-width analysis."""

    def test_hist_entry(self):
        """l1i_hist_entry: tag(58) + time_diff(20) + bb_size(7) = 85 bits."""
        out = run_tool("analyze", EIP, "l1i_hist_entry")
        assert out["bits_per_entry"] == 85
        members = {m["name"]: m["bits"] for m in out["members"]}
        assert members["tag"] == 58
        assert members["time_diff"] == 20
        assert members["bb_size"] == 7

    def test_timing_mshr_entry(self):
        """l1i_timing_mshr_entry: valid(1) + tag(42) + bere(58) + ts(12) + acc(1) = 114."""
        out = run_tool("analyze", EIP, "l1i_timing_mshr_entry")
        assert out["bits_per_entry"] == 114
        members = {m["name"]: m["bits"] for m in out["members"]}
        assert members["valid"] == 1
        assert members["tag"] == 42
        assert members["bere_line_addr"] == 58
        assert members["timestamp"] == 12
        assert members["accessed"] == 1

    def test_timing_cache_entry(self):
        """l1i_timing_cache_entry: valid(1) + tag(36) + bere(58) + acc(1) = 96.

        tag bits = L1I_TIMING_CACHE_TAG_BITS = L1I_TIMING_MSHR_TAG_BITS - L1I_SET_BITS
        = 42 - 6 = 36 (requires cross-file macro resolution).
        """
        out = run_tool("analyze", EIP, "l1i_timing_cache_entry")
        assert out["bits_per_entry"] == 96

    def test_xpq_entry(self):
        """l1i_xpq_entry: line_addr(58) + entangled_addr(58) + bb_size(7) = 123."""
        out = run_tool("analyze", EIP, "l1i_xpq_entry")
        assert out["bits_per_entry"] == 123
        members = {m["name"]: m["bits"] for m in out["members"]}
        assert members["line_addr"] == 58
        assert members["entangled_addr"] == 58
        assert members["bb_size"] == 7


class TestBudget:
    """Tests for full storage budget computation."""

    def test_baseline_zero(self):
        """No-prefetcher baseline should report 0 bytes storage."""
        out = run_tool("budget", BASELINE)
        assert out["total_storage_bytes"] == 0
        assert out["within_budget"] is True
        assert out["budget_limit_bytes"] == 131072

    def test_fnlmma_total(self):
        """FNL+MMA total storage must be 99107 bytes.

        Requires resolving AHEAD.SIZEWAYNEXTMISS = 2048 by tracing:
        - AHEAD is a PredictMiss instance
        - AHEAD.init(DISTAHEAD, 11) called in l1i_prefetcher_initialize()
        - init sets SIZEWAYNEXTMISS = 1 << (LOGSIZE + LOGMULTSIZE) = 1 << 11

        Storage breakdown:
        - Miss Ahead Prediction Table: 72 * 4 * 2048 / 8 = 73728
        - I-Shadow cache: (192 * 17) / 8 = 408
        - Touched + WorthPF: (65536 * 3) / 8 = 24576
        - MMA filter: (17 * 58) / 8 = 123 (integer division)
        - FNL filter: (128 * 17) / 8 = 272
        - TOTAL = 99107
        """
        out = run_tool("budget", FNLMMA)
        assert out["total_storage_bytes"] == 99107
        assert out["within_budget"] is True

    def test_fnlmma_budget_limit(self):
        """Budget limit must be 128KB = 131072 bytes."""
        out = run_tool("budget", FNLMMA)
        assert out["budget_limit_bytes"] == 131072


class TestReport:
    """Tests for comparative report across all prefetchers."""

    def test_report_all_prefetchers(self):
        """Report must include all prefetcher files in /app/prefetchers/."""
        out = run_tool("report")
        filenames = [p["file"] for p in out["prefetchers"]]
        assert any("FNLMMA" in f for f in filenames), "FNLMMA missing from report"
        assert any("no_l1i_pref" in f for f in filenames), "baseline missing from report"
        assert any("entangling" in f or "EPI" in f for f in filenames), "EIP missing"
        assert any("PIPS" in f for f in filenames), "PIPS missing from report"

    def test_report_has_ranking(self):
        """Report must include a ranking from most to least storage."""
        out = run_tool("report")
        assert "ranking" in out
        assert len(out["ranking"]) == len(out["prefetchers"])

    def test_report_fnlmma_value(self):
        """FNLMMA budget in report must match standalone budget result."""
        out = run_tool("report")
        fnlmma = [p for p in out["prefetchers"] if "FNLMMA" in p["file"]]
        assert len(fnlmma) == 1
        assert fnlmma[0]["total_storage_bytes"] == 99107
        assert fnlmma[0]["within_budget"] is True

    def test_report_baseline_zero_in_report(self):
        """Baseline should report 0 bytes in the comparative report."""
        out = run_tool("report")
        baseline = [p for p in out["prefetchers"] if "no_l1i_pref" in p["file"]]
        assert len(baseline) == 1
        assert baseline[0]["total_storage_bytes"] == 0

    def test_report_ranking_descending(self):
        """Ranking entries should be ordered by storage, descending."""
        out = run_tool("report")
        ranked_storages = []
        for name in out["ranking"]:
            for p in out["prefetchers"]:
                if p["file"] == name:
                    ranked_storages.append(p["total_storage_bytes"])
                    break
        for i in range(len(ranked_storages) - 1):
            assert ranked_storages[i] >= ranked_storages[i + 1], \
                f"Ranking not descending: {ranked_storages[i]} < {ranked_storages[i+1]}"
