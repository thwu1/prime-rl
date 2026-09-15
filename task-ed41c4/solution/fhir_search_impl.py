"""FHIR R4 Search Query Parser — Complete Implementation.

"""

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import unquote_plus

COMPARISON_PREFIXES = frozenset({
    "eq", "ne", "lt", "le", "gt", "ge", "sa", "eb", "ap"
})

VALID_MODIFIERS = frozenset({
    "missing", "exact", "contains", "text", "in", "not-in",
    "below", "above", "not", "type", "identifier", "of-type",
})


@dataclass
class ParameterValue:
    raw_value: str
    prefix: Optional[str] = None
    parts: Optional[List[str]] = None
    is_composite: bool = False
    components: Optional[List['ParameterValue']] = None

    def to_dict(self) -> dict:
        d = {"raw_value": self.raw_value, "prefix": self.prefix}
        if self.parts is not None:
            d["parts"] = self.parts
        if self.is_composite:
            d["is_composite"] = True
            d["components"] = [c.to_dict() for c in (self.components or [])]
        return d


@dataclass
class SearchParameter:
    name: str
    modifier: Optional[str] = None
    values: List[ParameterValue] = field(default_factory=list)
    chain: Optional[List[str]] = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "modifier": self.modifier,
            "values": [v.to_dict() for v in self.values],
        }
        if self.chain is not None:
            d["chain"] = self.chain
        return d


@dataclass
class SortField:
    field_name: str
    order: str = "asc"

    def to_dict(self) -> dict:
        return {"field": self.field_name, "order": self.order}


@dataclass
class IncludeParam:
    resource: str
    search_param: str
    target_type: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "resource": self.resource,
            "search_param": self.search_param,
            "target_type": self.target_type,
        }


@dataclass
class HasParam:
    resource: str
    reference_param: str
    search_param: str
    value: str

    def to_dict(self) -> dict:
        return {
            "resource": self.resource,
            "reference_param": self.reference_param,
            "search_param": self.search_param,
            "value": self.value,
        }


@dataclass
class ParsedSearch:
    parameters: List[SearchParameter] = field(default_factory=list)
    sort: List[SortField] = field(default_factory=list)
    count: Optional[int] = None
    page: Optional[int] = None
    include: List[IncludeParam] = field(default_factory=list)
    revinclude: List[IncludeParam] = field(default_factory=list)
    has_params: List[HasParam] = field(default_factory=list)
    summary: Optional[str] = None
    elements: List[str] = field(default_factory=list)
    pretty: Optional[bool] = None
    format_param: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "parameters": [p.to_dict() for p in self.parameters],
            "sort": [s.to_dict() for s in self.sort],
            "count": self.count,
            "page": self.page,
            "include": [i.to_dict() for i in self.include],
            "revinclude": [r.to_dict() for r in self.revinclude],
            "has_params": [h.to_dict() for h in self.has_params],
            "summary": self.summary,
            "elements": self.elements,
            "pretty": self.pretty,
            "format_param": self.format_param,
        }


def _extract_prefix(value):
    """Extract comparison prefix from a value string.

    Only extracts when the prefix is followed by a digit, minus sign, or period.
    """
    for pfx in ("ge", "le", "gt", "lt", "ne", "eq", "sa", "eb", "ap"):
        if value.startswith(pfx) and len(value) > len(pfx):
            next_char = value[len(pfx)]
            if next_char in "0123456789.-":
                return pfx, value[len(pfx):]
    return None, value


def _parse_value(raw):
    """Parse a single parameter value string into a ParameterValue."""
    # Check for composite ($-separated)
    if "$" in raw:
        components = [_parse_value(part) for part in raw.split("$")]
        return ParameterValue(
            raw_value=raw,
            is_composite=True,
            components=components,
        )

    # Extract prefix
    prefix, value = _extract_prefix(raw)

    # Check for pipe-separated parts
    parts = None
    if "|" in value:
        parts = value.split("|")

    return ParameterValue(
        raw_value=value,
        prefix=prefix,
        parts=parts,
    )


def _parse_include(value):
    """Parse an _include or _revinclude value."""
    segments = value.split(":")
    return IncludeParam(
        resource=segments[0],
        search_param=segments[1] if len(segments) > 1 else "",
        target_type=segments[2] if len(segments) > 2 else None,
    )


def parse_fhir_search(query_string):
    """Parse a FHIR search query string into a structured representation."""
    result = ParsedSearch()

    if not query_string or not query_string.strip():
        return result

    pairs = query_string.split("&")

    for pair in pairs:
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = unquote_plus(key)
        value = unquote_plus(value)

        # --- special parameters ---
        if key == "_sort":
            for f in value.split(","):
                if f.startswith("-"):
                    result.sort.append(SortField(field_name=f[1:], order="desc"))
                else:
                    result.sort.append(SortField(field_name=f, order="asc"))
            continue

        if key == "_count":
            result.count = int(value)
            continue

        if key == "page":
            result.page = int(value)
            continue

        if key == "_summary":
            result.summary = value
            continue

        if key == "_elements":
            result.elements = value.split(",")
            continue

        if key == "_pretty":
            result.pretty = value.lower() == "true"
            continue

        if key == "_format":
            result.format_param = value
            continue

        if key == "_include":
            result.include.append(_parse_include(value))
            continue

        if key == "_revinclude":
            result.revinclude.append(_parse_include(value))
            continue

        if key.startswith("_has:"):
            has_parts = key.split(":")
            if len(has_parts) >= 4:
                result.has_params.append(HasParam(
                    resource=has_parts[1],
                    reference_param=has_parts[2],
                    search_param=has_parts[3],
                    value=value,
                ))
            continue

        # --- regular parameters ---
        name = key
        modifier = None
        chain = None

        # Check for chain (dot-separated)
        if "." in name:
            chain_parts = name.split(".")
            name = chain_parts[0].split(":")[0] if ":" in chain_parts[0] else chain_parts[0]
            chain = chain_parts
        elif ":" in name:
            name, modifier = name.split(":", 1)

        # Parse comma-separated values (OR semantics)
        values = [_parse_value(v) for v in value.split(",")]

        param = SearchParameter(
            name=name,
            modifier=modifier,
            values=values,
            chain=chain,
        )
        result.parameters.append(param)

    return result


def build_query_string(parsed):
    """Build a FHIR search query string from a ParsedSearch object."""
    parts = []

    for param in parsed.parameters:
        # Reconstruct key
        if param.chain:
            key = ".".join(param.chain)
        elif param.modifier:
            key = f"{param.name}:{param.modifier}"
        else:
            key = param.name

        # Reconstruct values
        val_strs = []
        for v in param.values:
            if v.is_composite and v.components:
                comp_strs = []
                for c in v.components:
                    s = ""
                    if c.prefix:
                        s += c.prefix
                    if c.parts:
                        s += "|".join(c.parts)
                    else:
                        s += c.raw_value
                    comp_strs.append(s)
                val_strs.append("$".join(comp_strs))
            else:
                s = ""
                if v.prefix:
                    s += v.prefix
                if v.parts:
                    s += "|".join(v.parts)
                else:
                    s += v.raw_value
                val_strs.append(s)

        parts.append(f"{key}={','.join(val_strs)}")

    # Special parameters
    if parsed.sort:
        sort_fields = []
        for s in parsed.sort:
            if s.order == "desc":
                sort_fields.append(f"-{s.field_name}")
            else:
                sort_fields.append(s.field_name)
        parts.append(f"_sort={','.join(sort_fields)}")

    if parsed.count is not None:
        parts.append(f"_count={parsed.count}")

    if parsed.page is not None:
        parts.append(f"page={parsed.page}")

    for inc in parsed.include:
        val = f"{inc.resource}:{inc.search_param}"
        if inc.target_type:
            val += f":{inc.target_type}"
        parts.append(f"_include={val}")

    for rinc in parsed.revinclude:
        val = f"{rinc.resource}:{rinc.search_param}"
        if rinc.target_type:
            val += f":{rinc.target_type}"
        parts.append(f"_revinclude={val}")

    for h in parsed.has_params:
        parts.append(
            f"_has:{h.resource}:{h.reference_param}:{h.search_param}={h.value}"
        )

    if parsed.summary:
        parts.append(f"_summary={parsed.summary}")

    if parsed.elements:
        parts.append(f"_elements={','.join(parsed.elements)}")

    if parsed.pretty is not None:
        parts.append(f"_pretty={'true' if parsed.pretty else 'false'}")

    if parsed.format_param:
        parts.append(f"_format={parsed.format_param}")

    return "&".join(parts)
