
"""
Verify vtable_engine JSON output against runtime introspection reference.

The test compares:
1. Object sizes (sizeof)
2. Object alignment (alignof)
3. Base subobject offsets (static_cast pointer arithmetic)
4. Virtual base offsets
5. Vtable component structure (count, kinds, values)
"""

import os
import json
import subprocess
import pytest

REFERENCE_DIR = "/app/reference_output"
CANDIDATE_DIR = "/app/candidate_output"
TEST_HEADERS_DIR = "/app/test_headers"


def get_test_names():
    """Discover test headers."""
    names = []
    for f in sorted(os.listdir(TEST_HEADERS_DIR)):
        if f.startswith("test") and f.endswith(".h"):
            names.append(f.replace(".h", ""))
    return names


def load_json(filepath):
    """Load JSON file, return empty dict if missing or invalid."""
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


class TestVtableEngine:
    """Test vtable_engine output against runtime reference."""

    def test_binary_exists(self):
        """The vtable_engine binary must exist."""
        assert os.path.isfile("/app/vtable_engine"), \
            "vtable_engine binary not found at /app/vtable_engine"

    def test_binary_runs(self):
        """The binary must run without crashing on a valid header."""
        result = subprocess.run(
            ["/app/vtable_engine", "/app/test_headers/test01_simple.h"],
            capture_output=True, timeout=30
        )
        assert result.returncode == 0, \
            f"vtable_engine crashed with code {result.returncode}: " \
            f"{result.stderr.decode()[:500]}"

    def test_produces_valid_json(self):
        """The binary must produce valid JSON output."""
        result = subprocess.run(
            ["/app/vtable_engine", "/app/test_headers/test01_simple.h"],
            capture_output=True, timeout=30
        )
        output = result.stdout.decode().strip()
        assert len(output) > 0, "vtable_engine produced no output"
        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            pytest.fail(f"vtable_engine output is not valid JSON: {e}\n"
                        f"Output: {output[:500]}")
        assert isinstance(data, dict), "Top-level JSON must be an object"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_object_sizes(self, test_name):
        """Verify object sizes match runtime sizeof()."""
        ref = load_json(f"{REFERENCE_DIR}/{test_name}.ref.json")
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")

        assert ref, f"Reference data missing for {test_name}"
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, ref_info in ref.items():
            assert class_name in cand, \
                f"Class '{class_name}' missing from candidate output for {test_name}"

            cand_info = cand[class_name]
            ref_size = ref_info.get("object_size")
            cand_size = cand_info.get("object_size")

            assert cand_size is not None, \
                f"Missing 'object_size' for class '{class_name}'"
            assert ref_size == cand_size, \
                f"object_size mismatch for '{class_name}': " \
                f"expected {ref_size}, got {cand_size}"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_object_alignment(self, test_name):
        """Verify object alignment matches runtime alignof()."""
        ref = load_json(f"{REFERENCE_DIR}/{test_name}.ref.json")
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")

        assert ref, f"Reference data missing for {test_name}"
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, ref_info in ref.items():
            if class_name not in cand:
                continue  # covered by other test

            cand_info = cand[class_name]
            ref_align = ref_info.get("object_align")
            cand_align = cand_info.get("object_align")

            assert cand_align is not None, \
                f"Missing 'object_align' for class '{class_name}'"
            assert ref_align == cand_align, \
                f"object_align mismatch for '{class_name}': " \
                f"expected {ref_align}, got {cand_align}"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_subobject_offsets(self, test_name):
        """Verify base subobject offsets match runtime pointer arithmetic."""
        ref = load_json(f"{REFERENCE_DIR}/{test_name}.ref.json")
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")

        assert ref, f"Reference data missing for {test_name}"
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, ref_info in ref.items():
            if class_name not in cand:
                continue

            cand_info = cand[class_name]
            ref_offsets = ref_info.get("subobject_offsets", {})
            cand_offsets = cand_info.get("subobject_offsets", {})

            for base_name, ref_off in ref_offsets.items():
                if ref_off == -1:
                    continue  # abstract class, skip
                assert base_name in cand_offsets, \
                    f"Missing subobject offset for '{base_name}' in " \
                    f"'{class_name}' (test {test_name})"
                cand_off = cand_offsets[base_name]
                assert ref_off == cand_off, \
                    f"subobject_offset mismatch for '{base_name}' in " \
                    f"'{class_name}': expected {ref_off}, got {cand_off}"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_virtual_base_offsets(self, test_name):
        """Verify virtual base offsets match runtime values."""
        ref = load_json(f"{REFERENCE_DIR}/{test_name}.ref.json")
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")

        assert ref, f"Reference data missing for {test_name}"
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, ref_info in ref.items():
            if class_name not in cand:
                continue

            cand_info = cand[class_name]
            ref_vbases = ref_info.get("vbase_offsets", {})
            cand_vbases = cand_info.get("vbase_offsets", {})

            for vb_name, ref_off in ref_vbases.items():
                if ref_off == -1:
                    continue  # abstract class, skip
                assert vb_name in cand_vbases, \
                    f"Missing vbase_offset for '{vb_name}' in " \
                    f"'{class_name}' (test {test_name})"
                cand_off = cand_vbases[vb_name]
                assert ref_off == cand_off, \
                    f"vbase_offset mismatch for '{vb_name}' in " \
                    f"'{class_name}': expected {ref_off}, got {cand_off}"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_vtable_components_present(self, test_name):
        """Verify vtable_components field exists and has entries."""
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, cand_info in cand.items():
            components = cand_info.get("vtable_components")
            assert components is not None, \
                f"Missing 'vtable_components' for '{class_name}'"
            assert isinstance(components, list), \
                f"'vtable_components' must be a list for '{class_name}'"
            assert len(components) > 0, \
                f"'vtable_components' is empty for '{class_name}'"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_vtable_component_structure(self, test_name):
        """Verify each vtable component has required fields and valid kinds."""
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")
        assert cand, f"Candidate data missing for {test_name}"

        valid_kinds = {
            "vbase_offset", "vcall_offset", "offset_to_top",
            "rtti", "function", "complete_dtor", "deleting_dtor"
        }

        for class_name, cand_info in cand.items():
            components = cand_info.get("vtable_components", [])
            for i, comp in enumerate(components):
                assert "index" in comp, \
                    f"Component {i} missing 'index' in '{class_name}'"
                assert "kind" in comp, \
                    f"Component {i} missing 'kind' in '{class_name}'"
                assert "value" in comp, \
                    f"Component {i} missing 'value' in '{class_name}'"
                assert comp["kind"] in valid_kinds, \
                    f"Invalid kind '{comp['kind']}' in component {i} " \
                    f"of '{class_name}'. Valid: {valid_kinds}"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_vtable_has_rtti(self, test_name):
        """Every polymorphic class vtable must have an RTTI entry."""
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, cand_info in cand.items():
            components = cand_info.get("vtable_components", [])
            rtti_entries = [c for c in components if c["kind"] == "rtti"]
            assert len(rtti_entries) >= 1, \
                f"No RTTI component found for '{class_name}'"
            # The RTTI value should reference the class name
            assert rtti_entries[0]["value"] == class_name, \
                f"RTTI entry should reference '{class_name}', " \
                f"got '{rtti_entries[0]['value']}'"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_vtable_has_offset_to_top(self, test_name):
        """Every polymorphic class vtable must have an offset_to_top entry."""
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, cand_info in cand.items():
            components = cand_info.get("vtable_components", [])
            ott_entries = [c for c in components if c["kind"] == "offset_to_top"]
            assert len(ott_entries) >= 1, \
                f"No offset_to_top component found for '{class_name}'"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_vtable_entry_count(self, test_name):
        """Verify num_vtable_entries matches component list length."""
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, cand_info in cand.items():
            num = cand_info.get("num_vtable_entries")
            components = cand_info.get("vtable_components", [])
            if num is not None:
                assert num == len(components), \
                    f"num_vtable_entries ({num}) doesn't match " \
                    f"component count ({len(components)}) for '{class_name}'"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_primary_vtable_offset_to_top_zero(self, test_name):
        """The primary vtable's first offset_to_top must be 0."""
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")
        assert cand, f"Candidate data missing for {test_name}"

        for class_name, cand_info in cand.items():
            components = cand_info.get("vtable_components", [])
            ott_entries = [c for c in components if c["kind"] == "offset_to_top"]
            if ott_entries:
                assert ott_entries[0]["value"] == 0, \
                    f"Primary offset_to_top must be 0 for '{class_name}', " \
                    f"got {ott_entries[0]['value']}"

    @pytest.mark.parametrize("test_name", get_test_names())
    def test_class_coverage(self, test_name):
        """All polymorphic classes from reference must appear in candidate."""
        ref = load_json(f"{REFERENCE_DIR}/{test_name}.ref.json")
        cand = load_json(f"{CANDIDATE_DIR}/{test_name}.json")

        assert ref, f"Reference data missing for {test_name}"
        assert cand, f"Candidate data missing for {test_name}"

        for class_name in ref:
            assert class_name in cand, \
                f"Class '{class_name}' from reference missing in candidate " \
                f"for {test_name}. Got classes: {list(cand.keys())}"
