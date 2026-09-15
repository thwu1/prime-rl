import json
import os
import pytest


ANALYSIS_PATH = "/app/output/analysis.json"


@pytest.fixture
def analysis():
    assert os.path.exists(ANALYSIS_PATH), f"Output file not found: {ANALYSIS_PATH}"
    with open(ANALYSIS_PATH) as f:
        return json.load(f)


# ---- Structure tests ----

def test_has_resolved_macros(analysis):
    assert "resolved_macros" in analysis
    assert isinstance(analysis["resolved_macros"], dict)
    assert len(analysis["resolved_macros"]) >= 20, (
        f"Expected at least 20 resolved macros, got {len(analysis['resolved_macros'])}"
    )


def test_has_storage_section(analysis):
    assert "storage" in analysis
    s = analysis["storage"]
    for key in [
        "FNLMMA_total_bytes",
        "FNLMMA_within_budget",
        "PIPS_total_bits",
        "PIPS_total_kb",
        "PIPS_within_budget",
    ]:
        assert key in s, f"Missing storage key: {key}"


# ---- Framework macros (champsim.h and cache.h) ----

def test_framework_num_cpus(analysis):
    assert analysis["resolved_macros"]["NUM_CPUS"] == 1


def test_framework_block_size(analysis):
    assert analysis["resolved_macros"]["BLOCK_SIZE"] == 64


def test_framework_log2_block_size(analysis):
    assert analysis["resolved_macros"]["LOG2_BLOCK_SIZE"] == 6


def test_framework_l1i_set(analysis):
    assert analysis["resolved_macros"]["L1I_SET"] == 64


def test_framework_l1i_way(analysis):
    assert analysis["resolved_macros"]["L1I_WAY"] == 8


def test_framework_l1i_pq_size(analysis):
    assert analysis["resolved_macros"]["L1I_PQ_SIZE"] == 32


def test_framework_l1i_mshr_size(analysis):
    assert analysis["resolved_macros"]["L1I_MSHR_SIZE"] == 8


# ---- FNLMMA macros (chained macro resolution) ----

def test_fnlmma_fnl_nbentries(analysis):
    """FNL_NBENTRIES = (1 << (16 + LOGMULTSIZE)) where LOGMULTSIZE=0 => 65536"""
    assert analysis["resolved_macros"]["FNL_NBENTRIES"] == 65536


def test_fnlmma_sizeshadowicache(analysis):
    """SIZESHADOWICACHE = (64 * NBWAYISHADOW) where NBWAYISHADOW=3 => 192"""
    assert analysis["resolved_macros"]["SIZESHADOWICACHE"] == 192


def test_fnlmma_sizefilterfnl(analysis):
    """SIZEFILTERFNL = (SIZEWAYFILTERFNL * NBWAYFILTERFNL) = 32*4 = 128"""
    assert analysis["resolved_macros"]["SIZEFILTERFNL"] == 128


def test_fnlmma_mma_filt_size(analysis):
    assert analysis["resolved_macros"]["MMA_FILT_SIZE"] == 17


# ---- EIP macros (cross-file + complex expressions + type casts) ----

def test_eip_bbsize_max_value(analysis):
    """L1I_MERGE_BBSIZE_MAX_VALUE = ((1 << L1I_MERGE_BBSIZE_BITS) - 1) = 127"""
    assert analysis["resolved_macros"]["L1I_MERGE_BBSIZE_MAX_VALUE"] == 127


def test_eip_time_diff_overflow(analysis):
    """L1I_TIME_DIFF_OVERFLOW = ((uint64_t)1 << 20) = 1048576
    Tests type cast handling."""
    assert analysis["resolved_macros"]["L1I_TIME_DIFF_OVERFLOW"] == 1048576


def test_eip_timing_mshr_size(analysis):
    """L1I_TIMING_MSHR_SIZE = (L1I_PQ_SIZE + L1I_MSHR_SIZE + 2) = 42
    Tests cross-file macro resolution (L1I_PQ_SIZE from cache.h)."""
    assert analysis["resolved_macros"]["L1I_TIMING_MSHR_SIZE"] == 42


def test_eip_entangled_table_sets(analysis):
    """L1I_ENTANGLED_TABLE_SETS = (1 << L1I_ENTANGLED_TABLE_INDEX_BITS) = 256"""
    assert analysis["resolved_macros"]["L1I_ENTANGLED_TABLE_SETS"] == 256


def test_eip_tag_bits(analysis):
    """L1I_TAG_BITS = (42 - L1I_ENTANGLED_TABLE_INDEX_BITS) = 34"""
    assert analysis["resolved_macros"]["L1I_TAG_BITS"] == 34


def test_eip_xpq_mask(analysis):
    """L1I_XPQ_MASK = (L1I_XPQ_ENTRIES - 1) = 31"""
    assert analysis["resolved_macros"]["L1I_XPQ_MASK"] == 31


def test_eip_hist_tag_mask(analysis):
    """L1I_HIST_TAG_MASK = (((uint64_t)1 << 58) - 1) = 288230376151711743
    Tests uint64_t cast handling and 64-bit arithmetic."""
    assert analysis["resolved_macros"]["L1I_HIST_TAG_MASK"] == 288230376151711743


def test_eip_max_entangled_per_line(analysis):
    """L1I_MAX_ENTANGLED_PER_LINE = L1I_ENTANGLED_NUM_FORMATS = 6
    Tests simple macro alias resolution."""
    assert analysis["resolved_macros"]["L1I_MAX_ENTANGLED_PER_LINE"] == 6


# ---- PIPS macros ----

def test_pips_cmax(analysis):
    """CMAX = ((1<<CBITS)-1) where CBITS=4 => 15"""
    assert analysis["resolved_macros"]["CMAX"] == 15


# ---- FNLMMA storage budget ----

def test_fnlmma_storage_total(analysis):
    """FNLMMA total from final_stats() printf:
    Miss Ahead Prediction Table: 72*4*2048/8 = 73728
    I-Shadow cache: (192*17)/8 = 408
    Touched+WorthPF: (65536*3)/8 = 24576
    MMA filter: (17*58)/8 = 123
    FNL filter: (128*17)/8 = 272
    Total: 99107 bytes"""
    assert analysis["storage"]["FNLMMA_total_bytes"] == 99107


def test_fnlmma_within_budget(analysis):
    """99107 < 131072 => within budget"""
    assert analysis["storage"]["FNLMMA_within_budget"] is True


# ---- PIPS storage budget ----

def test_pips_storage_bits(analysis):
    """PIPS total:
    LHT_ENTRY::size() = 3*22 + 4*4 = 82 bits
    lht: (82+16+3) * (10*1024) = 101*10240 = 1034240 bits
    scc: (82+16+2) * (4*32) = 100*128 = 12800 bits
    Total: 1047040 bits"""
    assert analysis["storage"]["PIPS_total_bits"] == 1047040


def test_pips_storage_kb(analysis):
    """1047040 / 8192 = 127.8125, rounded to 2dp = 127.81"""
    assert abs(analysis["storage"]["PIPS_total_kb"] - 127.81) < 0.01


def test_pips_within_budget(analysis):
    """127.81 < 128.0 => within budget"""
    assert analysis["storage"]["PIPS_within_budget"] is True
