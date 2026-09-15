#!/usr/bin/env python3
"""Design matrix builder compatible with patsy's Wilkinson-Rogers formula language.

"""

import numpy as np
import re
from collections import OrderedDict

# =============================================================================
# Constants
# =============================================================================

INTERCEPT = frozenset()
_ANTI_MARKER = "__ANTI__"
ANTI_INTERCEPT = frozenset([_ANTI_MARKER])

# =============================================================================
# Tokenizer
# =============================================================================

def _tokenize(formula):
    """Tokenize a formula string. Returns list of tokens.
    Tokens: str for operators/parens, int for numbers, str for factor names.
    Factor names include function calls like C(a, Sum).
    """
    tokens = []
    i = 0
    n = len(formula)
    while i < n:
        if formula[i].isspace():
            i += 1
            continue
        c = formula[i]
        if c in "+-:~":
            tokens.append(c)
            i += 1
        elif c == "*":
            if i + 1 < n and formula[i + 1] == "*":
                tokens.append("**")
                i += 2
            else:
                tokens.append("*")
                i += 1
        elif c == "/":
            tokens.append("/")
            i += 1
        elif c == "(":
            tokens.append("(")
            i += 1
        elif c == ")":
            tokens.append(")")
            i += 1
        elif c.isdigit():
            j = i
            while j < n and formula[j].isdigit():
                j += 1
            tokens.append(int(formula[i:j]))
            i = j
        elif c.isalpha() or c == "_":
            j = i
            while j < n and (formula[j].isalnum() or formula[j] == "_"):
                j += 1
            # Check for function call
            k = j
            while k < n and formula[k].isspace():
                k += 1
            if k < n and formula[k] == "(":
                depth = 1
                k += 1
                while k < n and depth > 0:
                    if formula[k] == "(":
                        depth += 1
                    elif formula[k] == ")":
                        depth -= 1
                    k += 1
                tokens.append(("FACTOR", formula[i:k]))
                i = k
            else:
                tokens.append(("FACTOR", formula[i:j]))
                i = j
        else:
            raise ValueError(f"Unexpected character in formula: {c!r}")
    return tokens


# =============================================================================
# Parser (recursive descent)
# =============================================================================

class _Parser:
    OPS = {"+", "-", "*", "/", ":", "**", "~", "(", ")"}

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _eat(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def _peek_is_op(self, *ops):
        t = self._peek()
        return t in ops

    def parse(self):
        r = self._add_sub()
        if self._peek_is_op("~"):
            self._eat()
            r = self._add_sub()
        return r

    def _add_sub(self):
        left = self._mul_div()
        while self._peek_is_op("+", "-"):
            op = self._eat()
            right = self._mul_div()
            if op == "+":
                left = _op_plus(left, right)
            else:
                left = _op_minus(left, right)
        return left

    def _mul_div(self):
        left = self._colon()
        while self._peek_is_op("*", "/"):
            op = self._eat()
            right = self._colon()
            if op == "*":
                left = _op_star(left, right)
            else:
                left = _op_slash(left, right)
        return left

    def _colon(self):
        left = self._power()
        while self._peek_is_op(":"):
            self._eat()
            right = self._power()
            left = _op_colon(left, right)
        return left

    def _power(self):
        left = self._unary()
        if self._peek_is_op("**"):
            self._eat()
            n_tok = self._eat()
            if not isinstance(n_tok, int):
                raise ValueError("** requires integer exponent")
            left = _op_power(left, n_tok)
        return left

    def _unary(self):
        if self._peek_is_op("+", "-"):
            op = self._eat()
            operand = self._unary()
            if op == "-":
                return _op_unary_minus(operand)
            return operand
        return self._primary()

    def _primary(self):
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of formula")
        if isinstance(tok, int):
            self._eat()
            if tok == 0:
                return [ANTI_INTERCEPT]
            elif tok == 1:
                return [INTERCEPT]
            else:
                raise ValueError(f"Only 0 and 1 are valid as terms, got {tok}")
        elif tok == "(":
            self._eat()
            r = self._add_sub()
            if self._peek_is_op("~"):
                self._eat()
                r = self._add_sub()
            if self._eat() != ")":
                raise ValueError("Expected )")
            return r
        elif isinstance(tok, tuple) and tok[0] == "FACTOR":
            self._eat()
            return [frozenset([tok[1]])]
        else:
            raise ValueError(f"Unexpected token: {tok!r}")


# =============================================================================
# Term algebra
# =============================================================================

def _uniqueify(lst):
    seen = set()
    result = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _op_plus(left, right):
    has_anti_l = ANTI_INTERCEPT in left
    has_anti_r = ANTI_INTERCEPT in right
    cl = [t for t in left if t != ANTI_INTERCEPT]
    cr = [t for t in right if t != ANTI_INTERCEPT]
    result = cl + cr
    if has_anti_l or has_anti_r:
        result = [t for t in result if t != INTERCEPT]
    return _uniqueify(result)


def _op_minus(left, right):
    has_anti = ANTI_INTERCEPT in right
    to_remove = set(right) - {ANTI_INTERCEPT}
    result = [t for t in left if t not in to_remove]
    if has_anti:
        if INTERCEPT not in result:
            result.append(INTERCEPT)
    return _uniqueify(result)


def _op_colon(left, right):
    result = []
    for lt in left:
        if lt == ANTI_INTERCEPT:
            continue
        for rt in right:
            if rt == ANTI_INTERCEPT:
                continue
            result.append(lt | rt)
    return _uniqueify(result)


def _op_star(left, right):
    return _op_plus(_op_plus(left, right), _op_colon(left, right))


def _op_slash(left, right):
    all_factors = frozenset()
    for t in left:
        if t != ANTI_INTERCEPT and t != INTERCEPT:
            all_factors = all_factors | t
    new_terms = []
    for rt in right:
        if rt != ANTI_INTERCEPT:
            new_terms.append(all_factors | rt)
    return _uniqueify(left + new_terms)


def _op_power(terms, n):
    if n < 1:
        raise ValueError("Power must be >= 1")
    result = terms
    for _ in range(n - 1):
        result = _op_star(result, terms)
    return result


def _op_unary_minus(terms):
    if terms == [INTERCEPT]:
        return [ANTI_INTERCEPT]
    if terms == [ANTI_INTERCEPT]:
        return [INTERCEPT]
    raise ValueError("Unary minus only valid for 0 or 1")


def _parse_formula(formula_str):
    """Parse formula, return ordered list of terms (frozensets of factor names)."""
    formula_str = formula_str.strip()
    if "~" in formula_str:
        formula_str = formula_str.split("~", 1)[1].strip()
    formula_str = "1 + " + formula_str
    tokens = _tokenize(formula_str)
    parser = _Parser(tokens)
    terms = parser.parse()
    terms = [t for t in terms if t != ANTI_INTERCEPT]
    return terms


# =============================================================================
# Factor info helpers
# =============================================================================

def _parse_factor_name(factor_name):
    """Parse factor name -> (data_column, coding_scheme, transform).
    E.g. 'C(a, Sum)' -> ('a', 'Sum', None)
         'center(x)' -> ('x', None, 'center')
         'x' -> ('x', None, None)
    """
    m = re.match(r"^C\(\s*(\w+)\s*,\s*(\w+)\s*\)$", factor_name)
    if m:
        return m.group(1), m.group(2), None
    m = re.match(r"^(center|standardize)\(\s*(\w+)\s*\)$", factor_name)
    if m:
        return m.group(2), None, m.group(1)
    return factor_name, None, None


def _infer_type(values):
    for v in values:
        if isinstance(v, (str, bool)):
            return "categorical"
    return "numerical"


def _get_levels(values):
    return sorted(set(values))


# =============================================================================
# Contrast coding schemes
# =============================================================================

class _ContrastMatrix:
    def __init__(self, matrix, column_suffixes):
        self.matrix = np.asarray(matrix, dtype=float)
        self.column_suffixes = list(column_suffixes)


class _Treatment:
    def code_with_intercept(self, levels):
        n = len(levels)
        return _ContrastMatrix(np.eye(n), ["[%s]" % str(l) for l in levels])

    def code_without_intercept(self, levels):
        n = len(levels)
        ref = 0
        eye = np.eye(n - 1)
        contrasts = np.vstack(
            (eye[:ref], np.zeros((1, n - 1)), eye[ref:])
        )
        included = [levels[i] for i in range(n) if i != ref]
        return _ContrastMatrix(contrasts, ["[T.%s]" % str(l) for l in included])


class _Sum:
    def code_without_intercept(self, levels):
        n = len(levels)
        omit = n - 1
        eye = np.eye(n - 1)
        out = np.empty((n, n - 1))
        out[:omit] = eye[:omit]
        out[omit] = -1
        if omit + 1 < n:
            out[omit + 1 :] = eye[omit:]
        included = [levels[i] for i in range(n) if i != omit]
        return _ContrastMatrix(out, ["[S.%s]" % str(l) for l in included])

    def code_with_intercept(self, levels):
        c = self.code_without_intercept(levels)
        matrix = np.column_stack((np.ones(len(levels)), c.matrix))
        return _ContrastMatrix(matrix, ["[mean]"] + c.column_suffixes)


class _Poly:
    def _code_either(self, intercept, levels):
        n = len(levels)
        scores = np.arange(n, dtype=float)
        scores -= scores.mean()
        raw_poly = scores.reshape(-1, 1) ** np.arange(n).reshape(1, -1)
        q, r = np.linalg.qr(raw_poly)
        q *= np.sign(np.diag(r))
        # Normalize: q /= column norms
        col_norms = np.sqrt(np.sum(q ** 2, axis=0))
        col_norms[col_norms == 0] = 1
        q /= col_norms
        q[:, 0] = 1
        names = [".Constant", ".Linear", ".Quadratic", ".Cubic"]
        names += ["^%s" % i for i in range(4, n)]
        names = names[:n]
        if intercept:
            return _ContrastMatrix(q, names)
        else:
            return _ContrastMatrix(q[:, 1:], names[1:])

    def code_with_intercept(self, levels):
        return self._code_either(True, levels)

    def code_without_intercept(self, levels):
        return self._code_either(False, levels)


class _Helmert:
    def _helmert_contrast(self, levels):
        n = len(levels)
        contr = np.zeros((n, n - 1))
        for j in range(n - 1):
            contr[j + 1, j] = j + 1
        for j in range(n - 1):
            for i in range(j + 1):
                contr[i, j] = -1
        return contr

    def code_with_intercept(self, levels):
        c = np.column_stack(
            (np.ones(len(levels)), self._helmert_contrast(levels))
        )
        names = ["[H.intercept]"] + ["[H.%s]" % str(l) for l in levels[1:]]
        return _ContrastMatrix(c, names)

    def code_without_intercept(self, levels):
        return _ContrastMatrix(
            self._helmert_contrast(levels),
            ["[H.%s]" % str(l) for l in levels[1:]],
        )


class _Diff:
    def _diff_contrast(self, levels):
        n = len(levels)
        contr = np.zeros((n, n - 1))
        int_range = np.arange(1, n)
        upper_int = np.repeat(int_range, int_range)
        row_i, col_i = np.triu_indices(n - 1)
        col_order = np.argsort(col_i)
        contr[row_i[col_order], col_i[col_order]] = (upper_int - n) / float(n)
        lower_int = np.repeat(int_range, int_range[::-1])
        row_i, col_i = np.tril_indices(n - 1)
        col_order = np.argsort(col_i)
        contr[row_i[col_order] + 1, col_i[col_order]] = lower_int / float(n)
        return contr

    def code_with_intercept(self, levels):
        c = np.column_stack(
            (np.ones(len(levels)), self._diff_contrast(levels))
        )
        return _ContrastMatrix(c, ["[D.%s]" % str(l) for l in levels])

    def code_without_intercept(self, levels):
        return _ContrastMatrix(
            self._diff_contrast(levels),
            ["[D.%s]" % str(l) for l in levels[:-1]],
        )


_CODING_SCHEMES = {
    "Treatment": _Treatment,
    "Sum": _Sum,
    "Poly": _Poly,
    "Helmert": _Helmert,
    "Diff": _Diff,
}


# =============================================================================
# Redundancy detection
# =============================================================================

def _all_subsets(factors):
    """Return all subsets of a set of factors."""
    factors = list(factors)
    n = len(factors)
    result = set()
    for mask in range(2 ** n):
        subset = frozenset(factors[i] for i in range(n) if mask & (1 << i))
        result.add(subset)
    return result


def _greedy_recombine(subterms):
    """Greedily merge subterms using the rule:
    If subterm S and subterm S+{f} exist where f is reduced-rank in S+{f}
    and all shared factors have the same rank mode, merge them by promoting
    f to full-rank.

    Each subterm is a dict {factor_name: 'full'|'reduced'}.
    Returns a list of merged subterms.
    """
    subterms = [dict(s) for s in subterms]
    changed = True
    while changed:
        changed = False
        subterms.sort(key=lambda s: len(s))
        for i in range(len(subterms)):
            for j in range(i + 1, len(subterms)):
                si = subterms[i]
                sj = subterms[j]
                si_keys = set(si.keys())
                sj_keys = set(sj.keys())
                extra = sj_keys - si_keys
                if len(extra) == 1 and si_keys.issubset(sj_keys):
                    f = next(iter(extra))
                    if sj[f] == "reduced":
                        shared = si_keys & sj_keys
                        if all(si[k] == sj[k] for k in shared):
                            merged = dict(sj)
                            merged[f] = "full"
                            subterms = [
                                s
                                for idx, s in enumerate(subterms)
                                if idx != i and idx != j
                            ]
                            subterms.append(merged)
                            changed = True
                            break
            if changed:
                break
    return subterms


def _pick_contrasts_for_term(cat_factors, used_pieces):
    """Determine contrast coding for categorical factors in a term.

    Returns list of dicts {factor_name: True/False} where True = full-rank.
    Updates used_pieces in-place.
    """
    all_pieces = _all_subsets(cat_factors)
    remaining = all_pieces - used_pieces

    # Sort remaining pieces deterministically for reproducible column ordering
    remaining_sorted = sorted(remaining, key=lambda s: tuple(sorted(s)))

    # Convert remaining pieces to subterms
    initial_subterms = []
    for piece in remaining_sorted:
        subterm = {f: "reduced" for f in piece}
        initial_subterms.append(subterm)

    merged = _greedy_recombine(initial_subterms)

    # Update used_pieces
    used_pieces.update(all_pieces)

    # Convert to factor_coding dicts
    result = []
    for subterm in merged:
        if not subterm:  # empty dict = intercept piece
            continue
        coding = {f: (mode == "full") for f, mode in subterm.items()}
        result.append(coding)

    return result


# =============================================================================
# Design matrix builder
# =============================================================================

def _build_factor_info(terms, data):
    """Determine type and metadata for each factor appearing in the terms."""
    all_factors = set()
    for term in terms:
        all_factors.update(term)

    factor_info = {}
    for factor_name in all_factors:
        if factor_name == _ANTI_MARKER:
            continue
        data_col, coding_scheme, transform = _parse_factor_name(factor_name)
        if data_col not in data:
            raise ValueError(f"Variable {data_col!r} not found in data")
        values = data[data_col]

        if coding_scheme is not None:
            ftype = "categorical"
        elif transform is not None:
            ftype = "numerical"
        else:
            ftype = _infer_type(values)

        info = {
            "name": factor_name,
            "data_col": data_col,
            "type": ftype,
            "coding_scheme": coding_scheme,
            "transform": transform,
        }
        if ftype == "categorical":
            info["levels"] = _get_levels(values)
        factor_info[factor_name] = info

    return factor_info


def _get_coding_object(scheme_name):
    if scheme_name is None:
        return _Treatment()
    cls = _CODING_SCHEMES.get(scheme_name)
    if cls is None:
        raise ValueError(f"Unknown coding scheme: {scheme_name}")
    return cls()


def _compute_transform(transform_name, values):
    arr = np.asarray(values, dtype=float)
    if transform_name == "center":
        return arr - arr.mean()
    elif transform_name == "standardize":
        mean = arr.mean()
        std = np.sqrt(np.mean((arr - mean) ** 2))
        if std == 0:
            return arr - mean
        return (arr - mean) / std
    raise ValueError(f"Unknown transform: {transform_name}")


def _group_terms(terms, factor_info):
    """Group terms by their set of numeric factors.
    Returns OrderedDict: frozenset_of_numeric_factors -> [terms_in_order].
    No-numerics group comes first.
    """
    buckets = OrderedDict()
    bucket_order = []
    for term in terms:
        num_factors = frozenset(
            f for f in term if f in factor_info and factor_info[f]["type"] == "numerical"
        )
        if num_factors not in buckets:
            bucket_order.append(num_factors)
            buckets[num_factors] = []
        buckets[num_factors].append(term)

    # Move no-numerics bucket to front
    empty = frozenset()
    if empty in buckets:
        bucket_order.remove(empty)
        bucket_order.insert(0, empty)

    ordered = OrderedDict()
    for key in bucket_order:
        ordered[key] = buckets[key]
    return ordered


def _sort_terms_in_group(terms):
    """Sort terms by degree (number of factors), stable."""
    return sorted(terms, key=lambda t: len(t))


def _column_combinations(columns_per_factor):
    """Generate column index combinations with left-most factor iterating fastest.
    Matches patsy/R convention."""
    import itertools as _it
    if not columns_per_factor:
        yield ()
        return
    iterators = [range(n) for n in reversed(columns_per_factor)]
    for rev_combo in _it.product(*iterators):
        yield rev_combo[::-1]


def dmatrix(formula, data):
    """Build a design matrix from a formula string and data dict.

    Parameters:
        formula: Right-hand side formula string (Wilkinson-Rogers notation)
        data: Dict mapping variable names to lists of values

    Returns:
        Tuple of (column_names: list[str], matrix: list[list[float]])
    """
    terms = _parse_formula(formula)
    factor_info = _build_factor_info(terms, data)

    n_rows = None
    for col_values in data.values():
        n_rows = len(col_values)
        break

    # Group and sort terms
    grouped = _group_terms(terms, factor_info)

    # Process terms: determine contrast coding via redundancy detection
    # (separate used_pieces per numeric-factor group)
    column_names = []
    column_builders = []

    for bucket_key, bucket_terms in grouped.items():
        sorted_bucket = _sort_terms_in_group(bucket_terms)
        used_pieces = set()

        for term in sorted_bucket:
            if term == INTERCEPT:
                column_names.append("Intercept")
                column_builders.append(("intercept", None))
                used_pieces.add(frozenset())
                continue

            # Sort factors alphabetically for deterministic ordering
            term_factors_sorted = sorted(term)

            # Separate categorical and numeric factors
            cat_factors = frozenset(
                f for f in term_factors_sorted
                if factor_info[f]["type"] == "categorical"
            )
            num_factors = [
                f for f in term_factors_sorted
                if factor_info[f]["type"] == "numerical"
            ]

            # Get contrast codings for categorical factors
            factor_codings = _pick_contrasts_for_term(cat_factors, used_pieces)

            for coding_dict in factor_codings:
                subterm_factors = []
                contrast_matrices = {}

                for f in term_factors_sorted:
                    if factor_info[f]["type"] == "numerical":
                        subterm_factors.append(f)
                    elif f in coding_dict:
                        subterm_factors.append(f)
                        fi = factor_info[f]
                        coding_obj = _get_coding_object(fi["coding_scheme"])
                        if coding_dict[f]:  # full rank
                            cm = coding_obj.code_with_intercept(fi["levels"])
                        else:  # reduced rank
                            cm = coding_obj.code_without_intercept(fi["levels"])
                        contrast_matrices[f] = cm

                # Determine columns per factor for combination generation
                cols_per_factor = []
                for f in subterm_factors:
                    fi = factor_info[f]
                    if fi["type"] == "numerical":
                        cols_per_factor.append(1)
                    else:
                        cols_per_factor.append(
                            contrast_matrices[f].matrix.shape[1]
                        )

                # Generate columns with left-most factor iterating fastest
                for col_idxs in _column_combinations(cols_per_factor):
                    name_pieces = []
                    combo = []
                    for factor_i, (f, ci) in enumerate(
                        zip(subterm_factors, col_idxs)
                    ):
                        fi = factor_info[f]
                        if fi["type"] == "numerical":
                            name_pieces.append(fi["name"])
                            combo.append((f, "num", 0))
                        else:
                            cm = contrast_matrices[f]
                            suffix = cm.column_suffixes[ci]
                            name_pieces.append(fi["name"] + suffix)
                            combo.append((f, "cat", ci))
                    col_name = ":".join(name_pieces)
                    column_names.append(col_name)
                    column_builders.append(
                        ("subterm", combo, contrast_matrices)
                    )

            if not factor_codings and not cat_factors:
                # Pure numeric term
                combo = [(f, "num", 0) for f in num_factors]
                name_parts = [factor_info[f]["name"] for f in num_factors]
                col_name = ":".join(name_parts)
                column_names.append(col_name)
                column_builders.append(("subterm", combo, {}))

    # Build the actual matrix
    matrix = np.empty((n_rows, len(column_names)))
    for col_idx, builder in enumerate(column_builders):
        if builder[0] == "intercept":
            matrix[:, col_idx] = 1.0
        else:
            _, combo, contrast_matrices = builder
            col_values = np.ones(n_rows)
            for f, ftype, ci in combo:
                fi = factor_info[f]
                raw_values = data[fi["data_col"]]
                if ftype == "num":
                    if fi.get("transform"):
                        transformed = _compute_transform(
                            fi["transform"], raw_values
                        )
                        col_values *= transformed
                    else:
                        col_values *= np.asarray(raw_values, dtype=float)
                else:
                    cm = contrast_matrices[f]
                    levels = fi["levels"]
                    for row_idx in range(n_rows):
                        level_idx = levels.index(raw_values[row_idx])
                        col_values[row_idx] *= cm.matrix[level_idx, ci]

            matrix[:, col_idx] = col_values

    return column_names, matrix.tolist()
