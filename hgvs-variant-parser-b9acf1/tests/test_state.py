# -*- coding: utf-8 -*-

import sys
import os
import json
import subprocess
import sqlite3
import tempfile
import pytest

sys.path.insert(0, "/app")
from hgvs_parser import parse, format_variant, roundtrip, classify_edit, validate_grammar


# =============================================================================
# Round-trip tests: canonical variants must survive parse->format unchanged
# =============================================================================
CANONICAL_ROUNDTRIPS = [
    # --- DNA coordinate types ---
    "AC_01234.5:c.76A>C",
    "AC_01234.5:c.76_78del",
    "AC_01234.5:c.76_77insT",
    "AC_01234.5:c.112_117delinsTG",
    "AC_01234.5:c.77_79dup",
    "AC_01234.5:c.88+1G>T",
    "AC_01234.5:c.89-2A>C",
    "AC_01234.5:c.*46T>A",
    "AC_01234.5:c.-14G>C",
    "AC_01234.5:c.114_115delinsA",
    "AC_01234.5:c.113delinsTACTAGC",
    "AC_01234.5:c.31=",
    "AC_01234.5:g.1A>T",
    "AC_01234.5:g.5dup",
    "AC_01234.5:g.7_8dup",
    "AC_01234.5:m.1A>T",
    "AC_01234.5:n.1A>T",
    "AC_01234.5:r.1a>u",
    # --- Protein variants ---
    "AC_01234.5:p.Ala1Ser",
    "NP_001628.1:p.Gly528Arg",
    "NP_001628.1:p.Gly528Ter",
    "NP_000001.1:p.Gly25TrpfsTer10",
    "NP_078951.2:p.Arg1039fsTer",
    "NP_000040.1:p.Ter314TrpextTer45",
    "NP_000001.1:p.Met1Valext-10",
    "AC_01234.5:p.Phe2_Ala4del",
    "AC_01234.5:p.Phe2_Ala3insGlnGln",
    "AC_01234.5:p.Cys9_Val10delinsIleLeuGln",
]


@pytest.mark.parametrize("variant", CANONICAL_ROUNDTRIPS)
def test_roundtrip_canonical(variant):
    """Canonical HGVS strings must survive parse->format unchanged."""
    assert roundtrip(variant) == variant


# =============================================================================
# Normalization tests: non-canonical -> canonical output
# =============================================================================
NORMALIZATION_CASES = [
    # ref stripped by default max_ref_length=0
    ("AC_01234.5:g.5dupT", "AC_01234.5:g.5dup"),
    ("AC_01234.5:g.7_8dupTG", "AC_01234.5:g.7_8dup"),
    ("AC_01234.5:c.76_78delACT", "AC_01234.5:c.76_78del"),
    ("AC_01234.5:c.77_79dupCTG", "AC_01234.5:c.77_79dup"),
    ("AC_01234.5:c.76_78del3", "AC_01234.5:c.76_78del"),
    # ref identity stripped
    ("AC_01234.5:c.31T=", "AC_01234.5:c.31="),
    # Protein * -> Ter normalization (default p_term_asterisk=False)
    ("NP_000001.1:p.Gly25Trpfs*10", "NP_000001.1:p.Gly25TrpfsTer10"),
    ("NP_000040.1:p.Ter314Trpext*45", "NP_000040.1:p.Ter314TrpextTer45"),
    # Protein 1-letter -> 3-letter normalization
    ("NP_078951.2:p.N1039fs", "NP_078951.2:p.Asn1039fsTer"),
    ("AC_01234.5:p.A3F", "AC_01234.5:p.Ala3Phe"),
    ("AC_01234.5:p.A3_Y6del", "AC_01234.5:p.Ala3_Tyr6del"),
    # delXinsY single-char normalization to X>Y
    ("AC_01234.5:c.76delAinsT", "AC_01234.5:c.76A>T"),
]


@pytest.mark.parametrize("input_str,expected", NORMALIZATION_CASES)
def test_normalization(input_str, expected):
    """Non-canonical inputs must normalize to canonical form."""
    assert roundtrip(input_str) == expected


# =============================================================================
# Edit type classification
# =============================================================================
CLASSIFY_CASES = [
    ("AC_01234.5:c.76A>C", "sub"),
    ("AC_01234.5:c.88+1G>T", "sub"),
    ("AC_01234.5:c.76_78del", "del"),
    ("AC_01234.5:c.76_77insT", "ins"),
    ("AC_01234.5:c.112_117delinsTG", "delins"),
    ("AC_01234.5:c.113delinsTACTAGC", "delins"),
    ("AC_01234.5:g.5dup", "dup"),
    ("AC_01234.5:c.31=", "identity"),
    ("AC_01234.5:p.Ala1Ser", "sub"),
    ("NP_000001.1:p.Gly25TrpfsTer10", "fs"),
    ("NP_000040.1:p.Ter314TrpextTer45", "ext"),
    ("AC_01234.5:p.Phe2_Ala4del", "del"),
    ("AC_01234.5:p.Phe2_Ala3insGlnGln", "ins"),
    ("AC_01234.5:p.Cys9_Val10delinsIleLeuGln", "delins"),
]


@pytest.mark.parametrize("variant,expected_type", CLASSIFY_CASES)
def test_classify_edit(variant, expected_type):
    """classify_edit must return the correct edit type string."""
    assert classify_edit(variant) == expected_type


# =============================================================================
# Configurable formatting
# =============================================================================
class TestFormatConfig:
    def test_p_3_letter_false(self):
        v = parse("NP_001628.1:p.Gly528Arg")
        assert format_variant(v, {"p_3_letter": False}) == "NP_001628.1:p.G528R"

    def test_p_3_letter_false_with_ter(self):
        v = parse("NP_001628.1:p.Gly528Ter")
        assert format_variant(v, {"p_3_letter": False}) == "NP_001628.1:p.G528*"

    def test_p_term_asterisk_true(self):
        v = parse("NP_001628.1:p.Gly528Ter")
        assert format_variant(v, {"p_term_asterisk": True}) == "NP_001628.1:p.Gly528*"

    def test_p_term_asterisk_false_default(self):
        v = parse("NP_001628.1:p.Gly528Ter")
        assert format_variant(v) == "NP_001628.1:p.Gly528Ter"

    def test_max_ref_length_none_del(self):
        v = parse("AC_01234.5:c.76_78delACT")
        assert format_variant(v, {"max_ref_length": None}) == "AC_01234.5:c.76_78delACT"

    def test_max_ref_length_short(self):
        v = parse("AC_01234.5:c.76_78delACT")
        assert format_variant(v, {"max_ref_length": 2}) == "AC_01234.5:c.76_78del"

    def test_max_ref_length_exact(self):
        v = parse("AC_01234.5:c.76_78delACT")
        assert format_variant(v, {"max_ref_length": 3}) == "AC_01234.5:c.76_78delACT"

    def test_max_ref_length_none_dup(self):
        v = parse("AC_01234.5:g.5dupT")
        assert format_variant(v, {"max_ref_length": None}) == "AC_01234.5:g.5dupT"

    def test_max_ref_length_none_identity(self):
        v = parse("AC_01234.5:c.31T=")
        assert format_variant(v, {"max_ref_length": None}) == "AC_01234.5:c.31T="

    def test_max_ref_length_zero_identity(self):
        v = parse("AC_01234.5:c.31T=")
        assert format_variant(v) == "AC_01234.5:c.31="

    def test_fs_p_term_asterisk(self):
        v = parse("NP_000001.1:p.Gly25TrpfsTer10")
        assert format_variant(v, {"p_term_asterisk": True}) == "NP_000001.1:p.Gly25Trpfs*10"

    def test_fs_p_3_letter_false(self):
        v = parse("NP_000001.1:p.Gly25TrpfsTer10")
        assert format_variant(v, {"p_3_letter": False}) == "NP_000001.1:p.G25Wfs*10"

    def test_ext_p_term_asterisk(self):
        v = parse("NP_000040.1:p.Ter314TrpextTer45")
        assert format_variant(v, {"p_term_asterisk": True}) == "NP_000040.1:p.*314Trpext*45"

    def test_delins_max_ref_none(self):
        v = parse("AC_01234.5:c.76_77delinsTT")
        assert format_variant(v, {"max_ref_length": None}) == "AC_01234.5:c.76_77delinsTT"


# =============================================================================
# Grammar validation
# =============================================================================
GRAMMAR_VALID_CASES = [
    # Accessions
    ("accn", "NM_123456.7", True),
    ("accn", "NC_999999.9", True),
    ("accn", "NP_023456.7", True),
    ("accn", "U14680.1", True),
    ("accn", "NM_", False),
    ("accn", "3M", False),
    # DNA characters
    ("dna", "A", True),
    ("dna", "C", True),
    ("dna", "G", True),
    ("dna", "T", True),
    ("dna", "N", True),
    ("dna", "a", True),
    ("dna", "U", False),
    ("dna", "E", False),
    # RNA characters
    ("rna", "A", True),
    ("rna", "U", True),
    ("rna", "G", True),
    ("rna", "a", True),
    ("rna", "T", False),
    ("rna", "E", False),
    # Amino acid codes
    ("aa1", "A", True),
    ("aa1", "G", True),
    ("aa1", "Y", True),
    ("aa1", "J", False),
    ("aa1", "O", False),
    ("aa3", "Ala", True),
    ("aa3", "Trp", True),
    ("aa3", "Sec", True),
    ("aa3", "Zaa", False),
    ("aa13", "Ala", True),
    ("aa13", "A", True),
    ("aa13", "O", False),
    # Terminators
    ("term1", "X", True),
    ("term1", "*", True),
    ("term1", "T", False),
    ("term3", "Ter", True),
    ("term3", "ter", False),
    ("term13", "Ter", True),
    ("term13", "X", True),
    ("term13", "*", True),
    # Numbers
    ("num", "123", True),
    ("num", "0", True),
    ("snum", "+123", True),
    ("snum", "-123", True),
    ("snum", "123", True),
    # Full variants
    ("hgvs_variant", "AC_01234.5:c.1A>T", True),
    ("hgvs_variant", "AC_01234.5:g.1A>T", True),
    ("hgvs_variant", "AC_01234.5:p.Ala1Ser", True),
    ("hgvs_variant", "AC_01234.5:r.1A>U", True),
    ("g_variant", "AC_01234.5:g.7_8dup", True),
    ("c_variant", "AC_01234.5:c.88+1G>T", True),
    ("c_variant", "AC_01234.5:c.*46T>A", True),
    ("p_variant", "NP_000001.1:p.Gly25TrpfsTer10", True),
    ("p_variant", "NP_000040.1:p.Ter314TrpextTer45", True),
    ("n_variant", "AC_01234.5:n.1A>T", True),
    ("m_variant", "AC_01234.5:m.1A>T", True),
    ("r_variant", "AC_01234.5:r.1A>U", True),
]


@pytest.mark.parametrize("rule,input_str,expected", GRAMMAR_VALID_CASES)
def test_grammar_validation(rule, input_str, expected):
    """validate_grammar must correctly accept/reject inputs for each rule."""
    assert validate_grammar(rule, input_str) == expected


# =============================================================================
# Parsed structure verification
# =============================================================================
class TestParsedStructure:
    def test_parse_returns_object(self):
        v = parse("AC_01234.5:c.76A>C")
        assert v is not None

    def test_format_recovers_string(self):
        s = "AC_01234.5:c.76A>C"
        v = parse(s)
        assert format_variant(v) == s

    def test_parse_protein_frameshift(self):
        """Frameshift with no trailing length parses and formats correctly."""
        assert roundtrip("NP_078951.2:p.Arg1039fsTer") == "NP_078951.2:p.Arg1039fsTer"

    def test_parse_protein_extension_negative(self):
        """Extension with negative length parses correctly."""
        assert roundtrip("NP_000001.1:p.Met1Valext-10") == "NP_000001.1:p.Met1Valext-10"

    def test_parse_intronic_positive_offset(self):
        """Intronic positive offset preserved in round-trip."""
        assert roundtrip("AC_01234.5:c.88+1G>T") == "AC_01234.5:c.88+1G>T"

    def test_parse_intronic_negative_offset(self):
        """Intronic negative offset preserved in round-trip."""
        assert roundtrip("AC_01234.5:c.89-2A>C") == "AC_01234.5:c.89-2A>C"

    def test_parse_cds_end_datum(self):
        """CDS_END datum position (*) preserved in round-trip."""
        assert roundtrip("AC_01234.5:c.*46T>A") == "AC_01234.5:c.*46T>A"

    def test_parse_negative_base(self):
        """Negative base (5' UTR) preserved in round-trip."""
        assert roundtrip("AC_01234.5:c.-14G>C") == "AC_01234.5:c.-14G>C"

    def test_parse_with_gene(self):
        """Gene expression in parentheses preserved."""
        assert roundtrip("NM_01234.5(BOGUS):c.65A>C") == "NM_01234.5(BOGUS):c.65A>C"

    def test_parse_rna_lowercase(self):
        """RNA variant with lowercase preserved."""
        assert roundtrip("AC_01234.5:r.1a>u") == "AC_01234.5:r.1a>u"


# =============================================================================
# Edge cases: delins single-char normalization
# =============================================================================
class TestDelinsNormalization:
    def test_delins_single_char_becomes_sub(self):
        """delXinsY with single non-digit chars -> X>Y."""
        result = roundtrip("AC_01234.5:c.76delAinsT")
        assert result == "AC_01234.5:c.76A>T"

    def test_delins_multi_char_stays_delins(self):
        """delXXinsY with multi-char ref -> delinsY (ref stripped)."""
        result = roundtrip("AC_01234.5:c.76_77delAAinsC")
        assert result == "AC_01234.5:c.76_77delinsC"

    def test_delins_numeric_ref(self):
        """del5insT with numeric ref -> delinsT (ref stripped)."""
        result = roundtrip("AC_01234.5:c.76del5insT")
        assert result == "AC_01234.5:c.76delinsT"


# =============================================================================
# Protein interval operations
# =============================================================================
class TestProteinIntervals:
    def test_protein_deletion_interval(self):
        assert roundtrip("AC_01234.5:p.Phe2_Ala4del") == "AC_01234.5:p.Phe2_Ala4del"
        assert classify_edit("AC_01234.5:p.Phe2_Ala4del") == "del"

    def test_protein_insertion_interval(self):
        assert roundtrip("AC_01234.5:p.Gly10_Phe11insMetMet") == "AC_01234.5:p.Gly10_Phe11insMetMet"
        assert classify_edit("AC_01234.5:p.Gly10_Phe11insMetMet") == "ins"

    def test_protein_delins_interval(self):
        assert roundtrip("AC_01234.5:p.Cys200_Tyr205delinsIleLeuGln") == "AC_01234.5:p.Cys200_Tyr205delinsIleLeuGln"
        assert classify_edit("AC_01234.5:p.Cys200_Tyr205delinsIleLeuGln") == "delins"

    def test_protein_dup(self):
        assert roundtrip("AC_01234.5:p.Ala3dup") == "AC_01234.5:p.Ala3dup"
        assert classify_edit("AC_01234.5:p.Ala3dup") == "dup"

    def test_protein_1letter_insertion(self):
        """1-letter AA input normalizes to 3-letter in protein insertions."""
        assert roundtrip("AC_01234.5:p.G10_F11insMM") == "AC_01234.5:p.Gly10_Phe11insMetMet"

    def test_protein_1letter_delins(self):
        """1-letter AA input normalizes to 3-letter in protein delins."""
        assert roundtrip("AC_01234.5:p.C200_Y205delinsILQ") == "AC_01234.5:p.Cys200_Tyr205delinsIleLeuGln"


# =============================================================================
# CLI tool tests
# =============================================================================
class TestCLIParse:
    def test_parse_basic(self):
        """CLI parse outputs JSON with correct schema."""
        result = subprocess.run(
            ["/app/hgvs-tool", "parse"],
            input="AC_01234.5:c.76A>C\n",
            capture_output=True, text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["input"] == "AC_01234.5:c.76A>C"
        assert data[0]["accession"] == "AC_01234.5"
        assert data[0]["gene"] is None
        assert data[0]["type"] == "c"
        assert data[0]["edit_type"] == "sub"

    def test_parse_with_gene(self):
        """CLI parse preserves gene field."""
        result = subprocess.run(
            ["/app/hgvs-tool", "parse"],
            input="NM_01234.5(BOGUS):c.65A>C\n",
            capture_output=True, text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data[0]["gene"] == "BOGUS"
        assert data[0]["accession"] == "NM_01234.5"

    def test_parse_multiple_lines(self):
        """CLI parse handles multiple stdin lines."""
        inp = "AC_01234.5:c.76A>C\nAC_01234.5:g.5dup\nNP_000001.1:p.Gly25TrpfsTer10\n"
        result = subprocess.run(
            ["/app/hgvs-tool", "parse"],
            input=inp, capture_output=True, text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 3
        assert data[0]["edit_type"] == "sub"
        assert data[1]["edit_type"] == "dup"
        assert data[2]["edit_type"] == "fs"


class TestCLIClassify:
    def test_classify_tsv(self):
        """CLI classify outputs tab-separated variant and type."""
        inp = "AC_01234.5:c.76A>C\nAC_01234.5:c.76_78del\n"
        result = subprocess.run(
            ["/app/hgvs-tool", "classify"],
            input=inp, capture_output=True, text=True
        )
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 2
        parts0 = lines[0].split("\t")
        assert parts0[0] == "AC_01234.5:c.76A>C"
        assert parts0[1] == "sub"
        parts1 = lines[1].split("\t")
        assert parts1[0] == "AC_01234.5:c.76_78del"
        assert parts1[1] == "del"


class TestCLIValidate:
    def test_validate_rule(self):
        """CLI validate outputs JSON with valid booleans."""
        inp = "NM_123456.7\nNM_\n"
        result = subprocess.run(
            ["/app/hgvs-tool", "validate", "--rule", "accn"],
            input=inp, capture_output=True, text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["input"] == "NM_123456.7"
        assert data[0]["valid"] is True
        assert data[1]["input"] == "NM_"
        assert data[1]["valid"] is False


class TestCLIBatch:
    def test_batch_processing(self):
        """CLI batch processes TSV with roundtrip, classify, and validate operations."""
        result = subprocess.run(
            ["/app/hgvs-tool", "batch", "/app/data/test_batch.tsv"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        results = {d["id"]: d["result"] for d in data}
        # roundtrip results
        assert results["RT1"] == "AC_01234.5:c.76A>C"
        assert results["RT2"] == "AC_01234.5:g.5dup"
        assert results["RT3"] == "NP_000001.1:p.Gly25TrpfsTer10"
        # classify results
        assert results["CL1"] == "del"
        assert results["CL2"] == "fs"
        assert results["CL3"] == "ins"
        # validate results
        assert results["VL1"] is True
        assert results["VL2"] is False
        assert results["VL3"] is True
        assert results["VL4"] is False


class TestCLIPipeline:
    def test_jq_edit_type(self):
        """CLI parse output is jq-parseable for field extraction."""
        result = subprocess.run(
            'echo "AC_01234.5:c.76A>C" | /app/hgvs-tool parse | jq -r ".[0].edit_type"',
            shell=True, capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "sub"

    def test_jq_type_field(self):
        """CLI parse type field extractable via jq."""
        result = subprocess.run(
            'echo "NP_001628.1:p.Gly528Arg" | /app/hgvs-tool parse | jq ".[0].type"',
            shell=True, capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.strip() == '"p"'


# =============================================================================
# SQLite database tests
# =============================================================================
class TestDBLoad:
    def test_db_load_creates_database(self):
        """db load creates a SQLite database with correct schema."""
        db_path = tempfile.mktemp(suffix='.db')
        variant_file = tempfile.mktemp(suffix='.txt')
        try:
            with open(variant_file, 'w') as f:
                f.write("AC_01234.5:c.76A>C\nAC_01234.5:g.5dup\n")
            result = subprocess.run(
                ["/app/hgvs-tool", "db", "load", variant_file, "--db", db_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"db load failed: {result.stderr}"
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT * FROM variants").fetchall()
            assert len(rows) == 2
            cols = [d[0] for d in conn.execute("SELECT * FROM variants LIMIT 1").description]
            assert "accession" in cols
            assert "gene" in cols
            assert "type" in cols
            assert "edit_type" in cols
            assert "raw" in cols
            assert "formatted" in cols
            conn.close()
        finally:
            for p in [db_path, variant_file]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_db_load_correct_values(self):
        """db load stores correct parsed data."""
        db_path = tempfile.mktemp(suffix='.db')
        variant_file = tempfile.mktemp(suffix='.txt')
        try:
            with open(variant_file, 'w') as f:
                f.write("NP_001628.1:p.Gly528Arg\n")
            subprocess.run(
                ["/app/hgvs-tool", "db", "load", variant_file, "--db", db_path],
                capture_output=True, text=True
            )
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("SELECT * FROM variants").fetchall()]
            assert len(rows) == 1
            r = rows[0]
            assert r["accession"] == "NP_001628.1"
            assert r["type"] == "p"
            assert r["edit_type"] == "sub"
            assert r["raw"] == "NP_001628.1:p.Gly528Arg"
            assert r["formatted"] == "NP_001628.1:p.Gly528Arg"
            conn.close()
        finally:
            for p in [db_path, variant_file]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_db_load_gene_field(self):
        """db load correctly stores gene field when present."""
        db_path = tempfile.mktemp(suffix='.db')
        variant_file = tempfile.mktemp(suffix='.txt')
        try:
            with open(variant_file, 'w') as f:
                f.write("NM_01234.5(BOGUS):c.65A>C\n")
            subprocess.run(
                ["/app/hgvs-tool", "db", "load", variant_file, "--db", db_path],
                capture_output=True, text=True
            )
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("SELECT * FROM variants").fetchall()]
            assert len(rows) == 1
            assert rows[0]["gene"] == "BOGUS"
            assert rows[0]["accession"] == "NM_01234.5"
            conn.close()
        finally:
            for p in [db_path, variant_file]:
                if os.path.exists(p):
                    os.unlink(p)


class TestDBQuery:
    def test_db_query_group_by(self):
        """db query returns valid JSON with aggregation."""
        db_path = tempfile.mktemp(suffix='.db')
        variant_file = tempfile.mktemp(suffix='.txt')
        try:
            with open(variant_file, 'w') as f:
                f.write("AC_01234.5:c.76A>C\nAC_01234.5:g.5dup\nAC_01234.5:p.Ala1Ser\n")
            subprocess.run(
                ["/app/hgvs-tool", "db", "load", variant_file, "--db", db_path],
                capture_output=True, text=True
            )
            result = subprocess.run(
                ["/app/hgvs-tool", "db", "query", "--db", db_path,
                 "--sql", "SELECT type, COUNT(*) as count FROM variants GROUP BY type ORDER BY type"],
                capture_output=True, text=True
            )
            assert result.returncode == 0
            data = json.loads(result.stdout)
            counts = {d["type"]: d["count"] for d in data}
            assert counts["c"] == 1
            assert counts["g"] == 1
            assert counts["p"] == 1
        finally:
            for p in [db_path, variant_file]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_db_query_where_clause(self):
        """db query with WHERE clause filters correctly."""
        db_path = tempfile.mktemp(suffix='.db')
        variant_file = tempfile.mktemp(suffix='.txt')
        try:
            with open(variant_file, 'w') as f:
                f.write("AC_01234.5:c.76A>C\nAC_01234.5:c.76_78del\nAC_01234.5:g.5dup\n")
            subprocess.run(
                ["/app/hgvs-tool", "db", "load", variant_file, "--db", db_path],
                capture_output=True, text=True
            )
            result = subprocess.run(
                ["/app/hgvs-tool", "db", "query", "--db", db_path,
                 "--sql", "SELECT raw FROM variants WHERE edit_type = 'sub'"],
                capture_output=True, text=True
            )
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert len(data) == 1
            assert data[0]["raw"] == "AC_01234.5:c.76A>C"
        finally:
            for p in [db_path, variant_file]:
                if os.path.exists(p):
                    os.unlink(p)


# =============================================================================
# Makefile tests
# =============================================================================
class TestMakefile:
    @pytest.fixture(autouse=True)
    def clean_output(self):
        subprocess.run(["rm", "-rf", "/app/output"], capture_output=True)
        yield

    def test_makefile_exists(self):
        """Makefile exists at /app/Makefile."""
        assert os.path.exists("/app/Makefile")

    def test_make_batch(self):
        """make batch produces batch_results.json with correct content."""
        result = subprocess.run(
            ["make", "-C", "/app", "batch"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"make batch failed: {result.stderr}"
        assert os.path.exists("/app/output/batch_results.json")
        with open("/app/output/batch_results.json") as f:
            data = json.loads(f.read())
        results_map = {d["id"]: d["result"] for d in data}
        assert results_map["RT1"] == "AC_01234.5:c.76A>C"
        assert results_map["CL1"] == "del"
        assert results_map["VL1"] is True
        assert results_map["VL2"] is False

    def test_make_db_create(self):
        """make db-create populates variants.db with 12 variants."""
        result = subprocess.run(
            ["make", "-C", "/app", "db-create"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"make db-create failed: {result.stderr}"
        assert os.path.exists("/app/output/variants.db")
        conn = sqlite3.connect("/app/output/variants.db")
        count = conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0]
        assert count == 12
        conn.close()

    def test_make_db_stats(self):
        """make db-stats produces correct type counts."""
        # First create db
        subprocess.run(
            ["make", "-C", "/app", "db-create"],
            capture_output=True, text=True
        )
        result = subprocess.run(
            ["make", "-C", "/app", "db-stats"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"make db-stats failed: {result.stderr}"
        assert os.path.exists("/app/output/db_stats.json")
        with open("/app/output/db_stats.json") as f:
            data = json.loads(f.read())
        counts = {d["type"]: d["count"] for d in data}
        assert counts["c"] == 5
        assert counts["g"] == 2
        assert counts["p"] == 5


# =============================================================================
# Multi-tool pipeline composition tests
# =============================================================================
class TestPipelineComposition:
    def test_parse_jq_filter_by_type(self):
        """Pipeline: parse | jq to filter variants by coordinate type."""
        cmd = (
            'printf "AC_01234.5:c.76A>C\\nAC_01234.5:g.5dup\\nNP_001628.1:p.Gly528Arg\\n" '
            '| /app/hgvs-tool parse '
            "| jq '[.[] | select(.type == \"p\")] | length'"
        )
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        assert result.returncode == 0
        assert result.stdout.strip() == "1"

    def test_classify_awk_filter(self):
        """Pipeline: classify | awk to extract variants of a specific edit type."""
        cmd = (
            'printf "AC_01234.5:c.76A>C\\nAC_01234.5:c.76_78del\\nAC_01234.5:g.5dup\\n" '
            "| /app/hgvs-tool classify "
            "| awk -F'\\t' '$2 == \"sub\" {print $1}'"
        )
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        assert result.returncode == 0
        assert result.stdout.strip() == "AC_01234.5:c.76A>C"

    def test_db_sqlite3_cli_interop(self):
        """Pipeline: load variants then query via sqlite3 CLI tool."""
        db_path = tempfile.mktemp(suffix='.db')
        variant_file = tempfile.mktemp(suffix='.txt')
        try:
            with open(variant_file, 'w') as f:
                f.write("AC_01234.5:c.76A>C\nAC_01234.5:g.5dup\n")
            subprocess.run(
                ["/app/hgvs-tool", "db", "load", variant_file, "--db", db_path],
                capture_output=True, text=True
            )
            result = subprocess.run(
                ["sqlite3", db_path, "SELECT COUNT(*) FROM variants WHERE type='c';"],
                capture_output=True, text=True
            )
            assert result.returncode == 0
            assert result.stdout.strip() == "1"
        finally:
            for p in [db_path, variant_file]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_parse_jq_to_sqlite3(self):
        """Multi-step pipeline: parse | jq transform | verify structure."""
        cmd = (
            'printf "AC_01234.5:c.76A>C\\nAC_01234.5:c.76_78del\\n" '
            '| /app/hgvs-tool parse '
            "| jq '[.[] | {variant: .input, kind: .edit_type}]'"
        )
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["variant"] == "AC_01234.5:c.76A>C"
        assert data[0]["kind"] == "sub"
        assert data[1]["kind"] == "del"
