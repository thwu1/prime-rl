"""CSS selector parser.

Parses CSS selector strings into structured selector chains supporting
type, class, ID, attribute selectors, compound selectors, descendant
and child combinators, and comma-separated selector lists.

"""


def _parse_compound(s):
    """Parse a compound selector string like 'div.foo#bar[attr="v"]'."""
    result = {"type": None, "id": None, "classes": [], "attributes": {}}
    i = 0
    n = len(s)
    if i < n and (s[i].isalpha() or s[i] == "*"):
        if s[i] == "*":
            result["type"] = "*"
            i += 1
        else:
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            result["type"] = s[i:j]
            i = j
    while i < n:
        if s[i] == "#":
            i += 1
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            result["id"] = s[i:j]
            i = j
        elif s[i] == ".":
            i += 1
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            result["classes"].append(s[i:j])
            i = j
        elif s[i] == "[":
            i += 1
            j = i
            while j < n and s[j] not in "=]":
                j += 1
            attr_name = s[i:j].strip()
            attr_value = None
            if j < n and s[j] == "=":
                j += 1
                if j < n and s[j] in "\"'":
                    q = s[j]
                    j += 1
                    k = j
                    while k < n and s[k] != q:
                        k += 1
                    attr_value = s[j:k]
                    j = k + 1
                else:
                    k = j
                    while k < n and s[k] != "]":
                        k += 1
                    attr_value = s[j:k].strip()
                    j = k
            if j < n and s[j] == "]":
                j += 1
            result["attributes"][attr_name] = attr_value
            i = j
        else:
            break
    return result


def _tokenize_group(s):
    """Tokenize one selector group into compounds and combinators."""
    tokens = []
    i = 0
    n = len(s)
    while i < n:
        ws_start = i
        while i < n and s[i] in " \t":
            i += 1
        had_ws = i > ws_start
        if i >= n:
            break
        if s[i] == ">":
            tokens.append(("comb", ">"))
            i += 1
            continue
        start = i
        in_brackets = False
        in_quotes = False
        qchar = None
        while i < n:
            c = s[i]
            if in_quotes:
                if c == qchar:
                    in_quotes = False
                i += 1
                continue
            if c in "\"'":
                in_quotes = True
                qchar = c
                i += 1
                continue
            if c == "[":
                in_brackets = True
                i += 1
                continue
            if c == "]":
                in_brackets = False
                i += 1
                continue
            if in_brackets:
                i += 1
                continue
            if c in " \t>":
                break
            i += 1
        compound_str = s[start:i]
        if compound_str:
            if had_ws and tokens and tokens[-1][0] == "comp":
                tokens.append(("comb", " "))
            tokens.append(("comp", compound_str))
    return tokens


def parse_selector(selector_str):
    """Parse a CSS selector string into structured selector chains.

    Returns a list of selector chains (one per comma-separated group).
    Each chain is a list of (combinator, compound) tuples.
    """
    chains = []
    for group in selector_str.split(","):
        group = group.strip()
        if not group:
            continue
        tokens = _tokenize_group(group)
        compounds = []
        combinators = []
        for ttype, tval in tokens:
            if ttype == "comp":
                compounds.append(_parse_compound(tval))
            else:
                combinators.append(tval)
        chain = []
        for idx in range(len(compounds)):
            comb = combinators[idx] if idx < len(combinators) else None
            chain.append((comb, compounds[idx]))
        chains.append(chain)
    return chains
