"""
Tests for the RIME Spelling Algebra Engine and Native Deployment.

"""

import hashlib
import os
import subprocess
import tempfile
import yaml

SCHEMA = "/app/rime_data/challenge.schema.yaml"
DICT = "/app/rime_data/challenge.dict.yaml"
ENGINE = "/app/engine.py"

EXPECTED_PROJECTION_MD5 = "fe8b2951553ad4e7d7182cba22307f7e"
EXPECTED_TOTAL_PAIRS = 271
EXPECTED_UNIQUE_SPELLINGS = 175
EXPECTED_UNIQUE_SYLLABLES = 45


def run_engine(args):
    """Run the engine and return stdout."""
    result = subprocess.run(
        ["python3", ENGINE] + args,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Engine exited with {result.returncode}: {result.stderr}"
    return result.stdout


class TestProjection:
    """Tests for the spelling algebra projection."""

    def _get_projection(self):
        output = run_engine(["project", SCHEMA, DICT])
        return output.strip()

    def test_engine_exists(self):
        assert os.path.exists(ENGINE), f"Engine not found at {ENGINE}"

    def test_projection_total_pairs(self):
        output = self._get_projection()
        lines = output.split("\n")
        assert len(lines) == EXPECTED_TOTAL_PAIRS, (
            f"Expected {EXPECTED_TOTAL_PAIRS} pairs, got {len(lines)}"
        )

    def test_projection_md5(self):
        output = self._get_projection()
        md5 = hashlib.md5((output + "\n").encode()).hexdigest()
        assert md5 == EXPECTED_PROJECTION_MD5, (
            f"Projection output MD5 mismatch: expected {EXPECTED_PROJECTION_MD5}, got {md5}"
        )

    def test_unique_spellings_count(self):
        output = self._get_projection()
        lines = output.split("\n")
        spellings = set()
        for line in lines:
            parts = line.split("\t")
            spellings.add(parts[0])
        assert len(spellings) == EXPECTED_UNIQUE_SPELLINGS, (
            f"Expected {EXPECTED_UNIQUE_SPELLINGS} unique spellings, got {len(spellings)}"
        )

    def test_unique_syllables_count(self):
        output = self._get_projection()
        lines = output.split("\n")
        syllables = set()
        for line in lines:
            parts = line.split("\t")
            syllables.add(parts[1])
        assert len(syllables) == EXPECTED_UNIQUE_SYLLABLES, (
            f"Expected {EXPECTED_UNIQUE_SYLLABLES} unique syllables, got {len(syllables)}"
        )

    def test_basic_syllable_mappings(self):
        """Core syllable mappings after tone processing."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("zhong", "zhong1") in pairs
        assert ("guo", "guo2") in pairs
        assert ("shi", "shi4") in pairs

    def test_filtered_entries(self):
        """Certain syllables should be excluded from the mapping."""
        output = self._get_projection()
        lines = output.split("\n")
        spellings = {l.split("\t")[0] for l in lines}
        assert "xx" not in spellings
        assert "hm" not in spellings
        assert "m" not in spellings

    def test_initial_vowel_combinations(self):
        """Specific initial-vowel interaction mappings."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("xue", "xue2") in pairs

    def test_fuzzy_pinyin_retroflex(self):
        """Bidirectional fuzzy mappings for retroflex initials."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("zhang", "zhang1") in pairs
        assert ("zang", "zhang1") in pairs
        assert ("zhang", "zang1") in pairs

    def test_fuzzy_pinyin_nasal(self):
        """Bidirectional fuzzy mappings for nasal initials."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("lan", "nan2") in pairs
        assert ("nan", "lan2") in pairs

    def test_misspelling_final_ng_gn(self):
        """Common misspelling tolerance for final consonant clusters."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("bagn", "bang1") in pairs
        assert ("dogn", "dong1") in pairs

    def test_misspelling_final_ao_oa(self):
        """Common misspelling tolerance for diphthong transposition."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("hoa", "hao3") in pairs
        assert ("goa", "gao1") in pairs

    def test_misspelling_final_ong_on(self):
        """Common misspelling tolerance for final nasal simplification."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("don", "dong1") in pairs
        assert ("gon", "gong1") in pairs

    def test_alternative_ui_uei(self):
        """Alternative spelling for ui final."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("guei", "gui1") in pairs
        assert ("huei", "hui2") in pairs

    def test_alternative_iu_iou(self):
        """Alternative spelling for iu final."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("liou", "liu4") in pairs
        assert ("jiou", "jiu3") in pairs

    def test_nve_lve_alternatives(self):
        """Alternative spellings for nve/lve syllables."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("nue", "nve4") in pairs
        assert ("lue", "lve4") in pairs
        assert ("nve", "nve4") in pairs
        assert ("lve", "lve4") in pairs

    def test_two_char_shortcodes(self):
        """Two-character shortcode spellings."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("bg", "bang1") in pairs
        assert ("dg", "dong1") in pairs
        assert ("yu", "you3") in pairs

    def test_single_letter_abbreviations(self):
        """Single-letter abbreviation spellings."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("b", "bang1") in pairs
        assert ("b", "bu4") in pairs
        assert ("d", "da4") in pairs
        assert ("d", "dong1") in pairs
        assert ("z", "zai4") in pairs

    def test_two_letter_initial_abbreviations(self):
        """Two-letter abbreviation spellings for multi-char initials."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("zh", "zhang1") in pairs
        assert ("zh", "zhong1") in pairs
        assert ("sh", "shang4") in pairs
        assert ("sh", "shi4") in pairs
        assert ("sh", "shuang1") in pairs
        assert ("ch", "chang2") in pairs
        assert ("ch", "chuang4") in pairs

    def test_abbreviation_fuzzy_interaction(self):
        """Abbreviations should also cover entries created by fuzzy rules."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("zh", "zai4") in pairs
        assert ("zh", "zang1") in pairs

    def test_abbreviation_cross_initial_coverage(self):
        """Multi-char initial abbreviation should cover cross-initial derived entries."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("sh", "song4") in pairs

    def test_sorted_output(self):
        """Output must be sorted lexicographically by spelling, then syllable."""
        output = self._get_projection()
        lines = output.split("\n")
        for i in range(len(lines) - 1):
            assert lines[i] <= lines[i + 1], (
                f"Output not sorted at line {i}: '{lines[i]}' > '{lines[i+1]}'"
            )

    def test_tab_separated(self):
        """Each line should contain exactly one tab."""
        output = self._get_projection()
        lines = output.split("\n")
        for i, line in enumerate(lines):
            assert line.count("\t") == 1, (
                f"Line {i} does not have exactly one tab: '{line}'"
            )

    def test_vowel_transposition(self):
        """Transposed vowel-medial spellings."""
        output = self._get_projection()
        lines = output.split("\n")
        pairs = {(l.split("\t")[0], l.split("\t")[1]) for l in lines}
        assert ("tain", "tian1") in pairs
        assert ("dain", "dian3") in pairs
        assert ("xaing", "xiang3") in pairs


class TestPreedit:
    """Tests for the preedit_format transformation."""

    def test_nv_to_umlaut(self):
        output = run_engine(["preedit", SCHEMA, "nv"]).strip()
        assert output == "n\u00fc", f"Expected 'n\u00fc', got '{output}'"

    def test_lv_to_umlaut(self):
        output = run_engine(["preedit", SCHEMA, "lv"]).strip()
        assert output == "l\u00fc", f"Expected 'l\u00fc', got '{output}'"

    def test_lve_display(self):
        output = run_engine(["preedit", SCHEMA, "lve"]).strip()
        assert output == "l\u00fce", f"Expected 'l\u00fce', got '{output}'"

    def test_nue_display(self):
        output = run_engine(["preedit", SCHEMA, "nue"]).strip()
        assert output == "n\u00fce", f"Expected 'n\u00fce', got '{output}'"

    def test_jqxy_v_display(self):
        output_j = run_engine(["preedit", SCHEMA, "jv"]).strip()
        assert output_j == "ju", f"Expected 'ju', got '{output_j}'"
        output_x = run_engine(["preedit", SCHEMA, "xv"]).strip()
        assert output_x == "xu", f"Expected 'xu', got '{output_x}'"
        output_q = run_engine(["preedit", SCHEMA, "qv"]).strip()
        assert output_q == "qu", f"Expected 'qu', got '{output_q}'"

    def test_case_normalization(self):
        output = run_engine(["preedit", SCHEMA, "HELLO"]).strip()
        assert output == "hello", f"Expected 'hello', got '{output}'"

    def test_mixed_case(self):
        output = run_engine(["preedit", SCHEMA, "NvHaO"]).strip()
        assert output == "nvhao", f"Expected 'nvhao', got '{output}'"

    def test_rule_ordering(self):
        """Test that preedit rules are applied in the correct sequential order."""
        output = run_engine(["preedit", SCHEMA, "xvlve"]).strip()
        assert output == "xul\u00fce", f"Expected 'xul\u00fce', got '{output}'"

    def test_passthrough(self):
        output = run_engine(["preedit", SCHEMA, "pinyin"]).strip()
        assert output == "pinyin", f"Expected 'pinyin', got '{output}'"

    def test_repeated_pattern(self):
        output = run_engine(["preedit", SCHEMA, "nvnv"]).strip()
        assert output == "n\u00fcn\u00fc", f"Expected 'n\u00fcn\u00fc', got '{output}'"


class TestGeneralization:
    """Verify the engine generalizes to a different schema (anti-hardcoding)."""

    def _create_test_files(self):
        tmpdir = tempfile.mkdtemp()
        schema_path = os.path.join(tmpdir, "gen_test.schema.yaml")
        dict_path = os.path.join(tmpdir, "gen_test.dict.yaml")

        schema_content = (
            "schema:\n"
            "  schema_id: gen_test\n"
            "  name: Generalization Test\n"
            "  version: '1.0'\n"
            "speller:\n"
            "  algebra:\n"
            "    - xform/^([a-z]+)[0-9]$/$1/\n"
            "    - erase/^xx$/\n"
            "    - derive/^b/p/\n"
            "    - abbrev/^([a-z]).+$/$1/\n"
            "translator:\n"
            "  preedit_format:\n"
            "    - xlit/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/\n"
        )

        dict_content = (
            "---\n"
            "name: gen_test\n"
            'version: "1.0"\n'
            "sort: by_weight\n"
            "...\n"
            "\n"
            "\u767d\tbai2\n"
            "\u62cd\tpai1\n"
            "\u5927\tda4\n"
        )

        with open(schema_path, "w", encoding="utf-8") as f:
            f.write(schema_content)
        with open(dict_path, "w", encoding="utf-8") as f:
            f.write(dict_content)

        return schema_path, dict_path

    def test_generalized_projection_pair_count(self):
        schema_path, dict_path = self._create_test_files()
        result = subprocess.run(
            ["python3", ENGINE, "project", schema_path, dict_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Engine failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 8, (
            f"Expected 8 pairs for generalization schema, got {len(lines)}: {lines}"
        )

    def test_generalized_projection_specific_pairs(self):
        schema_path, dict_path = self._create_test_files()
        result = subprocess.run(
            ["python3", ENGINE, "project", schema_path, dict_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Engine failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        pairs = set()
        for line in lines:
            parts = line.split("\t")
            pairs.add((parts[0], parts[1]))

        # derive/^b/p/ should create pai->bai2 alongside existing pai->pai1
        assert ("pai", "bai2") in pairs, f"Missing derived pair (pai, bai2)"
        assert ("pai", "pai1") in pairs, f"Missing original pair (pai, pai1)"

        # abbrev should create single-letter shortcuts
        assert ("b", "bai2") in pairs, f"Missing abbreviation (b, bai2)"
        assert ("d", "da4") in pairs, f"Missing abbreviation (d, da4)"

        # p abbreviation should cover both pai1 and derived bai2
        assert ("p", "pai1") in pairs, f"Missing abbreviation (p, pai1)"
        assert ("p", "bai2") in pairs, f"Missing abbreviation (p, bai2)"

    def test_generalized_projection_sorted(self):
        schema_path, dict_path = self._create_test_files()
        result = subprocess.run(
            ["python3", ENGINE, "project", schema_path, dict_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Engine failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        for i in range(len(lines) - 1):
            assert lines[i] <= lines[i + 1], (
                f"Generalized output not sorted at line {i}: '{lines[i]}' > '{lines[i+1]}'"
            )

    def test_generalized_preedit(self):
        schema_path, _ = self._create_test_files()
        result = subprocess.run(
            ["python3", ENGINE, "preedit", schema_path, "BAI"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Engine failed: {result.stderr}"
        assert result.stdout.strip() == "bai", (
            f"Expected 'bai', got '{result.stdout.strip()}'"
        )

    def test_generalized_erase(self):
        """Verify erase operator works on a schema with an erasable entry."""
        tmpdir = tempfile.mkdtemp()
        schema_path = os.path.join(tmpdir, "erase_test.schema.yaml")
        dict_path = os.path.join(tmpdir, "erase_test.dict.yaml")

        schema_content = (
            "schema:\n"
            "  schema_id: erase_test\n"
            "  name: Erase Test\n"
            "  version: '1.0'\n"
            "speller:\n"
            "  algebra:\n"
            "    - erase/^test$/\n"
            "translator:\n"
            "  preedit_format: []\n"
        )
        dict_content = (
            "---\n"
            "name: erase_test\n"
            'version: "1.0"\n'
            "sort: by_weight\n"
            "...\n"
            "\n"
            "\u6d4b\ttest\n"
            "\u597d\thao\n"
        )

        with open(schema_path, "w", encoding="utf-8") as f:
            f.write(schema_content)
        with open(dict_path, "w", encoding="utf-8") as f:
            f.write(dict_content)

        result = subprocess.run(
            ["python3", ENGINE, "project", schema_path, dict_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Engine failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        spellings = {l.split("\t")[0] for l in lines}
        assert "test" not in spellings, "Erase operator did not remove 'test'"
        assert "hao" in spellings, "Non-erased entry 'hao' should remain"
        assert len(lines) == 1, f"Expected 1 pair after erase, got {len(lines)}"


class TestNativeDeployment:
    """Tests for the native RIME deployment using rime_deployer."""

    DEPLOY_DIR = "/app/rime_deploy"
    BUILD_DIR = "/app/rime_deploy/build"

    def test_deployer_installed(self):
        """rime_deployer binary must be available in PATH."""
        result = subprocess.run(
            ["which", "rime_deployer"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, \
            "rime_deployer not found in PATH — is librime-bin installed?"

    def test_deploy_dir_exists(self):
        """Deployment directory must exist."""
        assert os.path.isdir(self.DEPLOY_DIR), \
            f"Deployment directory {self.DEPLOY_DIR} does not exist"

    def test_schema_in_deploy(self):
        """Challenge schema must be present in the deployment directory."""
        path = os.path.join(self.DEPLOY_DIR, "challenge.schema.yaml")
        assert os.path.isfile(path), \
            f"challenge.schema.yaml not found at {path}"

    def test_dict_in_deploy(self):
        """Challenge dictionary must be present in the deployment directory."""
        path = os.path.join(self.DEPLOY_DIR, "challenge.dict.yaml")
        assert os.path.isfile(path), \
            f"challenge.dict.yaml not found at {path}"

    def test_default_yaml_configured(self):
        """default.yaml must exist and list the challenge schema."""
        path = os.path.join(self.DEPLOY_DIR, "default.yaml")
        assert os.path.isfile(path), \
            f"default.yaml not found at {path}"
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data is not None, "default.yaml is empty or invalid"
        assert "schema_list" in data, \
            f"default.yaml missing 'schema_list' key, got keys: {list(data.keys())}"
        schemas = [entry.get("schema") for entry in data["schema_list"]]
        assert "challenge" in schemas, \
            f"'challenge' not found in schema_list: {schemas}"

    def test_build_dir_exists(self):
        """Build subdirectory must exist after compilation."""
        assert os.path.isdir(self.BUILD_DIR), \
            f"Build directory {self.BUILD_DIR} does not exist — was rime_deployer run?"

    def test_table_bin_compiled(self):
        """Compiled dictionary table binary must exist and be non-empty."""
        path = os.path.join(self.BUILD_DIR, "challenge.table.bin")
        assert os.path.isfile(path), \
            f"challenge.table.bin not found at {path}"
        size = os.path.getsize(path)
        assert size > 100, \
            f"challenge.table.bin is suspiciously small ({size} bytes)"

    def test_prism_bin_compiled(self):
        """Compiled spelling prism binary must exist and be non-empty."""
        path = os.path.join(self.BUILD_DIR, "challenge.prism.bin")
        assert os.path.isfile(path), \
            f"challenge.prism.bin not found at {path}"
        size = os.path.getsize(path)
        assert size > 100, \
            f"challenge.prism.bin is suspiciously small ({size} bytes)"

    def test_deployer_rebuild(self):
        """rime_deployer --build must succeed when re-run on the deployment."""
        assert os.path.isdir(self.DEPLOY_DIR), \
            f"Cannot rebuild: {self.DEPLOY_DIR} does not exist"
        result = subprocess.run(
            ["rime_deployer", "--build",
             self.DEPLOY_DIR,
             self.DEPLOY_DIR],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, \
            f"rime_deployer --build failed (exit {result.returncode}): {result.stderr[:500]}"
