#!/usr/bin/env python3
"""
ERDDAP Tabledap Query Engine -- Reference Implementation

Parses NCCSV (NetCDF-CSV) files and implements ERDDAP's tabledap constraint
syntax including server-side functions (orderBy, orderByMax, orderByMin,
orderByCount, distinct).
"""


import csv
import json
import math
import re
import sys
from io import StringIO


class NccsvDataset:
    """Represents a parsed NCCSV dataset with query capabilities."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.global_attrs = {}
        self.variables = {}
        self._var_order = []
        self.data = []
        self._parse(filepath)

    # ── Parsing ────────────────────────────────────────────────────────

    def _parse(self, filepath):
        with open(filepath, "r") as f:
            content = f.read()

        lines = content.strip().split("\n")
        in_metadata = True
        header_line = None
        data_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "*END_METADATA*":
                in_metadata = False
                continue
            if in_metadata:
                self._parse_metadata_line(stripped)
            elif header_line is None:
                header_line = stripped
            else:
                data_lines.append(stripped)

        columns = list(next(csv.reader(StringIO(header_line))))

        for dl in data_lines:
            values = list(next(csv.reader(StringIO(dl))))
            row = {}
            for col, val in zip(columns, values):
                row[col] = self._cast(col, val)
            self.data.append(row)

    def _parse_metadata_line(self, line):
        parts = list(next(csv.reader(StringIO(line))))
        if len(parts) < 3:
            return
        var_name, attr_name = parts[0], parts[1]
        attr_value = parts[2]

        if var_name == "*GLOBAL*":
            self.global_attrs[attr_name] = attr_value
        else:
            if var_name not in self.variables:
                self.variables[var_name] = {"data_type": "String", "attrs": {}}
                self._var_order.append(var_name)
            if attr_name == "*DATA_TYPE*":
                self.variables[var_name]["data_type"] = attr_value
            else:
                self.variables[var_name]["attrs"][attr_name] = attr_value

    def _cast(self, col, raw):
        dtype = self.variables.get(col, {}).get("data_type", "String")
        if dtype == "String":
            return raw if raw else None
        if dtype in ("float", "double"):
            if raw == "" or raw in ("NaN", "NaNf"):
                return float("nan")
            return float(raw.rstrip("fFdD"))
        if dtype in ("int", "short", "byte", "long"):
            if raw == "":
                return None
            return int(raw.rstrip("iIsSlLbB"))
        return raw

    # ── Helpers ────────────────────────────────────────────────────────

    def _get_units(self, var):
        return self.variables.get(var, {}).get("attrs", {}).get("units", "")

    def _get_dtype(self, var):
        return self.variables.get(var, {}).get("data_type", "String")

    def _is_missing(self, val, dtype):
        if val is None:
            return True
        if dtype in ("float", "double") and isinstance(val, float) and math.isnan(val):
            return True
        return False

    # ── Query ──────────────────────────────────────────────────────────

    def query(self, variables=None, constraints=None, function=None):
        rows = list(self.data)

        if constraints:
            for c in constraints:
                rows = self._apply_constraint(rows, c)

        if variables is None:
            variables = list(self._var_order)

        if function:
            rows, variables, extra = self._apply_function(rows, variables, function)
        else:
            extra = None

        return QueryResult(self, rows, variables, extra)

    # ── Constraint engine ──────────────────────────────────────────────

    _CONSTRAINT_RE = re.compile(r"^(\w+)(=~|!=|>=|<=|>|<|=)(.*)$")

    def _apply_constraint(self, rows, constraint):
        m = self._CONSTRAINT_RE.match(constraint)
        if not m:
            raise ValueError(f"Invalid constraint: {constraint}")
        var, op, raw_val = m.group(1), m.group(2), m.group(3)
        dtype = self._get_dtype(var)

        if op == "=~":
            pattern = re.compile(raw_val.strip('"'))
            return [
                r
                for r in rows
                if not self._is_missing(r.get(var), dtype)
                and pattern.search(str(r.get(var)))
            ]

        cmp_val = self._parse_cmp_value(raw_val, dtype)

        out = []
        for r in rows:
            v = r.get(var)
            missing = self._is_missing(v, dtype)

            if op == "!=":
                if missing or v != cmp_val:
                    out.append(r)
            else:
                if missing:
                    continue
                if op == "=" and v == cmp_val:
                    out.append(r)
                elif op == ">" and v > cmp_val:
                    out.append(r)
                elif op == ">=" and v >= cmp_val:
                    out.append(r)
                elif op == "<" and v < cmp_val:
                    out.append(r)
                elif op == "<=" and v <= cmp_val:
                    out.append(r)
        return out

    def _parse_cmp_value(self, raw, dtype):
        raw = raw.strip('"')
        if dtype in ("float", "double"):
            return float(raw)
        if dtype in ("int", "short", "byte", "long"):
            return int(raw)
        return raw

    # ── Server-side functions ──────────────────────────────────────────

    _FUNC_RE = re.compile(r'^(\w+)\("([^"]*)"\)$')

    def _apply_function(self, rows, variables, function):
        if function.strip() == "distinct()":
            return self._fn_distinct(rows, variables)

        m = self._FUNC_RE.match(function)
        if not m:
            raise ValueError(f"Invalid function: {function}")
        name = m.group(1)
        args = [a.strip() for a in m.group(2).split(",")]

        dispatch = {
            "orderBy": self._fn_orderby,
            "orderByMax": self._fn_orderby_max,
            "orderByMin": self._fn_orderby_min,
            "orderByCount": self._fn_orderby_count,
        }
        fn = dispatch.get(name)
        if fn is None:
            raise ValueError(f"Unknown function: {name}")
        return fn(rows, variables, args)

    def _sort_key(self, row, var):
        v = row.get(var)
        dtype = self._get_dtype(var)
        if self._is_missing(v, dtype):
            return (1, "")
        return (0, v)

    def _fn_orderby(self, rows, variables, sort_vars):
        out = sorted(
            rows,
            key=lambda r: tuple(self._sort_key(r, v) for v in sort_vars),
        )
        return out, variables, None

    def _fn_orderby_max(self, rows, variables, fv):
        return self._fn_extremal(rows, variables, fv, max_mode=True)

    def _fn_orderby_min(self, rows, variables, fv):
        return self._fn_extremal(rows, variables, fv, max_mode=False)

    def _fn_extremal(self, rows, variables, fv, *, max_mode):
        group_vars, target = fv[:-1], fv[-1]
        dtype = self._get_dtype(target)
        groups = {}

        for r in rows:
            key = tuple(r.get(g) for g in group_vars) if group_vars else ("__all__",)
            tv = r.get(target)
            if self._is_missing(tv, dtype):
                continue
            if key not in groups:
                groups[key] = (tv, r)
            else:
                if (max_mode and tv > groups[key][0]) or (
                    not max_mode and tv < groups[key][0]
                ):
                    groups[key] = (tv, r)

        result = [groups[k][1] for k in sorted(groups.keys())]
        return result, variables, None

    def _fn_orderby_count(self, rows, variables, group_vars):
        counts = {}
        for r in rows:
            key = tuple(r.get(g) for g in group_vars)
            counts[key] = counts.get(key, 0) + 1

        result = []
        for key in sorted(counts.keys()):
            row = dict(zip(group_vars, key))
            row["count"] = counts[key]
            result.append(row)

        return result, list(group_vars) + ["count"], {"count_column": True}

    def _fn_distinct(self, rows, variables):
        seen = set()
        unique = []
        for r in rows:
            vals = tuple(r.get(v) for v in variables)
            hash_key = tuple(
                "__NaN__" if isinstance(x, float) and math.isnan(x) else x
                for x in vals
            )
            if hash_key not in seen:
                seen.add(hash_key)
                unique.append(r)

        unique.sort(
            key=lambda r: tuple(self._sort_key(r, v) for v in variables)
        )
        return unique, variables, None


class QueryResult:
    """Result of a tabledap query."""

    def __init__(self, dataset, rows, variables, extra=None):
        self.dataset = dataset
        self.rows = rows
        self.variables = variables
        self._extra = extra

    def to_csv(self, filepath=None):
        buf = StringIO()
        w = csv.writer(buf)

        w.writerow(self.variables)

        units = []
        for v in self.variables:
            if v == "count":
                units.append("")
            else:
                units.append(self.dataset._get_units(v))
        w.writerow(units)

        for r in self.rows:
            vals = []
            for v in self.variables:
                val = r.get(v)
                if val is None:
                    vals.append("")
                elif isinstance(val, float) and math.isnan(val):
                    vals.append("NaN")
                else:
                    vals.append(val)
            w.writerow(vals)

        content = buf.getvalue()
        if filepath:
            with open(filepath, "w") as f:
                f.write(content)
        return content

    def to_json(self, filepath=None):
        col_types = []
        col_units = []
        for v in self.variables:
            if v == "count":
                col_types.append("int")
                col_units.append("")
            else:
                col_types.append(self.dataset._get_dtype(v))
                col_units.append(self.dataset._get_units(v))

        json_rows = []
        for r in self.rows:
            jr = []
            for v in self.variables:
                val = r.get(v)
                if val is None:
                    jr.append(None)
                elif isinstance(val, float) and math.isnan(val):
                    jr.append(None)
                else:
                    jr.append(val)
            json_rows.append(jr)

        obj = {
            "table": {
                "columnNames": list(self.variables),
                "columnTypes": col_types,
                "columnUnits": col_units,
                "rows": json_rows,
            }
        }

        content = json.dumps(obj, indent=2)
        if filepath:
            with open(filepath, "w") as f:
                f.write(content)
        return content


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 tabledap_engine.py <nccsv_file> [options]")
        sys.exit(1)

    nccsv_file = sys.argv[1]
    variables = None
    constraints = []
    function = None
    fmt = "csv"
    output_file = None

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--select" and i + 1 < len(sys.argv):
            variables = sys.argv[i + 1].split(",")
            i += 2
        elif arg == "--constraint" and i + 1 < len(sys.argv):
            constraints.append(sys.argv[i + 1])
            i += 2
        elif arg == "--function" and i + 1 < len(sys.argv):
            function = sys.argv[i + 1]
            i += 2
        elif arg == "--format" and i + 1 < len(sys.argv):
            fmt = sys.argv[i + 1]
            i += 2
        elif arg == "--output" and i + 1 < len(sys.argv):
            output_file = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    ds = NccsvDataset(nccsv_file)
    result = ds.query(
        variables=variables,
        constraints=constraints or None,
        function=function,
    )

    if fmt == "json":
        content = result.to_json(output_file)
    else:
        content = result.to_csv(output_file)

    if not output_file:
        print(content, end="")
