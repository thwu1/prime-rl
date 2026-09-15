
import os
import re
import csv
import json
import pytest

# Layer bottom elevations from the DIS file (feet)
LAYER_BOTTOMS = {1: -150.0, 2: -200.0, 3: -300.0, 4: -350.0, 5: -450.0}


class TestConvergence:
    """Verify the MODFLOW 6 simulation achieved normal termination."""

    def test_listing_file_exists(self):
        assert os.path.exists("/app/model/mfsim.lst"), (
            "Simulation listing file mfsim.lst not found in /app/model/"
        )

    def test_normal_termination(self):
        with open("/app/model/mfsim.lst") as f:
            content = f.read()
        assert "Normal termination" in content, (
            "Simulation did not achieve normal termination. "
            "Check mfsim.lst for convergence failure details."
        )


class TestModelStructure:
    """Verify that model defects were correctly diagnosed and repaired."""

    def test_ims_outer_maximum(self):
        ims_path = "/app/model/ex-gwf-twri01.ims"
        assert os.path.exists(ims_path), "IMS file not found"
        with open(ims_path) as f:
            content = f.read()
        match = re.search(r'OUTER_MAXIMUM\s+(\d+)', content, re.IGNORECASE)
        assert match, "OUTER_MAXIMUM not found in IMS file"
        val = int(match.group(1))
        assert val >= 10, (
            f"OUTER_MAXIMUM = {val} is too low for convergence (should be >= 10)"
        )

    def _get_k33_constants(self):
        npf_path = "/app/model/ex-gwf-twri01.npf"
        assert os.path.exists(npf_path), "NPF file not found"
        with open(npf_path) as f:
            content = f.read()
        k33_match = re.search(
            r'K33\s+LAYERED\s*(.*?)(?=END\s+GRIDDATA|\Z)',
            content, re.IGNORECASE | re.DOTALL
        )
        assert k33_match, "K33 LAYERED section not found in NPF file"
        constants = re.findall(
            r'CONSTANT\s+([0-9eE.+-]+)', k33_match.group(1), re.IGNORECASE
        )
        assert len(constants) == 5, (
            f"Expected 5 K33 CONSTANT entries, found {len(constants)}"
        )
        return [float(c) for c in constants]

    def test_confining_layer2_k33(self):
        k33_vals = self._get_k33_constants()
        assert k33_vals[1] < 1e-5, (
            f"K33 for confining layer 2 = {k33_vals[1]}, "
            f"must be << 1 for a confining unit (expected ~1e-8)"
        )

    def test_confining_layer4_k33(self):
        k33_vals = self._get_k33_constants()
        assert k33_vals[3] < 1e-4, (
            f"K33 for confining layer 4 = {k33_vals[3]}, "
            f"must be << 1 for a confining unit (expected ~5e-7)"
        )

    def _get_chd_layers(self):
        chd_path = "/app/model/ex-gwf-twri01.chd"
        assert os.path.exists(chd_path), "CHD file not found"
        with open(chd_path) as f:
            content = f.read()
        period_match = re.search(
            r'BEGIN\s+PERIOD\s+1\s*(.*?)\s*END\s+PERIOD',
            content, re.IGNORECASE | re.DOTALL
        )
        assert period_match, "PERIOD 1 block not found in CHD file"
        lines = [
            l.strip() for l in period_match.group(1).strip().splitlines()
            if l.strip() and not l.strip().startswith(('#', '!'))
        ]
        layers = set()
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                layers.add(int(parts[0]))
        return layers

    def test_chd_layer1_present(self):
        layers = self._get_chd_layers()
        assert 1 in layers, "Aquifer layer 1 should have constant head boundaries"

    def test_chd_layer3_present(self):
        layers = self._get_chd_layers()
        assert 3 in layers, (
            "Aquifer layer 3 should have constant head boundaries"
        )

    def test_chd_layer2_absent(self):
        layers = self._get_chd_layers()
        assert 2 not in layers, (
            "Confining layer 2 should NOT have constant head boundaries"
        )


class TestBudgetAnalysis:
    """Verify the volumetric water budget evaluation."""

    def test_file_exists(self):
        assert os.path.exists("/app/results/budget_analysis.json"), (
            "budget_analysis.json not found"
        )

    def test_required_keys(self):
        with open("/app/results/budget_analysis.json") as f:
            data = json.load(f)
        for key in ["total_inflow_ft3ps", "total_outflow_ft3ps",
                     "percent_discrepancy"]:
            assert key in data, f"Missing key: {key}"

    def test_positive_flows(self):
        with open("/app/results/budget_analysis.json") as f:
            data = json.load(f)
        assert data["total_inflow_ft3ps"] > 0, (
            "Total inflow must be positive"
        )
        assert data["total_outflow_ft3ps"] > 0, (
            "Total outflow must be positive"
        )

    def test_budget_closes(self):
        with open("/app/results/budget_analysis.json") as f:
            data = json.load(f)
        assert abs(data["percent_discrepancy"]) < 1.0, (
            f"Budget discrepancy {data['percent_discrepancy']}% exceeds 1%"
        )

    def test_flow_magnitudes_reasonable(self):
        """Inflow and outflow should be in plausible range for TWRI model."""
        with open("/app/results/budget_analysis.json") as f:
            data = json.load(f)
        # Total recharge alone is ~169 ft³/s, so total inflow should exceed that
        assert data["total_inflow_ft3ps"] > 100, (
            f"Total inflow {data['total_inflow_ft3ps']} ft³/s implausibly low"
        )
        assert data["total_outflow_ft3ps"] > 100, (
            f"Total outflow {data['total_outflow_ft3ps']} ft³/s implausibly low"
        )


class TestModelAssessment:
    """Verify the physical behavior assessment of the corrected model."""

    def test_file_exists(self):
        assert os.path.exists("/app/results/model_assessment.json"), (
            "model_assessment.json not found"
        )

    def test_required_keys(self):
        with open("/app/results/model_assessment.json") as f:
            data = json.load(f)
        required = [
            "max_head_layer1", "max_head_layer5",
            "head_at_center_l1", "head_at_center_l5",
            "vertical_gradient_positive", "drains_removing_water"
        ]
        for key in required:
            assert key in data, f"Missing key: {key}"

    def test_positive_heads(self):
        """Recharge-driven system with CHD=0 should produce positive interior heads."""
        with open("/app/results/model_assessment.json") as f:
            data = json.load(f)
        assert data["max_head_layer1"] > 0, (
            f"Max head layer 1 = {data['max_head_layer1']}, expected positive"
        )
        assert data["max_head_layer5"] > 0, (
            f"Max head layer 5 = {data['max_head_layer5']}, expected positive"
        )
        assert data["head_at_center_l1"] > 0, (
            f"Center head L1 = {data['head_at_center_l1']}, expected positive"
        )
        assert data["head_at_center_l5"] > 0, (
            f"Center head L5 = {data['head_at_center_l5']}, expected positive"
        )

    def test_vertical_gradient(self):
        """Head should decrease with depth due to downward flow from surface recharge."""
        with open("/app/results/model_assessment.json") as f:
            data = json.load(f)
        assert data["vertical_gradient_positive"] is True, (
            "Vertical gradient should be positive (head decreases with depth). "
            f"Center L1={data.get('head_at_center_l1')}, "
            f"Center L5={data.get('head_at_center_l5')}"
        )
        assert data["head_at_center_l1"] > data["head_at_center_l5"], (
            "Layer 1 center head must exceed layer 5 center head "
            "(downward gradient from recharge)"
        )

    def test_drains_active(self):
        """TWRI model drains should be actively discharging."""
        with open("/app/results/model_assessment.json") as f:
            data = json.load(f)
        assert data["drains_removing_water"] is True, (
            "Drains should be actively removing water in the TWRI model"
        )

    def test_head_magnitudes_plausible(self):
        """Head values should be within physically plausible range for TWRI."""
        with open("/app/results/model_assessment.json") as f:
            data = json.load(f)
        assert data["max_head_layer1"] < 500, (
            f"Max head L1 = {data['max_head_layer1']}, implausibly high"
        )
        assert data["max_head_layer5"] < 500, (
            f"Max head L5 = {data['max_head_layer5']}, implausibly high"
        )


class TestWellDesign:
    """Verify the supplemental well field meets all design constraints."""

    def _load_wells(self):
        with open("/app/results/well_design.csv") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_file_exists(self):
        assert os.path.exists("/app/results/well_design.csv"), (
            "well_design.csv not found"
        )

    def test_columns(self):
        with open("/app/results/well_design.csv") as f:
            reader = csv.DictReader(f)
            for col in ["layer", "row", "col", "rate"]:
                assert col in reader.fieldnames, f"Missing column: {col}"

    def test_well_count(self):
        wells = self._load_wells()
        assert 3 <= len(wells) <= 8, (
            f"Expected 3-8 new wells, got {len(wells)}"
        )

    def test_total_extraction(self):
        wells = self._load_wells()
        total = sum(abs(float(w["rate"])) for w in wells)
        assert total >= 20.0, (
            f"Total new extraction {total:.2f} ft³/s < 20 ft³/s minimum"
        )

    def test_individual_rate_limit(self):
        wells = self._load_wells()
        for i, w in enumerate(wells):
            rate_mag = abs(float(w["rate"]))
            assert rate_mag <= 7.0, (
                f"Well {i+1} rate magnitude {rate_mag} exceeds 7 ft³/s limit"
            )

    def test_aquifer_layers_only(self):
        wells = self._load_wells()
        for i, w in enumerate(wells):
            layer = int(w["layer"])
            assert layer in (1, 3, 5), (
                f"Well {i+1} in layer {layer} (confining unit). "
                f"Wells must be in aquifer layers (1, 3, or 5)"
            )

    def test_rates_negative(self):
        wells = self._load_wells()
        for i, w in enumerate(wells):
            assert float(w["rate"]) < 0, (
                f"Well {i+1} rate must be negative (extraction), "
                f"got {w['rate']}"
            )

    def test_valid_grid_coords(self):
        wells = self._load_wells()
        for i, w in enumerate(wells):
            row, col = int(w["row"]), int(w["col"])
            assert 1 <= row <= 15, (
                f"Well {i+1} row {row} out of grid range [1, 15]"
            )
            assert 1 <= col <= 15, (
                f"Well {i+1} col {col} out of grid range [1, 15]"
            )

    def test_multiple_layers_used(self):
        wells = self._load_wells()
        layers = set(int(w["layer"]) for w in wells)
        assert len(layers) >= 2, (
            f"Wells must use at least 2 distinct aquifer layers, "
            f"only found layer(s): {sorted(layers)}"
        )


class TestHeadsCSV:
    """Verify the augmented-simulation head distribution."""

    def _load_heads(self):
        heads = {}
        with open("/app/results/heads.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (int(row["layer"]), int(row["row"]), int(row["col"]))
                heads[key] = float(row["head"])
        return heads

    def test_file_exists(self):
        assert os.path.exists("/app/results/heads.csv"), (
            "heads.csv not found"
        )

    def test_columns(self):
        with open("/app/results/heads.csv") as f:
            reader = csv.DictReader(f)
            for col in ["layer", "row", "col", "head"]:
                assert col in reader.fieldnames, f"Missing column: {col}"

    def test_row_count(self):
        with open("/app/results/heads.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) >= 1125, (
            f"Expected at least 1125 entries (5*15*15), got {len(rows)}"
        )

    def test_no_dry_cells(self):
        """No computed head should fall below the layer's bottom elevation."""
        heads = self._load_heads()
        for (layer, row, col), head in heads.items():
            bottom = LAYER_BOTTOMS[layer]
            assert head >= bottom - 1.0, (
                f"Head {head:.2f} at cell ({layer},{row},{col}) is below "
                f"layer bottom elevation {bottom} — indicates over-pumping "
                f"or model instability"
            )

    def test_chd_cells_near_zero(self):
        """CHD cells on western edge of layer 1 should have head near 0."""
        heads = self._load_heads()
        for r in range(1, 16):
            h = heads.get((1, r, 1))
            if h is not None:
                assert abs(h) < 1.0, (
                    f"CHD cell (1,{r},1) head={h:.4f}, expected ~0.0"
                )

    def test_chd_cells_layer3_near_zero(self):
        """CHD cells on western edge of layer 3 should have head near 0."""
        heads = self._load_heads()
        for r in range(1, 16):
            h = heads.get((3, r, 1))
            if h is not None:
                assert abs(h) < 1.0, (
                    f"CHD cell (3,{r},1) head={h:.4f}, expected ~0.0"
                )

    def test_interior_heads_positive(self):
        """Interior heads should be positive in a recharge-driven system."""
        heads = self._load_heads()
        center = heads.get((1, 8, 8))
        assert center is not None, "Center cell (1,8,8) not found in results"
        assert center > 0, (
            f"Center head at (1,8,8) = {center:.4f}, expected positive"
        )

    def test_heads_in_range(self):
        """All heads should be within physically reasonable bounds."""
        heads = self._load_heads()
        for key, h in heads.items():
            assert -500 < h < 500, (
                f"Head at cell {key} = {h} outside reasonable range [-500, 500]"
            )

    def test_head_gradient_from_boundary(self):
        """Heads should increase away from the CHD boundary (west edge, h=0)."""
        heads = self._load_heads()
        h_col1 = heads.get((1, 8, 1), 0.0)
        h_col8 = heads.get((1, 8, 8))
        assert h_col8 is not None
        assert h_col8 > h_col1, (
            f"Head at (1,8,8)={h_col8:.4f} should exceed "
            f"head at (1,8,1)={h_col1:.4f} (recharge gradient)"
        )
