#!/usr/bin/env python3
"""ERDDAP Dataset Schema Reconciliation Pipeline.


Cross-references ERDDAP datasets.xml configuration against pre-captured
OPeNDAP DAS/DDS server metadata and local NetCDF files to produce a
reconciliation report and NCCSV metadata exports.
"""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

# OPeNDAP type -> ERDDAP config type mapping
OPENDAP_TO_CONFIG = {
    "Float32": "float",
    "Float64": "double",
    "Int16": "short",
    "Int32": "int",
    "Byte": "byte",
    "String": "String",
}

COMPOSITE_TYPES = {"EDDGridSideBySide", "EDDGridAggregateExistingDimension"}
WRAPPER_TYPES = {"EDDGridLon0360", "EDDGridLonPM180"}
LOCAL_FILE_TYPES = {"EDDGridFromNcFiles", "EDDGridFromNcFilesUnpacked"}


# ── DAS Parser ──────────────────────────────────────────────────

def parse_das(filepath):
    """Parse OPeNDAP DAS file into {varname: {attrname: {type, value}}}."""
    result = {}
    current_var = None
    depth = 0

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.endswith("{"):
                depth += 1
                if depth == 2:
                    varname = stripped[:-1].strip()
                    current_var = varname
                    result[current_var] = {}
            elif stripped == "}":
                if depth == 2:
                    current_var = None
                depth -= 1
            elif current_var is not None and ";" in stripped:
                m = re.match(r"^(\w+)\s+(\w+)\s+(.+);$", stripped)
                if m:
                    attr_type = m.group(1)
                    attr_name = m.group(2)
                    attr_value = m.group(3).strip()
                    if attr_value.startswith('"') and attr_value.endswith('"'):
                        attr_value = attr_value[1:-1]
                    result[current_var][attr_name] = {
                        "type": attr_type,
                        "value": attr_value,
                    }
    return result


# ── DDS Parser ──────────────────────────────────────────────────

def parse_dds(filepath):
    """Parse OPeNDAP DDS file into structured dict."""
    with open(filepath) as f:
        content = f.read()

    result = {
        "dataset_name": "",
        "dimensions": {},
        "axes": [],
        "data_variables": [],
    }

    # Dataset name from last line
    lines = content.strip().split("\n")
    last = lines[-1].strip()
    m = re.match(r"}\s*(\w+)\s*;", last)
    if m:
        result["dataset_name"] = m.group(1)

    # Top-level axis declarations (before first Grid block)
    grid_start = content.find("Grid {")
    if grid_start == -1:
        grid_start = content.find("Grid{")
    pre_grid = content[:grid_start] if grid_start > 0 else content

    for m in re.finditer(
        r"^\s+(\w+)\s+(\w+)\[(\w+)\s*=\s*(\d+)\]\s*;", pre_grid, re.MULTILINE
    ):
        dtype, name, dim, size = m.group(1), m.group(2), m.group(3), int(m.group(4))
        result["dimensions"][dim] = size
        if name not in [a["name"] for a in result["axes"]]:
            result["axes"].append(
                {"name": name, "type": dtype, "dimension": dim, "size": size}
            )

    # Data variables from Grid Array entries
    for m in re.finditer(
        r"Array:\s*\n\s+(\w+)\s+(\w+)((?:\[\w+\s*=\s*\d+\])+)\s*;", content
    ):
        dtype, name, dims_str = m.group(1), m.group(2), m.group(3)
        dims = [
            (d, int(s)) for d, s in re.findall(r"\[(\w+)\s*=\s*(\d+)\]", dims_str)
        ]
        result["data_variables"].append(
            {"name": name, "type": dtype, "dimensions": dims}
        )

    return result


# ── ncdump Header Parser ───────────────────────────────────────

def parse_ncdump_header(text):
    """Parse ncdump -h output into structured dict."""
    result = {"dimensions": {}, "variables": [], "global_attributes": {}}

    # Dimensions
    dim_section = re.search(r"dimensions:\n(.*?)variables:", text, re.DOTALL)
    if dim_section:
        for m in re.finditer(r"(\w+)\s*=\s*(\d+)", dim_section.group(1)):
            result["dimensions"][m.group(1)] = int(m.group(2))

    # Variables with attributes
    var_section = re.search(
        r"variables:\n(.*?)(?:// global attributes:|data:|\}\s*$)", text, re.DOTALL
    )
    if var_section:
        current_var = None
        for line in var_section.group(1).split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # Variable declaration: type name(dim1, dim2, ...) ;
            vm = re.match(r"(\w+)\s+(\w+)\(([^)]+)\)\s*;", stripped)
            if vm:
                vtype, vname, dims = vm.group(1), vm.group(2), vm.group(3)
                dim_list = [d.strip() for d in dims.split(",")]
                current_var = {
                    "name": vname,
                    "type": vtype,
                    "dimensions": dim_list,
                    "attributes": {},
                }
                result["variables"].append(current_var)
                continue
            # Variable attribute: varname:attrname = value ;
            if current_var:
                am = re.match(r"(\w+):(\w+)\s*=\s*(.+)\s*;", stripped)
                if am and am.group(1) == current_var["name"]:
                    attr_value = am.group(3).strip()
                    if attr_value.startswith('"') and attr_value.endswith('"'):
                        attr_value = attr_value[1:-1]
                    current_var["attributes"][am.group(2)] = attr_value

    # Global attributes
    global_section = re.search(
        r"// global attributes:\n(.*?)(?:data:|\}\s*$)", text, re.DOTALL
    )
    if global_section:
        for m in re.finditer(r':(\w+)\s*=\s*"([^"]*)"\s*;', global_section.group(1)):
            result["global_attributes"][m.group(1)] = m.group(2)

    return result


# ── datasets.xml Parser ────────────────────────────────────────

def parse_dataset_element(elem):
    ds = {
        "id": elem.get("datasetID", ""),
        "type": elem.get("type", ""),
        "active": elem.get("active", "true").lower() != "false",
        "source_url": None,
        "file_dir": None,
        "file_name_regex": None,
        "axis_variables": [],
        "data_variables": [],
        "add_attributes": {},
        "children": [],
    }

    for tag, attr in [
        ("sourceUrl", "source_url"),
        ("fileDir", "file_dir"),
        ("fileNameRegex", "file_name_regex"),
    ]:
        el = elem.find(tag)
        if el is not None and el.text:
            ds[attr] = el.text.strip()

    for av in elem.findall("axisVariable"):
        sn = av.find("sourceName")
        dn = av.find("destinationName")
        source = sn.text.strip() if sn is not None and sn.text else ""
        dest = dn.text.strip() if dn is not None and dn.text else source
        ds["axis_variables"].append({"source": source, "dest": dest})

    for dv in elem.findall("dataVariable"):
        sn = dv.find("sourceName")
        dn = dv.find("destinationName")
        dt = dv.find("dataType")
        source = sn.text.strip() if sn is not None and sn.text else ""
        dest = dn.text.strip() if dn is not None and dn.text else source
        dtype = dt.text.strip() if dt is not None and dt.text else ""
        attrs = {}
        aa = dv.find("addAttributes")
        if aa is not None:
            for att in aa.findall("att"):
                name = att.get("name", "")
                val = att.text.strip() if att.text else ""
                attrs[name] = val
        ds["data_variables"].append(
            {"source": source, "dest": dest, "dataType": dtype, "attributes": attrs}
        )

    aa = elem.find("addAttributes")
    if aa is not None:
        for att in aa.findall("att"):
            name = att.get("name", "")
            val = att.text.strip() if att.text else ""
            ds["add_attributes"][name] = val

    for child_elem in elem.findall("dataset"):
        ds["children"].append(parse_dataset_element(child_elem))

    return ds


def parse_datasets_xml(filepath):
    tree = ET.parse(filepath)
    root = tree.getroot()
    return [parse_dataset_element(e) for e in root.findall("dataset")]


# ── CF Table Loader ─────────────────────────────────────────────

def load_cf_table(filepath):
    cf = {}
    with open(filepath) as f:
        f.readline()  # skip header
        for line in f:
            parts = line.strip().split(",", 2)
            if parts and parts[0]:
                cf[parts[0]] = parts[1] if len(parts) > 1 else ""
    return cf


# ── Value Comparison ────────────────────────────────────────────

def values_match(v1, v2):
    """Compare attribute values; treat numeric equivalents as equal."""
    if v1 == v2:
        return True
    try:
        return float(v1) == float(v2)
    except (ValueError, TypeError):
        return False


# ── Dataset Reconciliation ──────────────────────────────────────

def reconcile_dataset(ds_config, das_data, dds_data, cf_table, source_type, metadata_source):
    entry = {
        "dataset_id": ds_config["id"],
        "dataset_type": ds_config["type"],
        "source_type": source_type,
        "metadata_source": metadata_source,
        "config_data_variables": [],
        "source_data_variables": [],
        "discrepancies": {
            "source_only_vars": [],
            "config_only_vars": [],
            "type_mismatches": [],
            "attribute_conflicts": [],
            "cf_violations": [],
        },
    }

    # Config variables
    for v in ds_config.get("data_variables", []):
        entry["config_data_variables"].append(
            {
                "source_name": v["source"],
                "destination_name": v["dest"],
                "config_type": v.get("dataType", ""),
            }
        )

    # Source data variables (from DDS or ncdump)
    if dds_data:
        for v in dds_data.get("data_variables", []):
            mapped_type = OPENDAP_TO_CONFIG.get(v["type"], v["type"])
            entry["source_data_variables"].append(
                {"name": v["name"], "type": mapped_type}
            )

    config_source_names = {v["source"] for v in ds_config.get("data_variables", [])}
    source_var_names = {v["name"] for v in entry["source_data_variables"]}

    # Source-only / config-only
    entry["discrepancies"]["source_only_vars"] = sorted(
        source_var_names - config_source_names
    )
    entry["discrepancies"]["config_only_vars"] = sorted(
        config_source_names - source_var_names
    )

    # Type mismatches
    config_type_map = {
        v["source"]: v.get("dataType", "") for v in ds_config.get("data_variables", [])
    }
    source_type_map = {v["name"]: v["type"] for v in entry["source_data_variables"]}

    for var_name in config_source_names & source_var_names:
        ct = config_type_map.get(var_name, "")
        st = source_type_map.get(var_name, "")
        if ct and st and ct != st:
            entry["discrepancies"]["type_mismatches"].append(
                {"variable": var_name, "config_type": ct, "source_type": st}
            )

    # Attribute conflicts
    if das_data:
        config_attrs = {}
        for v in ds_config.get("data_variables", []):
            if v.get("attributes"):
                config_attrs[v["source"]] = v["attributes"]

        for var_name in config_source_names & source_var_names:
            if var_name in das_data and var_name in config_attrs:
                for attr_name, cfg_value in config_attrs[var_name].items():
                    if attr_name in das_data[var_name]:
                        src_value = das_data[var_name][attr_name]
                        src_val_str = (
                            src_value["value"]
                            if isinstance(src_value, dict)
                            else str(src_value)
                        )
                        if not values_match(src_val_str, cfg_value):
                            entry["discrepancies"]["attribute_conflicts"].append(
                                {
                                    "variable": var_name,
                                    "attribute": attr_name,
                                    "source_value": src_val_str,
                                    "config_value": cfg_value,
                                }
                            )

    # CF violations (check source standard_names)
    if das_data:
        for var_name, attrs in das_data.items():
            if var_name == "NC_GLOBAL":
                continue
            if isinstance(attrs, dict) and "standard_name" in attrs:
                sn_entry = attrs["standard_name"]
                sn = sn_entry["value"] if isinstance(sn_entry, dict) else str(sn_entry)
                if sn and sn not in cf_table:
                    entry["discrepancies"]["cf_violations"].append(
                        {
                            "variable": var_name,
                            "standard_name": sn,
                            "reason": "not_in_cf_table",
                        }
                    )

    return entry


# ── Hierarchy Audit ─────────────────────────────────────────────

def resolve_effective_vars(ds):
    t = ds["type"]
    if t == "EDDGridSideBySide":
        result = []
        for child in ds.get("children", []):
            child_vars = resolve_effective_vars(child)
            for v in child_vars:
                v2 = dict(v)
                if "from_child" not in v2:
                    v2["from_child"] = child["id"]
                result.append(v2)
        return result
    elif t == "EDDGridAggregateExistingDimension":
        if ds.get("children"):
            return resolve_effective_vars(ds["children"][0])
        return []
    elif t in WRAPPER_TYPES:
        if ds.get("children"):
            return resolve_effective_vars(ds["children"][0])
        return []
    else:
        return [
            {"source": v["source"], "dest": v["dest"]}
            for v in ds.get("data_variables", [])
        ]


def get_axis_names(ds):
    t = ds["type"]
    if t in COMPOSITE_TYPES or t in WRAPPER_TYPES:
        if ds.get("children"):
            return get_axis_names(ds["children"][0])
        return []
    return [a["source"] for a in ds.get("axis_variables", [])]


def check_axis_compatibility(ds):
    children = ds.get("children", [])
    if not children:
        return {"compatible": True, "shared_axes": [], "issues": []}

    t = ds["type"]
    if t in WRAPPER_TYPES:
        return {
            "compatible": True,
            "shared_axes": get_axis_names(children[0]),
            "issues": [],
        }

    first_axes = get_axis_names(children[0])
    issues = []
    for child in children[1:]:
        child_axes = get_axis_names(child)
        if set(child_axes) != set(first_axes):
            issues.append(
                f"Child {child['id']} axes {child_axes} differ from {first_axes}"
            )

    return {
        "compatible": len(issues) == 0,
        "shared_axes": first_axes,
        "issues": issues,
    }


def audit_hierarchies(all_datasets):
    results = []

    def walk(ds_list):
        for ds in ds_list:
            if not ds.get("active", True):
                continue
            if ds["type"] in COMPOSITE_TYPES or ds["type"] in WRAPPER_TYPES:
                results.append(
                    {
                        "dataset_id": ds["id"],
                        "dataset_type": ds["type"],
                        "children": [c["id"] for c in ds.get("children", [])],
                        "effective_variables": resolve_effective_vars(ds),
                        "axis_compatibility": check_axis_compatibility(ds),
                    }
                )
            walk(ds.get("children", []))

    walk(all_datasets)
    return results


# ── NCCSV Generation ───────────────────────────────────────────

def generate_nccsv(dataset_id, das_data, dds_data, output_dir):
    lines = []

    # Global attributes (alphabetical)
    if "NC_GLOBAL" in das_data:
        for attr_name in sorted(das_data["NC_GLOBAL"].keys()):
            val = das_data["NC_GLOBAL"][attr_name]["value"]
            if "," in val:
                val = f'"{val}"'
            lines.append(f"*GLOBAL*,{attr_name},{val}")

    # Determine variable order: axes in DDS order, then data vars alphabetically
    axes_order = [a["name"] for a in dds_data.get("axes", [])] if dds_data else []
    data_vars = (
        sorted([v["name"] for v in dds_data.get("data_variables", [])])
        if dds_data
        else []
    )

    # Type mapping from DDS
    type_map = {}
    if dds_data:
        for a in dds_data.get("axes", []):
            type_map[a["name"]] = OPENDAP_TO_CONFIG.get(a["type"], a["type"])
        for v in dds_data.get("data_variables", []):
            type_map[v["name"]] = OPENDAP_TO_CONFIG.get(v["type"], v["type"])

    for var_name in axes_order + data_vars:
        if var_name not in das_data:
            continue
        dtype = type_map.get(var_name, "String")
        lines.append(f"{var_name},*DATA_TYPE*,{dtype}")

        for attr_name in sorted(das_data[var_name].keys()):
            if attr_name.startswith("_Coordinate"):
                continue
            attr = das_data[var_name][attr_name]
            val = attr["value"] if isinstance(attr, dict) else str(attr)
            if "," in str(val):
                val = f'"{val}"'
            lines.append(f"{var_name},{attr_name},{val}")

    lines.append("*END_METADATA*")

    filepath = os.path.join(output_dir, f"{dataset_id}.nccsv")
    with open(filepath, "w") as f:
        f.write("\n".join(lines) + "\n")


def generate_nccsv_recursive(ds, server_metadata_dir, nccsv_dir):
    das_path = os.path.join(server_metadata_dir, f"{ds['id']}.das")
    dds_path = os.path.join(server_metadata_dir, f"{ds['id']}.dds")
    if os.path.isfile(das_path) and os.path.isfile(dds_path):
        das = parse_das(das_path)
        dds = parse_dds(dds_path)
        generate_nccsv(ds["id"], das, dds, nccsv_dir)
    for child in ds.get("children", []):
        generate_nccsv_recursive(child, server_metadata_dir, nccsv_dir)


# ── ncdump-to-DAS/DDS conversion ──────────────────────────────

def build_das_from_ncdump(nc_summary):
    result = {}
    for var in nc_summary.get("variables", []):
        result[var["name"]] = {
            attr: {"type": "String", "value": val}
            for attr, val in var.get("attributes", {}).items()
        }
    if nc_summary.get("global_attributes"):
        result["NC_GLOBAL"] = {
            attr: {"type": "String", "value": val}
            for attr, val in nc_summary["global_attributes"].items()
        }
    return result


def build_dds_from_ncdump(nc_summary, ds_config):
    axis_source_names = {a["source"] for a in ds_config.get("axis_variables", [])}
    result = {
        "dataset_name": ds_config["id"],
        "dimensions": nc_summary.get("dimensions", {}),
        "axes": [],
        "data_variables": [],
    }
    dims = nc_summary.get("dimensions", {})
    for var in nc_summary.get("variables", []):
        if var["name"] in axis_source_names:
            dim_name = var["dimensions"][0] if var["dimensions"] else ""
            result["axes"].append(
                {
                    "name": var["name"],
                    "type": var["type"],
                    "dimension": dim_name,
                    "size": dims.get(dim_name, 0),
                }
            )
        else:
            result["data_variables"].append(
                {
                    "name": var["name"],
                    "type": var["type"],
                    "dimensions": [
                        (d, dims.get(d, 0)) for d in var["dimensions"]
                    ],
                }
            )
    return result


# ── Main ────────────────────────────────────────────────────────

def main():
    ncdump_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ncdump_header.txt"

    datasets_xml_path = "/app/datasets.xml"
    server_metadata_dir = "/app/server_metadata"
    nc_file_path = "/app/source_data/sample_bathy.nc"
    cf_table_path = "/app/cf_standard_names.csv"
    output_dir = "/app/output"
    nccsv_dir = os.path.join(output_dir, "datasets_nccsv")

    os.makedirs(nccsv_dir, exist_ok=True)

    # Parse datasets.xml
    all_datasets = parse_datasets_xml(datasets_xml_path)

    # Load CF table
    cf_table = load_cf_table(cf_table_path)

    # Parse ncdump output
    with open(ncdump_file) as f:
        ncdump_text = f.read()
    nc_summary = parse_ncdump_header(ncdump_text)

    # Reconcile each dataset that has source metadata
    reconciliation_datasets = []

    def find_and_reconcile(ds_list):
        for ds in ds_list:
            if not ds.get("active", True):
                find_and_reconcile(ds.get("children", []))
                continue

            das_path = os.path.join(server_metadata_dir, f"{ds['id']}.das")
            dds_path = os.path.join(server_metadata_dir, f"{ds['id']}.dds")

            if os.path.isfile(das_path) and os.path.isfile(dds_path):
                das_data = parse_das(das_path)
                dds_data = parse_dds(dds_path)
                result = reconcile_dataset(
                    ds, das_data, dds_data, cf_table, "opendap", das_path
                )
                reconciliation_datasets.append(result)

            elif ds["type"] in LOCAL_FILE_TYPES and ds.get("file_dir"):
                file_dir = ds["file_dir"]
                nc_files = [
                    f
                    for f in os.listdir(file_dir)
                    if f.endswith(".nc")
                ]
                if nc_files:
                    local_nc = os.path.join(file_dir, nc_files[0])
                    local_ncdump = subprocess.run(
                        ["ncdump", "-h", local_nc],
                        capture_output=True,
                        text=True,
                    ).stdout
                    local_summary = parse_ncdump_header(local_ncdump)
                    local_das = build_das_from_ncdump(local_summary)
                    local_dds = build_dds_from_ncdump(local_summary, ds)
                    result = reconcile_dataset(
                        ds, local_das, local_dds, cf_table, "local_file", local_nc
                    )
                    reconciliation_datasets.append(result)

            find_and_reconcile(ds.get("children", []))

    find_and_reconcile(all_datasets)

    # Audit hierarchies
    hierarchy_entries = audit_hierarchies(all_datasets)

    # Generate NCCSV files
    for ds in all_datasets:
        generate_nccsv_recursive(ds, server_metadata_dir, nccsv_dir)

    # Build final report
    report = {
        "datasets": reconciliation_datasets,
        "hierarchy_audit": hierarchy_entries,
        "netcdf_summary": {
            "file": nc_file_path,
            "dimensions": nc_summary["dimensions"],
            "variables": [
                {
                    "name": v["name"],
                    "type": v["type"],
                    "dimensions": v["dimensions"],
                }
                for v in nc_summary["variables"]
            ],
            "global_attributes": nc_summary["global_attributes"],
        },
    }

    with open(os.path.join(output_dir, "reconciliation.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("Reconciliation complete.")


if __name__ == "__main__":
    main()
