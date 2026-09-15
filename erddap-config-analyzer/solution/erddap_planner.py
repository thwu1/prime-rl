#!/usr/bin/env python3
"""ERDDAP datasets.xml Analyzer and Query URL Generator.


Parses ERDDAP datasets.xml configuration files, resolves dataset hierarchies,
generates ERDDAP REST API query URLs, and validates configurations.
"""

import sys
import json
import xml.etree.ElementTree as ET


GRID_TYPES = frozenset([
    "EDDGridFromEtopo", "EDDGridFromDap", "EDDGridFromErddap",
    "EDDGridFromNcFiles", "EDDGridFromNcFilesUnpacked",
    "EDDGridFromAudioFiles", "EDDGridFromMergeIRFiles",
    "EDDGridFromEDDTable", "EDDGridFromFiles",
    "EDDGridSideBySide", "EDDGridAggregateExistingDimension",
    "EDDGridLon0360", "EDDGridLonPM180", "EDDGridCopy",
])

TABLE_TYPES = frozenset([
    "EDDTableFromErddap", "EDDTableFromNcFiles", "EDDTableFromAsciiFiles",
    "EDDTableFromDapSequence", "EDDTableFromDatabase",
    "EDDTableFromCassandra", "EDDTableFromMqtt",
    "EDDTableFromNcCFFiles", "EDDTableFromNccsvFiles",
    "EDDTableFromHttpGet", "EDDTableFromJsonlCSVFiles",
    "EDDTableFromColumnarAsciiFiles", "EDDTableFromAwsXmlFiles",
    "EDDTableFromMultidimNcFiles", "EDDTableFromParquetFiles",
    "EDDTableFromSOS", "EDDTableFromWFSFiles", "EDDTableFromOBIS",
    "EDDTableFromFileNames", "EDDTableFromHyraxFiles",
    "EDDTableFromThreddsFiles", "EDDTableFromAsciiServiceNOS",
    "EDDTableFromAudioFiles", "EDDTableFromEDDGrid",
    "EDDTableFromInvalidCRAFiles",
    "EDDTableAggregateRows", "EDDTableCopy", "EDDTableFromFiles",
])

COMPOSITE_TYPES = frozenset(["EDDGridSideBySide", "EDDGridAggregateExistingDimension"])
WRAPPER_TYPES = frozenset(["EDDGridLon0360", "EDDGridLonPM180"])


def get_protocol(ds_type):
    if ds_type in GRID_TYPES:
        return "griddap"
    if ds_type in TABLE_TYPES:
        return "tabledap"
    if "Grid" in ds_type:
        return "griddap"
    if "Table" in ds_type:
        return "tabledap"
    return "unknown"


def get_lon_convention(ds_type):
    if ds_type == "EDDGridLon0360":
        return "0-360"
    if ds_type == "EDDGridLonPM180":
        return "-180/+180"
    return "source"


def parse_dataset(elem):
    ds = {
        "id": elem.get("datasetID", ""),
        "type": elem.get("type", ""),
        "active": elem.get("active", "true").lower() != "false",
        "source_url": None,
        "reload_minutes": None,
        "axis_variables": [],
        "data_variables": [],
        "attributes": {},
        "children": [],
    }

    su = elem.find("sourceUrl")
    if su is not None and su.text:
        ds["source_url"] = su.text.strip()

    rm = elem.find("reloadEveryNMinutes")
    if rm is not None and rm.text:
        try:
            ds["reload_minutes"] = int(rm.text.strip())
        except ValueError:
            pass

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
        ds["data_variables"].append({
            "source": source, "dest": dest,
            "dataType": dtype, "attributes": attrs,
        })

    aa = elem.find("addAttributes")
    if aa is not None:
        for att in aa.findall("att"):
            name = att.get("name", "")
            val = att.text.strip() if att.text else ""
            ds["attributes"][name] = val

    for child_elem in elem.findall("dataset"):
        ds["children"].append(parse_dataset(child_elem))

    return ds


def parse_datasets_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()
    return [parse_dataset(e) for e in root.findall("dataset")]


def resolve_effective_vars(ds):
    t = ds["type"]
    if t == "EDDGridSideBySide":
        result = []
        for child in ds["children"]:
            child_vars = resolve_effective_vars(child)
            for v in child_vars:
                v2 = dict(v)
                v2["from_child"] = child["id"]
                result.append(v2)
        return result
    elif t == "EDDGridAggregateExistingDimension":
        if ds["children"]:
            return resolve_effective_vars(ds["children"][0])
        return []
    elif t in WRAPPER_TYPES:
        if ds["children"]:
            return resolve_effective_vars(ds["children"][0])
        return []
    else:
        return [{"source": v["source"], "dest": v["dest"],
                 "dataType": v.get("dataType", ""),
                 "attributes": v.get("attributes", {})}
                for v in ds["data_variables"]]


def resolve_effective_axes(ds):
    t = ds["type"]
    if t in COMPOSITE_TYPES or t in WRAPPER_TYPES:
        if ds["children"]:
            return resolve_effective_axes(ds["children"][0])
        return []
    return [{"source": a["source"], "dest": a["dest"]} for a in ds["axis_variables"]]


def get_dependency_chain(ds):
    result = []
    for child in ds["children"]:
        result.append(child["id"])
        result.extend(get_dependency_chain(child))
    return result


def find_dataset(datasets, dataset_id):
    for ds in datasets:
        if ds["id"] == dataset_id:
            return ds
        found = find_dataset(ds["children"], dataset_id)
        if found:
            return found
    return None


def cmd_catalog(path):
    datasets = parse_datasets_xml(path)
    result = []
    for ds in datasets:
        if not ds["active"]:
            continue
        entry = {
            "id": ds["id"],
            "type": ds["type"],
            "protocol": get_protocol(ds["type"]),
        }
        if ds["source_url"]:
            entry["source_url"] = ds["source_url"]
        if ds["children"]:
            entry["children"] = [c["id"] for c in ds["children"]]
        result.append(entry)
    return result


def cmd_resolve(path, dataset_id):
    datasets = parse_datasets_xml(path)
    ds = find_dataset(datasets, dataset_id)
    if ds is None:
        return {"error": f"Dataset '{dataset_id}' not found"}

    result = {
        "id": ds["id"],
        "type": ds["type"],
        "active": ds["active"],
        "protocol": get_protocol(ds["type"]),
        "lon_convention": get_lon_convention(ds["type"]),
        "effective_data_variables": resolve_effective_vars(ds),
        "effective_axes": resolve_effective_axes(ds),
        "dependencies": get_dependency_chain(ds),
    }
    if ds["source_url"]:
        result["source_url"] = ds["source_url"]
    if ds["attributes"]:
        result["attributes"] = ds["attributes"]
    return result


def cmd_build_url(path, dataset_id, query_json):
    datasets = parse_datasets_xml(path)
    ds = find_dataset(datasets, dataset_id)
    if ds is None:
        return {"error": f"Dataset '{dataset_id}' not found"}

    query = json.loads(query_json) if isinstance(query_json, str) else query_json
    server = query["server"].rstrip("/")
    variables = query["variables"]
    constraints = query.get("constraints", {})
    fmt = query.get("format", "csv")
    protocol = get_protocol(ds["type"])

    if protocol == "griddap":
        axes = resolve_effective_axes(ds)
        var_parts = []
        for var in variables:
            parts = [var]
            for axis in axes:
                axis_dest = axis["dest"]
                if axis_dest in constraints:
                    c = constraints[axis_dest]
                    if isinstance(c, dict):
                        start = c["start"]
                        stop = c["stop"]
                        stride = c.get("stride")
                        if stride:
                            parts.append(f"[({start}):({stride}):({stop})]")
                        else:
                            parts.append(f"[({start}):({stop})]")
                    else:
                        parts.append(f"[({c})]")
            var_parts.append("".join(parts))
        query_str = ",".join(var_parts)
        url = f"{server}/erddap/griddap/{dataset_id}.{fmt}?{query_str}"
        return {"url": url}

    elif protocol == "tabledap":
        var_str = ",".join(variables)
        constraint_parts = []
        for key, value in constraints.items():
            constraint_parts.append(f"{key}{value}")
        url = f"{server}/erddap/tabledap/{dataset_id}.{fmt}?{var_str}"
        if constraint_parts:
            url += "&" + "&".join(constraint_parts)
        return {"url": url}

    return {"error": f"Unknown protocol '{protocol}'"}


def cmd_validate(path):
    datasets = parse_datasets_xml(path)
    issues = []

    # Duplicate active top-level IDs
    id_counts = {}
    for ds in datasets:
        if ds["active"]:
            id_counts[ds["id"]] = id_counts.get(ds["id"], 0) + 1
    for did, count in id_counts.items():
        if count > 1:
            issues.append({
                "dataset_id": did,
                "issue": "duplicate_dataset_id",
                "severity": "error",
                "message": f"Dataset ID '{did}' appears {count} times at top level",
            })

    # Insecure HTTP source URLs (recursive)
    def check_urls(ds_list):
        for ds in ds_list:
            if ds["source_url"] and ds["source_url"].startswith("http://"):
                issues.append({
                    "dataset_id": ds["id"],
                    "issue": "insecure_source_url",
                    "severity": "warning",
                    "message": f"Source URL uses HTTP instead of HTTPS: {ds['source_url']}",
                })
            check_urls(ds["children"])

    check_urls(datasets)
    return issues


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: erddap_planner.py <command> <xml_path> [args...]"}))
        sys.exit(1)

    cmd = sys.argv[1]
    path = sys.argv[2]

    if cmd == "catalog":
        result = cmd_catalog(path)
    elif cmd == "resolve":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "dataset_id required"}))
            sys.exit(1)
        result = cmd_resolve(path, sys.argv[3])
    elif cmd == "build-url":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "dataset_id and query JSON required"}))
            sys.exit(1)
        result = cmd_build_url(path, sys.argv[3], sys.argv[4])
    elif cmd == "validate":
        result = cmd_validate(path)
    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
