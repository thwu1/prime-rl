#!/usr/bin/env python3
"""ORD Parquet Dataset Analyzer.


Reads an ORD parquet dataset, validates cross-references, extracts yields
with normalized conditions, and computes statistics.

Usage: python3 ord_analyze.py <parquet_file> <output_json>
"""

import json
import sys

import numpy as np
import pyarrow.parquet as pq

import reaction_pb2


# ---------------------------------------------------------------------------
# Parquet I/O
# ---------------------------------------------------------------------------

def read_parquet(path):
    """Read an ORD parquet file. Returns (name, description, [Reaction])."""
    pf = pq.ParquetFile(path)
    meta = pf.schema_arrow.metadata or {}

    dataset_name = meta.get(b"ord.name", b"").decode()
    dataset_description = meta.get(b"ord.description", b"").decode()

    reactions = []
    for batch in pf.iter_batches(columns=["reaction_id", "reaction"]):
        blobs = batch.column("reaction").to_pylist()
        for blob in blobs:
            rxn = reaction_pb2.Reaction.FromString(blob)
            reactions.append(rxn)

    pf.close()
    return dataset_name, dataset_description, reactions


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

def temperature_to_celsius(value, units):
    """Convert a temperature value to Celsius."""
    if units == reaction_pb2.Temperature.CELSIUS:
        return value
    if units == reaction_pb2.Temperature.FAHRENHEIT:
        return (value - 32.0) * 5.0 / 9.0
    if units == reaction_pb2.Temperature.KELVIN:
        return value - 273.15
    return None


def time_to_hours(value, units):
    """Convert a time value to hours."""
    factors = {
        reaction_pb2.Time.HOUR: 1.0,
        reaction_pb2.Time.MINUTE: 1.0 / 60.0,
        reaction_pb2.Time.SECOND: 1.0 / 3600.0,
        reaction_pb2.Time.DAY: 24.0,
    }
    f = factors.get(units)
    return value * f if f is not None else None


def pressure_to_bar(value, units):
    """Convert a pressure value to bar.

    Strategy: convert to atmosphere first, then multiply by 1.01325.
    """
    # Factors to convert each unit to atmosphere
    to_atm = {
        reaction_pb2.Pressure.BAR: 1.0 / 1.01325,
        reaction_pb2.Pressure.ATMOSPHERE: 1.0,
        reaction_pb2.Pressure.PSI: 1.0 / 14.69595,
        reaction_pb2.Pressure.KPSI: 1000.0 / 14.69595,
        reaction_pb2.Pressure.PASCAL: 1.0 / 101325.0,
        reaction_pb2.Pressure.KILOPASCAL: 1000.0 / 101325.0,
        reaction_pb2.Pressure.TORR: 1.0 / 760.0,
        reaction_pb2.Pressure.MM_HG: 1.0 / 760.0,
    }
    factor = to_atm.get(units)
    if factor is None:
        return None
    atm_value = value * factor
    return atm_value * 1.01325


# ---------------------------------------------------------------------------
# Condition extraction helpers
# ---------------------------------------------------------------------------

def _has_message(parent, field_name):
    """Check if a proto3 message field is present."""
    try:
        return parent.HasField(field_name)
    except ValueError:
        return False


def get_temperature_celsius(rxn):
    """Extract and normalize the temperature setpoint from conditions."""
    if not _has_message(rxn, "conditions"):
        return None
    cond = rxn.conditions
    if not _has_message(cond, "temperature"):
        return None
    tc = cond.temperature
    if not _has_message(tc, "setpoint"):
        return None
    sp = tc.setpoint
    if not sp.HasField("value") or sp.units == reaction_pb2.Temperature.UNSPECIFIED:
        return None
    return temperature_to_celsius(sp.value, sp.units)


def get_pressure_bar(rxn):
    """Extract and normalize the pressure setpoint from conditions."""
    if not _has_message(rxn, "conditions"):
        return None
    cond = rxn.conditions
    if not _has_message(cond, "pressure"):
        return None
    pc = cond.pressure
    if not _has_message(pc, "setpoint"):
        return None
    sp = pc.setpoint
    if not sp.HasField("value") or sp.units == reaction_pb2.Pressure.UNSPECIFIED:
        return None
    return pressure_to_bar(sp.value, sp.units)


def get_time_hours(outcome):
    """Extract and normalize the reaction time from an outcome."""
    if not _has_message(outcome, "reaction_time"):
        return None
    rt = outcome.reaction_time
    if not rt.HasField("value") or rt.units == reaction_pb2.Time.UNSPECIFIED:
        return None
    return time_to_hours(rt.value, rt.units)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_dataset(reactions):
    """Validate cross-references across all reactions."""
    all_ids = [r.reaction_id for r in reactions]
    id_set = set(all_ids)

    # Duplicate IDs
    seen = set()
    duplicates = set()
    for rid in all_ids:
        if rid in seen:
            duplicates.add(rid)
        seen.add(rid)

    orphaned_crude = []
    orphaned_prep = []
    self_refs = set()
    invalid_keys = []

    for rxn in reactions:
        rid = rxn.reaction_id

        for _input_key, input_val in rxn.inputs.items():
            # Crude component references
            for crude in input_val.crude_components:
                ref = crude.reaction_id
                if ref == rid:
                    self_refs.add(rid)
                elif ref and ref not in id_set:
                    orphaned_crude.append({
                        "reaction_id": rid,
                        "orphaned_ref": ref,
                    })

            # Compound preparation references (SYNTHESIZED only)
            for comp in input_val.components:
                for prep in comp.preparations:
                    if (prep.type == reaction_pb2.CompoundPreparation.SYNTHESIZED
                            and prep.reaction_id):
                        ref = prep.reaction_id
                        if ref == rid:
                            self_refs.add(rid)
                        elif ref not in id_set:
                            orphaned_prep.append({
                                "reaction_id": rid,
                                "orphaned_ref": ref,
                            })

        # Analysis key references
        for outcome in rxn.outcomes:
            analysis_keys = set(outcome.analyses.keys())
            for prod_idx, product in enumerate(outcome.products):
                for meas_idx, measurement in enumerate(product.measurements):
                    ak = measurement.analysis_key
                    if ak and ak not in analysis_keys:
                        invalid_keys.append({
                            "reaction_id": rid,
                            "product_index": prod_idx,
                            "measurement_index": meas_idx,
                            "key": ak,
                        })

    return {
        "duplicate_reaction_ids": sorted(duplicates),
        "orphaned_crude_refs": orphaned_crude,
        "orphaned_preparation_refs": orphaned_prep,
        "self_references": sorted(self_refs),
        "invalid_analysis_keys": invalid_keys,
    }


# ---------------------------------------------------------------------------
# Yield extraction
# ---------------------------------------------------------------------------

def extract_yields(reactions):
    """Extract all YIELD measurements with normalized conditions."""
    yields = []

    for rxn in reactions:
        temp_c = get_temperature_celsius(rxn)
        press_b = get_pressure_bar(rxn)

        for outcome in rxn.outcomes:
            time_h = get_time_hours(outcome)
            analysis_map = dict(outcome.analyses)

            for product in outcome.products:
                for measurement in product.measurements:
                    if measurement.type != reaction_pb2.ProductMeasurement.YIELD:
                        continue
                    if not measurement.HasField("percentage"):
                        continue

                    # Determine analysis type name for grouping
                    analysis_type_name = None
                    ak = measurement.analysis_key
                    if ak and ak in analysis_map:
                        analysis_obj = analysis_map[ak]
                        if analysis_obj.type != reaction_pb2.Analysis.UNSPECIFIED:
                            analysis_type_name = (
                                reaction_pb2.Analysis.AnalysisType.Name(
                                    analysis_obj.type
                                )
                            )

                    yields.append({
                        "reaction_id": rxn.reaction_id,
                        "yield_percent": round(float(measurement.percentage.value), 4),
                        "temperature_celsius": (
                            round(float(temp_c), 4) if temp_c is not None else None
                        ),
                        "time_hours": (
                            round(float(time_h), 4) if time_h is not None else None
                        ),
                        "pressure_bar": (
                            round(float(press_b), 4) if press_b is not None else None
                        ),
                        "_analysis_type": analysis_type_name,
                    })

    return yields


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_statistics(yields_list):
    """Compute aggregate yield statistics."""
    if not yields_list:
        return {
            "mean_yield": 0.0,
            "std_yield": 0.0,
            "median_yield": 0.0,
            "num_yields": 0,
            "yield_by_temperature_bin": {},
            "yield_by_analysis_type": {},
        }

    values = np.array([y["yield_percent"] for y in yields_list], dtype=float)

    # Temperature bins: name → [yield values]
    bin_defs = [
        ("below_0", lambda t: t < 0),
        ("0_to_25", lambda t: 0 <= t < 25),
        ("25_to_50", lambda t: 25 <= t < 50),
        ("50_to_100", lambda t: 50 <= t < 100),
        ("above_100", lambda t: t >= 100),
    ]
    bins = {name: [] for name, _ in bin_defs}

    for y in yields_list:
        t = y["temperature_celsius"]
        if t is None:
            continue
        for name, pred in bin_defs:
            if pred(t):
                bins[name].append(y["yield_percent"])
                break

    bin_stats = {}
    for name, vals in bins.items():
        if vals:
            bin_stats[name] = {
                "mean": round(float(np.mean(vals)), 4),
                "count": len(vals),
            }

    # Analysis type grouping
    type_groups = {}
    for y in yields_list:
        at = y.get("_analysis_type")
        if at:
            type_groups.setdefault(at, []).append(y["yield_percent"])

    type_stats = {}
    for at, vals in sorted(type_groups.items()):
        type_stats[at] = {
            "mean": round(float(np.mean(vals)), 4),
            "count": len(vals),
        }

    return {
        "mean_yield": round(float(np.mean(values)), 4),
        "std_yield": round(float(np.std(values)), 4),
        "median_yield": round(float(np.median(values)), 4),
        "num_yields": len(values),
        "yield_by_temperature_bin": bin_stats,
        "yield_by_analysis_type": type_stats,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 ord_analyze.py <parquet_file> <output_json>",
            file=sys.stderr,
        )
        sys.exit(1)

    parquet_path = sys.argv[1]
    output_path = sys.argv[2]

    dataset_name, dataset_description, reactions = read_parquet(parquet_path)
    validation = validate_dataset(reactions)
    yields_list = extract_yields(reactions)
    stats = compute_statistics(yields_list)

    # Strip internal fields from yields before output
    output_yields = [
        {k: v for k, v in y.items() if not k.startswith("_")}
        for y in yields_list
    ]

    output = {
        "dataset_name": dataset_name,
        "dataset_description": dataset_description,
        "num_reactions": len(reactions),
        "validation": validation,
        "yields": output_yields,
        "statistics": stats,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
