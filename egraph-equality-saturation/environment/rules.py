"""Rewrite rule definitions for arithmetic equality saturation."""


class Pattern:
    """Base class for rewrite-rule patterns."""
    pass


class PatVar(Pattern):
    """Pattern variable (e.g., ?a) that matches any e-class."""
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"?{self.name}"


class PatNum(Pattern):
    """Pattern that matches a specific integer constant."""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return str(self.value)


class PatOp(Pattern):
    """Pattern for a binary operation node."""
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"({self.op} {self.left} {self.right})"


class Rule:
    """A rewrite rule: lhs pattern => rhs pattern."""
    def __init__(self, name, lhs, rhs):
        self.name = name
        self.lhs = lhs
        self.rhs = rhs

    def __repr__(self):
        return f"Rule({self.name}: {self.lhs} => {self.rhs})"


def _tokenize_pat(s):
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c in '()':
            tokens.append(c)
            i += 1
        elif c == '?':
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] == '_'):
                j += 1
            tokens.append(s[i:j])
            i = j
        elif c.isdigit() or (c == '-' and i + 1 < len(s) and s[i + 1].isdigit()):
            j = i + 1
            while j < len(s) and s[j].isdigit():
                j += 1
            tokens.append(s[i:j])
            i = j
        elif c.isalpha() or c == '_':
            j = i
            while j < len(s) and (s[j].isalnum() or s[j] == '_'):
                j += 1
            tokens.append(s[i:j])
            i = j
        else:
            tokens.append(c)
            i += 1
    return tokens


def _parse_pat_tokens(tokens, pos):
    if tokens[pos] == '(':
        pos += 1
        op = tokens[pos]
        pos += 1
        left, pos = _parse_pat_tokens(tokens, pos)
        right, pos = _parse_pat_tokens(tokens, pos)
        assert tokens[pos] == ')', f"Expected ), got {tokens[pos]}"
        pos += 1
        return PatOp(op, left, right), pos
    elif tokens[pos].startswith('?'):
        return PatVar(tokens[pos][1:]), pos + 1
    else:
        return PatNum(int(tokens[pos])), pos + 1


def parse_pattern(s):
    """Parse a pattern string into a Pattern tree.

    Pattern variables start with '?', e.g. '?a', '?b'.
    Constants are integers. Operations use S-expression syntax.

    Example: parse_pattern("(+ ?a 0)") -> PatOp("+", PatVar("a"), PatNum(0))
    """
    tokens = _tokenize_pat(s.strip())
    pat, _ = _parse_pat_tokens(tokens, 0)
    return pat


# Standard arithmetic rewrite rules.
# Each rule's LHS is matched against e-graph nodes; when it matches,
# the RHS is instantiated and merged into the same equivalence class.
RULES = [
    Rule("comm-add",
         parse_pattern("(+ ?a ?b)"),
         parse_pattern("(+ ?b ?a)")),

    Rule("comm-mul",
         parse_pattern("(* ?a ?b)"),
         parse_pattern("(* ?b ?a)")),

    Rule("assoc-add",
         parse_pattern("(+ (+ ?a ?b) ?c)"),
         parse_pattern("(+ ?a (+ ?b ?c))")),

    Rule("assoc-mul",
         parse_pattern("(* (* ?a ?b) ?c)"),
         parse_pattern("(* ?a (* ?b ?c))")),

    Rule("add-zero",
         parse_pattern("(+ ?a 0)"),
         parse_pattern("?a")),

    Rule("mul-one",
         parse_pattern("(* ?a 1)"),
         parse_pattern("?a")),

    Rule("mul-zero",
         parse_pattern("(* ?a 0)"),
         parse_pattern("0")),

    Rule("distribute",
         parse_pattern("(* ?a (+ ?b ?c))"),
         parse_pattern("(+ (* ?a ?b) (* ?a ?c))")),

    Rule("factor",
         parse_pattern("(+ (* ?a ?b) (* ?a ?c))"),
         parse_pattern("(* ?a (+ ?b ?c))")),

    Rule("double",
         parse_pattern("(+ ?a ?a)"),
         parse_pattern("(* 2 ?a)")),
]
