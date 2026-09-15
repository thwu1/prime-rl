"""
Cursorless Scope Fixture Engine - Solution Implementation

Parses, renders, and maps Cursorless .scope test fixture files.
Integrates with tree-sitter for end-to-end scope annotation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import re


@dataclass
class Range:
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def __eq__(self, other):
        if not isinstance(other, Range):
            return NotImplemented
        return (self.start_line == other.start_line and
                self.start_col == other.start_col and
                self.end_line == other.end_line and
                self.end_col == other.end_col)

    def __hash__(self):
        return hash((self.start_line, self.start_col, self.end_line, self.end_col))

    def __repr__(self):
        return f"Range({self.start_line}:{self.start_col}-{self.end_line}:{self.end_col})"


@dataclass
class Scope:
    ranges: Dict[str, Range] = field(default_factory=dict)
    insertion_delimiter: str = "\n"


def _parse_range_spec(spec: str) -> Range:
    """Parse a range specification like '0:0-2:1' into a Range."""
    m = re.match(r'(\d+):(\d+)-(\d+):(\d+)', spec.strip())
    if not m:
        raise ValueError(f"Invalid range spec: {spec!r}")
    return Range(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))


def parse_fixture(text: str) -> List[Scope]:
    """Parse a .scope fixture file into a list of Scope objects."""
    # Split into source and scopes sections at first ---
    parts = text.split("---\n", 1)
    if len(parts) != 2:
        raise ValueError("Fixture must contain --- separator")

    scopes_text = parts[1]
    scopes = []
    current_labels = []
    current_range = None
    current_scope = None

    lines = scopes_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Empty line between scopes
        if line.strip() == "":
            if current_scope is not None:
                scopes.append(current_scope)
                current_scope = None
            current_labels = []
            current_range = None
            i += 1
            continue

        # Insertion delimiter line
        delim_match = re.match(r'\[Insertion delimiter\] = "(.*)"', line)
        if delim_match:
            if current_scope is not None:
                # Unescape the delimiter
                delim = delim_match.group(1).replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
                current_scope.insertion_delimiter = delim
            i += 1
            continue

        # Range label line: [Label] = or [Label] = L:C-L:C
        label_match = re.match(r'\[(\w+)\]\s*=\s*(.*)', line)
        if label_match:
            label = label_match.group(1)
            range_str = label_match.group(2).strip()

            if current_scope is None:
                current_scope = Scope()

            if range_str:
                # This label has an explicit range, and all pending labels share it
                r = _parse_range_spec(range_str)
                current_labels.append(label)
                for lbl in current_labels:
                    current_scope.ranges[lbl] = Range(r.start_line, r.start_col, r.end_line, r.end_col)
                current_range = r
                current_labels = []
            else:
                # Label without range — it shares the range of the next label with a range
                current_labels.append(label)

            i += 1
            continue

        # Visual range lines (>...<) and source lines (N| ...) — skip them
        # These are just visual representations of the already-parsed range
        i += 1

    # Don't forget the last scope
    if current_scope is not None:
        scopes.append(current_scope)

    return scopes


def render_fixture(source: str, scopes: List[Scope]) -> str:
    """Render source code and scopes into a .scope fixture string."""
    source_lines = source.split("\n")
    result = source + "\n---\n"

    for scope_idx, scope in enumerate(scopes):
        result += "\n"

        # Group facets by their range to identify which share the same range
        # Preserve order: collect unique ranges in order of first appearance
        facet_order = ["Content", "Removal", "Domain", "Leading", "Trailing", "Interior"]
        present_facets = [(f, scope.ranges[f]) for f in facet_order if f in scope.ranges]

        # Group consecutive facets that share the same range
        groups = []
        if present_facets:
            current_group = [present_facets[0]]
            for j in range(1, len(present_facets)):
                facet, r = present_facets[j]
                if r == current_group[0][1]:
                    current_group.append((facet, r))
                else:
                    groups.append(current_group)
                    current_group = [(facet, r)]
            groups.append(current_group)

        for group in groups:
            r = group[0][1]  # All ranges in group are equal

            # Print label lines
            for k, (label, _) in enumerate(group):
                if k < len(group) - 1:
                    result += f"[{label}] =\n"
                else:
                    result += f"[{label}] = {r.start_line}:{r.start_col}-{r.end_line}:{r.end_col}\n"

            # Render visual representation
            result += _render_visual_range(r, source_lines)

        # Insertion delimiter
        delim_escaped = scope.insertion_delimiter.replace("\n", "\\n").replace("\t", "\\t").replace('"', '\\"')
        result += f'[Insertion delimiter] = "{delim_escaped}"\n'

    return result


def _render_visual_range(r: Range, source_lines: List[str]) -> str:
    """Render the visual annotation for a range."""
    result = ""
    lines_in_range = list(range(r.start_line, r.end_line + 1))
    max_line_num = max(lines_in_range)
    line_num_width = len(str(max_line_num))

    if r.start_line == r.end_line:
        # Single-line range
        line = source_lines[r.start_line]
        range_len = r.end_col - r.start_col
        marker_padding = " " * r.start_col

        if range_len == 0:
            marker = "><"
        elif range_len == 1:
            marker = ">-<"
        else:
            marker = ">" + "-" * range_len + "<"

        result += marker_padding + marker + "\n"
        result += f"{r.start_line:>{line_num_width}}| {line}\n"
    else:
        # Multi-line range
        first_line = source_lines[r.start_line]

        # First visual line: start_col spaces + > + dashes to end of first source line
        first_padding = " " * r.start_col
        first_line_content_len = len(first_line) - r.start_col
        first_marker = ">" + "-" * first_line_content_len
        result += first_padding + first_marker + "\n"

        # Source lines with line numbers
        for line_num in lines_in_range:
            line = source_lines[line_num]
            result += f"{line_num:>{line_num_width}}| {line}\n"

        # Final visual line: end_col dashes + <
        final_marker = "-" * r.end_col + "<"
        result += final_marker + "\n"

    return result


def map_captures_to_scopes(
    captures: List[Tuple[str, Tuple[int, int], Tuple[int, int]]],
    insertion_delimiter: str = "\n"
) -> List[Scope]:
    """Map tree-sitter query captures to Scope objects.

    Each capture is (capture_name, start_point, end_point) where points are (line, col).
    Capture names follow Cursorless conventions:
      @name -> Content
      @name.domain -> Domain
      @name.interior -> Interior
      @name.leading -> Leading
      @name.trailing -> Trailing
      @name.removal -> Removal
    """
    ASPECT_MAP = {
        "domain": "Domain",
        "interior": "Interior",
        "leading": "Leading",
        "trailing": "Trailing",
        "removal": "Removal",
    }

    # Group captures by scope instance.
    # Multiple bare @name captures create separate scope instances.
    # Aspect captures (@name.aspect) attach to the most recent bare instance.
    scope_instances: List[Tuple[str, Dict[str, Range]]] = []
    base_to_current_indices: Dict[str, List[int]] = {}

    for capture_name, start_pt, end_pt in captures:
        r = Range(start_pt[0], start_pt[1], end_pt[0], end_pt[1])

        parts = capture_name.split(".", 1)
        base_name = parts[0]

        if len(parts) == 1:
            # Bare capture -> new Content scope instance
            idx = len(scope_instances)
            scope_instances.append((base_name, {"Content": r}))
            if base_name not in base_to_current_indices:
                base_to_current_indices[base_name] = []
            base_to_current_indices[base_name].append(idx)
        else:
            aspect = parts[1]
            facet = ASPECT_MAP.get(aspect)
            if facet and base_name in base_to_current_indices:
                # Attach to the most recent instance of this base name
                idx = base_to_current_indices[base_name][-1]
                scope_instances[idx][1][facet] = r

    # Build Scope objects with derived ranges
    result = []
    for base_name, range_dict in scope_instances:
        scope = Scope(insertion_delimiter=insertion_delimiter)
        scope.ranges = dict(range_dict)

        content = scope.ranges.get("Content")

        # Derive Removal if not explicitly set
        if "Removal" not in scope.ranges and content:
            leading = scope.ranges.get("Leading")
            trailing = scope.ranges.get("Trailing")

            if leading or trailing:
                # Union of leading + content + trailing
                all_ranges = [r for r in [leading, content, trailing] if r is not None]
                start_line = min(r.start_line for r in all_ranges)
                start_col = min(r.start_col for r in all_ranges if r.start_line == start_line)
                end_line = max(r.end_line for r in all_ranges)
                end_col = max(r.end_col for r in all_ranges if r.end_line == end_line)

                scope.ranges["Removal"] = Range(start_line, start_col, end_line, end_col)
            else:
                scope.ranges["Removal"] = Range(content.start_line, content.start_col,
                                                 content.end_line, content.end_col)

        # Derive Domain if not explicitly set
        if "Domain" not in scope.ranges:
            removal = scope.ranges.get("Removal", content)
            if removal:
                scope.ranges["Domain"] = Range(removal.start_line, removal.start_col,
                                                removal.end_line, removal.end_col)

        result.append(scope)

    return result


def annotate_source(source, language, query_text, insertion_delimiter="\n"):
    """Annotate source code using a tree-sitter query and produce .scope fixture output.

    Args:
        source: The source code string to annotate.
        language: A tree-sitter Language object for the source language.
        query_text: Tree-sitter query pattern string (.scm format).
        insertion_delimiter: Delimiter string for scope insertion.

    Returns:
        Complete .scope fixture text with source code and annotated scopes.
    """
    from tree_sitter import Parser

    # Handle both old and new Parser API
    try:
        parser = Parser(language)
    except TypeError:
        parser = Parser()
        parser.set_language(language)

    tree = parser.parse(bytes(source, "utf8"))
    query = language.query(query_text)

    raw_captures = query.captures(tree.root_node)

    # Handle both tree-sitter API variants:
    # - 0.22+: dict[str, list[Node]]
    # - 0.21: list[tuple[Node, str]]
    capture_list = []
    if isinstance(raw_captures, dict):
        for name, nodes in raw_captures.items():
            if not isinstance(nodes, list):
                nodes = [nodes]
            for node in nodes:
                sp = node.start_point
                ep = node.end_point
                capture_list.append((name, (sp[0], sp[1]), (ep[0], ep[1])))
    else:
        for item in raw_captures:
            if isinstance(item, tuple) and len(item) == 2:
                node, name = item
                sp = node.start_point
                ep = node.end_point
                capture_list.append((name, (sp[0], sp[1]), (ep[0], ep[1])))

    # Sort: by start position, then bare names before aspects at same position,
    # then by end position
    capture_list.sort(key=lambda c: (c[1], "." in c[0], c[2]))

    scopes = map_captures_to_scopes(capture_list, insertion_delimiter)
    return render_fixture(source, scopes)
