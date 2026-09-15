#!/usr/bin/env python3
"""Write the typesim parser module."""

content = r'''"""Parser for Python type annotation strings into TypeNode trees."""


class TypeNode:
    """Represents a parsed type annotation."""

    def __init__(self, name, args=None, is_union=False):
        self.name = name
        self.args = args if args is not None else []
        self.is_union = is_union

    def __repr__(self):
        if self.is_union:
            return "Union[" + ", ".join(repr(a) for a in self.args) + "]"
        if self.args:
            return self.name + "[" + ", ".join(repr(a) for a in self.args) + "]"
        return self.name

    def __eq__(self, other):
        if not isinstance(other, TypeNode):
            return False
        return (self.name == other.name and self.args == other.args
                and self.is_union == other.is_union)


# Container name mapping (Title-case generics -> lowercase builtins)
_NAME_MAP = {
    "List": "list",
    "Dict": "dict",
    "Tuple": "tuple",
    "Set": "set",
    "FrozenSet": "frozenset",
    "Deque": "deque",
}


def _tokenize(s):
    """Tokenize a type annotation string."""
    tokens = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == ' ':
            i += 1
            continue
        if c in '[](),':
            tokens.append(c)
            i += 1
        elif c == '.' and i + 2 < n and s[i:i+3] == '...':
            tokens.append('...')
            i += 3
        else:
            j = i
            while j < n and s[j] not in '[](), ':
                j += 1
            tokens.append(s[i:j])
            i = j
    return tokens


def _parse_expr(tokens, pos):
    """Parse a single type expression starting at pos."""
    if pos >= len(tokens):
        raise ValueError("Unexpected end of type string")

    name = tokens[pos]
    pos += 1

    if name == 'Union':
        return _parse_union(tokens, pos)

    if name == 'Optional':
        return _parse_optional(tokens, pos)

    if name == 'Callable':
        return _parse_callable(tokens, pos)

    mapped = _NAME_MAP.get(name, name)

    if pos < len(tokens) and tokens[pos] == '[':
        pos += 1  # skip '['
        args = []
        while pos < len(tokens) and tokens[pos] != ']':
            if tokens[pos] == ',':
                pos += 1
                continue
            if tokens[pos] == '...':
                args.append(TypeNode('...'))
                pos += 1
                continue
            arg, pos = _parse_expr(tokens, pos)
            args.append(arg)
        if pos < len(tokens):
            pos += 1  # skip ']'
        return TypeNode(mapped, args), pos

    return TypeNode(mapped), pos


def _parse_union(tokens, pos):
    """Parse Union[X, Y, ...]."""
    if pos < len(tokens) and tokens[pos] == '[':
        pos += 1
        args = []
        while pos < len(tokens) and tokens[pos] != ']':
            if tokens[pos] == ',':
                pos += 1
                continue
            arg, pos = _parse_expr(tokens, pos)
            args.append(arg)
        if pos < len(tokens):
            pos += 1
        return TypeNode("Union", args, is_union=True), pos
    return TypeNode("Union", [], is_union=True), pos


def _parse_optional(tokens, pos):
    """Parse Optional[X] as Union[X, None]."""
    if pos < len(tokens) and tokens[pos] == '[':
        pos += 1
        arg, pos = _parse_expr(tokens, pos)
        if pos < len(tokens) and tokens[pos] == ']':
            pos += 1
        return TypeNode("Union", [arg, TypeNode("None")], is_union=True), pos
    return TypeNode("Union", [TypeNode("Any"), TypeNode("None")], is_union=True), pos


def _parse_callable(tokens, pos):
    """Parse Callable[[A, B], R]."""
    if pos < len(tokens) and tokens[pos] == '[':
        pos += 1  # skip outer '['
        param_args = []
        if pos < len(tokens) and tokens[pos] == '[':
            pos += 1  # skip inner '['
            while pos < len(tokens) and tokens[pos] != ']':
                if tokens[pos] == ',':
                    pos += 1
                    continue
                arg, pos = _parse_expr(tokens, pos)
                param_args.append(arg)
            if pos < len(tokens):
                pos += 1  # skip inner ']'
        if pos < len(tokens) and tokens[pos] == ',':
            pos += 1
        ret, pos = _parse_expr(tokens, pos)
        if pos < len(tokens) and tokens[pos] == ']':
            pos += 1
        all_args = param_args + [ret]
        return TypeNode("Callable", all_args), pos
    return TypeNode("Callable"), pos


def parse_type(s):
    """Parse a type annotation string into a TypeNode tree.

    Args:
        s: A Python type annotation string, e.g. "Dict[str, List[int]]"

    Returns:
        A TypeNode representing the parsed type.
    """
    tokens = _tokenize(s.strip())
    node, _ = _parse_expr(tokens, 0)
    return node
'''

with open("/app/typesim/parser.py", "w") as f:
    f.write(content)
