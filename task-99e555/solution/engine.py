#!/usr/bin/env python3
"""
RIME Spelling Algebra Engine — reference implementation.

"""

import re
import sys
import yaml


def perl_repl_to_python(repl):
    """Convert Perl-style replacement ($1, $2, etc.) to Python-style (\\1, \\2)."""
    return re.sub(r'\$(\d+)', r'\\\1', repl)


def parse_rule(rule_str):
    """Parse a RIME spelling algebra rule string into (operator, args).

    Format: <operator><delim><arg1><delim><arg2><delim>...
    The delimiter is the first character after the operator name.
    Replacement arguments are converted from Perl ($1) to Python (\\1) style.
    """
    # Extract operator name (letters at start)
    match = re.match(r'^([a-z]+)', rule_str)
    if not match:
        raise ValueError(f"Cannot parse rule: {rule_str}")
    operator = match.group(1)
    rest = rule_str[len(operator):]

    if not rest:
        return operator, []

    delim = rest[0]
    parts = rest.split(delim)
    # parts[0] is empty (before first delim), then arg1, arg2, ...
    # Last element may be empty if rule ends with delimiter
    args = [p for p in parts[1:]]
    # Remove trailing empty string if present
    if args and args[-1] == '':
        args = args[:-1]

    # Convert replacement patterns from Perl to Python style
    # For operators with pattern+replacement, the replacement is args[1]
    if operator in ('xform', 'derive', 'abbrev', 'fuzz') and len(args) >= 2:
        args[1] = perl_repl_to_python(args[1])

    return operator, args


def apply_xlit(text, left, right):
    """Transliteration: character-by-character mapping from left to right strings."""
    if len(left) != len(right):
        raise ValueError(f"xlit: left and right must have same length: '{left}' vs '{right}'")
    mapping = {}
    for l_char, r_char in zip(left, right):
        mapping[l_char] = r_char
    result = []
    for ch in text:
        result.append(mapping.get(ch, ch))
    return ''.join(result)


def project(syllables, algebra_rules):
    """Apply the projection algorithm.

    Starting from identity mapping {s -> s for s in syllables},
    apply each algebra rule in sequence.

    Returns list of (spelling, original_syllable) pairs.
    """
    # Current mapping: dict of spelling -> set of original syllables
    current = {}
    for s in syllables:
        current.setdefault(s, set()).add(s)

    for rule_str in algebra_rules:
        operator, args = parse_rule(rule_str)

        if operator == 'xlit':
            left, right = args[0], args[1]
            new_current = {}
            for spelling, originals in current.items():
                new_spelling = apply_xlit(spelling, left, right)
                if new_spelling not in new_current:
                    new_current[new_spelling] = set()
                new_current[new_spelling].update(originals)
            current = new_current

        elif operator == 'xform':
            pattern, replacement = args[0], args[1]
            new_current = {}
            for spelling, originals in current.items():
                new_spelling = re.sub(pattern, replacement, spelling)
                if new_spelling not in new_current:
                    new_current[new_spelling] = set()
                new_current[new_spelling].update(originals)
            current = new_current

        elif operator == 'erase':
            pattern = args[0]
            new_current = {}
            for spelling, originals in current.items():
                if re.fullmatch(pattern, spelling):
                    continue  # erase this spelling
                new_current[spelling] = originals
            current = new_current

        elif operator in ('derive', 'abbrev', 'fuzz'):
            pattern, replacement = args[0], args[1]
            additions = {}
            for spelling, originals in current.items():
                new_spelling = re.sub(pattern, replacement, spelling)
                if new_spelling != spelling:
                    if new_spelling not in additions:
                        additions[new_spelling] = set()
                    additions[new_spelling].update(originals)
            # Merge additions into current (keep originals)
            for sp, origs in additions.items():
                if sp not in current:
                    current[sp] = set()
                current[sp].update(origs)

        else:
            raise ValueError(f"Unknown operator: {operator}")

    # Flatten to sorted list of (spelling, syllable) pairs
    pairs = []
    for spelling, originals in current.items():
        for orig in originals:
            pairs.append((spelling, orig))
    pairs.sort()
    return pairs


def apply_preedit_format(text, preedit_rules):
    """Apply preedit_format rules (xform/xlit) sequentially to a string."""
    for rule_str in preedit_rules:
        operator, args = parse_rule(rule_str)
        if operator == 'xform':
            pattern, replacement = args[0], args[1]
            text = re.sub(pattern, replacement, text)
        elif operator == 'xlit':
            left, right = args[0], args[1]
            text = apply_xlit(text, left, right)
        else:
            raise ValueError(f"Unsupported preedit operator: {operator}")
    return text


def load_schema(schema_path):
    """Load and parse a RIME schema YAML file."""
    with open(schema_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data


def load_syllables(dict_path):
    """Load syllables from a RIME dictionary file.

    The dict file has a YAML header between --- and ..., then
    tab-separated entries: character<TAB>syllable[<TAB>weight]
    """
    syllables = set()
    in_body = False
    with open(dict_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if line == '...':
                in_body = True
                continue
            if not in_body:
                continue
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 2:
                syllable = parts[1]
                syllables.add(syllable)
    return sorted(syllables)


def main():
    if len(sys.argv) < 3:
        print("Usage:", file=sys.stderr)
        print("  engine.py project <schema.yaml> <dict.yaml>", file=sys.stderr)
        print("  engine.py preedit <schema.yaml> <input_string>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    schema_path = sys.argv[2]
    schema = load_schema(schema_path)

    if command == 'project':
        dict_path = sys.argv[3]
        syllables = load_syllables(dict_path)
        algebra_rules = schema.get('speller', {}).get('algebra', [])
        pairs = project(syllables, algebra_rules)
        for spelling, syllable in pairs:
            print(f"{spelling}\t{syllable}")

    elif command == 'preedit':
        input_string = sys.argv[3]
        preedit_rules = schema.get('translator', {}).get('preedit_format', [])
        result = apply_preedit_format(input_string, preedit_rules)
        print(result)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
