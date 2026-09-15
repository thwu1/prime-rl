#!/usr/bin/env python3
"""
systemd ExecStart tokenizer engine.
Implements the command-line parsing rules documented in systemd.service(5)
and systemd.syntax(7).

"""
import sys
import os
import re


def parse_c_escape(s, i):
    """Parse a C-style escape sequence starting at s[i] (char after backslash).
    Returns (character, new_index).
    """
    if i >= len(s):
        return '\\', i
    c = s[i]
    simple = {
        'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n',
        'r': '\r', 't': '\t', 'v': '\v', '\\': '\\',
        '"': '"', "'": "'", 's': ' '
    }
    if c in simple:
        return simple[c], i + 1
    if c == 'x' and i + 2 < len(s):
        hx = s[i + 1:i + 3]
        if all(ch in '0123456789abcdefABCDEF' for ch in hx):
            return chr(int(hx, 16)), i + 3
    if c in '01234567':
        end = i
        while end < len(s) and end < i + 3 and s[end] in '01234567':
            end += 1
        return chr(int(s[i:end], 8)), end
    if c == 'u' and i + 4 < len(s):
        hx = s[i + 1:i + 5]
        if len(hx) == 4 and all(ch in '0123456789abcdefABCDEF' for ch in hx):
            return chr(int(hx, 16)), i + 5
    if c == 'U' and i + 8 < len(s):
        hx = s[i + 1:i + 9]
        if len(hx) == 8 and all(ch in '0123456789abcdefABCDEF' for ch in hx):
            return chr(int(hx, 16)), i + 9
    # Unknown escape — return the character literally (with warning in real systemd)
    return c, i + 1


def tokenize(line):
    """Tokenize a string using systemd's quoting rules.

    Key rule: opening quotes are only recognized at the start of a token
    (at the beginning of the string or immediately after unquoted whitespace).
    A quote character appearing mid-token is treated as literal.
    """
    tokens = []
    current = []
    i = 0
    n = len(line)
    token_started = False

    while i < n:
        c = line[i]

        # Whitespace outside quotes: token boundary
        if c in (' ', '\t'):
            if token_started:
                tokens.append(''.join(current))
                current = []
                token_started = False
            i += 1
            continue

        # Double quote at token start
        if c == '"' and not token_started:
            token_started = True
            i += 1
            while i < n and line[i] != '"':
                if line[i] == '\\' and i + 1 < n:
                    esc, i = parse_c_escape(line, i + 1)
                    current.append(esc)
                else:
                    current.append(line[i])
                    i += 1
            if i < n:
                i += 1  # skip closing quote
            continue

        # Single quote at token start
        if c == "'" and not token_started:
            token_started = True
            i += 1
            while i < n and line[i] != "'":
                current.append(line[i])
                i += 1
            if i < n:
                i += 1  # skip closing quote
            continue

        # Backslash escape outside quotes
        if c == '\\' and i + 1 < n:
            esc, i = parse_c_escape(line, i + 1)
            current.append(esc)
            token_started = True
            continue

        # Regular character
        current.append(c)
        token_started = True
        i += 1

    if token_started:
        tokens.append(''.join(current))

    return tokens


def parse_env_line(line, env):
    """Parse an Environment= line and update the env dict."""
    prefix = 'Environment='
    if not line.startswith(prefix):
        return
    rest = line[len(prefix):]
    tokens = tokenize(rest)
    for token in tokens:
        eq = token.find('=')
        if eq >= 0:
            key = token[:eq]
            val = token[eq + 1:]
            env[key] = val


def detect_prefixes(s):
    """Detect and strip ExecStart prefixes from the command string.
    Returns (set_of_prefixes, remaining_string).
    """
    prefixes = []
    i = 0
    while i < len(s) and s[i] in '@-:+!|':
        prefixes.append(s[i])
        i += 1
    return set(prefixes), s[i:]


def expand_token(token, env):
    """Expand variables in a single token.

    If the entire token is a standalone $VARNAME, the value is re-tokenized
    (split on whitespace respecting quotes) producing zero or more results.

    Otherwise, ${VAR} and $VAR within a word are expanded inline (no splitting),
    and $$ becomes a literal $.
    """
    # Check for standalone $VARNAME pattern
    m = re.match(r'^\$([A-Za-z_][A-Za-z_0-9]*)$', token)
    if m:
        name = m.group(1)
        val = env.get(name, '')
        if not val:
            return []  # empty/undefined -> zero tokens
        return tokenize(val)

    # Inline expansion
    result = []
    i = 0
    while i < len(token):
        if token[i] == '$':
            if i + 1 < len(token) and token[i + 1] == '$':
                # $$ -> literal $
                result.append('$')
                i += 2
            elif i + 1 < len(token) and token[i + 1] == '{':
                # ${VAR} -> exact substitution
                end = token.find('}', i + 2)
                if end >= 0:
                    name = token[i + 2:end]
                    result.append(env.get(name, ''))
                    i = end + 1
                else:
                    result.append(token[i])
                    i += 1
            elif i + 1 < len(token) and (token[i + 1].isalpha() or token[i + 1] == '_'):
                # $VAR inline (part of larger token) -> expand like ${VAR}
                j = i + 1
                while j < len(token) and (token[j].isalnum() or token[j] == '_'):
                    j += 1
                name = token[i + 1:j]
                result.append(env.get(name, ''))
                i = j
            else:
                result.append(token[i])
                i += 1
        else:
            result.append(token[i])
            i += 1

    return [''.join(result)]


def expand_variables(tokens, env, suppress=False):
    """Expand environment variables in a list of tokens."""
    if suppress:
        return tokens
    result = []
    for token in tokens:
        result.extend(expand_token(token, env))
    return result


def resolve_command(cmd):
    """Resolve a simple command name to an absolute path."""
    if os.path.isabs(cmd):
        return cmd
    search_dirs = [
        '/usr/local/bin', '/usr/local/sbin',
        '/usr/bin', '/usr/sbin',
        '/bin', '/sbin'
    ]
    for d in search_dirs:
        path = os.path.join(d, cmd)
        if os.path.exists(path):
            return path
    return cmd  # return as-is if not found


def merge_continuation_lines(lines):
    """Merge lines ending with backslash (line continuation)."""
    merged = []
    buf = ''
    for line in lines:
        stripped = line.rstrip('\n\r')
        if stripped.endswith('\\'):
            buf += stripped[:-1] + ' '
        else:
            buf += stripped
            merged.append(buf)
            buf = ''
    if buf:
        merged.append(buf)
    return merged


def process(text):
    """Process input text and output tokenized ExecStart results."""
    env = {}
    lines = text.split('\n')
    merged = merge_continuation_lines(lines)

    exec_directives = ('ExecStart=', 'ExecStartPre=', 'ExecStartPost=')

    for line in merged:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue

        if line.startswith('Environment='):
            parse_env_line(line, env)
            continue

        is_exec = False
        for directive in exec_directives:
            if line.startswith(directive):
                is_exec = True
                value = line[len(directive):]
                break

        if not is_exec:
            continue

        # Detect and strip prefixes
        prefixes, remaining = detect_prefixes(value)

        # Tokenize the command line
        tokens = tokenize(remaining)
        if not tokens:
            continue

        cmd = tokens[0]
        args = tokens[1:]

        suppress = ':' in prefixes

        # Expand variables in command and args
        if not suppress:
            cmd_expanded = expand_token(cmd, env)
            cmd = cmd_expanded[0] if cmd_expanded else cmd
            args = expand_variables(args, env, suppress=False)

        # Resolve command path
        cmd = resolve_command(cmd)

        # Build output
        all_argv = [cmd] + args
        prefix_str = ''.join(sorted(prefixes)) if prefixes else 'NONE'

        print(f'PREFIXES:{prefix_str}')
        for idx, arg in enumerate(all_argv):
            print(f'ARGV[{idx}]:{arg}')
        print('---')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    process(text)
