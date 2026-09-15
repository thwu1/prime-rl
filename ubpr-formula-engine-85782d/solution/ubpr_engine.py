#!/usr/bin/env python3
"""
UBPR Formula Computation Engine - Reference Solution

Parses CDR expression language formulas, ingests multi-format Call Report data
(JSON + XBRL/XML), resolves dependency graphs, evaluates multi-period averaging
functions, computes bank performance ratios, and writes a SQLite audit database
with evaluations, dependencies, and analytical views.

"""

import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date
from collections import defaultdict

# ─── Date utilities ──────────────────────────────────────────────────────────

def parse_date(s):
    """Parse 'YYYY-MM-DD' string to date object."""
    parts = s.split('-')
    return date(int(parts[0]), int(parts[1]), int(parts[2]))

def quarter_of(d):
    """Return quarter number (1-4) for a date."""
    return (d.month - 1) // 3 + 1

def shift_quarter(d, n):
    """Shift date by n quarters (negative = backward)."""
    q = quarter_of(d)
    total_q = (d.year * 4 + (q - 1)) + n
    new_year = total_q // 4
    new_q = total_q % 4 + 1
    new_month = new_q * 3
    if new_month in (3, 12):
        new_day = 31
    elif new_month in (6, 9):
        new_day = 30
    else:
        new_day = 28
    return date(new_year, new_month, new_day)

def shift_year(d, n):
    """Shift date by n years."""
    new_year = d.year + n
    try:
        return d.replace(year=new_year)
    except ValueError:
        return date(new_year, d.month, 28)

def date_to_str(d):
    return d.strftime('%Y-%m-%d')

def get_ann_factor(d):
    """Annualization factor: Q1=4, Q2=2, Q3=4/3, Q4=1."""
    q = quarter_of(d)
    return {1: 4.0, 2: 2.0, 3: 4.0/3.0, 4: 1.0}[q]

def get_quarters_in_year(d):
    """Return list of quarter-end dates from Q1 up to current quarter."""
    year = d.year
    q = quarter_of(d)
    dates = []
    for i in range(1, q + 1):
        m = i * 3
        day = 31 if m in (3, 12) else 30
        dates.append(date(year, m, day))
    return dates

def get_prior_dec(d):
    """Return prior year December 31."""
    return date(d.year - 1, 12, 31)


# ─── XBRL Parser ────────────────────────────────────────────────────────────

XBRL_NS = {
    'xbrli': 'http://www.xbrl.org/2003/instance',
}
CALL_NS_URI = 'http://www.ffiec.gov/xbrl/call/2024'

def parse_xbrl(xbrl_path):
    """Parse XBRL instance document and return data dict.

    Returns dict mapping MDRM code -> {date_str -> numeric_value}.
    Handles both instant contexts (<xbrli:instant>) and duration contexts
    (<xbrli:startDate>/<xbrli:endDate>), using endDate for duration periods.
    """
    tree = ET.parse(xbrl_path)
    root = tree.getroot()

    # Build context map: context_id -> date string
    context_map = {}
    for ctx in root.findall('{http://www.xbrl.org/2003/instance}context'):
        ctx_id = ctx.get('id')
        period = ctx.find('{http://www.xbrl.org/2003/instance}period')
        if period is None:
            continue

        # Try instant first
        instant = period.find('{http://www.xbrl.org/2003/instance}instant')
        if instant is not None and instant.text:
            context_map[ctx_id] = instant.text.strip()
            continue

        # Try duration (use endDate)
        end_date = period.find('{http://www.xbrl.org/2003/instance}endDate')
        if end_date is not None and end_date.text:
            context_map[ctx_id] = end_date.text.strip()

    # Extract data elements from the call namespace
    data = {}
    call_ns_prefix = '{' + CALL_NS_URI + '}'

    for elem in root:
        tag = elem.tag
        if not tag.startswith(call_ns_prefix):
            continue

        # Extract MDRM code from qualified tag name
        mdrm_code = tag[len(call_ns_prefix):]
        ctx_ref = elem.get('contextRef')

        if ctx_ref and ctx_ref in context_map:
            date_str = context_map[ctx_ref]
            value_text = elem.text.strip() if elem.text else None
            if value_text is not None:
                try:
                    if '.' in value_text:
                        value = float(value_text)
                    else:
                        value = int(value_text)
                except ValueError:
                    continue
                if mdrm_code not in data:
                    data[mdrm_code] = {}
                data[mdrm_code][date_str] = value

    return data


# ─── AST Dependency Extraction ──────────────────────────────────────────────

def extract_uc_deps(ast):
    """Extract all uc: concept IDs directly referenced by an AST."""
    deps = set()
    if ast is None:
        return deps

    node_type = ast[0]

    if node_type == 'concept':
        prefix, code, period = ast[1], ast[2], ast[3]
        if prefix == 'uc':
            deps.add(code)
    elif node_type == 'cavg_ref':
        if ast[1] == 'uc':
            deps.add(ast[2])
    elif node_type in ('binop', 'cmp'):
        deps.update(extract_uc_deps(ast[2]))
        deps.update(extract_uc_deps(ast[3]))
    elif node_type == 'neg':
        deps.update(extract_uc_deps(ast[1]))
    elif node_type == 'call':
        for arg in ast[2]:
            deps.update(extract_uc_deps(arg))

    return deps


# ─── Tokenizer ──────────────────────────────────────────────────────────────

TOKEN_PATTERNS = [
    ('WHITESPACE', r'\s+'),
    ('STRING',     r"'[^']*'"),
    ('NUMBER',     r'-?\d+\.?\d*'),
    ('CONCEPT',    r'(?:uc|cc):[A-Za-z0-9_]+\[(?:P0|\-P\d+[QY])\]'),
    ('CAVG_ARG',   r'#(?:uc|cc):[A-Za-z0-9_]+'),
    ('IDENT',      r'[A-Za-z_][A-Za-z0-9_]*'),
    ('OP2',        r'<>|>=|<='),
    ('OP1',        r'[+\-*/><=%]'),
    ('LPAREN',     r'\('),
    ('RPAREN',     r'\)'),
    ('COMMA',      r','),
]

TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pat})' for name, pat in TOKEN_PATTERNS))

def tokenize(formula_str):
    tokens = []
    for m in TOKEN_RE.finditer(formula_str):
        kind = m.lastgroup
        value = m.group()
        if kind == 'WHITESPACE':
            continue
        if kind == 'OP1' and value == '=':
            kind = 'OP2'
        tokens.append((kind, value))
    return tokens


# ─── Parser (recursive descent) ─────────────────────────────────────────────

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def consume(self, expected_kind=None):
        if self.pos >= len(self.tokens):
            raise ValueError("Unexpected end of tokens")
        kind, val = self.tokens[self.pos]
        if expected_kind and kind != expected_kind:
            raise ValueError(f"Expected {expected_kind}, got {kind} ({val!r}) at pos {self.pos}")
        self.pos += 1
        return (kind, val)

    def parse(self):
        result = self.parse_expr()
        return result

    def parse_expr(self):
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        while self.peek()[0] == 'OP2' or (self.peek()[0] == 'OP1' and self.peek()[1] in ('>', '<')):
            kind, op = self.consume()
            right = self.parse_additive()
            left = ('cmp', op, left, right)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.peek()[0] == 'OP1' and self.peek()[1] in ('+', '-'):
            _, op = self.consume()
            right = self.parse_multiplicative()
            left = ('binop', op, left, right)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.peek()[0] == 'OP1' and self.peek()[1] in ('*', '/'):
            _, op = self.consume()
            right = self.parse_unary()
            left = ('binop', op, left, right)
        return left

    def parse_unary(self):
        if self.peek()[1] == '-' and self.peek()[0] == 'OP1':
            self.consume()
            operand = self.parse_primary()
            return ('neg', operand)
        return self.parse_primary()

    def parse_primary(self):
        kind, val = self.peek()

        if kind == 'NUMBER':
            self.consume()
            if '.' in val:
                return ('num', float(val))
            return ('num', int(val))

        if kind == 'STRING':
            self.consume()
            return ('str', val.strip("'"))

        if kind == 'CONCEPT':
            self.consume()
            return self.parse_concept_ref(val)

        if kind == 'CAVG_ARG':
            self.consume()
            prefix, code = val[1:].split(':')  # skip #
            return ('cavg_ref', prefix, code)

        if kind == 'IDENT':
            if val == 'null':
                self.consume()
                return ('null',)
            if val == 'ANN':
                self.consume()
                return ('ann',)
            # Check if it's a function call
            if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][0] == 'LPAREN':
                return self.parse_function_call()
            self.consume()
            return ('ident', val)

        if kind == 'LPAREN':
            self.consume()
            expr = self.parse_expr()
            self.consume('RPAREN')
            return expr

        raise ValueError(f"Unexpected token: {kind} {val!r} at pos {self.pos}")

    def parse_concept_ref(self, val):
        prefix, rest = val.split(':', 1)
        bracket_idx = rest.index('[')
        code = rest[:bracket_idx]
        period = rest[bracket_idx+1:-1]
        return ('concept', prefix, code, period)

    def parse_function_call(self):
        _, fname = self.consume('IDENT')
        self.consume('LPAREN')
        args = []
        if self.peek()[0] != 'RPAREN':
            args.append(self.parse_expr())
            while self.peek()[0] == 'COMMA':
                self.consume('COMMA')
                args.append(self.parse_expr())
        self.consume('RPAREN')
        return ('call', fname, args)


def parse_formula(formula_str):
    tokens = tokenize(formula_str)
    parser = Parser(tokens)
    return parser.parse()


# ─── Evaluator ───────────────────────────────────────────────────────────────

SYSTEM_CONCEPTS = {'UBPRC752', 'UBPR9999'}

class UBPREngine:
    def __init__(self, formulas, call_data, config):
        self.formulas = {}       # id -> parsed AST
        self.formula_defs = {}   # id -> raw formula string
        self.formula_deps = {}   # id -> set of uc: dependency concept IDs
        self.call_data = call_data
        self.config = config
        self.report_date = parse_date(config['report_date'])
        self.form_type = config['call_report_form']
        self.ann_factor = get_ann_factor(self.report_date)
        self.cache = {}          # (concept_id, date_str) -> value
        self.evaluating = set()  # cycle detection

        # Parse all formulas and extract dependencies
        for f in formulas:
            fid = f['id']
            self.formula_defs[fid] = f['formula']
            try:
                ast = parse_formula(f['formula'])
                self.formulas[fid] = ast
                self.formula_deps[fid] = extract_uc_deps(ast)
            except Exception as e:
                print(f"Warning: Failed to parse formula {fid}: {e}")
                self.formulas[fid] = ('null',)
                self.formula_deps[fid] = set()

    def resolve_period(self, period_str, base_date):
        if period_str == 'P0':
            return base_date
        m = re.match(r'-P(\d+)([QY])', period_str)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if unit == 'Q':
                return shift_quarter(base_date, -n)
            elif unit == 'Y':
                return shift_year(base_date, -n)
        raise ValueError(f"Unknown period: {period_str}")

    def lookup_cc(self, mdrm_code, target_date):
        date_str = date_to_str(target_date)
        if mdrm_code in self.call_data:
            return self.call_data[mdrm_code].get(date_str)
        return None

    def get_system_concept(self, concept_id, target_date):
        if concept_id == 'UBPRC752':
            return self.form_type
        if concept_id == 'UBPR9999':
            return date_to_str(target_date)
        return None

    def evaluate(self, concept_id, target_date=None):
        if target_date is None:
            target_date = self.report_date
        date_str = date_to_str(target_date)
        cache_key = (concept_id, date_str)

        if cache_key in self.cache:
            return self.cache[cache_key]

        # System concepts
        if concept_id in SYSTEM_CONCEPTS:
            sys_val = self.get_system_concept(concept_id, target_date)
            self.cache[cache_key] = sys_val
            return sys_val

        # Check for formula
        if concept_id not in self.formulas:
            return None

        # Cycle detection
        if cache_key in self.evaluating:
            return None
        self.evaluating.add(cache_key)

        try:
            ast = self.formulas[concept_id]
            result = self.eval_ast(ast, target_date)
            self.cache[cache_key] = result
            return result
        finally:
            self.evaluating.discard(cache_key)

    def eval_ast(self, ast, eval_date):
        if ast is None:
            return None

        node_type = ast[0]

        if node_type == 'num':
            return ast[1]
        if node_type == 'str':
            return ast[1]
        if node_type == 'null':
            return None
        if node_type == 'ann':
            return get_ann_factor(eval_date)

        if node_type == 'neg':
            val = self.eval_ast(ast[1], eval_date)
            if val is None:
                return None
            return -val

        if node_type == 'concept':
            prefix, code, period = ast[1], ast[2], ast[3]
            target = self.resolve_period(period, eval_date)
            if prefix == 'cc':
                return self.lookup_cc(code, target)
            elif prefix == 'uc':
                return self.evaluate(code, target)
            return None

        if node_type == 'binop':
            op, left_ast, right_ast = ast[1], ast[2], ast[3]
            left = self.eval_ast(left_ast, eval_date)
            right = self.eval_ast(right_ast, eval_date)
            if left is None or right is None:
                return None
            if op == '+':
                return left + right
            elif op == '-':
                return left - right
            elif op == '*':
                return left * right
            elif op == '/':
                if right == 0:
                    return None
                return left / right

        if node_type == 'cmp':
            op, left_ast, right_ast = ast[1], ast[2], ast[3]
            left = self.eval_ast(left_ast, eval_date)
            right = self.eval_ast(right_ast, eval_date)
            if left is None or right is None:
                return False
            if isinstance(left, str) and isinstance(right, str):
                try:
                    left_d = parse_date(left)
                    right_d = parse_date(right)
                    left, right = left_d, right_d
                except Exception:
                    pass
            if op == '>':
                return left > right
            elif op == '<':
                return left < right
            elif op == '=':
                return left == right
            elif op == '<>':
                return left != right
            elif op == '>=':
                return left >= right
            elif op == '<=':
                return left <= right

        if node_type == 'call':
            fname, args = ast[1], ast[2]
            return self.eval_function(fname, args, eval_date)

        if node_type == 'cavg_ref':
            return ('cavg_ref', ast[1], ast[2])

        if node_type == 'ident':
            return None

        raise ValueError(f"Unknown AST node type: {node_type}")

    def eval_function(self, fname, args, eval_date):
        fname_upper = fname.upper()

        if fname_upper == 'IF':
            if len(args) != 3:
                return None
            cond = self.eval_ast(args[0], eval_date)
            if cond is True or (isinstance(cond, (int, float)) and cond != 0):
                return self.eval_ast(args[1], eval_date)
            else:
                return self.eval_ast(args[2], eval_date)

        if fname_upper == 'AND':
            if len(args) != 2:
                return False
            left = self.eval_ast(args[0], eval_date)
            right = self.eval_ast(args[1], eval_date)
            left_bool = left is True or (isinstance(left, (int, float)) and left != 0)
            right_bool = right is True or (isinstance(right, (int, float)) and right != 0)
            return left_bool and right_bool

        if fname_upper == 'PCTOFANN':
            if len(args) != 2:
                return None
            num = self.eval_ast(args[0], eval_date)
            den = self.eval_ast(args[1], eval_date)
            if num is None or den is None or den == 0:
                return None
            ann = get_ann_factor(eval_date)
            return (num / den) * ann * 100

        if fname_upper == 'PCTOF':
            if len(args) != 2:
                return None
            num = self.eval_ast(args[0], eval_date)
            den = self.eval_ast(args[1], eval_date)
            if num is None or den is None or den == 0:
                return None
            return (num / den) * 100

        if fname_upper == 'CAVG04X':
            if len(args) != 1:
                return None
            return self.eval_cavg04x(args[0], eval_date)

        if fname_upper == 'CAVG05X':
            if len(args) != 1:
                return None
            return self.eval_cavg05x(args[0], eval_date)

        if fname_upper == 'EXISTINGOF':
            if len(args) < 1:
                return None
            val = self.eval_ast(args[0], eval_date)
            if val is not None:
                return val
            if len(args) >= 2:
                return self.eval_ast(args[1], eval_date)
            return None

        return None

    def eval_cavg04x(self, arg_ast, eval_date):
        concept_id = self._extract_cavg_concept(arg_ast)
        if concept_id is None:
            return None
        quarters = get_quarters_in_year(eval_date)
        values = []
        for q_date in quarters:
            val = self.evaluate(concept_id, q_date)
            if val is not None:
                values.append(val)
        if not values:
            return None
        return sum(values) / len(values)

    def eval_cavg05x(self, arg_ast, eval_date):
        concept_id = self._extract_cavg_concept(arg_ast)
        if concept_id is None:
            return None
        prior_dec = get_prior_dec(eval_date)
        quarters = get_quarters_in_year(eval_date)
        values = []
        val = self.evaluate(concept_id, prior_dec)
        if val is not None:
            values.append(val)
        for q_date in quarters:
            val = self.evaluate(concept_id, q_date)
            if val is not None:
                values.append(val)
        if not values:
            return None
        return sum(values) / len(values)

    def _extract_cavg_concept(self, arg_ast):
        if arg_ast[0] == 'cavg_ref':
            return arg_ast[2]
        return None

    def compute_outputs(self):
        output_ids = self.config.get('output_concepts', [])
        results = {}
        for concept_id in output_ids:
            val = self.evaluate(concept_id)
            if val is not None and isinstance(val, float):
                val = round(val, 4)
            results[concept_id] = val
        return results

    def write_sqlite(self, db_path):
        """Write all evaluations, formula dependencies, and analytical views."""
        conn = sqlite3.connect(db_path)

        conn.execute('''CREATE TABLE IF NOT EXISTS evaluations (
            concept_id TEXT NOT NULL,
            eval_date TEXT NOT NULL,
            value REAL,
            PRIMARY KEY (concept_id, eval_date)
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS formula_deps (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id)
        )''')

        # Write evaluations from cache (exclude system concepts)
        for (concept_id, date_str), value in self.cache.items():
            if concept_id in SYSTEM_CONCEPTS:
                continue
            if concept_id not in self.formulas:
                continue
            if isinstance(value, (int, float)):
                db_val = round(float(value), 4)
            else:
                db_val = None
            conn.execute(
                "INSERT OR REPLACE INTO evaluations "
                "(concept_id, eval_date, value) VALUES (?, ?, ?)",
                (concept_id, date_str, db_val)
            )

        # Write formula dependencies
        for fid, deps in self.formula_deps.items():
            for dep in deps:
                conn.execute(
                    "INSERT OR REPLACE INTO formula_deps "
                    "(source_id, target_id) VALUES (?, ?)",
                    (fid, dep)
                )

        # Create quarter-over-quarter trends view using window functions
        conn.execute('''CREATE VIEW IF NOT EXISTS qoq_trends AS
            SELECT
                concept_id,
                eval_date,
                value,
                LAG(value) OVER (PARTITION BY concept_id ORDER BY eval_date) AS prior_value,
                value - LAG(value) OVER (PARTITION BY concept_id ORDER BY eval_date) AS abs_change,
                CASE
                    WHEN LAG(value) OVER (PARTITION BY concept_id ORDER BY eval_date) IS NOT NULL
                         AND LAG(value) OVER (PARTITION BY concept_id ORDER BY eval_date) != 0
                    THEN (value - LAG(value) OVER (PARTITION BY concept_id ORDER BY eval_date))
                         / LAG(value) OVER (PARTITION BY concept_id ORDER BY eval_date) * 100.0
                    ELSE NULL
                END AS pct_change
            FROM evaluations
            ORDER BY concept_id, eval_date
        ''')

        conn.commit()
        conn.close()


def main():
    with open('/app/config.json') as f:
        config = json.load(f)
    with open('/app/formulas.json') as f:
        formula_data = json.load(f)
    with open('/app/call_report_data.json') as f:
        call_data_raw = json.load(f)

    # Load JSON Call Report data (RCON balance sheet items)
    call_data = call_data_raw['data']

    # Load XBRL supplement (RIAD income items + RCONA supplemental items)
    xbrl_path = '/app/xbrl_supplement.xml'
    if os.path.exists(xbrl_path):
        xbrl_data = parse_xbrl(xbrl_path)
        # Merge XBRL data into call_data
        for mdrm, date_vals in xbrl_data.items():
            if mdrm not in call_data:
                call_data[mdrm] = {}
            call_data[mdrm].update(date_vals)

    formulas = formula_data['formulas']

    engine = UBPREngine(formulas, call_data, config)
    results = engine.compute_outputs()

    os.makedirs('/app/output', exist_ok=True)

    # Write JSON output
    with open('/app/output/ratios.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Write SQLite audit database (tables + views)
    engine.write_sqlite('/app/output/ubpr.db')

    print(f"Computed {len(results)} output concepts.")
    for k, v in sorted(results.items()):
        print(f"  {k}: {v}")

    # Report database stats
    conn = sqlite3.connect('/app/output/ubpr.db')
    eval_count = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    dep_count = conn.execute("SELECT COUNT(*) FROM formula_deps").fetchone()[0]
    view_count = conn.execute("SELECT COUNT(*) FROM qoq_trends").fetchone()[0]
    conn.close()
    print(f"SQLite: {eval_count} evaluations, {dep_count} dependency edges, {view_count} trend rows.")


if __name__ == '__main__':
    main()
