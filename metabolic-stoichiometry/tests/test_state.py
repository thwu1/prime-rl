
import json
import os
import sqlite3
import subprocess
import pytest

RESULTS_DIR = "/app/results"


def load_json(filename):
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


# -- Makefile structure -------------------------------------------------------

class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Missing /app/Makefile"

    def test_has_all_target(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "all" in content, "Makefile missing 'all' target"

    def test_has_individual_targets(self):
        with open("/app/Makefile") as f:
            content = f.read()
        for target in ["metabolic.db", "data_recovery.json", "balance_report.json",
                       "pathway_stoichiometry.json", "dead_ends.json", "chokepoints.json",
                       "shortest_paths.json", "stoichiometric_matrix.mtx"]:
            assert target in content, f"Makefile missing reference to {target}"


# -- metabolic.db (corrected SQLite database) --------------------------------

class TestDatabase:
    @pytest.fixture(autouse=True)
    def load(self):
        db_path = os.path.join(RESULTS_DIR, "metabolic.db")
        assert os.path.exists(db_path), f"Missing database file: {db_path}"
        self.conn = sqlite3.connect(db_path)
        yield
        self.conn.close()

    def test_all_tables_exist(self):
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        for t in ("compounds", "reactions", "reaction_participants",
                  "compound_synonyms", "pathways", "pathway_reactions"):
            assert t in tables, f"Missing table: {t}"

    def test_no_null_formulas_for_referenced_compounds(self):
        rows = self.conn.execute("""
            SELECT DISTINCT c.id FROM compounds c
            JOIN reaction_participants rp ON rp.compound_id = c.id
            WHERE c.formula IS NULL
        """).fetchall()
        assert len(rows) == 0, (
            f"Compounds with NULL formulas still in reactions: {[r[0] for r in rows]}"
        )

    def test_no_synonym_ids_in_reaction_participants(self):
        rows = self.conn.execute("""
            SELECT rp.reaction_id, rp.compound_id
            FROM reaction_participants rp
            INNER JOIN compound_synonyms cs ON rp.compound_id = cs.synonym_id
        """).fetchall()
        assert len(rows) == 0, (
            f"Synonym IDs still in reaction_participants: {rows}"
        )

    def test_acetyl_coa_formula_recovered(self):
        row = self.conn.execute(
            "SELECT formula FROM compounds WHERE id = 'C00024'"
        ).fetchone()
        assert row is not None and row[0] == "C23H38N7O17P3S"

    def test_succinyl_coa_formula_recovered(self):
        row = self.conn.execute(
            "SELECT formula FROM compounds WHERE id = 'C00091'"
        ).fetchone()
        assert row is not None and row[0] == "C25H40N7O19P3S"

    def test_compound_count(self):
        count = self.conn.execute("SELECT count(*) FROM compounds").fetchone()[0]
        assert count >= 48

    def test_reaction_count(self):
        count = self.conn.execute("SELECT count(*) FROM reactions").fetchone()[0]
        assert count == 32


# -- stoich_entries table in database ----------------------------------------

class TestStoichEntries:
    @pytest.fixture(autouse=True)
    def load(self):
        db_path = os.path.join(RESULTS_DIR, "metabolic.db")
        assert os.path.exists(db_path)
        self.conn = sqlite3.connect(db_path)
        yield
        self.conn.close()

    def test_table_exists(self):
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "stoich_entries" in tables, "Missing stoich_entries table"

    def test_entry_count(self):
        count = self.conn.execute("SELECT count(*) FROM stoich_entries").fetchone()[0]
        assert count == 129, f"Expected 129 stoich_entries, got {count}"

    def test_no_synonym_ids(self):
        rows = self.conn.execute("""
            SELECT se.reaction_id, se.compound_id
            FROM stoich_entries se
            INNER JOIN compound_synonyms cs ON se.compound_id = cs.synonym_id
        """).fetchall()
        assert len(rows) == 0, f"Synonym IDs in stoich_entries: {rows}"

    def test_r00004_coefficients(self):
        """R00004: Diphosphate + H2O => 2 Orthophosphate"""
        entries = dict(self.conn.execute(
            "SELECT compound_id, coefficient FROM stoich_entries WHERE reaction_id = 'R00004'"
        ).fetchall())
        assert abs(entries["C00013"] - (-1.0)) < 1e-9, "C00013 should be -1.0 (left side)"
        assert abs(entries["C00001"] - (-1.0)) < 1e-9, "C00001 should be -1.0 (left side)"
        assert abs(entries["C00009"] - 2.0) < 1e-9, "C00009 should be 2.0 (right side, coeff 2)"

    def test_r00621_synonym_resolved(self):
        """R00621 uses synonym C05535 for Succinyl-CoA (C00091) -- must be resolved"""
        entries = dict(self.conn.execute(
            "SELECT compound_id, coefficient FROM stoich_entries WHERE reaction_id = 'R00621'"
        ).fetchall())
        assert "C00091" in entries, "C00091 (canonical) should appear, not C05535 (synonym)"
        assert "C05535" not in entries, "Synonym C05535 should not appear in stoich_entries"
        assert entries["C00091"] > 0, "Succinyl-CoA should be produced (positive)"

    def test_left_side_negative(self):
        """All left-side participants should have negative coefficients"""
        # R01786: ATP(L) + Glucose(L) => ADP(R) + G6P(R)
        entries = dict(self.conn.execute(
            "SELECT compound_id, coefficient FROM stoich_entries WHERE reaction_id = 'R01786'"
        ).fetchall())
        assert entries["C00002"] < 0, "ATP (left side) should be negative"
        assert entries["C00267"] < 0, "Glucose (left side) should be negative"
        assert entries["C00008"] > 0, "ADP (right side) should be positive"
        assert entries["C00668"] > 0, "G6P (right side) should be positive"


# -- data_recovery.json ------------------------------------------------------

class TestDataRecovery:
    @pytest.fixture(autouse=True)
    def load(self):
        self.recovery = load_json("data_recovery.json")

    def test_is_dict(self):
        assert isinstance(self.recovery, dict)

    def test_expected_compounds_recovered(self):
        expected_ids = {"C00024", "C00091", "C00236", "C00345", "C00354", "C05382"}
        assert set(self.recovery.keys()) == expected_ids

    def test_acetyl_coa_formula(self):
        assert self.recovery["C00024"] == "C23H38N7O17P3S"

    def test_succinyl_coa_formula(self):
        assert self.recovery["C00091"] == "C25H40N7O19P3S"

    def test_bpg_formula(self):
        assert self.recovery["C00236"] == "C3H8O10P2"

    def test_6pg_formula(self):
        assert self.recovery["C00345"] == "C6H13O10P"

    def test_fbp_formula(self):
        assert self.recovery["C00354"] == "C6H14O12P2"

    def test_sed7p_formula(self):
        assert self.recovery["C05382"] == "C7H15O10P"


# -- balance_report.json -----------------------------------------------------

class TestBalanceReport:
    @pytest.fixture(autouse=True)
    def load(self):
        self.report = load_json("balance_report.json")

    def test_all_reactions_present(self):
        expected_ids = {
            "R01786", "R02739", "R00756", "R01068", "R01015", "R01061",
            "R01512", "R01662", "R00658", "R00200", "R00209", "R00351",
            "R01325", "R01900", "R00709", "R00621", "R00432", "R02164",
            "R01082", "R00342", "R02736", "R02035", "R01528", "R01056",
            "R01529", "R01641", "R01827", "R00258", "R00243", "R00355",
            "R00004", "RX0001",
        }
        assert set(self.report.keys()) == expected_ids

    def test_balanced_count(self):
        balanced = [r for r, v in self.report.items() if v["balanced"]]
        assert len(balanced) == 25

    def test_unbalanced_count(self):
        unbalanced = [r for r, v in self.report.items() if not v["balanced"]]
        assert len(unbalanced) == 7

    def test_known_balanced_reactions(self):
        for rxn_id in ["R01786", "R02739", "R00756", "R01068", "R01015",
                        "R01512", "R01662", "R00658", "R00200",
                        "R01325", "R01900", "R00709", "R00621", "R00432",
                        "R02164", "R01082", "R02035", "R01528", "R01056",
                        "R01529", "R01641", "R01827", "R00258", "R00355",
                        "R00004"]:
            assert self.report[rxn_id]["balanced"], f"{rxn_id} should be balanced"

    def test_h_unbalanced_reactions(self):
        for rxn_id in ["R01061", "R00209", "R00351", "R00342", "R02736", "R00243"]:
            entry = self.report[rxn_id]
            assert not entry["balanced"], f"{rxn_id} should be unbalanced"
            assert entry["element_deltas"]["H"] == -1, (
                f"{rxn_id} H delta should be -1, got {entry['element_deltas']['H']}"
            )

    def test_rx0001_c_and_o_unbalanced(self):
        entry = self.report["RX0001"]
        assert not entry["balanced"]
        assert entry["element_deltas"]["C"] == 1
        assert entry["element_deltas"]["O"] == 2
        assert entry["element_deltas"].get("H", 0) == 0

    def test_r00004_coefficient_balanced(self):
        entry = self.report["R00004"]
        assert entry["balanced"]


# -- pathway_stoichiometry.json ----------------------------------------------

class TestPathwayStoichiometry:
    @pytest.fixture(autouse=True)
    def load(self):
        self.stoich = load_json("pathway_stoichiometry.json")

    def test_all_pathways_present(self):
        assert set(self.stoich.keys()) == {
            "PWY-GLY", "PWY-TCA", "PWY-PPP", "PWY-PDH", "PWY-AA"
        }

    def test_glycolysis_net_consumed(self):
        consumed = self.stoich["PWY-GLY"]["net_consumed"]
        assert consumed == {
            "C00267": 1,
            "C00008": 2,
            "C00003": 2,
            "C00009": 2,
        }

    def test_glycolysis_net_produced(self):
        produced = self.stoich["PWY-GLY"]["net_produced"]
        assert produced == {
            "C00022": 2,
            "C00002": 2,
            "C00004": 2,
            "C00080": 2,
            "C00001": 2,
        }

    def test_tca_net_consumed(self):
        consumed = self.stoich["PWY-TCA"]["net_consumed"]
        assert consumed == {
            "C00024": 1,
            "C00001": 2,
            "C00003": 3,
            "C00035": 1,
            "C00009": 1,
            "C00016": 1,
        }

    def test_tca_net_produced(self):
        produced = self.stoich["PWY-TCA"]["net_produced"]
        assert produced == {
            "C00010": 1,
            "C00080": 2,
            "C00011": 2,
            "C00004": 3,
            "C00044": 1,
            "C01352": 1,
        }

    def test_ppp_net_consumed(self):
        consumed = self.stoich["PWY-PPP"]["net_consumed"]
        assert consumed == {
            "C00668": 1,
            "C00006": 2,
            "C00001": 1,
        }

    def test_ppp_net_produced(self):
        produced = self.stoich["PWY-PPP"]["net_produced"]
        assert produced == {
            "C00005": 2,
            "C00080": 1,
            "C00199": 1,
            "C00011": 1,
        }

    def test_pdh_net(self):
        consumed = self.stoich["PWY-PDH"]["net_consumed"]
        produced = self.stoich["PWY-PDH"]["net_produced"]
        assert consumed == {"C00022": 1, "C00010": 1, "C00003": 1}
        assert produced == {"C00024": 1, "C00011": 1, "C00004": 1, "C00080": 1}

    def test_aa_net(self):
        consumed = self.stoich["PWY-AA"]["net_consumed"]
        produced = self.stoich["PWY-AA"]["net_produced"]
        assert consumed == {"C00041": 1, "C00049": 1, "C00026": 2}
        assert produced == {"C00022": 1, "C00025": 2, "C00036": 1}

    def test_glycolysis_intermediates_canceled(self):
        intermediates = {"C00668", "C00085", "C00354", "C00111", "C00118",
                         "C00236", "C00197", "C00631", "C00074"}
        consumed = set(self.stoich["PWY-GLY"]["net_consumed"].keys())
        produced = set(self.stoich["PWY-GLY"]["net_produced"].keys())
        assert intermediates.isdisjoint(consumed | produced)

    # -- element_balance sub-tests --

    def test_glycolysis_element_balance(self):
        eb = self.stoich["PWY-GLY"]["element_balance"]
        assert eb["consistent"] is False
        assert eb["element_deltas"] == {"H": -2}

    def test_tca_element_balance(self):
        eb = self.stoich["PWY-TCA"]["element_balance"]
        assert eb["consistent"] is False
        assert eb["element_deltas"] == {"H": -2}

    def test_ppp_element_balance(self):
        eb = self.stoich["PWY-PPP"]["element_balance"]
        assert eb["consistent"] is False
        assert eb["element_deltas"] == {"H": -1}

    def test_pdh_element_balance(self):
        eb = self.stoich["PWY-PDH"]["element_balance"]
        assert eb["consistent"] is False
        assert eb["element_deltas"] == {"H": -1}

    def test_aa_element_balance(self):
        eb = self.stoich["PWY-AA"]["element_balance"]
        assert eb["consistent"] is True
        assert eb["element_deltas"] == {}


# -- dead_ends.json ----------------------------------------------------------

class TestDeadEnds:
    @pytest.fixture(autouse=True)
    def load(self):
        self.dead_ends = load_json("dead_ends.json")

    def test_is_sorted_list(self):
        assert isinstance(self.dead_ends, list)
        assert self.dead_ends == sorted(self.dead_ends)

    def test_expected_dead_ends(self):
        expected = [
            "C00013",
            "C00014",
            "C00016",
            "C00035",
            "C00041",
            "C00044",
            "C00049",
            "C00267",
            "C00279",
            "C01352",
        ]
        assert self.dead_ends == expected

    def test_count(self):
        assert len(self.dead_ends) == 10


# -- chokepoints.json --------------------------------------------------------

class TestChokepoints:
    @pytest.fixture(autouse=True)
    def load(self):
        self.chokepoints = load_json("chokepoints.json")

    def test_is_sorted_list(self):
        assert isinstance(self.chokepoints, list)
        assert self.chokepoints == sorted(self.chokepoints)

    def test_expected_chokepoints(self):
        expected = [
            "R00004",
            "R00243",
            "R00258",
            "R00355",
            "R00432",
            "R01786",
            "R01827",
            "R02164",
        ]
        assert self.chokepoints == expected

    def test_count(self):
        assert len(self.chokepoints) == 8


# -- shortest_paths.json -----------------------------------------------------

class TestShortestPaths:
    @pytest.fixture(autouse=True)
    def load(self):
        self.paths = load_json("shortest_paths.json")

    def test_all_queries_present(self):
        expected_keys = {
            "C00668->C00022",
            "C00022->C00149",
            "C00158->C00022",
            "C00267->C00117",
        }
        assert set(self.paths.keys()) == expected_keys

    def test_g6p_to_pyruvate(self):
        assert self.paths["C00668->C00022"] == 7

    def test_pyruvate_to_malate(self):
        assert self.paths["C00022->C00149"] == 3

    def test_citrate_to_pyruvate(self):
        assert self.paths["C00158->C00022"] == 2

    def test_glucose_to_ribose5p(self):
        assert self.paths["C00267->C00117"] == 4


# -- stoichiometric_matrix.mtx -----------------------------------------------

class TestStoichiometricMatrix:
    @pytest.fixture(autouse=True)
    def load(self):
        path = os.path.join(RESULTS_DIR, "stoichiometric_matrix.mtx")
        assert os.path.exists(path), f"Missing output file: {path}"
        with open(path) as f:
            self.lines = f.readlines()

    def test_header_line(self):
        assert self.lines[0].strip() == "%%MatrixMarket matrix coordinate real general"

    def test_has_row_comment(self):
        row_lines = [l for l in self.lines if l.startswith("% ROWS:")]
        assert len(row_lines) == 1, "Must have exactly one '% ROWS:' comment line"
        row_ids = row_lines[0].split(":", 1)[1].strip().split()
        assert row_ids[0] == "R00004", "First reaction (sorted) should be R00004"
        assert row_ids[-1] == "RX0001", "Last reaction (sorted) should be RX0001"
        assert len(row_ids) == 32, f"Expected 32 reaction IDs, got {len(row_ids)}"

    def test_has_col_comment(self):
        col_lines = [l for l in self.lines if l.startswith("% COLS:")]
        assert len(col_lines) == 1, "Must have exactly one '% COLS:' comment line"
        col_ids = col_lines[0].split(":", 1)[1].strip().split()
        assert col_ids[0] == "C00001", "First compound (sorted) should be C00001"
        assert len(col_ids) == 48, f"Expected 48 compound IDs, got {len(col_ids)}"

    def test_dimensions(self):
        for line in self.lines[1:]:
            if not line.startswith("%"):
                parts = line.strip().split()
                assert len(parts) == 3
                assert parts == ["32", "48", "129"], (
                    f"Expected dimensions 32 48 129, got {' '.join(parts)}"
                )
                break

    def test_r00004_entries(self):
        """R00004 is row 1: C00001(col 1)=-1, C00009(col 8)=+2, C00013(col 11)=-1"""
        entries = self._parse_entries()
        assert abs(entries.get((1, 1), 0) - (-1.0)) < 1e-9
        assert abs(entries.get((1, 8), 0) - 2.0) < 1e-9
        assert abs(entries.get((1, 11), 0) - (-1.0)) < 1e-9

    def test_r01786_entries(self):
        """R01786 is row 25: C00002(col 2)=-1, C00008(col 7)=+1, C00267(col 38)=-1, C00668(col 45)=+1"""
        entries = self._parse_entries()
        assert abs(entries.get((25, 2), 0) - (-1.0)) < 1e-9
        assert abs(entries.get((25, 7), 0) - 1.0) < 1e-9
        assert abs(entries.get((25, 38), 0) - (-1.0)) < 1e-9
        assert abs(entries.get((25, 45), 0) - 1.0) < 1e-9

    def test_synonym_resolved_entries(self):
        """R00621 (row 10): C00091 (col 27) should be +1.0 (synonym C05535 resolved)"""
        entries = self._parse_entries()
        assert abs(entries.get((10, 27), 0) - 1.0) < 1e-9

    def test_total_entries(self):
        entries = self._parse_entries()
        assert len(entries) == 129, f"Expected 129 non-zero entries, got {len(entries)}"

    def test_entries_sorted(self):
        coords = []
        past_header = False
        for line in self.lines:
            if line.startswith("%") or line.startswith("%%"):
                continue
            if not past_header:
                past_header = True
                continue
            parts = line.strip().split()
            if len(parts) == 3:
                coords.append((int(parts[0]), int(parts[1])))
        assert coords == sorted(coords), "Data entries must be sorted by (row, col)"

    def _parse_entries(self):
        entries = {}
        past_header = False
        for line in self.lines:
            if line.startswith("%") or line.startswith("%%"):
                continue
            if not past_header:
                past_header = True
                continue
            parts = line.strip().split()
            if len(parts) == 3:
                entries[(int(parts[0]), int(parts[1]))] = float(parts[2])
        return entries


# -- Makefile dependency chain verification -----------------------------------

class TestMakefileDependencies:
    """Verify that the Makefile has proper prerequisite declarations."""

    def test_target_triggers_prerequisite_rebuild(self):
        """Deleting the database and building a dependent target must rebuild the db."""
        db_path = os.path.join(RESULTS_DIR, "metabolic.db")
        if os.path.exists(db_path):
            os.remove(db_path)
        result = subprocess.run(
            ["make", "-C", "/app", "results/stoichiometric_matrix.mtx"],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"make target failed (exit {result.returncode}): {result.stderr}"
        )
        assert os.path.exists(db_path), (
            "Database was not rebuilt as prerequisite of stoichiometric_matrix.mtx"
        )
