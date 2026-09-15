"""Tests for ORD Parquet Analyzer."""


import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import reaction_pb2


def create_test_parquet(reactions, name="test_dataset", description="test description"):
    """Create a test parquet file from a list of Reaction messages."""
    fd, path = tempfile.mkstemp(suffix=".parquet")
    os.close(fd)

    ids = [r.reaction_id for r in reactions]
    blobs = [r.SerializeToString(deterministic=True) for r in reactions]

    schema = pa.schema([
        pa.field("reaction_id", pa.string(), nullable=False),
        pa.field("reaction", pa.binary(), nullable=False),
    ]).with_metadata({
        "ord.schema_version": "1",
        "ord.name": name,
        "ord.description": description,
    })

    table = pa.table({"reaction_id": ids, "reaction": blobs}, schema=schema)
    pq.write_table(table, path)
    return path


def make_reaction(reaction_id):
    """Create a basic Reaction with the given ID."""
    rxn = reaction_pb2.Reaction()
    rxn.reaction_id = reaction_id
    return rxn


def run_analyzer(parquet_path):
    """Run the analyzer tool and return parsed JSON output."""
    fd, output_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)

    result = subprocess.run(
        ["python3", "/app/ord_analyze.py", parquet_path, output_path],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"Analyzer failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    with open(output_path) as f:
        data = json.load(f)

    os.unlink(output_path)
    return data


def build_main_dataset():
    """Build the comprehensive test dataset with 11 reactions."""
    reactions = []

    # R1: Fahrenheit temp (77°F → 25°C), minute time (120 min → 2h), yield 85%
    r1 = make_reaction("ord-00000000000000000000000000000001")
    r1.conditions.temperature.setpoint.value = 77.0
    r1.conditions.temperature.setpoint.units = reaction_pb2.Temperature.FAHRENHEIT
    outcome = r1.outcomes.add()
    outcome.reaction_time.value = 120.0
    outcome.reaction_time.units = reaction_pb2.Time.MINUTE
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CCO")
    product.is_desired_product = True
    outcome.analyses["lcms_1"].type = reaction_pb2.Analysis.LCMS
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "lcms_1"
    m.percentage.value = 85.0
    reactions.append(r1)

    # R2: Kelvin temp (373.15K → 100°C), hour time (2h), yield 42%
    r2 = make_reaction("ord-00000000000000000000000000000002")
    r2.conditions.temperature.setpoint.value = 373.15
    r2.conditions.temperature.setpoint.units = reaction_pb2.Temperature.KELVIN
    outcome = r2.outcomes.add()
    outcome.reaction_time.value = 2.0
    outcome.reaction_time.units = reaction_pb2.Time.HOUR
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="c1ccccc1")
    outcome.analyses["gc_1"].type = reaction_pb2.Analysis.GC
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "gc_1"
    m.percentage.value = 42.0
    reactions.append(r2)

    # R3: PSI pressure (14.69595 PSI → 1.01325 bar), day time (1 day → 24h),
    #     Celsius temp (50°C), yield 55%
    r3 = make_reaction("ord-00000000000000000000000000000003")
    r3.conditions.temperature.setpoint.value = 50.0
    r3.conditions.temperature.setpoint.units = reaction_pb2.Temperature.CELSIUS
    r3.conditions.pressure.setpoint.value = 14.69595
    r3.conditions.pressure.setpoint.units = reaction_pb2.Pressure.PSI
    outcome = r3.outcomes.add()
    outcome.reaction_time.value = 1.0
    outcome.reaction_time.units = reaction_pb2.Time.DAY
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CC=O")
    outcome.analyses["nmr_1"].type = reaction_pb2.Analysis.NMR_1H
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "nmr_1"
    m.percentage.value = 55.0
    reactions.append(r3)

    # R4: No conditions at all, yield 60%
    r4 = make_reaction("ord-00000000000000000000000000000004")
    outcome = r4.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CC(=O)O")
    outcome.analyses["wt_1"].type = reaction_pb2.Analysis.WEIGHT
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "wt_1"
    m.percentage.value = 60.0
    reactions.append(r4)

    # R5: Valid crude component reference to R1, no conditions, yield 70%
    r5 = make_reaction("ord-00000000000000000000000000000005")
    crude_input = r5.inputs["crude"]
    crude = crude_input.crude_components.add()
    crude.reaction_id = "ord-00000000000000000000000000000001"
    crude.has_derived_amount = True
    outcome = r5.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CCCC")
    outcome.analyses["a1"].type = reaction_pb2.Analysis.LC
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "a1"
    m.percentage.value = 70.0
    reactions.append(r5)

    # R6: Orphaned crude component reference (nonexistent target), yield 30%
    r6 = make_reaction("ord-00000000000000000000000000000006")
    crude_input = r6.inputs["crude"]
    crude = crude_input.crude_components.add()
    crude.reaction_id = "ord-ffffffffffffffffffffffffffffffff"
    crude.has_derived_amount = True
    outcome = r6.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CCCCC")
    outcome.analyses["a1"].type = reaction_pb2.Analysis.LC
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "a1"
    m.percentage.value = 30.0
    reactions.append(r6)

    # R7: Self-referencing reaction via crude component (no yield)
    r7 = make_reaction("ord-00000000000000000000000000000007")
    crude_input = r7.inputs["crude"]
    crude = crude_input.crude_components.add()
    crude.reaction_id = "ord-00000000000000000000000000000007"
    crude.has_derived_amount = True
    outcome = r7.outcomes.add()
    reactions.append(r7)

    # R8a: Duplicate ID (first occurrence), temp -10°C, yield 90%
    r8a = make_reaction("ord-00000000000000000000000000000008")
    r8a.conditions.temperature.setpoint.value = -10.0
    r8a.conditions.temperature.setpoint.units = reaction_pb2.Temperature.CELSIUS
    outcome = r8a.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CC")
    outcome.analyses["a1"].type = reaction_pb2.Analysis.WEIGHT
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "a1"
    m.percentage.value = 90.0
    reactions.append(r8a)

    # R8b: Duplicate ID (second occurrence), temp -20°C, yield 95%
    r8b = make_reaction("ord-00000000000000000000000000000008")
    r8b.conditions.temperature.setpoint.value = -20.0
    r8b.conditions.temperature.setpoint.units = reaction_pb2.Temperature.CELSIUS
    outcome = r8b.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CCC")
    outcome.analyses["a1"].type = reaction_pb2.Analysis.WEIGHT
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "a1"
    m.percentage.value = 95.0
    reactions.append(r8b)

    # R9: Invalid analysis key, temp 150°C, yield 75%
    r9 = make_reaction("ord-00000000000000000000000000000009")
    r9.conditions.temperature.setpoint.value = 150.0
    r9.conditions.temperature.setpoint.units = reaction_pb2.Temperature.CELSIUS
    outcome = r9.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CCCCCC")
    outcome.analyses["real_analysis"].type = reaction_pb2.Analysis.LCMS
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "nonexistent_key"
    m.percentage.value = 75.0
    reactions.append(r9)

    # R10: Orphaned preparation reference (SYNTHESIZED type), temp 80°C, yield 50%
    r10 = make_reaction("ord-0000000000000000000000000000000a")
    comp_input = r10.inputs["reagent"]
    compound = comp_input.components.add()
    compound.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CC(C)C")
    compound.amount.mass.value = 100.0
    compound.amount.mass.units = reaction_pb2.Mass.MILLIGRAM
    prep = compound.preparations.add()
    prep.type = reaction_pb2.CompoundPreparation.SYNTHESIZED
    prep.reaction_id = "ord-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    r10.conditions.temperature.setpoint.value = 80.0
    r10.conditions.temperature.setpoint.units = reaction_pb2.Temperature.CELSIUS
    outcome = r10.outcomes.add()
    product = outcome.products.add()
    product.identifiers.add(type=reaction_pb2.CompoundIdentifier.SMILES, value="CC(C)CC")
    outcome.analyses["a1"].type = reaction_pb2.Analysis.WEIGHT
    m = product.measurements.add()
    m.type = reaction_pb2.ProductMeasurement.YIELD
    m.analysis_key = "a1"
    m.percentage.value = 50.0
    reactions.append(r10)

    return reactions


@pytest.fixture(scope="module")
def main_output():
    """Create the main test dataset and run the analyzer."""
    reactions = build_main_dataset()
    parquet_path = create_test_parquet(
        reactions,
        name="HTE Test Dataset",
        description="Synthetic dataset for testing ORD analyzer"
    )
    data = run_analyzer(parquet_path)
    os.unlink(parquet_path)
    return data


# ---- Metadata tests ----

class TestMetadata:
    def test_dataset_name(self, main_output):
        assert main_output["dataset_name"] == "HTE Test Dataset"

    def test_dataset_description(self, main_output):
        assert main_output["dataset_description"] == "Synthetic dataset for testing ORD analyzer"

    def test_num_reactions(self, main_output):
        # 11 Reaction messages total (including the duplicate-ID pair)
        assert main_output["num_reactions"] == 11


# ---- Validation tests ----

class TestValidation:
    def test_duplicate_reaction_ids(self, main_output):
        dups = main_output["validation"]["duplicate_reaction_ids"]
        assert "ord-00000000000000000000000000000008" in dups
        assert len(dups) == 1

    def test_orphaned_crude_refs(self, main_output):
        orphans = main_output["validation"]["orphaned_crude_refs"]
        refs = {(o["reaction_id"], o["orphaned_ref"]) for o in orphans}
        assert (
            "ord-00000000000000000000000000000006",
            "ord-ffffffffffffffffffffffffffffffff",
        ) in refs

    def test_no_false_positive_crude_refs(self, main_output):
        """R5's crude ref to R1 is valid and should NOT appear as orphaned."""
        orphans = main_output["validation"]["orphaned_crude_refs"]
        for o in orphans:
            assert o["orphaned_ref"] != "ord-00000000000000000000000000000001"

    def test_self_references(self, main_output):
        selfs = main_output["validation"]["self_references"]
        assert "ord-00000000000000000000000000000007" in selfs

    def test_orphaned_preparation_refs(self, main_output):
        orphans = main_output["validation"]["orphaned_preparation_refs"]
        refs = {(o["reaction_id"], o["orphaned_ref"]) for o in orphans}
        assert (
            "ord-0000000000000000000000000000000a",
            "ord-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        ) in refs

    def test_invalid_analysis_keys(self, main_output):
        invalids = main_output["validation"]["invalid_analysis_keys"]
        keys = {(i["reaction_id"], i["key"]) for i in invalids}
        assert (
            "ord-00000000000000000000000000000009",
            "nonexistent_key",
        ) in keys


# ---- Yield extraction tests ----

class TestYieldExtraction:
    def test_num_yields(self, main_output):
        # 10 YIELD measurements across all reactions (R7 has none)
        assert len(main_output["yields"]) == 10

    def test_fahrenheit_to_celsius(self, main_output):
        """77°F → 25°C"""
        r1 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000001"]
        assert len(r1) == 1
        assert abs(r1[0]["temperature_celsius"] - 25.0) < 0.01
        assert r1[0]["yield_percent"] == 85.0

    def test_kelvin_to_celsius(self, main_output):
        """373.15K → 100°C"""
        r2 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000002"]
        assert len(r2) == 1
        assert abs(r2[0]["temperature_celsius"] - 100.0) < 0.01
        assert r2[0]["yield_percent"] == 42.0

    def test_celsius_passthrough(self, main_output):
        """50°C stays 50°C"""
        r3 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000003"]
        assert len(r3) == 1
        assert abs(r3[0]["temperature_celsius"] - 50.0) < 0.01

    def test_time_minute_to_hours(self, main_output):
        """120 minutes → 2 hours"""
        r1 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000001"]
        assert abs(r1[0]["time_hours"] - 2.0) < 0.001

    def test_time_day_to_hours(self, main_output):
        """1 day → 24 hours"""
        r3 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000003"]
        assert abs(r3[0]["time_hours"] - 24.0) < 0.001

    def test_time_hour_passthrough(self, main_output):
        """2 hours stays 2 hours"""
        r2 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000002"]
        assert abs(r2[0]["time_hours"] - 2.0) < 0.001

    def test_pressure_psi_to_bar(self, main_output):
        """14.69595 PSI → 1.01325 bar"""
        r3 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000003"]
        assert abs(r3[0]["pressure_bar"] - 1.01325) < 0.001

    def test_null_conditions(self, main_output):
        """R4 has no conditions → all null"""
        r4 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000004"]
        assert len(r4) == 1
        assert r4[0]["temperature_celsius"] is None
        assert r4[0]["time_hours"] is None
        assert r4[0]["pressure_bar"] is None

    def test_null_pressure_when_unset(self, main_output):
        """R1 has temperature but no pressure → pressure is null"""
        r1 = [y for y in main_output["yields"]
              if y["reaction_id"] == "ord-00000000000000000000000000000001"]
        assert r1[0]["pressure_bar"] is None

    def test_negative_temperature_celsius(self, main_output):
        """Negative Celsius temperatures should be preserved"""
        r8_yields = [y for y in main_output["yields"]
                     if y["reaction_id"] == "ord-00000000000000000000000000000008"]
        temps = sorted([y["temperature_celsius"] for y in r8_yields])
        assert len(temps) == 2
        assert abs(temps[0] - (-20.0)) < 0.01
        assert abs(temps[1] - (-10.0)) < 0.01


# ---- Statistics tests ----

class TestStatistics:
    def test_num_yields(self, main_output):
        assert main_output["statistics"]["num_yields"] == 10

    def test_mean_yield(self, main_output):
        # Yields: 85, 42, 55, 60, 70, 30, 90, 95, 75, 50 → mean = 65.2
        expected = 65.2
        assert abs(main_output["statistics"]["mean_yield"] - expected) < 0.01

    def test_median_yield(self, main_output):
        # Sorted: 30, 42, 50, 55, 60, 70, 75, 85, 90, 95 → median = (60+70)/2 = 65.0
        expected = 65.0
        assert abs(main_output["statistics"]["median_yield"] - expected) < 0.01

    def test_std_yield(self, main_output):
        # Population std of [85, 42, 55, 60, 70, 30, 90, 95, 75, 50]
        vals = [85, 42, 55, 60, 70, 30, 90, 95, 75, 50]
        expected = float(np.std(vals))
        assert abs(main_output["statistics"]["std_yield"] - expected) < 0.1

    def test_bin_below_0(self, main_output):
        """temps -10, -20 → yields 90, 95 → mean=92.5"""
        bins = main_output["statistics"]["yield_by_temperature_bin"]
        assert "below_0" in bins
        assert bins["below_0"]["count"] == 2
        assert abs(bins["below_0"]["mean"] - 92.5) < 0.01

    def test_bin_25_to_50(self, main_output):
        """temp 25 → yield 85 → mean=85.0"""
        bins = main_output["statistics"]["yield_by_temperature_bin"]
        assert "25_to_50" in bins
        assert bins["25_to_50"]["count"] == 1
        assert abs(bins["25_to_50"]["mean"] - 85.0) < 0.01

    def test_bin_50_to_100(self, main_output):
        """temps 50, 80 → yields 55, 50 → mean=52.5"""
        bins = main_output["statistics"]["yield_by_temperature_bin"]
        assert "50_to_100" in bins
        assert bins["50_to_100"]["count"] == 2
        assert abs(bins["50_to_100"]["mean"] - 52.5) < 0.01

    def test_bin_above_100(self, main_output):
        """temps 100, 150 → yields 42, 75 → mean=58.5"""
        bins = main_output["statistics"]["yield_by_temperature_bin"]
        assert "above_100" in bins
        assert bins["above_100"]["count"] == 2
        assert abs(bins["above_100"]["mean"] - 58.5) < 0.01

    def test_bin_0_to_25_omitted(self, main_output):
        """No yields in [0, 25) range → bin should be omitted"""
        bins = main_output["statistics"]["yield_by_temperature_bin"]
        assert "0_to_25" not in bins

    def test_yield_by_analysis_type_lcms(self, main_output):
        """R1 uses LCMS → yield 85"""
        by_type = main_output["statistics"]["yield_by_analysis_type"]
        assert "LCMS" in by_type
        assert by_type["LCMS"]["count"] == 1
        assert abs(by_type["LCMS"]["mean"] - 85.0) < 0.01

    def test_yield_by_analysis_type_gc(self, main_output):
        """R2 uses GC → yield 42"""
        by_type = main_output["statistics"]["yield_by_analysis_type"]
        assert "GC" in by_type
        assert by_type["GC"]["count"] == 1
        assert abs(by_type["GC"]["mean"] - 42.0) < 0.01

    def test_yield_by_analysis_type_nmr(self, main_output):
        """R3 uses NMR_1H → yield 55"""
        by_type = main_output["statistics"]["yield_by_analysis_type"]
        assert "NMR_1H" in by_type
        assert by_type["NMR_1H"]["count"] == 1
        assert abs(by_type["NMR_1H"]["mean"] - 55.0) < 0.01

    def test_yield_by_analysis_type_weight(self, main_output):
        """R4(60), R8a(90), R8b(95), R10(50) use WEIGHT → mean=73.75"""
        by_type = main_output["statistics"]["yield_by_analysis_type"]
        assert "WEIGHT" in by_type
        assert by_type["WEIGHT"]["count"] == 4
        assert abs(by_type["WEIGHT"]["mean"] - 73.75) < 0.01

    def test_yield_by_analysis_type_lc(self, main_output):
        """R5(70), R6(30) use LC → mean=50.0"""
        by_type = main_output["statistics"]["yield_by_analysis_type"]
        assert "LC" in by_type
        assert by_type["LC"]["count"] == 2
        assert abs(by_type["LC"]["mean"] - 50.0) < 0.01

    def test_yield_by_analysis_type_excludes_invalid_key(self, main_output):
        """R9 has invalid analysis key → its yield (75) should NOT appear in any type group"""
        by_type = main_output["statistics"]["yield_by_analysis_type"]
        total_typed = sum(v["count"] for v in by_type.values())
        # 9 out of 10 yields should be grouped (R9 excluded)
        assert total_typed == 9


# ---- Standalone pressure conversion tests ----

class TestPressureConversions:
    def test_pascal_to_bar(self):
        """202650 Pa → 2.0265 bar"""
        rxn = make_reaction("ord-a0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 202650.0
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.PASCAL
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="pa_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        # 202650 Pa = 2 atm = 2 * 1.01325 bar = 2.0265 bar
        assert abs(data["yields"][0]["pressure_bar"] - 2.0265) < 0.001

    def test_atmosphere_to_bar(self):
        """2 atm → 2.0265 bar"""
        rxn = make_reaction("ord-b0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 2.0
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.ATMOSPHERE
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="atm_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["pressure_bar"] - 2.0265) < 0.001

    def test_kilopascal_to_bar(self):
        """101.325 kPa → 1.01325 bar"""
        rxn = make_reaction("ord-c0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 101.325
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.KILOPASCAL
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="kpa_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["pressure_bar"] - 1.01325) < 0.001

    def test_bar_passthrough(self):
        """1.5 bar stays 1.5 bar"""
        rxn = make_reaction("ord-d0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 1.5
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.BAR
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="bar_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["pressure_bar"] - 1.5) < 0.001

    def test_torr_to_bar(self):
        """1520 Torr → 2 atm → 2.0265 bar"""
        rxn = make_reaction("ord-f0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 1520.0
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.TORR
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="torr_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["pressure_bar"] - 2.0265) < 0.001

    def test_mmhg_to_bar(self):
        """760 mmHg → 1 atm → 1.01325 bar"""
        rxn = make_reaction("ord-g0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 760.0
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.MM_HG
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="mmhg_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["pressure_bar"] - 1.01325) < 0.001

    def test_kpsi_to_bar(self):
        """0.01469595 KPSI = 14.69595 PSI → 1 atm → 1.01325 bar"""
        rxn = make_reaction("ord-h0000000000000000000000000000001")
        rxn.conditions.pressure.setpoint.value = 0.01469595
        rxn.conditions.pressure.setpoint.units = reaction_pb2.Pressure.KPSI
        outcome = rxn.outcomes.add()
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="kpsi_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["pressure_bar"] - 1.01325) < 0.001


# ---- Edge case: time in seconds ----

class TestTimeConversion:
    def test_seconds_to_hours(self):
        """7200 seconds → 2 hours"""
        rxn = make_reaction("ord-e0000000000000000000000000000001")
        outcome = rxn.outcomes.add()
        outcome.reaction_time.value = 7200.0
        outcome.reaction_time.units = reaction_pb2.Time.SECOND
        product = outcome.products.add()
        product.identifiers.add(
            type=reaction_pb2.CompoundIdentifier.SMILES, value="C"
        )
        outcome.analyses["a"].type = reaction_pb2.Analysis.WEIGHT
        m = product.measurements.add()
        m.type = reaction_pb2.ProductMeasurement.YIELD
        m.analysis_key = "a"
        m.percentage.value = 50.0

        path = create_test_parquet([rxn], name="sec_test", description="test")
        data = run_analyzer(path)
        os.unlink(path)

        assert len(data["yields"]) == 1
        assert abs(data["yields"][0]["time_hours"] - 2.0) < 0.001


# ---- Rounding test ----

class TestRounding:
    def test_floats_are_rounded(self, main_output):
        """All float values should be rounded to 4 decimal places."""
        for y in main_output["yields"]:
            for key in ["yield_percent", "temperature_celsius", "time_hours", "pressure_bar"]:
                val = y[key]
                if val is not None:
                    # Check that the value has at most 4 decimal places
                    s = f"{val:.10f}"
                    decimal_part = s.split(".")[1]
                    # After the 4th decimal digit, remaining should be zeros
                    assert decimal_part[4:] == "000000", (
                        f"{key}={val} has more than 4 decimal places"
                    )
