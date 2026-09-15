#!/usr/bin/env python3
"""EAMxx Namelist Parameter Resolution Engine — corrected version."""


import re
import xml.etree.ElementTree as ET
import yaml
from typing import Any, Dict, List, Optional

_META_ATTRS = frozenset({"type", "constraints", "valid_values", "locked", "doc"})


class NamelistResolver:
    """Resolves EAMxx namelist parameters from XML configuration."""

    def __init__(self, xml_path: str, case_env: Dict[str, str]):
        self._xml_path = xml_path
        self._case_env = dict(case_env)
        self._tree = ET.parse(xml_path)
        self._root = self._tree.getroot()
        self._selectors: Dict[str, dict] = {}
        self._selector_values: Dict[str, Optional[str]] = {}
        self._params: Dict[str, dict] = {}
        self._parse_selectors()
        self._resolve_all()

    # ------------------------------------------------------------------
    # Selector parsing
    # ------------------------------------------------------------------

    def _parse_selectors(self):
        sel_elem = self._root.find("selectors")
        if sel_elem is None:
            return
        for sel in sel_elem.findall("selector"):
            name = sel.get("name")
            case_key = sel.get("case_env")
            regex = sel.get("regex")
            self._selectors[name] = {"case_env": case_key, "regex": regex}
            raw = self._case_env.get(case_key, "")
            if regex:
                m = re.match(regex, raw)
                self._selector_values[name] = m.group(1) if m else None
            else:
                self._selector_values[name] = raw if raw else None

    # ------------------------------------------------------------------
    # Selector matching
    # ------------------------------------------------------------------

    @staticmethod
    def _has_selectors(elem) -> bool:
        return any(a not in _META_ATTRS for a in elem.attrib)

    def _matches_selectors(self, elem) -> bool:
        for attr_name, attr_val in elem.attrib.items():
            if attr_name in _META_ATTRS:
                continue
            negated = attr_val.startswith("!")
            match_val = attr_val[1:] if negated else attr_val

            if attr_name in self._selectors:
                resolved = self._selector_values.get(attr_name)
                matched = resolved is not None and resolved == match_val
            elif attr_name in self._case_env:
                matched = bool(re.fullmatch(match_val, self._case_env[attr_name]))
            else:
                matched = False

            if negated:
                matched = not matched
            if not matched:
                return False
        return True

    # ------------------------------------------------------------------
    # Type helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_type(value_str: str) -> str:
        v = value_str.strip()
        if v.lower() in ("true", "false"):
            return "logical"
        if "," in v:
            return "array(string)"
        try:
            int(v)
            return "integer"
        except ValueError:
            pass
        try:
            float(v)
            return "real"
        except ValueError:
            pass
        return "string"

    def _parse_value(self, value_str: str, type_str: str) -> Any:
        v = value_str.strip()
        if type_str == "logical":
            return v.lower() == "true"
        if type_str == "integer":
            return int(v)
        if type_str == "real":
            return float(v)
        if type_str.startswith("array("):
            return [x.strip() for x in v.split(",")]
        if type_str == "file":
            return self._substitute_vars(v)
        return v

    def _substitute_vars(self, value: str) -> str:
        def _replace(m):
            var = m.group(1)
            if var in self._case_env:
                return self._case_env[var]
            low = var.lower()
            if low in self._selector_values and self._selector_values[low] is not None:
                return self._selector_values[low]
            return m.group(0)
        return re.sub(r"\$\{(\w+)\}", _replace, str(value))

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _resolve_all(self):
        atm = self._root.find("atmosphere")
        if atm is not None:
            self._resolve_group(atm, "atmosphere")

    def _resolve_group(self, parent, prefix: str):
        tag_to_elements: Dict[str, List] = {}
        tag_order: List[str] = []
        for child in parent:
            tag = child.tag
            if tag not in tag_to_elements:
                tag_to_elements[tag] = []
                tag_order.append(tag)
            tag_to_elements[tag].append(child)

        for tag in tag_order:
            elements = tag_to_elements[tag]
            path = f"{prefix}.{tag}"
            is_group = False
            is_param = False
            for e in elements:
                if not self._has_selectors(e) and len(list(e)) > 0:
                    is_group = True
                if (e.text and e.text.strip()) or e.get("type") is not None:
                    is_param = True
            if is_group and not is_param:
                for e in elements:
                    if not self._has_selectors(e):
                        self._resolve_group(e, path)
                        break
            elif is_param:
                self._resolve_param(elements, path)

    def _resolve_param(self, elements, path: str):
        meta_elem = elements[0]
        for e in elements:
            if not self._has_selectors(e):
                meta_elem = e
                break

        type_str = meta_elem.get("type")
        constraints = meta_elem.get("constraints")
        valid_values = meta_elem.get("valid_values")
        locked = meta_elem.get("locked", "false").lower() == "true"
        doc = meta_elem.get("doc", "")

        resolved_text: Optional[str] = None
        for e in elements:
            text = (e.text or "").strip()
            if not text:
                continue
            if self._has_selectors(e):
                if self._matches_selectors(e):
                    resolved_text = text
            else:
                resolved_text = text

        if resolved_text is None:
            return
        if type_str is None:
            type_str = self._infer_type(resolved_text)

        parsed = self._parse_value(resolved_text, type_str)
        if type_str == "string":
            parsed = self._substitute_vars(parsed)
        elif type_str.startswith("array("):
            parsed = [self._substitute_vars(item) if isinstance(item, str) else item
                       for item in parsed]

        self._params[path] = {
            "value": parsed,
            "type": type_str,
            "constraints": constraints,
            "valid_values": valid_values,
            "locked": locked,
            "doc": doc,
        }

    # ------------------------------------------------------------------
    # Constraint validation
    # ------------------------------------------------------------------

    def _validate_constraints(self, value: Any, constraints_str: Optional[str]) -> bool:
        if not constraints_str:
            return True
        if " @@ " in constraints_str:
            parts = [p.strip() for p in constraints_str.split(" @@ ")]
            return all(self._check_one(value, p) for p in parts)
        if " || " in constraints_str:
            parts = [p.strip() for p in constraints_str.split(" || ")]
            return any(self._check_one(value, p) for p in parts)
        return self._check_one(value, constraints_str.strip())

    @staticmethod
    def _check_one(value: Any, constraint: str) -> bool:
        tokens = constraint.split()
        if len(tokens) != 2:
            return True
        op, operand_str = tokens
        try:
            operand = float(operand_str)
            num = float(value)
        except (ValueError, TypeError):
            return True
        if op == "gt": return num > operand
        if op == "ge": return num >= operand
        if op == "lt": return num < operand
        if op == "le": return num <= operand
        if op == "ne": return num != operand
        if op == "mod": return num % operand == 0
        return True

    def _validate_valid_values(self, value: Any, valid_str: Optional[str]) -> bool:
        if not valid_str:
            return True
        allowed = [v.strip() for v in valid_str.split(",")]
        return str(value) in allowed

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_path(self, param_path: str) -> str:
        if param_path in self._params:
            return param_path
        if "::" in param_path:
            group, param = param_path.split("::", 1)
            matches = [p for p in self._params
                       if p.split(".")[-1] == param and group in p.split(".")]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous scoped path '{param_path}': {matches}")
            raise KeyError(f"Parameter '{param_path}' not found")
        matches = [p for p in self._params if p.split(".")[-1] == param_path]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous parameter name '{param_path}': {matches}")
        raise KeyError(f"Parameter '{param_path}' not found")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, param_path: str) -> Any:
        return self._params[self._resolve_path(param_path)]["value"]

    def get_metadata(self, param_path: str) -> dict:
        resolved = self._resolve_path(param_path)
        meta = dict(self._params[resolved])
        meta["group_path"] = ".".join(resolved.split(".")[:-1])
        return meta

    def query(self, pattern: str) -> List[str]:
        rx = re.compile(pattern)
        return sorted(p for p in self._params if rx.search(p))

    def set(self, param_path: str, value: str) -> None:
        resolved = self._resolve_path(param_path)
        meta = self._params[resolved]
        if meta["locked"]:
            raise PermissionError(f"Parameter '{resolved}' is locked")
        parsed = self._parse_value(value, meta["type"])
        if not self._validate_constraints(parsed, meta["constraints"]):
            raise ValueError(
                f"Value {value} violates constraints '{meta['constraints']}'")
        if not self._validate_valid_values(parsed, meta["valid_values"]):
            raise ValueError(
                f"Value {value} not in valid_values '{meta['valid_values']}'")
        meta["value"] = parsed

    def append(self, param_path: str, value: str) -> None:
        resolved = self._resolve_path(param_path)
        meta = self._params[resolved]
        if meta["locked"]:
            raise PermissionError(f"Parameter '{resolved}' is locked")
        if not meta["type"].startswith("array("):
            raise TypeError(f"Parameter '{resolved}' is not an array type")
        meta["value"].append(value.strip())

    def remove(self, param_path: str, value: str) -> None:
        resolved = self._resolve_path(param_path)
        meta = self._params[resolved]
        if meta["locked"]:
            raise PermissionError(f"Parameter '{resolved}' is locked")
        if not meta["type"].startswith("array("):
            raise TypeError(f"Parameter '{resolved}' is not an array type")
        v = value.strip()
        if v not in meta["value"]:
            raise ValueError(f"Value '{v}' not found in array")
        meta["value"].remove(v)

    def list_params(self, group_path: str = "") -> List[str]:
        if group_path:
            prefix = group_path + "."
            return sorted(p for p in self._params if p.startswith(prefix))
        return sorted(self._params.keys())

    def to_yaml(self) -> str:
        tree: dict = {}
        for path in sorted(self._params):
            parts = path.split(".")
            node = tree
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = self._params[path]["value"]
        return yaml.dump(tree, default_flow_style=False, sort_keys=True)
