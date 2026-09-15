#!/usr/bin/env python3

"""
RoboCup Standard Coach Language (CLang) Parser and Tactical Analyzer.
Parses CLang messages, tracks entity state, and performs tactical analysis.
"""

import sys
import json
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# TOKENIZER
# ============================================================

class TokenType:
    LPAREN = 'LPAREN'
    RPAREN = 'RPAREN'
    LBRACE = 'LBRACE'
    RBRACE = 'RBRACE'
    STRING = 'STRING'
    NUMBER = 'NUMBER'
    IDENT = 'IDENT'

@dataclass
class Token:
    type: str
    value: Any

def tokenize(text: str) -> list:
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == '(':
            tokens.append(Token(TokenType.LPAREN, '('))
            i += 1
        elif c == ')':
            tokens.append(Token(TokenType.RPAREN, ')'))
            i += 1
        elif c == '{':
            tokens.append(Token(TokenType.LBRACE, '{'))
            i += 1
        elif c == '}':
            tokens.append(Token(TokenType.RBRACE, '}'))
            i += 1
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 1
            tokens.append(Token(TokenType.STRING, text[i+1:j]))
            i = j + 1
        elif c == '-' and i + 1 < n and (text[i+1].isdigit() or text[i+1] == '.'):
            if tokens and tokens[-1].type == TokenType.RPAREN:
                tokens.append(Token(TokenType.IDENT, '-'))
                i += 1
            else:
                j = i + 1
                has_dot = False
                while j < n and (text[j].isdigit() or (text[j] == '.' and not has_dot)):
                    if text[j] == '.':
                        has_dot = True
                    j += 1
                val_str = text[i:j]
                tokens.append(Token(TokenType.NUMBER, float(val_str) if '.' in val_str else int(val_str)))
                i = j
        elif c.isdigit() or (c == '.' and i + 1 < n and text[i+1].isdigit()):
            j = i
            has_dot = False
            while j < n and (text[j].isdigit() or (text[j] == '.' and not has_dot)):
                if text[j] == '.':
                    has_dot = True
                j += 1
            val_str = text[i:j]
            tokens.append(Token(TokenType.NUMBER, float(val_str) if '.' in val_str else int(val_str)))
            i = j
        else:
            if c in '+-*/':
                tokens.append(Token(TokenType.IDENT, c))
                i += 1
            elif c in '<>=!':
                j = i + 1
                if j < n and text[j] == '=':
                    tokens.append(Token(TokenType.IDENT, text[i:j+1]))
                    i = j + 1
                else:
                    tokens.append(Token(TokenType.IDENT, c))
                    i += 1
            else:
                j = i
                while j < n and not text[j].isspace() and text[j] not in '(){}\"':
                    j += 1
                tokens.append(Token(TokenType.IDENT, text[i:j]))
                i = j
    return tokens


# ============================================================
# AST NODES
# ============================================================

@dataclass
class ASTNode:
    node_type: str
    children: list = field(default_factory=list)
    attrs: dict = field(default_factory=dict)


# ============================================================
# PARSER
# ============================================================

class ParseError(Exception):
    pass

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, ttype, value=None):
        t = self.advance()
        if t.type != ttype:
            raise ParseError(f"Expected {ttype} but got {t.type} ({t.value})")
        if value is not None and t.value != value:
            raise ParseError(f"Expected value '{value}' but got '{t.value}'")
        return t

    def expect_lparen(self):
        return self.expect(TokenType.LPAREN)

    def expect_rparen(self):
        return self.expect(TokenType.RPAREN)

    def parse_message(self):
        self.expect_lparen()
        keyword = self.expect(TokenType.IDENT).value
        if keyword == 'define':
            result = self.parse_define_message()
        elif keyword == 'rule':
            result = self.parse_rule_message()
        elif keyword == 'delete':
            result = self.parse_delete_message()
        elif keyword == 'freeform':
            result = self.parse_freeform_message()
        else:
            raise ParseError(f"Unknown message type: {keyword}")
        self.expect_rparen()
        return result

    def parse_define_message(self):
        node = ASTNode('define_message')
        while self.peek() and self.peek().type == TokenType.LPAREN:
            node.children.append(self.parse_define_token())
        return node

    def parse_define_token(self):
        self.expect_lparen()
        keyword = self.expect(TokenType.IDENT).value
        if keyword == 'definec':
            name = self.expect(TokenType.STRING).value
            condition = self.parse_condition()
            self.expect_rparen()
            return ASTNode('definec', attrs={'name': name}, children=[condition])
        elif keyword == 'definea':
            name = self.expect(TokenType.STRING).value
            action = self.parse_action()
            self.expect_rparen()
            return ASTNode('definea', attrs={'name': name}, children=[action])
        elif keyword == 'definer':
            name = self.expect(TokenType.STRING).value
            region = self.parse_region()
            self.expect_rparen()
            return ASTNode('definer', attrs={'name': name}, children=[region])
        elif keyword == 'defined':
            name = self.expect(TokenType.STRING).value
            directive = self.parse_directive()
            self.expect_rparen()
            return ASTNode('defined', attrs={'name': name}, children=[directive])
        elif keyword == 'definerule':
            rule = self.parse_define_rule()
            self.expect_rparen()
            return rule
        else:
            raise ParseError(f"Unknown define token: {keyword}")

    def parse_define_rule(self):
        name = self.expect(TokenType.IDENT).value
        mode = self.expect(TokenType.IDENT).value
        rule_body = self.parse_rule_body()
        return ASTNode('definerule', attrs={'name': name, 'mode': mode}, children=[rule_body])

    def parse_rule_body(self):
        t = self.peek()
        if t.type == TokenType.LPAREN:
            self.expect_lparen()
            first = self.peek()
            if first and first.type == TokenType.IDENT:
                _reserved = {
                    'true', 'false', 'and', 'or', 'not', 'bpos', 'bowner',
                    'playm', 'ppos', 'unum', 'time', 'opp_goals', 'our_goals',
                    'goal_diff', 'do', 'dont'
                }
                if first.value not in _reserved:
                    probe = self.pos
                    names = []
                    ok = True
                    while self.peek() and self.peek().type != TokenType.RPAREN:
                        if self.peek().type == TokenType.IDENT:
                            names.append(self.advance().value)
                        else:
                            ok = False
                            break
                    if ok and names:
                        self.expect_rparen()
                        return ASTNode('rule_body_idlist', attrs={'names': names})
                    self.pos = probe
            inner = self.parse_condition()
            items = []
            while self.peek() and self.peek().type != TokenType.RPAREN:
                pt = self.peek()
                if pt.type == TokenType.LPAREN:
                    saved = self.pos
                    self.expect_lparen()
                    kw = self.peek()
                    self.pos = saved
                    if kw and kw.type == TokenType.IDENT and kw.value in ('do', 'dont'):
                        items.append(('directive', self.parse_directive()))
                    else:
                        items.append(('rule', self.parse_rule_body()))
                elif pt.type == TokenType.STRING:
                    items.append(('directive', self.parse_directive()))
                elif pt.type == TokenType.IDENT:
                    items.append(('rule_ref', self.advance().value))
                else:
                    break
            self.expect_rparen()
            has_directives = any(t[0] == 'directive' for t in items)
            has_rules = any(t[0] in ('rule', 'rule_ref') for t in items)
            if has_rules and not has_directives:
                rule_refs = []
                for item_type, item_val in items:
                    if item_type == 'rule_ref':
                        rule_refs.append(ASTNode('rule_ref', attrs={'name': item_val}))
                    else:
                        rule_refs.append(item_val)
                return ASTNode('rule_body_nested', children=[inner] + rule_refs)
            else:
                directives = [v for t, v in items if t == 'directive']
                return ASTNode('rule_body_directives', children=[inner] + directives)
        elif t.type == TokenType.IDENT:
            names = []
            while self.peek() and self.peek().type == TokenType.IDENT:
                names.append(self.advance().value)
            return ASTNode('rule_body_idlist', attrs={'names': names})
        else:
            raise ParseError(f"Unexpected token in rule body: {t}")

    def parse_condition(self):
        t = self.peek()
        if t.type == TokenType.STRING:
            name = self.advance().value
            return ASTNode('condition_ref', attrs={'name': name})
        elif t.type == TokenType.LPAREN:
            self.expect_lparen()
            kw = self.peek()
            if kw.type == TokenType.IDENT:
                keyword = kw.value
                if keyword == 'true':
                    self.advance()
                    self.expect_rparen()
                    return ASTNode('condition_true')
                elif keyword == 'false':
                    self.advance()
                    self.expect_rparen()
                    return ASTNode('condition_false')
                elif keyword == 'and':
                    self.advance()
                    children = []
                    while self.peek() and self.peek().type != TokenType.RPAREN:
                        children.append(self.parse_condition())
                    self.expect_rparen()
                    return ASTNode('condition_and', children=children)
                elif keyword == 'or':
                    self.advance()
                    children = []
                    while self.peek() and self.peek().type != TokenType.RPAREN:
                        children.append(self.parse_condition())
                    self.expect_rparen()
                    return ASTNode('condition_or', children=children)
                elif keyword == 'not':
                    self.advance()
                    child = self.parse_condition()
                    self.expect_rparen()
                    return ASTNode('condition_not', children=[child])
                elif keyword == 'bpos':
                    self.advance()
                    region = self.parse_region()
                    self.expect_rparen()
                    return ASTNode('condition_bpos', children=[region])
                elif keyword == 'bowner':
                    self.advance()
                    team = self.expect(TokenType.IDENT).value
                    unum_set = self.parse_unum_set()
                    self.expect_rparen()
                    return ASTNode('condition_bowner', attrs={'team': team, 'players': unum_set})
                elif keyword == 'playm':
                    self.advance()
                    mode = self.expect(TokenType.IDENT).value
                    self.expect_rparen()
                    return ASTNode('condition_playm', attrs={'mode': mode})
                elif keyword == 'ppos':
                    self.advance()
                    team = self.expect(TokenType.IDENT).value
                    unum_set = self.parse_unum_set()
                    min_val = self.advance().value
                    max_val = self.advance().value
                    region = self.parse_region()
                    self.expect_rparen()
                    return ASTNode('condition_ppos', attrs={'team': team, 'players': unum_set, 'min': min_val, 'max': max_val}, children=[region])
                elif keyword == 'unum':
                    self.advance()
                    var = self.advance().value
                    unum_set = self.parse_unum_set()
                    self.expect_rparen()
                    return ASTNode('condition_unum', attrs={'var': var, 'players': unum_set})
                elif keyword in ('time', 'opp_goals', 'our_goals', 'goal_diff'):
                    self.advance()
                    comp = self.advance().value
                    val = self.advance().value
                    self.expect_rparen()
                    return ASTNode('condition_comp', attrs={'lhs': keyword, 'op': comp, 'rhs': val})
            if kw.type == TokenType.NUMBER:
                val = self.advance().value
                comp = self.advance().value
                keyword = self.advance().value
                self.expect_rparen()
                return ASTNode('condition_comp', attrs={'lhs': keyword, 'op': self._flip_comp(comp), 'rhs': val})
            depth = 1
            while depth > 0 and self.pos < len(self.tokens):
                t = self.advance()
                if t.type == TokenType.LPAREN:
                    depth += 1
                elif t.type == TokenType.RPAREN:
                    depth -= 1
            return ASTNode('condition_unknown')
        else:
            raise ParseError(f"Unexpected token in condition: {t}")

    def _flip_comp(self, op):
        flips = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
        return flips.get(op, op)

    def parse_action(self):
        t = self.peek()
        if t.type == TokenType.STRING:
            name = self.advance().value
            return ASTNode('action_ref', attrs={'name': name})
        elif t.type == TokenType.LPAREN:
            self.expect_lparen()
            keyword = self.expect(TokenType.IDENT).value
            if keyword in ('shoot', 'hold', 'intercept'):
                self.expect_rparen()
                return ASTNode('action', attrs={'type': keyword})
            elif keyword in ('pass', 'mark', 'markl', 'tackle'):
                if self.peek().type == TokenType.LBRACE:
                    unum_set = self.parse_unum_set()
                    self.expect_rparen()
                    return ASTNode('action', attrs={'type': keyword, 'players': unum_set})
                else:
                    region = self.parse_region()
                    self.expect_rparen()
                    return ASTNode('action', attrs={'type': keyword}, children=[region])
            elif keyword in ('pos', 'home', 'dribble', 'clear', 'oline'):
                region = self.parse_region()
                self.expect_rparen()
                return ASTNode('action', attrs={'type': keyword}, children=[region])
            elif keyword == 'htype':
                val = self.advance().value
                self.expect_rparen()
                return ASTNode('action', attrs={'type': keyword, 'value': val})
            else:
                depth = 1
                while depth > 0:
                    t = self.advance()
                    if t.type == TokenType.LPAREN:
                        depth += 1
                    elif t.type == TokenType.RPAREN:
                        depth -= 1
                return ASTNode('action', attrs={'type': keyword})
        else:
            raise ParseError(f"Unexpected token in action: {t}")

    def parse_directive(self):
        t = self.peek()
        if t.type == TokenType.STRING:
            name = self.advance().value
            return ASTNode('directive_ref', attrs={'name': name})
        elif t.type == TokenType.LPAREN:
            self.expect_lparen()
            mode = self.expect(TokenType.IDENT).value
            team = self.expect(TokenType.IDENT).value
            unum_set = self.parse_unum_set()
            actions = []
            while self.peek() and self.peek().type != TokenType.RPAREN:
                actions.append(self.parse_action())
            self.expect_rparen()
            return ASTNode('directive', attrs={'mode': mode, 'team': team, 'players': unum_set}, children=actions)
        else:
            raise ParseError(f"Unexpected token in directive: {t}")

    def parse_region(self):
        t = self.peek()
        if t.type == TokenType.STRING:
            name = self.advance().value
            return ASTNode('region_ref', attrs={'name': name})
        elif t.type == TokenType.LPAREN:
            self.expect_lparen()
            kw = self.peek()
            if kw.type == TokenType.IDENT:
                keyword = kw.value
                if keyword == 'null':
                    self.advance()
                    self.expect_rparen()
                    return ASTNode('region_null')
                elif keyword == 'rec':
                    self.advance()
                    p1 = self.parse_point()
                    p2 = self.parse_point()
                    self.expect_rparen()
                    return ASTNode('region_rec', children=[p1, p2])
                elif keyword == 'tri':
                    self.advance()
                    p1 = self.parse_point()
                    p2 = self.parse_point()
                    p3 = self.parse_point()
                    self.expect_rparen()
                    return ASTNode('region_tri', children=[p1, p2, p3])
                elif keyword == 'arc':
                    self.advance()
                    pt = self.parse_point()
                    r1 = self.advance().value
                    r2 = self.advance().value
                    a1 = self.advance().value
                    a2 = self.advance().value
                    self.expect_rparen()
                    return ASTNode('region_arc', attrs={'r_small': r1, 'r_large': r2, 'angle_begin': a1, 'angle_span': a2}, children=[pt])
                elif keyword == 'reg':
                    self.advance()
                    regions = []
                    while self.peek() and self.peek().type != TokenType.RPAREN:
                        regions.append(self.parse_region())
                    self.expect_rparen()
                    return ASTNode('region_union', children=regions)
                elif keyword == 'pt':
                    point = self.parse_point_inner()
                    self.expect_rparen()
                    return ASTNode('region_point', children=[point])
                else:
                    self.pos -= 1
                    point = self.parse_point_inner()
                    self.expect_rparen()
                    return ASTNode('region_point', children=[point])
            else:
                point = self.parse_point_inner()
                self.expect_rparen()
                return ASTNode('region_point', children=[point])
        else:
            raise ParseError(f"Unexpected token in region: {t}")

    def parse_point(self):
        self.expect_lparen()
        point = self.parse_point_inner()
        self.expect_rparen()
        return point

    def parse_point_inner(self):
        kw = self.peek()
        if kw.type == TokenType.IDENT and kw.value == 'pt':
            self.advance()
            t2 = self.peek()
            if t2.type == TokenType.IDENT and t2.value == 'ball':
                self.advance()
                return ASTNode('point_ball')
            elif t2.type == TokenType.IDENT and t2.value in ('our', 'opp'):
                team = self.advance().value
                unum = self.advance().value
                return ASTNode('point_player', attrs={'team': team, 'unum': unum})
            else:
                x = self.advance().value
                y = self.advance().value
                return ASTNode('point', attrs={'x': float(x), 'y': float(y)})
        else:
            p1 = self.parse_point()
            op = self.expect(TokenType.IDENT).value
            p2 = self.parse_point()
            return ASTNode('point_arith', attrs={'op': op}, children=[p1, p2])

    def parse_unum_set(self):
        self.expect(TokenType.LBRACE)
        players = []
        while self.peek() and self.peek().type != TokenType.RBRACE:
            t = self.advance()
            if t.type == TokenType.NUMBER:
                players.append(int(t.value))
            elif t.type == TokenType.IDENT:
                players.append(t.value)
            else:
                raise ParseError(f"Unexpected token in unum set: {t}")
        self.expect(TokenType.RBRACE)
        return players

    def parse_rule_message(self):
        node = ASTNode('rule_message')
        while self.peek() and self.peek().type == TokenType.LPAREN:
            self.expect_lparen()
            mode = self.expect(TokenType.IDENT).value
            names = []
            while self.peek() and self.peek().type != TokenType.RPAREN:
                t = self.peek()
                if t.type == TokenType.IDENT:
                    names.append(self.advance().value)
                elif t.type == TokenType.LPAREN:
                    self.expect_lparen()
                    while self.peek() and self.peek().type != TokenType.RPAREN:
                        names.append(self.expect(TokenType.IDENT).value)
                    self.expect_rparen()
                else:
                    break
            self.expect_rparen()
            node.children.append(ASTNode('activation', attrs={'mode': mode, 'names': names}))
        return node

    def parse_delete_message(self):
        names = []
        t = self.peek()
        if t.type == TokenType.IDENT:
            if t.value == 'all':
                self.advance()
                return ASTNode('delete_message', attrs={'names': ['__all__']})
            else:
                names.append(self.advance().value)
        elif t.type == TokenType.LPAREN:
            self.expect_lparen()
            while self.peek() and self.peek().type != TokenType.RPAREN:
                names.append(self.expect(TokenType.IDENT).value)
            self.expect_rparen()
        return ASTNode('delete_message', attrs={'names': names})

    def parse_freeform_message(self):
        msg = self.expect(TokenType.STRING).value
        return ASTNode('freeform_message', attrs={'message': msg})


# ============================================================
# ANALYZER
# ============================================================

class Analyzer:
    def __init__(self):
        self.conditions = {}
        self.actions = {}
        self.regions = {}
        self.directives_defs = {}
        self.rules = {}
        self.deleted = set()

    def process_file(self, filepath):
        with open(filepath) as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                tokens = tokenize(line)
                parser = Parser(tokens)
                msg = parser.parse_message()
                self.process_message(msg)
            except (ParseError, IndexError):
                pass

    def process_message(self, msg):
        if msg.node_type == 'define_message':
            for child in msg.children:
                self.process_define(child)
        elif msg.node_type == 'rule_message':
            for child in msg.children:
                mode = child.attrs['mode']
                for name in child.attrs['names']:
                    if name in self.rules and name not in self.deleted:
                        self.rules[name]['active'] = (mode == 'on')
        elif msg.node_type == 'delete_message':
            names = msg.attrs['names']
            if '__all__' in names:
                for name in list(self.rules.keys()):
                    self.deleted.add(name)
                    self.rules[name]['active'] = False
            else:
                for name in names:
                    self.deleted.add(name)
                    if name in self.rules:
                        self.rules[name]['active'] = False

    def process_define(self, node):
        if node.node_type == 'definec':
            self.conditions[node.attrs['name']] = node.children[0]
        elif node.node_type == 'definea':
            self.actions[node.attrs['name']] = node.children[0]
        elif node.node_type == 'definer':
            self.regions[node.attrs['name']] = node.children[0]
        elif node.node_type == 'defined':
            self.directives_defs[node.attrs['name']] = node.children[0]
        elif node.node_type == 'definerule':
            name = node.attrs['name']
            mode = node.attrs['mode']
            body = node.children[0]
            self.rules[name] = {
                'mode': mode,
                'body': body,
                'active': False,
            }

    def get_active_rules(self):
        return sorted([n for n, r in self.rules.items() if r['active'] and n not in self.deleted])

    def get_dependencies(self, rule_name):
        if rule_name not in self.rules:
            return []
        body = self.rules[rule_name]['body']
        deps = set()
        self._collect_deps(body, deps)
        return sorted(deps)

    def _collect_deps(self, node, deps):
        if node is None:
            return
        if node.node_type == 'condition_ref':
            deps.add(node.attrs['name'])
        elif node.node_type == 'action_ref':
            deps.add(node.attrs['name'])
        elif node.node_type == 'region_ref':
            deps.add(node.attrs['name'])
        elif node.node_type == 'directive_ref':
            deps.add(node.attrs['name'])
        elif node.node_type == 'rule_ref':
            deps.add(node.attrs['name'])
        elif node.node_type == 'rule_body_idlist':
            for name in node.attrs.get('names', []):
                deps.add(name)
        for child in node.children:
            if isinstance(child, ASTNode):
                self._collect_deps(child, deps)

    def get_player_coverage(self):
        coverage = {}
        active = self.get_active_rules()
        for rule_name in active:
            players = self._extract_players_from_rule(rule_name)
            for p in players:
                key = str(p)
                if key not in coverage:
                    coverage[key] = []
                if rule_name not in coverage[key]:
                    coverage[key].append(rule_name)
        for key in coverage:
            coverage[key] = sorted(coverage[key])
        return coverage

    def _extract_players_from_rule(self, rule_name):
        if rule_name not in self.rules:
            return set()
        body = self.rules[rule_name]['body']
        players = set()
        self._collect_players(body, players)
        return players

    def _collect_players(self, node, players):
        if node is None:
            return
        if node.node_type == 'directive':
            raw_players = node.attrs.get('players', [])
            resolved = self._resolve_unum_set(raw_players)
            players.update(resolved)
        elif node.node_type == 'rule_body_nested':
            for child in node.children[1:]:
                if isinstance(child, ASTNode):
                    if child.node_type == 'rule_ref':
                        ref_name = child.attrs['name']
                        sub_players = self._extract_players_from_rule(ref_name)
                        players.update(sub_players)
                    else:
                        self._collect_players(child, players)
        elif node.node_type == 'rule_body_idlist':
            for name in node.attrs.get('names', []):
                sub_players = self._extract_players_from_rule(name)
                players.update(sub_players)
        else:
            for child in node.children:
                if isinstance(child, ASTNode):
                    self._collect_players(child, players)

    def _resolve_unum_set(self, unum_set):
        result = set()
        for u in unum_set:
            if isinstance(u, int):
                if u == 0:
                    result.update(range(1, 12))
                else:
                    result.add(u)
        return result

    def expand_nested_rules(self):
        result = {}
        active = self.get_active_rules()
        for rule_name in active:
            body = self.rules[rule_name]['body']
            if body.node_type == 'rule_body_nested' or body.node_type == 'rule_body_idlist':
                clauses = self._expand_rule(body, None)
                if clauses:
                    result[rule_name] = {
                        'num_clauses': len(clauses),
                        'clauses': clauses
                    }
        return result

    def _expand_rule(self, body, outer_condition):
        clauses = []
        if body.node_type == 'rule_body_directives':
            condition = body.children[0] if body.children else None
            directives = []
            for child in body.children[1:]:
                if isinstance(child, ASTNode) and child.node_type == 'directive':
                    d = self._format_directive(child)
                    if d:
                        directives.append(d)
            clauses.append({'directives': directives})
        elif body.node_type == 'rule_body_nested':
            condition = body.children[0] if body.children else None
            if outer_condition and condition:
                combined = ASTNode('condition_and', children=[outer_condition, condition])
            elif outer_condition:
                combined = outer_condition
            else:
                combined = condition
            for child in body.children[1:]:
                if isinstance(child, ASTNode):
                    if child.node_type == 'rule_ref':
                        ref_name = child.attrs['name']
                        if ref_name in self.rules and ref_name not in self.deleted:
                            sub_body = self.rules[ref_name]['body']
                            sub_clauses = self._expand_rule(sub_body, combined)
                            clauses.extend(sub_clauses)
                    else:
                        sub_clauses = self._expand_rule(child, combined)
                        clauses.extend(sub_clauses)
        elif body.node_type == 'rule_body_idlist':
            for name in body.attrs.get('names', []):
                if name in self.rules and name not in self.deleted:
                    sub_body = self.rules[name]['body']
                    sub_clauses = self._expand_rule(sub_body, outer_condition)
                    clauses.extend(sub_clauses)
        return clauses

    def _format_directive(self, node):
        if node.node_type != 'directive':
            return None
        team = node.attrs.get('team', 'our')
        raw_players = node.attrs.get('players', [])
        players = sorted(self._resolve_unum_set(raw_players))
        actions = []
        for child in node.children:
            if isinstance(child, ASTNode):
                if child.node_type == 'action_ref':
                    ref_name = child.attrs['name']
                    if ref_name in self.actions:
                        action_type = self.actions[ref_name].attrs.get('type', ref_name)
                    else:
                        action_type = ref_name
                else:
                    action_type = child.attrs.get('type', 'unknown')
                actions.append(action_type)
        return {'team': team, 'players': players, 'actions': sorted(actions)}

    def find_conflicts(self):
        active = self.get_active_rules()
        conflicts = []
        rule_info = {}
        for name in active:
            condition = self._extract_top_condition(name)
            player_actions = self._extract_player_actions(name)
            rule_info[name] = {'condition': condition, 'player_actions': player_actions}
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                r1, r2 = active[i], active[j]
                info1 = rule_info[r1]
                info2 = rule_info[r2]
                if self._are_mutually_exclusive(info1['condition'], info2['condition']):
                    continue
                pa1 = info1['player_actions']
                pa2 = info2['player_actions']
                has_conflict = False
                for player in pa1:
                    if player in pa2:
                        if pa1[player] != pa2[player]:
                            has_conflict = True
                            break
                if has_conflict:
                    conflicts.append([r1, r2])
        return sorted(conflicts)

    def _extract_top_condition(self, rule_name):
        body = self.rules[rule_name]['body']
        if body.node_type in ('rule_body_directives', 'rule_body_nested'):
            return body.children[0] if body.children else None
        return None

    def _extract_player_actions(self, rule_name):
        body = self.rules[rule_name]['body']
        result = {}
        self._collect_player_actions(body, result, rule_name)
        return result

    def _collect_player_actions(self, node, result, rule_name):
        if node is None:
            return
        if node.node_type == 'directive':
            raw_players = node.attrs.get('players', [])
            resolved = self._resolve_unum_set(raw_players)
            for child in node.children:
                if isinstance(child, ASTNode):
                    if child.node_type == 'action_ref':
                        ref_name = child.attrs['name']
                        if ref_name in self.actions:
                            action_type = self.actions[ref_name].attrs.get('type', ref_name)
                        else:
                            action_type = ref_name
                    else:
                        action_type = child.attrs.get('type', 'unknown')
                    for p in resolved:
                        if p not in result:
                            result[p] = set()
                        result[p].add(action_type)
        elif node.node_type == 'rule_body_nested':
            for child in node.children[1:]:
                if isinstance(child, ASTNode):
                    if child.node_type == 'rule_ref':
                        ref_name = child.attrs['name']
                        if ref_name in self.rules and ref_name not in self.deleted:
                            sub_body = self.rules[ref_name]['body']
                            self._collect_player_actions(sub_body, result, ref_name)
                    else:
                        self._collect_player_actions(child, result, rule_name)
        elif node.node_type == 'rule_body_idlist':
            for name in node.attrs.get('names', []):
                if name in self.rules and name not in self.deleted:
                    sub_body = self.rules[name]['body']
                    self._collect_player_actions(sub_body, result, name)
        else:
            for child in node.children:
                if isinstance(child, ASTNode):
                    self._collect_player_actions(child, result, rule_name)

    def _are_mutually_exclusive(self, cond1, cond2):
        if cond1 is None or cond2 is None:
            return False
        atoms1 = []
        self._extract_atomic_conditions(cond1, atoms1, negated=False)
        atoms2 = []
        self._extract_atomic_conditions(cond2, atoms2, negated=False)
        for a1, neg1 in atoms1:
            for a2, neg2 in atoms2:
                if self._atoms_mutually_exclusive(a1, neg1, a2, neg2):
                    return True
        return False

    def _extract_atomic_conditions(self, cond, atoms, negated):
        if cond.node_type == 'condition_and':
            for child in cond.children:
                self._extract_atomic_conditions(child, atoms, negated)
        elif cond.node_type == 'condition_not':
            if cond.children:
                self._extract_atomic_conditions(cond.children[0], atoms, not negated)
        elif cond.node_type == 'condition_ref':
            name = cond.attrs['name']
            if name in self.conditions:
                self._extract_atomic_conditions(self.conditions[name], atoms, negated)
        elif cond.node_type == 'condition_or':
            pass
        else:
            atoms.append((cond, negated))

    def _atoms_mutually_exclusive(self, a1, neg1, a2, neg2):
        if neg1 or neg2:
            return False
        if a1.node_type == 'condition_bowner' and a2.node_type == 'condition_bowner':
            team1 = a1.attrs['team']
            team2 = a2.attrs['team']
            if team1 != team2:
                return True
            players1 = a1.attrs.get('players', [])
            players2 = a2.attrs.get('players', [])
            set1 = self._resolve_unum_set(players1)
            set2 = self._resolve_unum_set(players2)
            has_wildcard1 = 0 in players1 or set1 == set(range(1, 12))
            has_wildcard2 = 0 in players2 or set2 == set(range(1, 12))
            if not has_wildcard1 and not has_wildcard2:
                if set1.isdisjoint(set2):
                    return True
        if a1.node_type == 'condition_playm' and a2.node_type == 'condition_playm':
            if a1.attrs['mode'] != a2.attrs['mode']:
                return True
        return False

    def analyze(self):
        result = {
            'defined_conditions': sorted([n for n in self.conditions if n not in self.deleted]),
            'defined_actions': sorted([n for n in self.actions if n not in self.deleted]),
            'defined_regions': sorted([n for n in self.regions if n not in self.deleted]),
            'defined_directives': sorted([n for n in self.directives_defs if n not in self.deleted]),
            'active_rules': self.get_active_rules(),
            'deleted_entities': sorted(self.deleted),
            'dependencies': {},
            'conflicts': self.find_conflicts(),
            'player_coverage': self.get_player_coverage(),
            'expanded_rules': self.expand_nested_rules(),
        }
        for rule_name in self.rules:
            if rule_name not in self.deleted:
                result['dependencies'][rule_name] = self.get_dependencies(rule_name)
        return result


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 clang_analyzer.py <scenario_file>", file=sys.stderr)
        sys.exit(1)
    filepath = sys.argv[1]
    analyzer = Analyzer()
    analyzer.process_file(filepath)
    output = analyzer.analyze()
    print(json.dumps(output, indent=2, sort_keys=False))

if __name__ == '__main__':
    main()
