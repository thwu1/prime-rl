#!/usr/bin/env python3
"""
Multi-product satellite remote sensing QA decode, scale-factor, and EVI pipeline.

Dynamically discovers QA bitmask layouts and layer metadata from the AppEEARS API,
then processes mixed-product observations through decode → filter → scale → index stages.
"""


import json
import os
import sys
import requests
from collections import OrderedDict

API_BASE = "https://appeears.earthdatacloud.nasa.gov/api"

_qa_cache = {}
_product_cache = {}


def get_qa_field_specs(product, qa_layer):
    """Retrieve QA field definitions from the AppEEARS quality listing endpoint
    and infer the packed bitmask layout (bit widths and positions)."""
    key = f"{product}/{qa_layer}"
    if key in _qa_cache:
        return _qa_cache[key]

    url = f"{API_BASE}/quality/{product}/{qa_layer}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    entries = resp.json()

    # Group entries by field name, preserving the order of first appearance.
    # The API returns fields in bit-packing order (LSB-first).
    fields = OrderedDict()
    for entry in entries:
        name = entry["Name"]
        if name not in fields:
            fields[name] = {}
        fields[name][entry["Value"]] = entry["Description"]

    # Infer bit width per field from the maximum defined value.
    specs = []
    for name, value_map in fields.items():
        max_val = max(value_map.keys())
        bit_width = max(1, max_val.bit_length()) if max_val > 0 else 1
        specs.append({
            "name": name,
            "bit_width": bit_width,
            "values": value_map,
        })

    _qa_cache[key] = specs
    return specs


def decode_qa_value(qa_value, field_specs):
    """Decode a packed QA integer into its constituent named fields."""
    result = OrderedDict()
    bit_offset = 0
    for spec in field_specs:
        mask = (1 << spec["bit_width"]) - 1
        field_val = (qa_value >> bit_offset) & mask
        desc = spec["values"].get(field_val, f"Unknown value {field_val}")
        result[spec["name"]] = {"value": field_val, "description": desc}
        bit_offset += spec["bit_width"]
    return result


def get_product_layers(product):
    """Retrieve all layer metadata for a product from the AppEEARS product endpoint."""
    if product in _product_cache:
        return _product_cache[product]

    url = f"{API_BASE}/product/{product}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    _product_cache[product] = data
    return data


def scale_measurement(raw_value, layer_meta):
    """Apply ScaleFactor and AddOffset to a raw integer value.
    Returns (scaled_value_or_None, is_fill_bool)."""
    fv = layer_meta.get("FillValue")
    if fv is not None and raw_value == fv:
        return None, True

    sf = layer_meta.get("ScaleFactor", "")
    ao = layer_meta.get("AddOffset", "")

    if sf != "" and sf is not None:
        scaled = float(raw_value) * float(sf)
    else:
        scaled = float(raw_value)

    if ao != "" and ao is not None:
        scaled += float(ao)

    return scaled, False


def compute_evi(red, nir, blue):
    """Standard MODIS Enhanced Vegetation Index formula.
    EVI = G * (NIR - Red) / (NIR + C1*Red - C2*Blue + L)
    """
    G = 2.5
    C1 = 6.0
    C2 = 7.5
    L = 1.0
    denom = nir + C1 * red - C2 * blue + L
    if abs(denom) < 1e-10:
        return None
    return G * (nir - red) / denom


def check_filter(qa_decode, filter_rules):
    """Check if a decoded QA passes the filter spec.
    Returns True only if every filtered field's value is in its acceptable list."""
    for field_name, acceptable in filter_rules.items():
        if field_name in qa_decode:
            if qa_decode[field_name]["value"] not in acceptable:
                return False
    return True


def process(input_path, filter_path, output_path):
    with open(filter_path) as f:
        filter_spec = json.load(f)

    # Stats for report
    total = 0
    by_product = {}
    fill_count = 0
    indices_computed = {}

    with open(input_path) as fin, open(output_path, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            obs = json.loads(line)
            total += 1

            product = obs["product"]
            qa_layer = obs["qa_layer"]
            qa_value = obs["qa_value"]

            # QA Decode
            specs = get_qa_field_specs(product, qa_layer)
            qa_decode = decode_qa_value(qa_value, specs)

            # Quality Filter
            filter_key = f"{product}/{qa_layer}"
            rules = filter_spec.get(filter_key, {})
            quality_passed = check_filter(qa_decode, rules)

            # Track product stats
            if product not in by_product:
                by_product[product] = {"total": 0, "passed": 0, "failed": 0}
            by_product[product]["total"] += 1
            if quality_passed:
                by_product[product]["passed"] += 1
            else:
                by_product[product]["failed"] += 1

            # Scale Measurements
            product_layers = get_product_layers(product)
            scaled_measurements = []
            for meas in obs.get("measurements", []):
                lyr = meas["layer"]
                raw = meas["raw"]
                lmeta = product_layers.get(lyr, {})
                scaled, is_fill = scale_measurement(raw, lmeta)
                units = lmeta.get("Units", "")
                if is_fill:
                    fill_count += 1
                scaled_measurements.append({
                    "layer": lyr,
                    "raw": raw,
                    "scaled": scaled,
                    "units": units,
                    "is_fill": is_fill,
                })

            # EVI Computation for MOD09GA
            computed_indices = {}
            if product == "MOD09GA.061":
                bands = {}
                for sm in scaled_measurements:
                    if sm["layer"] == "sur_refl_b01_1":
                        bands["red"] = sm
                    elif sm["layer"] == "sur_refl_b02_1":
                        bands["nir"] = sm
                    elif sm["layer"] == "sur_refl_b03_1":
                        bands["blue"] = sm

                if all(k in bands for k in ("red", "nir", "blue")):
                    if any(bands[k]["is_fill"] for k in ("red", "nir", "blue")):
                        computed_indices["EVI"] = None
                    else:
                        computed_indices["EVI"] = compute_evi(
                            bands["red"]["scaled"],
                            bands["nir"]["scaled"],
                            bands["blue"]["scaled"],
                        )

            # Track computed indices
            for idx_name, idx_val in computed_indices.items():
                if idx_val is not None:
                    indices_computed[idx_name] = indices_computed.get(idx_name, 0) + 1

            output_obj = {
                "id": obs["id"],
                "product": product,
                "qa_decode": dict(qa_decode),
                "quality_passed": quality_passed,
                "scaled_measurements": scaled_measurements,
                "computed_indices": computed_indices,
            }
            fout.write(json.dumps(output_obj) + "\n")

    # Write report
    report = {
        "total": total,
        "by_product": by_product,
        "fill_count": fill_count,
        "indices_computed": indices_computed,
    }
    report_dir = os.path.dirname(output_path) or "."
    report_path = os.path.join(report_dir, "report.json")
    with open(report_path, "w") as rf:
        json.dump(report, rf)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python3 satqa.py <input.jsonl> <filter.json> <output.jsonl>",
            file=sys.stderr,
        )
        sys.exit(1)
    process(sys.argv[1], sys.argv[2], sys.argv[3])
