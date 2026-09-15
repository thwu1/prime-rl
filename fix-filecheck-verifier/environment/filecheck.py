#!/usr/bin/env python3
"""
A subset implementation of LLVM's FileCheck pattern matching verifier.

Supports: CHECK, CHECK-NEXT, CHECK-NOT, CHECK-SAME, CHECK-LABEL, CHECK-DAG,
          CHECK-COUNT-<N>, {{regex}}, [[VAR:regex]], [[VAR]],
          --check-prefix, --check-prefixes, --input-file, --match-full-lines
"""

import sys
import re
import argparse


class CheckDirective:
    """Represents a single check directive parsed from the check file."""

    def __init__(self, kind, pattern, lineno, prefix, count=1):
        self.kind = kind
        self.pattern = pattern
        self.lineno = lineno
        self.prefix = prefix
        self.count = count  # For CHECK-COUNT-<N>

    def __repr__(self):
        return f"CheckDirective({self.kind!r}, {self.pattern!r}, line={self.lineno})"


class FileCheckError(Exception):
    """Raised on unrecoverable pattern compilation errors."""
    pass


class FileChecker:
    """Core matching engine."""

    def __init__(self, check_prefix="CHECK", match_full_lines=False):
        self.check_prefix = check_prefix
        self.match_full_lines = match_full_lines
        self.variables = {}

    def parse_check_file(self, content):
        """Parse check directives from the check file content.

        Scans each line for directives of the form:
            ; PREFIX(-SUFFIX)?: pattern
        """
        directives = []
        prefix = self.check_prefix
        # Build the directive-matching regex.
        # Lines must start with '; ' followed by the prefix.
        directive_re = re.compile(
            r'^;\s*' + re.escape(prefix) +
            r'(-NEXT|-NOT|-SAME|-LABEL|-DAG|-COUNT-(\d+))?:\s*(.*?)\s*$'
        )
        for lineno, line in enumerate(content.splitlines(), 1):
            m = directive_re.match(line)
            if m:
                suffix = m.group(1) or ''
                count_str = m.group(2)
                pat = m.group(3)

                if count_str:
                    kind = prefix + '-COUNT'
                    count = int(count_str)
                else:
                    kind = prefix + suffix
                    count = 1

                directives.append(
                    CheckDirective(kind, pat, lineno, prefix, count))
        return directives

    # -----------------------------------------------------------------
    # Pattern compilation: FileCheck pattern -> Python regex
    # -----------------------------------------------------------------

    def compile_pattern(self, pattern_str):
        """Convert a FileCheck pattern string to a Python regex string.

        Handles:
          {{regex}}      - inline regex
          [[VAR:regex]]  - variable capture
          [[VAR]]        - variable substitution
          literal text   - escaped for regex
        """
        result = []
        i = 0
        n = len(pattern_str)
        while i < n:
            # Inline regex: {{...}}
            if i + 1 < n and pattern_str[i] == '{' and pattern_str[i + 1] == '{':
                close = pattern_str.find('}}', i + 2)
                if close == -1:
                    raise FileCheckError(
                        f"Unterminated '{{{{' in pattern: {pattern_str}")
                regex_body = pattern_str[i + 2:close]
                result.append(regex_body)
                i = close + 2
            # Variable capture / substitution: [[...]]
            elif i + 1 < n and pattern_str[i] == '[' and pattern_str[i + 1] == '[':
                close = pattern_str.find(']]', i + 2)
                if close == -1:
                    raise FileCheckError(
                        f"Unterminated '[[' in pattern: {pattern_str}")
                var_expr = pattern_str[i + 2:close]
                if ':' in var_expr:
                    var_name, var_regex = var_expr.split(':', 1)
                    result.append(f'({var_regex})')
                else:
                    if var_expr not in self.variables:
                        raise FileCheckError(
                            f"Undefined variable '{var_expr}' in pattern: "
                            f"{pattern_str}")
                    result.append(re.escape(self.variables[var_expr]))
                i = close + 2
            else:
                result.append(re.escape(pattern_str[i]))
                i += 1

        regex = ''.join(result)
        if self.match_full_lines:
            regex = r'^\s*' + regex + r'\s*$'
        return regex

    def try_match(self, pattern_str, text):
        """Try to match a FileCheck pattern against a single line of text.

        Returns the match object on success, None on failure.
        Side effect: captures variables on successful match.
        """
        regex = self.compile_pattern(pattern_str)
        m = re.search(regex, text)
        if m:
            self._capture_variables(pattern_str, m)
        return m

    def _capture_variables(self, pattern_str, match_obj):
        """Extract captured variable values from a successful match."""
        group_idx = 1
        i = 0
        n = len(pattern_str)
        while i < n:
            if i + 1 < n and pattern_str[i] == '[' and pattern_str[i + 1] == '[':
                close = pattern_str.find(']]', i + 2)
                var_expr = pattern_str[i + 2:close]
                if ':' in var_expr:
                    var_name = var_expr.split(':', 1)[0]
                    if group_idx <= len(match_obj.groups()):
                        self.variables[var_name] = match_obj.group(group_idx)
                    group_idx += 1
                i = close + 2
            elif i + 1 < n and pattern_str[i] == '{' and pattern_str[i + 1] == '{':
                close = pattern_str.find('}}', i + 2)
                regex_body = pattern_str[i + 2:close]
                # Count unescaped capturing groups inside the inline regex
                group_idx += len(re.findall(r'(?<!\\)\((?!\?)', regex_body))
                i = close + 2
            else:
                i += 1

    # -----------------------------------------------------------------
    # Main matching loop
    # -----------------------------------------------------------------

    def run(self, check_content, input_content):
        """Run FileCheck: match directives against input.

        Returns 0 on success, 1 on failure.
        """
        directives = self.parse_check_file(check_content)
        if not directives:
            print(
                f"{self.check_prefix}: error: no check strings found with "
                f"prefix '{self.check_prefix}'",
                file=sys.stderr)
            return 1

        input_lines = input_content.splitlines()
        cur = 0  # current scan position in input_lines

        idx = 0
        while idx < len(directives):
            d = directives[idx]
            suffix = d.kind[len(d.prefix):]

            if suffix == '-LABEL':
                found = False
                for j in range(cur, len(input_lines)):
                    if self.try_match(d.pattern, input_lines[j]):
                        cur = j + 1
                        found = True
                        break
                if not found:
                    self._error(d, input_lines, cur, "could not find label")
                    return 1

            elif suffix == '':
                # Plain CHECK: search forward
                found = False
                for j in range(cur, len(input_lines)):
                    if self.try_match(d.pattern, input_lines[j]):
                        cur = j + 1
                        found = True
                        break
                if not found:
                    self._error(d, input_lines, cur,
                                "expected string not found in input")
                    return 1

            elif suffix == '-COUNT':
                # CHECK-COUNT-<N>: search forward for first match only
                found = False
                for j in range(cur, len(input_lines)):
                    if self.try_match(d.pattern, input_lines[j]):
                        cur = j + 1
                        found = True
                        break
                if not found:
                    self._error(d, input_lines, cur,
                                f"CHECK-COUNT-{d.count}: pattern not found")
                    return 1

            elif suffix == '-NEXT':
                if cur >= len(input_lines):
                    self._error(d, input_lines, cur,
                                "CHECK-NEXT: reached end of input")
                    return 1
                if not self.try_match(d.pattern, input_lines[cur]):
                    self._error(d, input_lines, cur,
                                f"CHECK-NEXT: expected on line {cur + 1}")
                    return 1
                cur += 1

            elif suffix == '-SAME':
                if cur == 0:
                    self._error(d, input_lines, 0,
                                "CHECK-SAME: requires previous match")
                    return 1
                prev = cur - 1
                if not self.try_match(d.pattern, input_lines[prev]):
                    self._error(d, input_lines, prev,
                                "CHECK-SAME: expected on same line as "
                                "previous match")
                    return 1

            elif suffix == '-NOT':
                # CHECK-NOT: pattern must NOT appear from current position
                # to the end of input.
                scan_end = len(input_lines)
                for j in range(cur, scan_end):
                    if self.try_match(d.pattern, input_lines[j]):
                        self._error(d, input_lines, j,
                                    "CHECK-NOT: excluded string found "
                                    "in input")
                        return 1

            elif suffix == '-DAG':
                # Collect consecutive DAG directives into a group.
                dag_group = [d]
                while (idx + 1 < len(directives) and
                       directives[idx + 1].kind.endswith('-DAG')):
                    idx += 1
                    dag_group.append(directives[idx])

                # Match each DAG pattern greedily against remaining lines.
                search_lines = list(range(cur, len(input_lines)))
                used = set()
                for dag_d in dag_group:
                    matched = False
                    for j in search_lines:
                        if j in used:
                            continue
                        if self.try_match(dag_d.pattern, input_lines[j]):
                            used.add(j)
                            matched = True
                            break
                    if not matched:
                        self._error(dag_d, input_lines, cur,
                                    "CHECK-DAG: expected string not found "
                                    "in input")
                        return 1

                if used:
                    cur = max(used) + 1

            idx += 1

        return 0

    # -----------------------------------------------------------------
    # Error reporting
    # -----------------------------------------------------------------

    def _error(self, directive, input_lines, pos, message):
        """Report a match failure with surrounding input context."""
        print(f"error: {message}", file=sys.stderr)
        print(f"  from check file, line {directive.lineno}:", file=sys.stderr)
        print(f"    {directive.kind}: {directive.pattern}", file=sys.stderr)
        if input_lines:
            start = max(0, pos - 2)
            end = min(len(input_lines), pos + 3)
            print(f"  input context (around line {pos + 1}):", file=sys.stderr)
            for k in range(start, end):
                arrow = " >>> " if k == pos else "     "
                print(f"  {arrow}{k + 1}: {input_lines[k]}", file=sys.stderr)


# =====================================================================
# CLI entry point
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description='FileCheck-compatible pattern matching verifier')
    parser.add_argument('check_file',
                        help='File containing check directives')
    parser.add_argument('--input-file', default=None,
                        help='Input file to verify (reads stdin if omitted)')
    parser.add_argument('--check-prefix', default=None,
                        help='Use this prefix instead of CHECK')
    parser.add_argument('--check-prefixes', default=None,
                        help='Comma-separated list of check prefixes')
    parser.add_argument('--match-full-lines', action='store_true',
                        help='Require full line matches for positive patterns')

    args = parser.parse_args()

    with open(args.check_file) as f:
        check_content = f.read()

    if args.input_file:
        with open(args.input_file) as f:
            input_content = f.read()
    else:
        input_content = sys.stdin.read()

    # Determine which prefixes to use.
    if args.check_prefixes:
        prefixes = [p.strip() for p in args.check_prefixes.split(',')]
    elif args.check_prefix:
        prefixes = [args.check_prefix]
    else:
        prefixes = ['CHECK']

    # Run each prefix as an independent, full pass over the input.
    for prefix in prefixes:
        checker = FileChecker(check_prefix=prefix,
                              match_full_lines=args.match_full_lines)
        result = checker.run(check_content, input_content)
        if result != 0:
            sys.exit(result)

    sys.exit(0)


if __name__ == '__main__':
    main()
