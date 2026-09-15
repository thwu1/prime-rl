#!/usr/bin/env python3

"""
CSS Cascade Resolver — parses CSS selectors (including :is(), :not(), :where(),
:has(), attribute selectors, combinators), computes specificity per CSS Selectors
Level 4, matches selectors against a JSON DOM tree, and resolves the cascade.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# DOM representation
# ============================================================================

@dataclass
class DOMNode:
    tag: str
    id: Optional[str] = None
    classes: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Optional["DOMNode"] = None
    child_index: int = 0  # index among parent's element children

    def element_children(self):
        return [c for c in self.children if isinstance(c, DOMNode)]

    def path_segment(self):
        if self.id:
            return f"{self.tag}#{self.id}"
        if self.classes:
            sorted_classes = sorted(self.classes)
            return self.tag + "." + ".".join(sorted_classes)
        return self.tag

    def full_path(self):
        parts = []
        node = self
        while node:
            parts.append(node.path_segment())
            node = node.parent
        parts.reverse()
        return " > ".join(parts)

    def ancestors(self):
        node = self.parent
        while node:
            yield node
            node = node.parent

    def preceding_siblings(self):
        if not self.parent:
            return []
        siblings = self.parent.element_children()
        idx = None
        for i, s in enumerate(siblings):
            if s is self:
                idx = i
                break
        if idx is None or idx == 0:
            return []
        return siblings[:idx]

    def immediately_preceding_sibling(self):
        sibs = self.preceding_siblings()
        if sibs:
            return sibs[-1]
        return None

    def descendants(self):
        for c in self.children:
            if isinstance(c, DOMNode):
                yield c
                yield from c.descendants()


def build_dom(data, parent=None):
    if isinstance(data, str):
        return data
    node = DOMNode(
        tag=data.get("tag", ""),
        id=data.get("id"),
        classes=data.get("classes", []),
        attributes=data.get("attributes", {}),
        parent=parent,
    )
    idx = 0
    for child_data in data.get("children", []):
        child = build_dom(child_data, parent=node)
        if isinstance(child, DOMNode):
            child.child_index = idx
            idx += 1
        node.children.append(child)
    return node


def collect_elements(node):
    elements = []
    if isinstance(node, DOMNode):
        elements.append(node)
        for c in node.children:
            elements.extend(collect_elements(c))
    return elements


# ============================================================================
# CSS Selector AST
# ============================================================================

@dataclass
class TypeSelector:
    tag: str  # "*" for universal

@dataclass
class IDSelector:
    id: str

@dataclass
class ClassSelector:
    cls: str

@dataclass
class AttributeSelector:
    attr: str
    op: Optional[str] = None  # None, "=", "~=", "|=", "^=", "$=", "*="
    value: Optional[str] = None

@dataclass
class PseudoClassIs:
    selectors: list  # list of SelectorList items (each is a ComplexSelector)

@dataclass
class PseudoClassNot:
    selectors: list

@dataclass
class PseudoClassWhere:
    selectors: list

@dataclass
class PseudoClassHas:
    relative_selectors: list  # list of (combinator, compound_sequence) pairs as RelativeSelector

@dataclass
class CompoundSelector:
    """A sequence of simple selectors that must all match the same element."""
    simple_selectors: list  # list of TypeSelector | IDSelector | ClassSelector | AttributeSelector | PseudoClass*

@dataclass
class ComplexSelector:
    """A chain of compound selectors joined by combinators."""
    # [(compound, combinator), ...] where last combinator is None
    # Stored as: [(CompoundSelector, str|None), ...]
    # combinator: " " (descendant), ">" (child), "+" (adjacent), "~" (general sibling)
    parts: list  # [(CompoundSelector, combinator_to_next)]

@dataclass
class RelativeSelector:
    """Used inside :has(). Has an optional leading combinator."""
    combinator: Optional[str]  # leading combinator, None means descendant
    complex_selector: ComplexSelector


# ============================================================================
# CSS Tokenizer (minimal, for selectors and declarations)
# ============================================================================

class CSSTokenizer:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def peek(self):
        if self.pos >= len(self.text):
            return None
        return self.text[self.pos]

    def advance(self, n=1):
        self.pos += n

    def skip_ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n\r\f":
            self.pos += 1

    def at_end(self):
        return self.pos >= len(self.text)

    def remaining(self):
        return self.text[self.pos:]


# ============================================================================
# Selector Parser
# ============================================================================

class SelectorParser:
    def __init__(self, text):
        self.tok = CSSTokenizer(text.strip())

    def parse_selector_list(self):
        """Parse comma-separated list of complex selectors."""
        selectors = []
        sel = self.parse_complex_selector()
        if sel:
            selectors.append(sel)
        while not self.tok.at_end():
            self.tok.skip_ws()
            if self.tok.peek() == ",":
                self.tok.advance()
                self.tok.skip_ws()
                sel = self.parse_complex_selector()
                if sel:
                    selectors.append(sel)
            else:
                break
        return selectors

    def parse_complex_selector(self):
        """Parse a complex selector: compound ( combinator compound )*"""
        self.tok.skip_ws()
        compound = self.parse_compound_selector()
        if not compound:
            return None
        parts = [(compound, None)]

        while not self.tok.at_end():
            # Check for combinator
            had_ws = False
            ws_start = self.tok.pos
            self.tok.skip_ws()
            if self.tok.pos > ws_start:
                had_ws = True

            if self.tok.at_end() or self.tok.peek() in (",", ")", "}"):
                break

            ch = self.tok.peek()
            if ch in (">", "+", "~"):
                combinator = ch
                self.tok.advance()
                self.tok.skip_ws()
            elif had_ws:
                combinator = " "
            else:
                break

            compound = self.parse_compound_selector()
            if not compound:
                break
            parts[-1] = (parts[-1][0], combinator)
            parts.append((compound, None))

        return ComplexSelector(parts=parts)

    def parse_compound_selector(self):
        """Parse a compound selector (sequence of simple selectors)."""
        simple_selectors = []
        while not self.tok.at_end():
            ch = self.tok.peek()
            if ch is None:
                break
            if ch == "#":
                simple_selectors.append(self._parse_id())
            elif ch == ".":
                simple_selectors.append(self._parse_class())
            elif ch == "[":
                simple_selectors.append(self._parse_attribute())
            elif ch == ":":
                ps = self._parse_pseudo_class()
                if ps:
                    simple_selectors.append(ps)
            elif ch == "*":
                self.tok.advance()
                simple_selectors.append(TypeSelector(tag="*"))
            elif self._is_ident_start(ch):
                simple_selectors.append(self._parse_type())
            else:
                break
        if not simple_selectors:
            return None
        return CompoundSelector(simple_selectors=simple_selectors)

    def _is_ident_start(self, ch):
        return ch is not None and (ch.isalpha() or ch == "_" or ch == "-")

    def _is_ident_char(self, ch):
        return ch is not None and (ch.isalnum() or ch in ("_", "-"))

    def _read_ident(self):
        start = self.tok.pos
        while not self.tok.at_end() and self._is_ident_char(self.tok.peek()):
            self.tok.advance()
        return self.tok.text[start:self.tok.pos]

    def _parse_type(self):
        name = self._read_ident()
        return TypeSelector(tag=name)

    def _parse_id(self):
        self.tok.advance()  # skip #
        name = self._read_ident()
        return IDSelector(id=name)

    def _parse_class(self):
        self.tok.advance()  # skip .
        name = self._read_ident()
        return ClassSelector(cls=name)

    def _parse_attribute(self):
        self.tok.advance()  # skip [
        self.tok.skip_ws()
        attr_name = self._read_ident()
        self.tok.skip_ws()
        op = None
        value = None
        if not self.tok.at_end() and self.tok.peek() != "]":
            # Read operator
            ch = self.tok.peek()
            if ch == "=":
                op = "="
                self.tok.advance()
            elif ch in ("~", "|", "^", "$", "*"):
                op = ch + "="
                self.tok.advance()
                if self.tok.peek() == "=":
                    self.tok.advance()
            self.tok.skip_ws()
            value = self._read_string_or_ident()
            self.tok.skip_ws()
        if not self.tok.at_end() and self.tok.peek() == "]":
            self.tok.advance()
        return AttributeSelector(attr=attr_name, op=op, value=value)

    def _read_string_or_ident(self):
        ch = self.tok.peek()
        if ch in ('"', "'"):
            return self._read_string(ch)
        return self._read_ident()

    def _read_string(self, quote):
        self.tok.advance()  # skip opening quote
        start = self.tok.pos
        while not self.tok.at_end() and self.tok.peek() != quote:
            if self.tok.peek() == "\\":
                self.tok.advance()
            self.tok.advance()
        result = self.tok.text[start:self.tok.pos]
        if not self.tok.at_end():
            self.tok.advance()  # skip closing quote
        return result

    def _parse_pseudo_class(self):
        self.tok.advance()  # skip :
        if self.tok.at_end():
            return None
        # Check for :: (pseudo-element), skip for now
        if self.tok.peek() == ":":
            self.tok.advance()
            name = self._read_ident()
            return None  # pseudo-elements not handled

        name = self._read_ident()
        name_lower = name.lower()

        if not self.tok.at_end() and self.tok.peek() == "(":
            self.tok.advance()  # skip (
            if name_lower == "is":
                selectors = self._parse_inner_selector_list()
                self._skip_close_paren()
                return PseudoClassIs(selectors=selectors)
            elif name_lower == "not":
                selectors = self._parse_inner_selector_list()
                self._skip_close_paren()
                return PseudoClassNot(selectors=selectors)
            elif name_lower == "where":
                selectors = self._parse_inner_selector_list()
                self._skip_close_paren()
                return PseudoClassWhere(selectors=selectors)
            elif name_lower == "has":
                rel_selectors = self._parse_has_args()
                self._skip_close_paren()
                return PseudoClassHas(relative_selectors=rel_selectors)
            elif name_lower == "nth-child":
                # Skip nth-child args for now - consume until )
                self._skip_until_close_paren()
                return None
            else:
                self._skip_until_close_paren()
                return None
        return None  # simple pseudo-classes like :hover not relevant

    def _skip_close_paren(self):
        self.tok.skip_ws()
        if not self.tok.at_end() and self.tok.peek() == ")":
            self.tok.advance()

    def _skip_until_close_paren(self):
        depth = 1
        while not self.tok.at_end() and depth > 0:
            ch = self.tok.peek()
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            self.tok.advance()

    def _parse_inner_selector_list(self):
        """Parse selector list inside pseudo-class parens."""
        self.tok.skip_ws()
        selectors = []
        sel = self._parse_inner_complex_selector()
        if sel:
            selectors.append(sel)
        while not self.tok.at_end() and self.tok.peek() != ")":
            self.tok.skip_ws()
            if self.tok.peek() == ",":
                self.tok.advance()
                self.tok.skip_ws()
                sel = self._parse_inner_complex_selector()
                if sel:
                    selectors.append(sel)
            else:
                break
        return selectors

    def _parse_inner_complex_selector(self):
        return self.parse_complex_selector()

    def _parse_has_args(self):
        """Parse :has() arguments — relative selectors."""
        self.tok.skip_ws()
        selectors = []
        rel = self._parse_relative_selector()
        if rel:
            selectors.append(rel)
        while not self.tok.at_end() and self.tok.peek() != ")":
            self.tok.skip_ws()
            if self.tok.peek() == ",":
                self.tok.advance()
                self.tok.skip_ws()
                rel = self._parse_relative_selector()
                if rel:
                    selectors.append(rel)
            else:
                break
        return selectors

    def _parse_relative_selector(self):
        self.tok.skip_ws()
        combinator = None
        if not self.tok.at_end():
            ch = self.tok.peek()
            if ch in (">", "+", "~"):
                combinator = ch
                self.tok.advance()
                self.tok.skip_ws()
        complex_sel = self.parse_complex_selector()
        if not complex_sel:
            return None
        return RelativeSelector(combinator=combinator, complex_selector=complex_sel)


# ============================================================================
# Specificity computation
# ============================================================================

def specificity_of_compound(compound):
    """Compute (a, b, c) specificity of a CompoundSelector."""
    a, b, c = 0, 0, 0
    for simple in compound.simple_selectors:
        sa, sb, sc = specificity_of_simple(simple)
        a += sa
        b += sb
        c += sc
    return (a, b, c)


def specificity_of_simple(simple):
    if isinstance(simple, IDSelector):
        return (1, 0, 0)
    elif isinstance(simple, ClassSelector):
        return (0, 1, 0)
    elif isinstance(simple, AttributeSelector):
        return (0, 1, 0)
    elif isinstance(simple, TypeSelector):
        if simple.tag == "*":
            return (0, 0, 0)
        return (0, 0, 1)
    elif isinstance(simple, PseudoClassIs):
        # Takes specificity of most specific argument
        return max_specificity_of_selector_list(simple.selectors)
    elif isinstance(simple, PseudoClassNot):
        # Takes specificity of most specific argument
        return max_specificity_of_selector_list(simple.selectors)
    elif isinstance(simple, PseudoClassWhere):
        # Always zero specificity
        return (0, 0, 0)
    elif isinstance(simple, PseudoClassHas):
        # Takes specificity of most specific argument
        specs = []
        for rel in simple.relative_selectors:
            specs.append(specificity_of_complex(rel.complex_selector))
        if not specs:
            return (0, 0, 0)
        return max(specs)
    return (0, 0, 0)


def max_specificity_of_selector_list(selectors):
    if not selectors:
        return (0, 0, 0)
    specs = [specificity_of_complex(sel) for sel in selectors]
    return max(specs)


def specificity_of_complex(complex_sel):
    a, b, c = 0, 0, 0
    for compound, _ in complex_sel.parts:
        sa, sb, sc = specificity_of_compound(compound)
        a += sa
        b += sb
        c += sc
    return (a, b, c)


# ============================================================================
# Selector matching
# ============================================================================

def matches_compound(node, compound):
    """Check if node matches all simple selectors in compound."""
    for simple in compound.simple_selectors:
        if not matches_simple(node, simple):
            return False
    return True


def matches_simple(node, simple):
    if isinstance(simple, TypeSelector):
        return simple.tag == "*" or node.tag == simple.tag
    elif isinstance(simple, IDSelector):
        return node.id == simple.id
    elif isinstance(simple, ClassSelector):
        return simple.cls in node.classes
    elif isinstance(simple, AttributeSelector):
        return matches_attribute(node, simple)
    elif isinstance(simple, PseudoClassIs):
        return any(matches_complex(node, sel) for sel in simple.selectors)
    elif isinstance(simple, PseudoClassNot):
        return not any(matches_complex(node, sel) for sel in simple.selectors)
    elif isinstance(simple, PseudoClassWhere):
        return any(matches_complex(node, sel) for sel in simple.selectors)
    elif isinstance(simple, PseudoClassHas):
        return matches_has(node, simple)
    return False


def matches_attribute(node, attr_sel):
    val = node.attributes.get(attr_sel.attr)
    if val is None:
        return False
    if attr_sel.op is None:
        return True  # presence check
    if attr_sel.op == "=":
        return val == attr_sel.value
    elif attr_sel.op == "~=":
        return attr_sel.value in val.split()
    elif attr_sel.op == "|=":
        return val == attr_sel.value or val.startswith(attr_sel.value + "-")
    elif attr_sel.op == "^=":
        return val.startswith(attr_sel.value)
    elif attr_sel.op == "$=":
        return val.endswith(attr_sel.value)
    elif attr_sel.op == "*=":
        return attr_sel.value in val
    return False


def matches_has(node, has_sel):
    """Check if node matches :has() by checking if any descendant/child matches."""
    for rel in has_sel.relative_selectors:
        if rel.combinator == ">":
            # Direct children only
            for child in node.element_children():
                if matches_complex(child, rel.complex_selector):
                    return True
        else:
            # Descendant (default)
            for desc in node.descendants():
                if matches_complex(desc, rel.complex_selector):
                    return True
    return False


def matches_complex(node, complex_sel):
    """Check if node matches a complex selector (right-to-left matching)."""
    parts = complex_sel.parts
    if not parts:
        return False

    # The rightmost compound must match the node
    rightmost_compound = parts[-1][0]
    if not matches_compound(node, rightmost_compound):
        return False

    # Walk the remaining parts right-to-left
    current_node = node
    for i in range(len(parts) - 2, -1, -1):
        compound, combinator = parts[i]
        if combinator == " ":
            # Descendant: find any ancestor matching
            found = False
            for ancestor in current_node.ancestors():
                if matches_compound(ancestor, compound):
                    current_node = ancestor
                    found = True
                    break
            if not found:
                return False
        elif combinator == ">":
            # Child: parent must match
            parent = current_node.parent
            if parent is None or not matches_compound(parent, compound):
                return False
            current_node = parent
        elif combinator == "+":
            # Adjacent sibling: immediately preceding sibling must match
            sib = current_node.immediately_preceding_sibling()
            if sib is None or not matches_compound(sib, compound):
                return False
            current_node = sib
        elif combinator == "~":
            # General sibling: any preceding sibling must match
            found = False
            for sib in current_node.preceding_siblings():
                if matches_compound(sib, compound):
                    current_node = sib
                    found = True
                    break
            if not found:
                return False
    return True


# ============================================================================
# CSS Rule Parser
# ============================================================================

@dataclass
class Declaration:
    property: str
    value: str
    important: bool = False


@dataclass
class CSSRule:
    selectors: list  # list of ComplexSelector
    declarations: list  # list of Declaration
    source_order: int = 0


def parse_css(text):
    """Parse CSS text into a list of CSSRule objects."""
    rules = []
    # Remove comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    pos = 0
    order = 0
    while pos < len(text):
        # Find next rule
        brace_start = text.find("{", pos)
        if brace_start == -1:
            break
        selector_text = text[pos:brace_start].strip()

        # Find matching closing brace
        depth = 1
        brace_end = brace_start + 1
        while brace_end < len(text) and depth > 0:
            if text[brace_end] == "{":
                depth += 1
            elif text[brace_end] == "}":
                depth -= 1
            brace_end += 1

        decl_text = text[brace_start + 1:brace_end - 1].strip()

        if selector_text:
            parser = SelectorParser(selector_text)
            selectors = parser.parse_selector_list()
            declarations = parse_declarations(decl_text)
            if selectors and declarations:
                rules.append(CSSRule(
                    selectors=selectors,
                    declarations=declarations,
                    source_order=order
                ))
                order += 1

        pos = brace_end

    return rules


def parse_declarations(text):
    """Parse declaration block text into list of Declaration."""
    decls = []
    parts = text.split(";")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        colon = part.find(":")
        if colon == -1:
            continue
        prop = part[:colon].strip()
        val = part[colon + 1:].strip()
        important = False
        if val.endswith("!important"):
            important = True
            val = val[:-len("!important")].strip()
        elif "!important" in val:
            idx = val.find("!important")
            val = val[:idx].strip()
            important = True
        decls.append(Declaration(property=prop, value=val, important=important))
    return decls


# ============================================================================
# Cascade resolution
# ============================================================================

def resolve_cascade(dom_root, rules):
    """Resolve cascade for all elements, return {path: {prop: value}}."""
    elements = collect_elements(dom_root)
    result = {}

    for element in elements:
        # Collect all matching declarations with their specificity and order
        applicable = []  # (importance, specificity, source_order, decl_index, declaration)

        for rule in rules:
            for selector in rule.selectors:
                if matches_complex(element, selector):
                    spec = specificity_of_complex(selector)
                    for di, decl in enumerate(rule.declarations):
                        applicable.append((
                            1 if decl.important else 0,
                            spec,
                            rule.source_order,
                            di,
                            decl,
                        ))

        if not applicable:
            continue

        # Group by property, pick winner
        props = {}
        for importance, spec, source_order, decl_idx, decl in applicable:
            key = decl.property
            if key not in props:
                props[key] = []
            props[key].append((importance, spec, source_order, decl_idx, decl))

        resolved = {}
        for prop, entries in props.items():
            # Sort: importance DESC, specificity DESC, source_order DESC, decl_idx DESC
            entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
            winner = entries[-1]
            resolved[prop] = winner[4].value

        if resolved:
            path = element.full_path()
            if path in result:
                # Merge (shouldn't happen with unique paths, but handle duplicates)
                result[path].update(resolved)
            else:
                result[path] = resolved

    return result


# ============================================================================
# Main
# ============================================================================

def main():
    if len(sys.argv) < 3:
        print("Usage: cascade.py <dom.json> <styles.css>", file=sys.stderr)
        sys.exit(1)

    dom_path = sys.argv[1]
    css_path = sys.argv[2]

    with open(dom_path) as f:
        dom_data = json.load(f)
    with open(css_path) as f:
        css_text = f.read()

    dom_root = build_dom(dom_data)
    rules = parse_css(css_text)
    result = resolve_cascade(dom_root, rules)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
