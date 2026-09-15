"""CSS selector parser, rule parser, and AST definitions."""

import re
from dataclasses import dataclass, field
from typing import Optional

from tokenizer import CSSTokenizer


# ============================================================================
# Selector AST
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
    op: Optional[str] = None
    value: Optional[str] = None

@dataclass
class PseudoClassIs:
    selectors: list

@dataclass
class PseudoClassNot:
    selectors: list

@dataclass
class PseudoClassWhere:
    selectors: list

@dataclass
class PseudoClassHas:
    relative_selectors: list

@dataclass
class CompoundSelector:
    simple_selectors: list

@dataclass
class ComplexSelector:
    parts: list  # [(CompoundSelector, combinator_to_next), ...]

@dataclass
class RelativeSelector:
    combinator: Optional[str]
    complex_selector: ComplexSelector

@dataclass
class Declaration:
    property: str
    value: str
    important: bool = False

@dataclass
class CSSRule:
    selectors: list
    declarations: list
    source_order: int = 0


# ============================================================================
# Selector Parser
# ============================================================================

class SelectorParser:
    def __init__(self, text):
        self.tok = CSSTokenizer(text.strip())

    def parse_selector_list(self):
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
        self.tok.skip_ws()
        compound = self.parse_compound_selector()
        if not compound:
            return None
        parts = [(compound, None)]

        while not self.tok.at_end():
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
        self.tok.advance()
        name = self._read_ident()
        return IDSelector(id=name)

    def _parse_class(self):
        self.tok.advance()
        name = self._read_ident()
        return ClassSelector(cls=name)

    def _parse_attribute(self):
        self.tok.advance()
        self.tok.skip_ws()
        attr_name = self._read_ident()
        self.tok.skip_ws()
        op = None
        value = None
        if not self.tok.at_end() and self.tok.peek() != "]":
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
        self.tok.advance()
        start = self.tok.pos
        while not self.tok.at_end() and self.tok.peek() != quote:
            if self.tok.peek() == "\\":
                self.tok.advance()
            self.tok.advance()
        result = self.tok.text[start:self.tok.pos]
        if not self.tok.at_end():
            self.tok.advance()
        return result

    def _parse_pseudo_class(self):
        self.tok.advance()
        if self.tok.at_end():
            return None
        if self.tok.peek() == ":":
            self.tok.advance()
            self._read_ident()
            return None

        name = self._read_ident()
        name_lower = name.lower()

        if not self.tok.at_end() and self.tok.peek() == "(":
            self.tok.advance()
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
                self._skip_until_close_paren()
                return None
            else:
                self._skip_until_close_paren()
                return None
        return None

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
        self.tok.skip_ws()
        selectors = []
        sel = self.parse_complex_selector()
        if sel:
            selectors.append(sel)
        while not self.tok.at_end() and self.tok.peek() != ")":
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

    def _parse_has_args(self):
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
# CSS Rule Parser
# ============================================================================

def parse_css(text):
    rules = []
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    pos = 0
    order = 0
    while pos < len(text):
        brace_start = text.find("{", pos)
        if brace_start == -1:
            break
        selector_text = text[pos:brace_start].strip()

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
