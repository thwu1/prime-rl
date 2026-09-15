"""FHIR Search Parameter Parser

Implement a parser for FHIR REST API search query strings as defined by
the HL7 FHIR R4 specification (https://www.hl7.org/fhir/search.html).

The data model classes below define the expected output structure. You must
implement parse_fhir_search() and build_query_string() using these exact
class names and the to_dict() serialization interface.
"""

from dataclasses import dataclass, field
from typing import List, Optional

COMPARISON_PREFIXES = frozenset({
    "eq", "ne", "lt", "le", "gt", "ge", "sa", "eb", "ap"
})

VALID_MODIFIERS = frozenset({
    "missing", "exact", "contains", "text", "in", "not-in",
    "below", "above", "not", "type", "identifier", "of-type",
})


@dataclass
class ParameterValue:
    """A single parsed value within a FHIR search parameter.

    Attributes:
        raw_value: The value string after prefix extraction (no URL decoding
            needed - that is handled before this object is created).
        prefix: Comparison prefix if detected (eq/ne/lt/le/gt/ge/sa/eb/ap).
            Only extracted when followed by a digit, minus sign, or period.
        parts: Pipe-separated parts for token (system|code) or quantity
            (value|system|unit) values. None if no unescaped pipe present.
        is_composite: True if the value contains $-separated components.
        components: Sub-values for composite parameters.
    """
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
    """A parsed FHIR search parameter.

    Attributes:
        name: Parameter name (without modifier suffix).
        modifier: Modifier string if present (not/exact/contains/etc.).
        values: OR-joined values (from comma separation within one param).
            Repeated parameter names (AND semantics) create separate
            SearchParameter instances.
        chain: For chained parameters (dot-separated names like
            'medication.ingredient-code'), a list of the chain segments.
            None for non-chained parameters.
    """
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
    """A sort specification from the _sort parameter.

    Attributes:
        field_name: The field to sort by.
        order: 'asc' or 'desc'.
    """
    field_name: str
    order: str = "asc"

    def to_dict(self) -> dict:
        return {"field": self.field_name, "order": self.order}


@dataclass
class IncludeParam:
    """An _include or _revinclude directive.

    Format: Resource:search_param[:target_type]

    Attributes:
        resource: The source resource type.
        search_param: The search parameter name.
        target_type: Optional target resource type constraint.
    """
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
    """A _has reverse chaining parameter.

    Format: _has:Resource:reference_param:search_param=value

    Attributes:
        resource: The linking resource type.
        reference_param: The reference search parameter on the linking resource.
        search_param: The search parameter to filter on.
        value: The value to match.
    """
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
    """Complete parsed representation of a FHIR search query.

    Attributes:
        parameters: Regular search parameters (AND semantics for repeated names).
        sort: Sort specifications from _sort.
        count: Result limit from _count.
        page: Page number from page parameter.
        include: _include directives.
        revinclude: _revinclude directives.
        has_params: _has reverse chaining parameters.
        summary: _summary mode value (true/false/text/data/count).
        elements: Field names from _elements.
        pretty: _pretty flag.
        format_param: _format value.
    """
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


def parse_fhir_search(query_string: str) -> ParsedSearch:
    """Parse a FHIR search query string into a structured representation.

    Args:
        query_string: URL query string (without the leading '?').
            Standard URL encoding is expected (+ for space, %XX escapes).

    Returns:
        ParsedSearch object with all parsed components.
    """
    raise NotImplementedError("Implement this function")


def build_query_string(parsed: ParsedSearch) -> str:
    """Build a FHIR search query string from a ParsedSearch object.

    The generated query string, when re-parsed with parse_fhir_search(),
    should yield a structurally equivalent ParsedSearch (round-trip).

    Args:
        parsed: A ParsedSearch object.

    Returns:
        A URL query string representation.
    """
    raise NotImplementedError("Implement this function")
