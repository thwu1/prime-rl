#!/usr/bin/env python3

"""
SNOMED CT Expression Constraint Language (ECL) evaluator.

Reads from a SQLite database (built by load-rf2), parses ECL brief syntax,
and evaluates queries returning matching concept IDs.
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from typing import Optional


# ─── RF2 Data Loading from SQLite ──────────────────────────────────────────

ISA_TYPE_ID = "116680003"
SYNONYM_TYPE_ID = "900000000000013009"


class Ontology:
    """In-memory SNOMED CT ontology loaded from a SQLite database."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.active_concepts: set[int] = set()
        self.children: dict[int, set[int]] = defaultdict(set)
        self.parents: dict[int, set[int]] = defaultdict(set)
        self.source_rels: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        self.dest_rels: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        self.refset_members: dict[int, set[int]] = defaultdict(set)
        self.preferred_terms: dict[int, str] = {}
        self.descendants_cache: dict[int, set[int]] = {}
        self.ancestors_cache: dict[int, set[int]] = {}

        self._load_concepts()
        self._load_hierarchy()
        self._load_non_isa_rels()
        self._load_refsets()
        self._load_descriptions()

    def _load_concepts(self):
        cursor = self.conn.execute(
            "SELECT id FROM concepts WHERE active = 1 AND verhoeff_valid = 1"
        )
        self.active_concepts = {int(row[0]) for row in cursor}

    def _load_hierarchy(self):
        cursor = self.conn.execute(
            "SELECT sourceId, destinationId FROM relationships "
            "WHERE typeId = ? AND active = 1", (ISA_TYPE_ID,)
        )
        for src_str, dst_str in cursor:
            src, dst = int(src_str), int(dst_str)
            if src in self.active_concepts and dst in self.active_concepts:
                self.children[dst].add(src)
                self.parents[src].add(dst)

    def _load_non_isa_rels(self):
        cursor = self.conn.execute(
            "SELECT sourceId, destinationId, typeId, relationshipGroup "
            "FROM relationships WHERE active = 1 AND typeId != ?", (ISA_TYPE_ID,)
        )
        for src_str, dst_str, type_str, grp in cursor:
            src, dst, tid = int(src_str), int(dst_str), int(type_str)
            grp_int = int(grp)
            if src in self.active_concepts and dst in self.active_concepts:
                self.source_rels[src].append((tid, dst, grp_int))
                self.dest_rels[dst].append((tid, src, grp_int))

    def _load_refsets(self):
        cursor = self.conn.execute(
            "SELECT refsetId, referencedComponentId FROM refset_members WHERE active = 1"
        )
        for refset_str, comp_str in cursor:
            comp_id = int(comp_str)
            if comp_id in self.active_concepts:
                self.refset_members[int(refset_str)].add(comp_id)

    def _load_descriptions(self):
        cursor = self.conn.execute(
            "SELECT conceptId, term FROM descriptions "
            "WHERE active = 1 AND typeId = ?", (SYNONYM_TYPE_ID,)
        )
        for cid_str, term in cursor:
            cid = int(cid_str)
            if cid in self.active_concepts:
                self.preferred_terms[cid] = term

    def get_descendants(self, concept_id: int) -> set[int]:
        if concept_id in self.descendants_cache:
            return self.descendants_cache[concept_id]
        cursor = self.conn.execute(
            "SELECT descendant FROM transitive_closure WHERE ancestor = ?",
            (str(concept_id),)
        )
        result = {int(row[0]) for row in cursor} & self.active_concepts
        self.descendants_cache[concept_id] = result
        return result

    def get_ancestors(self, concept_id: int) -> set[int]:
        if concept_id in self.ancestors_cache:
            return self.ancestors_cache[concept_id]
        cursor = self.conn.execute(
            "SELECT ancestor FROM transitive_closure WHERE descendant = ?",
            (str(concept_id),)
        )
        result = {int(row[0]) for row in cursor} & self.active_concepts
        self.ancestors_cache[concept_id] = result
        return result

    def get_children(self, concept_id: int) -> set[int]:
        return self.children.get(concept_id, set()).copy()

    def get_parents(self, concept_id: int) -> set[int]:
        return self.parents.get(concept_id, set()).copy()


# ─── ECL Parser ─────────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


class Token:
    def __init__(self, kind: str, value: str, pos: int):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, {self.pos})"


class Lexer:
    """Tokenize an ECL expression (brief syntax)."""

    KEYWORDS = {"AND", "OR", "MINUS", "R"}

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens: list[Token] = []
        self._tokenize()
        self.idx = 0

    def _tokenize(self):
        text = self.text
        i = 0
        while i < len(text):
            if text[i] in " \t\n\r":
                i += 1
                continue

            # Three-char operators
            if i + 2 < len(text) and text[i:i+3] == "<<!":
                self.tokens.append(Token("CHILDORSELFOF", "<<!",  i))
                i += 3
                continue
            if i + 2 < len(text) and text[i:i+3] == ">>!":
                self.tokens.append(Token("PARENTORSELFOF", ">>!", i))
                i += 3
                continue

            # Two-char operators
            if i + 1 < len(text):
                two = text[i:i+2]
                if two == "<<":
                    self.tokens.append(Token("DESCENDANTORSELFOF", "<<", i)); i += 2; continue
                if two == ">>":
                    self.tokens.append(Token("ANCESTORORSELFOF", ">>", i)); i += 2; continue
                if two == "<!":
                    self.tokens.append(Token("CHILDOF", "<!", i)); i += 2; continue
                if two == ">!":
                    self.tokens.append(Token("PARENTOF", ">!", i)); i += 2; continue
                if two == "!=":
                    self.tokens.append(Token("NEQ", "!=", i)); i += 2; continue
                if two == "..":
                    self.tokens.append(Token("DOTDOT", "..", i)); i += 2; continue

            # Single-char
            ch = text[i]
            singles = {
                "<": "DESCENDANTOF", ">": "ANCESTOROF", "=": "EQ",
                "(": "LPAREN", ")": "RPAREN", "{": "LBRACE", "}": "RBRACE",
                "[": "LBRACKET", "]": "RBRACKET", ":": "COLON", ",": "COMMA",
                ".": "DOT", "^": "CARET", "*": "WILDCARD", "#": "HASH",
            }
            if ch in singles:
                self.tokens.append(Token(singles[ch], ch, i)); i += 1; continue

            # Pipe-delimited term
            if ch == "|":
                j = text.index("|", i + 1) + 1
                self.tokens.append(Token("TERM", text[i:j], i))
                i = j
                continue

            # Number (SCTID)
            if ch.isdigit():
                j = i
                while j < len(text) and text[j].isdigit():
                    j += 1
                self.tokens.append(Token("SCTID", text[i:j], i))
                i = j
                continue

            # Alpha keyword (case-insensitive)
            if ch.isalpha():
                j = i
                while j < len(text) and text[j].isalpha():
                    j += 1
                word = text[i:j]
                upper = word.upper()
                if upper in self.KEYWORDS:
                    self.tokens.append(Token(upper, word, i))
                else:
                    self.tokens.append(Token("WORD", word, i))
                i = j
                continue

            raise ParseError(f"Unexpected character {text[i]!r} at position {i}")

        self.tokens.append(Token("EOF", "", len(text)))

    def peek(self) -> Token:
        return self.tokens[self.idx]

    def advance(self) -> Token:
        tok = self.tokens[self.idx]
        self.idx += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.advance()
        if tok.kind != kind:
            raise ParseError(
                f"Expected {kind} at position {tok.pos}, got {tok.kind} ({tok.value!r})"
            )
        return tok

    def match(self, *kinds: str) -> Optional[Token]:
        if self.peek().kind in kinds:
            return self.advance()
        return None


# ─── AST Nodes ──────────────────────────────────────────────────────────────

class ASTNode:
    pass

class ConceptRef(ASTNode):
    def __init__(self, concept_id: int):
        self.concept_id = concept_id

class Wildcard(ASTNode):
    pass

class ConstraintOp(ASTNode):
    def __init__(self, op: str, operand: ASTNode):
        self.op = op
        self.operand = operand

class MemberOf(ASTNode):
    def __init__(self, operand: ASTNode):
        self.operand = operand

class Compound(ASTNode):
    def __init__(self, op: str, left: ASTNode, right: ASTNode):
        self.op = op
        self.left = left
        self.right = right

class Refinement(ASTNode):
    def __init__(self, focus: ASTNode, refinement):
        self.focus = focus
        self.refinement = refinement

class RefinementClause(ASTNode):
    def __init__(self, op: Optional[str], parts: list):
        self.op = op
        self.parts = parts

class AttributeGroup(ASTNode):
    def __init__(self, attr_set, cardinality=None):
        self.attr_set = attr_set
        self.cardinality = cardinality

class AttributeSet(ASTNode):
    def __init__(self, op: Optional[str], attrs: list):
        self.op = op
        self.attrs = attrs

class Attribute(ASTNode):
    def __init__(self, name: ASTNode, comp_op: str, value: ASTNode,
                 reverse: bool = False, cardinality=None):
        self.name = name
        self.comp_op = comp_op
        self.value = value
        self.reverse = reverse
        self.cardinality = cardinality

class DotExpr(ASTNode):
    def __init__(self, base: ASTNode, attrs: list[ASTNode]):
        self.base = base
        self.attrs = attrs


# ─── Parser ─────────────────────────────────────────────────────────────────

class Parser:
    def __init__(self, lexer: Lexer):
        self.lex = lexer

    def parse(self) -> ASTNode:
        node = self.parse_expression_constraint()
        if self.lex.peek().kind != "EOF":
            raise ParseError(
                f"Unexpected token {self.lex.peek().value!r} at position {self.lex.peek().pos}"
            )
        return node

    def parse_expression_constraint(self) -> ASTNode:
        left = self.parse_sub_expression_or_refined_or_dotted()
        while True:
            tok = self.lex.peek()
            if tok.kind in ("AND", "COMMA"):
                self.lex.advance()
                right = self.parse_sub_expression_or_refined_or_dotted()
                left = Compound("AND", left, right)
            elif tok.kind == "OR":
                self.lex.advance()
                right = self.parse_sub_expression_or_refined_or_dotted()
                left = Compound("OR", left, right)
            elif tok.kind == "MINUS":
                self.lex.advance()
                right = self.parse_sub_expression_or_refined_or_dotted()
                left = Compound("MINUS", left, right)
            else:
                break
        return left

    def parse_sub_expression_or_refined_or_dotted(self) -> ASTNode:
        node = self.parse_sub_expression()
        if self.lex.peek().kind == "COLON":
            self.lex.advance()
            ref = self.parse_refinement()
            node = Refinement(node, ref)
        while self.lex.peek().kind == "DOT":
            self.lex.advance()
            attr_name = self.parse_sub_expression()
            node = DotExpr(node, [attr_name])
        return node

    def parse_sub_expression(self) -> ASTNode:
        constraint_ops = {
            "CHILDORSELFOF", "PARENTORSELFOF",
            "DESCENDANTORSELFOF", "ANCESTORORSELFOF",
            "CHILDOF", "PARENTOF",
            "DESCENDANTOF", "ANCESTOROF",
        }
        tok = self.lex.peek()
        if tok.kind in constraint_ops:
            op_tok = self.lex.advance()
            if self.lex.peek().kind == "CARET":
                self.lex.advance()
                inner = self.parse_focus_concept_or_paren()
                inner = MemberOf(inner)
            else:
                inner = self.parse_focus_concept_or_paren()
            return ConstraintOp(op_tok.kind, inner)

        if tok.kind == "CARET":
            self.lex.advance()
            inner = self.parse_focus_concept_or_paren()
            return MemberOf(inner)

        return self.parse_focus_concept_or_paren()

    def parse_focus_concept_or_paren(self) -> ASTNode:
        tok = self.lex.peek()
        if tok.kind == "LPAREN":
            self.lex.advance()
            node = self.parse_expression_constraint()
            self.lex.expect("RPAREN")
            return node
        if tok.kind == "WILDCARD":
            self.lex.advance()
            return Wildcard()
        if tok.kind == "SCTID":
            sctid_tok = self.lex.advance()
            concept_id = int(sctid_tok.value)
            if self.lex.peek().kind == "TERM":
                self.lex.advance()
            return ConceptRef(concept_id)
        raise ParseError(
            f"Expected concept reference, wildcard, or '(' at position {tok.pos}, "
            f"got {tok.kind} ({tok.value!r})"
        )

    def parse_refinement(self) -> RefinementClause:
        parts = [self.parse_sub_refinement()]
        op = None
        while True:
            tok = self.lex.peek()
            if tok.kind in ("AND", "COMMA"):
                self.lex.advance()
                cur_op = "AND"
            elif tok.kind == "OR":
                self.lex.advance()
                cur_op = "OR"
            else:
                break
            if op is not None and op != cur_op:
                raise ParseError("Mixed AND/OR in refinement requires brackets")
            op = cur_op
            parts.append(self.parse_sub_refinement())
        return RefinementClause(op, parts)

    def parse_sub_refinement(self):
        tok = self.lex.peek()
        if tok.kind == "LBRACE":
            return self.parse_attribute_group()
        if tok.kind == "LBRACKET":
            next_tok = self._peek_past_cardinality()
            if next_tok and next_tok.kind == "LBRACE":
                return self.parse_attribute_group()
            return self.parse_attribute()
        if tok.kind == "LPAREN":
            self.lex.advance()
            ref = self.parse_refinement()
            self.lex.expect("RPAREN")
            return ref
        return self.parse_attribute()

    def _peek_past_cardinality(self) -> Optional[Token]:
        save = self.lex.idx
        try:
            self.lex.expect("LBRACKET")
            depth = 1
            while depth > 0:
                t = self.lex.advance()
                if t.kind == "LBRACKET":
                    depth += 1
                elif t.kind == "RBRACKET":
                    depth -= 1
                elif t.kind == "EOF":
                    return None
            return self.lex.peek()
        finally:
            self.lex.idx = save

    def parse_attribute_group(self):
        cardinality = None
        if self.lex.peek().kind == "LBRACKET":
            cardinality = self.parse_cardinality()
        self.lex.expect("LBRACE")
        attr_set = self.parse_attribute_set_inner()
        self.lex.expect("RBRACE")
        return AttributeGroup(attr_set, cardinality)

    def parse_attribute_set_inner(self) -> AttributeSet:
        attrs = [self.parse_attribute()]
        op = None
        while True:
            tok = self.lex.peek()
            if tok.kind in ("AND", "COMMA"):
                self.lex.advance()
                cur_op = "AND"
            elif tok.kind == "OR":
                self.lex.advance()
                cur_op = "OR"
            else:
                break
            if op is not None and op != cur_op:
                raise ParseError("Mixed AND/OR in attribute set requires brackets")
            op = cur_op
            attrs.append(self.parse_attribute())
        return AttributeSet(op, attrs)

    def parse_attribute(self) -> Attribute:
        cardinality = None
        reverse = False

        if self.lex.peek().kind == "LBRACKET":
            cardinality = self.parse_cardinality()

        if self.lex.peek().kind == "R":
            self.lex.advance()
            reverse = True

        name = self.parse_sub_expression()

        tok = self.lex.peek()
        if tok.kind == "EQ":
            self.lex.advance()
            comp_op = "="
        elif tok.kind == "NEQ":
            self.lex.advance()
            comp_op = "!="
        else:
            raise ParseError(
                f"Expected = or != at position {tok.pos}, got {tok.kind}"
            )

        value = self.parse_sub_expression()
        return Attribute(name, comp_op, value, reverse, cardinality)

    def parse_cardinality(self):
        self.lex.expect("LBRACKET")
        min_tok = self.lex.expect("SCTID")
        min_val = int(min_tok.value)
        self.lex.expect("DOTDOT")
        tok = self.lex.peek()
        if tok.kind == "WILDCARD":
            self.lex.advance()
            max_val = None
        else:
            max_tok = self.lex.expect("SCTID")
            max_val = int(max_tok.value)
        self.lex.expect("RBRACKET")
        return (min_val, max_val)


# ─── Evaluator ──────────────────────────────────────────────────────────────

class Evaluator:
    def __init__(self, ontology: Ontology):
        self.ont = ontology

    def evaluate(self, node: ASTNode) -> set[int]:
        if isinstance(node, ConceptRef):
            cid = node.concept_id
            if cid in self.ont.active_concepts:
                return {cid}
            return set()

        elif isinstance(node, Wildcard):
            return self.ont.active_concepts.copy()

        elif isinstance(node, ConstraintOp):
            inner = self.evaluate(node.operand)
            return self._apply_constraint(node.op, inner)

        elif isinstance(node, MemberOf):
            refset_ids = self.evaluate(node.operand)
            result = set()
            for rid in refset_ids:
                members = self.ont.refset_members.get(rid, set())
                result |= members
            return result & self.ont.active_concepts

        elif isinstance(node, Compound):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)
            if node.op == "AND":
                return left & right
            elif node.op == "OR":
                return left | right
            elif node.op == "MINUS":
                return left - right

        elif isinstance(node, Refinement):
            focus = self.evaluate(node.focus)
            return self._apply_refinement(focus, node.refinement)

        elif isinstance(node, DotExpr):
            base = self.evaluate(node.base)
            result = base
            for attr_node in node.attrs:
                attr_ids = self.evaluate(attr_node)
                result = self._dot_values(result, attr_ids)
            return result

        raise ParseError(f"Unknown AST node: {type(node)}")

    def _apply_constraint(self, op: str, concepts: set[int]) -> set[int]:
        result = set()
        for cid in concepts:
            if op == "DESCENDANTOF":
                result |= self.ont.get_descendants(cid)
            elif op == "DESCENDANTORSELFOF":
                result |= self.ont.get_descendants(cid) | {cid}
            elif op == "ANCESTOROF":
                result |= self.ont.get_ancestors(cid)
            elif op == "ANCESTORORSELFOF":
                result |= self.ont.get_ancestors(cid) | {cid}
            elif op == "CHILDOF":
                result |= self.ont.get_children(cid)
            elif op == "PARENTOF":
                result |= self.ont.get_parents(cid)
            elif op == "CHILDORSELFOF":
                result |= self.ont.get_children(cid) | {cid}
            elif op == "PARENTORSELFOF":
                result |= self.ont.get_parents(cid) | {cid}
        return result & self.ont.active_concepts

    def _apply_refinement(self, focus: set[int], ref_clause) -> set[int]:
        if isinstance(ref_clause, RefinementClause):
            if ref_clause.op is None or len(ref_clause.parts) == 1:
                return self._apply_sub_refinement(focus, ref_clause.parts[0])
            elif ref_clause.op == "AND":
                result = focus
                for part in ref_clause.parts:
                    result = self._apply_sub_refinement(result, part)
                return result
            elif ref_clause.op == "OR":
                result = set()
                for part in ref_clause.parts:
                    result |= self._apply_sub_refinement(focus, part)
                return result
        return self._apply_sub_refinement(focus, ref_clause)

    def _apply_sub_refinement(self, focus: set[int], sub) -> set[int]:
        if isinstance(sub, AttributeGroup):
            return self._apply_grouped(focus, sub)
        elif isinstance(sub, AttributeSet):
            return self._apply_attribute_set(focus, sub)
        elif isinstance(sub, Attribute):
            return self._apply_single_attribute(focus, sub)
        elif isinstance(sub, RefinementClause):
            return self._apply_refinement(focus, sub)
        return focus

    def _apply_grouped(self, focus: set[int], group: AttributeGroup) -> set[int]:
        attr_set = group.attr_set
        cardinality = group.cardinality or (1, None)
        min_card, max_card = cardinality

        attrs = attr_set.attrs if isinstance(attr_set, AttributeSet) else [attr_set]
        conj = attr_set.op if isinstance(attr_set, AttributeSet) else None

        result = set()
        for concept_id in focus:
            rels = self.ont.source_rels.get(concept_id, [])
            groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
            for type_id, dest_id, grp in rels:
                if grp > 0:
                    groups[grp].append((type_id, dest_id))

            matching_groups = 0
            for grp_num, grp_rels in groups.items():
                if conj == "OR":
                    if any(self._check_attr_in_group(attr, grp_rels) for attr in attrs):
                        matching_groups += 1
                else:
                    if all(self._check_attr_in_group(attr, grp_rels) for attr in attrs):
                        matching_groups += 1

            if matching_groups >= min_card and (max_card is None or matching_groups <= max_card):
                result.add(concept_id)
        return result

    def _check_attr_in_group(self, attr: Attribute, grp_rels: list[tuple[int, int]]) -> bool:
        name_ids = self.evaluate(attr.name)
        value_ids = self.evaluate(attr.value)
        for type_id, dest_id in grp_rels:
            if type_id not in name_ids:
                continue
            if attr.comp_op == "=":
                if dest_id in value_ids:
                    return True
            elif attr.comp_op == "!=":
                if dest_id not in value_ids:
                    return True
        return False

    def _apply_attribute_set(self, focus: set[int], attr_set: AttributeSet) -> set[int]:
        if attr_set.op == "OR":
            result = set()
            for attr in attr_set.attrs:
                result |= self._apply_sub_refinement(focus, attr)
            return result
        else:
            result = focus
            for attr in attr_set.attrs:
                result = self._apply_sub_refinement(result, attr)
            return result

    def _apply_single_attribute(self, focus: set[int], attr: Attribute) -> set[int]:
        name_ids = self.evaluate(attr.name)
        value_ids = self.evaluate(attr.value)
        cardinality = attr.cardinality or (1, None)
        min_card, max_card = cardinality

        result = set()
        for concept_id in focus:
            if attr.reverse:
                count = self._check_reverse_attr(concept_id, name_ids, value_ids, attr.comp_op)
            else:
                count = self._check_attr(concept_id, name_ids, value_ids, attr.comp_op)
            if count >= min_card and (max_card is None or count <= max_card):
                result.add(concept_id)
        return result

    def _check_attr(self, concept_id: int, name_ids: set[int],
                    value_ids: set[int], comp_op: str) -> int:
        rels = self.ont.source_rels.get(concept_id, [])
        count = 0
        for type_id, dest_id, grp in rels:
            if type_id not in name_ids:
                continue
            if comp_op == "=":
                if dest_id in value_ids:
                    count += 1
            elif comp_op == "!=":
                if dest_id not in value_ids:
                    count += 1
        return count

    def _check_reverse_attr(self, concept_id: int, name_ids: set[int],
                            value_ids: set[int], comp_op: str) -> int:
        rels = self.ont.dest_rels.get(concept_id, [])
        count = 0
        for type_id, src_id, grp in rels:
            if type_id not in name_ids:
                continue
            if comp_op == "=":
                if src_id in value_ids:
                    count += 1
            elif comp_op == "!=":
                if src_id not in value_ids:
                    count += 1
        return count

    def _dot_values(self, concepts: set[int], attr_ids: set[int]) -> set[int]:
        result = set()
        for concept_id in concepts:
            rels = self.ont.source_rels.get(concept_id, [])
            for type_id, dest_id, grp in rels:
                if type_id in attr_ids:
                    result.add(dest_id)
        return result & self.ont.active_concepts


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    json_mode = False

    if not args:
        print("Usage: ecl-eval [--json] <ecl-expression>", file=sys.stderr)
        sys.exit(1)

    if args[0] == "--json":
        json_mode = True
        args = args[1:]

    if not args:
        print("Usage: ecl-eval [--json] <ecl-expression>", file=sys.stderr)
        sys.exit(1)

    ecl_expr = args[0]
    db_path = os.environ.get("ECL_DB_PATH", "/app/snomed.db")

    try:
        ontology = Ontology(db_path)
    except Exception as e:
        print(f"Error loading database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        lexer = Lexer(ecl_expr)
        parser = Parser(lexer)
        ast = parser.parse()
    except ParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        sys.exit(1)

    evaluator = Evaluator(ontology)
    try:
        result = evaluator.evaluate(ast)
    except Exception as e:
        print(f"Evaluation error: {e}", file=sys.stderr)
        sys.exit(1)

    sorted_ids = sorted(result)

    if json_mode:
        expansion = []
        for cid in sorted_ids:
            term = ontology.preferred_terms.get(cid, "")
            expansion.append({"conceptId": str(cid), "display": term})
        output = {"total": len(sorted_ids), "expansion": expansion}
        print(json.dumps(output))
    else:
        for concept_id in sorted_ids:
            print(concept_id)


if __name__ == "__main__":
    main()
