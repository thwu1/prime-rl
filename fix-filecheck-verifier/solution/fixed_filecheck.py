#!/usr/bin/env python3
"""
Fixed FileCheck pattern matching verifier.

Bugs fixed:
  1. Parser: search for prefix anywhere in line (not just after ';')
  2. CHECK-NOT: defer evaluation until next positive match (bounded scope)
  3. CHECK-DAG: recursive backtracking with variable state save/restore
  4. Multi-prefix: merge directives from all prefixes sorted by line number
  5. CHECK-COUNT-N: match first forward, then N-1 consecutive (like CHECK-NEXT)
"""

import sys
import re
import argparse


class CheckDirective:
    def __init__(self, kind, pattern, lineno, prefix, count=1):
        self.kind = kind
        self.pattern = pattern
        self.lineno = lineno
        self.prefix = prefix
        self.count = count

    def __repr__(self):
        return f"CheckDirective({self.kind!r}, {self.pattern!r}, line={self.lineno})"


class FileCheckError(Exception):
    pass


class FileChecker:
    def __init__(self, match_full_lines=False):
        self.match_full_lines = match_full_lines
        self.variables = {}

    # -----------------------------------------------------------------
    # Parsing  (FIX 1: search anywhere in line, escape prefix)
    # -----------------------------------------------------------------

    def parse_check_file(self, content, prefix):
        """Parse check directives for a given prefix from the check file.

        FIX: Uses re.search (not re.match) and does not require a leading
        semicolon, so directives after //, #, or any other text are found.
        """
        directives = []
        directive_re = re.compile(
            re.escape(prefix) +
            r'(-NEXT|-NOT|-SAME|-LABEL|-DAG|-COUNT-(\d+))?:\s*(.*?)\s*$'
        )
        for lineno, line in enumerate(content.splitlines(), 1):
            m = directive_re.search(line)
            if m:
                suffix_str = m.group(1) or ''
                count_str = m.group(2)
                pat = m.group(3)

                if count_str:
                    kind = prefix + '-COUNT'
                    count = int(count_str)
                else:
                    kind = prefix + suffix_str
                    count = 1

                directives.append(
                    CheckDirective(kind, pat, lineno, prefix, count))
        return directives

    # -----------------------------------------------------------------
    # Pattern compilation
    # -----------------------------------------------------------------

    def compile_pattern(self, pattern_str):
        result = []
        i = 0
        n = len(pattern_str)
        while i < n:
            if i + 1 < n and pattern_str[i] == '{' and pattern_str[i + 1] == '{':
                close = pattern_str.find('}}', i + 2)
                if close == -1:
                    raise FileCheckError(
                        f"Unterminated '{{{{' in pattern: {pattern_str}")
                result.append(pattern_str[i + 2:close])
                i = close + 2
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
                            f"Undefined variable '{var_expr}'")
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
        regex = self.compile_pattern(pattern_str)
        m = re.search(regex, text)
        if m:
            self._capture_variables(pattern_str, m)
        return m

    def _capture_variables(self, pattern_str, match_obj):
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
                group_idx += len(re.findall(r'(?<!\\)\((?!\?)', regex_body))
                i = close + 2
            else:
                i += 1

    # -----------------------------------------------------------------
    # CHECK-NOT helper  (FIX 2)
    # -----------------------------------------------------------------

    def _check_pending_nots(self, pending_nots, input_lines, start, end):
        """Check that none of the pending NOT patterns match in [start, end).

        Returns (True, None) if clean, or (False, (directive, line_idx)).
        """
        for not_d in pending_nots:
            for j in range(start, end):
                saved = dict(self.variables)
                if self.try_match(not_d.pattern, input_lines[j]):
                    return False, (not_d, j)
                self.variables = saved
        return True, None

    # -----------------------------------------------------------------
    # CHECK-DAG helper  (FIX 3: backtracking)
    # -----------------------------------------------------------------

    def _match_dag_backtrack(self, dag_group, input_lines, search_range, used):
        """Recursively find a valid assignment of DAG patterns to input lines.

        Saves and restores self.variables on backtrack.
        """
        if not dag_group:
            return True

        d = dag_group[0]
        rest = dag_group[1:]

        for j in search_range:
            if j in used:
                continue
            saved_vars = dict(self.variables)
            if self.try_match(d.pattern, input_lines[j]):
                used.add(j)
                if self._match_dag_backtrack(rest, input_lines,
                                             search_range, used):
                    return True
                used.discard(j)
            self.variables = saved_vars

        return False

    # -----------------------------------------------------------------
    # Main matching loop
    # -----------------------------------------------------------------

    def run(self, directives, input_content):
        """Run matching of pre-parsed directives against input content.

        FIX 2: CHECK-NOT patterns are accumulated in pending_nots and
        verified only when the next positive directive establishes its
        match position, bounding the NOT scan range.

        FIX 5: CHECK-COUNT-N matches first forward, then N-1 consecutive.

        Returns 0 on success, 1 on failure.
        """
        if not directives:
            print("error: no check strings found", file=sys.stderr)
            return 1

        input_lines = input_content.splitlines()
        cur = 0
        pending_nots = []

        idx = 0
        while idx < len(directives):
            d = directives[idx]
            suffix = d.kind[len(d.prefix):]

            # -- CHECK-NOT: accumulate, don't verify yet ---------------
            if suffix == '-NOT':
                pending_nots.append(d)
                idx += 1
                continue

            # -- Positive directives -----------------------------------
            match_line = None

            if suffix == '-LABEL':
                for j in range(cur, len(input_lines)):
                    if self.try_match(d.pattern, input_lines[j]):
                        match_line = j
                        break
                if match_line is None:
                    self._error(d, input_lines, cur, "could not find label")
                    return 1

            elif suffix == '':
                for j in range(cur, len(input_lines)):
                    if self.try_match(d.pattern, input_lines[j]):
                        match_line = j
                        break
                if match_line is None:
                    self._error(d, input_lines, cur,
                                "expected string not found in input")
                    return 1

            elif suffix == '-COUNT':
                # FIX 5: Forward scan for first match
                match_line = None
                for j in range(cur, len(input_lines)):
                    if self.try_match(d.pattern, input_lines[j]):
                        match_line = j
                        break
                if match_line is None:
                    self._error(d, input_lines, cur,
                                f"CHECK-COUNT-{d.count}: pattern not found")
                    return 1

                # Check pending NOTs bounded by first match
                if pending_nots:
                    ok, fail = self._check_pending_nots(
                        pending_nots, input_lines, cur, match_line)
                    if not ok:
                        not_d, fail_line = fail
                        self._error(not_d, input_lines, fail_line,
                                    "CHECK-NOT: excluded string found")
                        return 1
                    pending_nots = []

                # Match remaining N-1 on consecutive lines
                cur = match_line + 1
                for k in range(1, d.count):
                    if cur >= len(input_lines):
                        self._error(d, input_lines, cur,
                                    f"CHECK-COUNT-{d.count}: reached end "
                                    f"at match {k + 1}/{d.count}")
                        return 1
                    if not self.try_match(d.pattern, input_lines[cur]):
                        self._error(d, input_lines, cur,
                                    f"CHECK-COUNT-{d.count}: mismatch at "
                                    f"line {cur + 1} (match {k + 1}/{d.count})")
                        return 1
                    cur += 1

                idx += 1
                continue

            elif suffix == '-NEXT':
                if cur >= len(input_lines):
                    self._error(d, input_lines, cur,
                                "CHECK-NEXT: reached end of input")
                    return 1
                if self.try_match(d.pattern, input_lines[cur]):
                    match_line = cur
                else:
                    self._error(d, input_lines, cur,
                                f"CHECK-NEXT: expected on line {cur + 1}")
                    return 1

            elif suffix == '-SAME':
                if cur == 0:
                    self._error(d, input_lines, 0,
                                "CHECK-SAME: requires previous match")
                    return 1
                prev = cur - 1
                if self.try_match(d.pattern, input_lines[prev]):
                    match_line = prev
                else:
                    self._error(d, input_lines, prev,
                                "CHECK-SAME: expected on same line")
                    return 1

            elif suffix == '-DAG':
                dag_group = [d]
                while (idx + 1 < len(directives) and
                       directives[idx + 1].kind.endswith('-DAG')):
                    idx += 1
                    dag_group.append(directives[idx])

                search_range = list(range(cur, len(input_lines)))
                used = set()
                if not self._match_dag_backtrack(dag_group, input_lines,
                                                 search_range, used):
                    self._error(dag_group[-1], input_lines, cur,
                                "CHECK-DAG: expected string not found")
                    return 1

                # Verify pending NOTs before the DAG region
                if used and pending_nots:
                    dag_start = min(used)
                    ok, fail = self._check_pending_nots(
                        pending_nots, input_lines, cur, dag_start)
                    if not ok:
                        not_d, fail_line = fail
                        self._error(not_d, input_lines, fail_line,
                                    "CHECK-NOT: excluded string found")
                        return 1
                    pending_nots = []

                if used:
                    cur = max(used) + 1
                idx += 1
                continue

            # -- Verify pending NOTs against range [cur, match_line) ---
            if match_line is not None and pending_nots:
                ok, fail = self._check_pending_nots(
                    pending_nots, input_lines, cur, match_line)
                if not ok:
                    not_d, fail_line = fail
                    self._error(not_d, input_lines, fail_line,
                                "CHECK-NOT: excluded string found in input")
                    return 1
                pending_nots = []

            # -- Advance scan cursor -----------------------------------
            if match_line is not None and suffix != '-SAME':
                cur = match_line + 1

            idx += 1

        # -- Trailing NOTs: check from cur to end of input -------------
        if pending_nots:
            ok, fail = self._check_pending_nots(
                pending_nots, input_lines, cur, len(input_lines))
            if not ok:
                not_d, fail_line = fail
                self._error(not_d, input_lines, fail_line,
                            "CHECK-NOT: excluded string found in input")
                return 1

        return 0

    # -----------------------------------------------------------------
    # Error reporting
    # -----------------------------------------------------------------

    def _error(self, directive, input_lines, pos, message):
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
# CLI  (FIX 4: merge prefixes into single pass)
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description='FileCheck-compatible pattern matching verifier')
    parser.add_argument('check_file')
    parser.add_argument('--input-file', default=None)
    parser.add_argument('--check-prefix', default=None)
    parser.add_argument('--check-prefixes', default=None)
    parser.add_argument('--match-full-lines', action='store_true')

    args = parser.parse_args()

    with open(args.check_file) as f:
        check_content = f.read()

    if args.input_file:
        with open(args.input_file) as f:
            input_content = f.read()
    else:
        input_content = sys.stdin.read()

    if args.check_prefixes:
        prefixes = [p.strip() for p in args.check_prefixes.split(',')]
    elif args.check_prefix:
        prefixes = [args.check_prefix]
    else:
        prefixes = ['CHECK']

    # FIX 4: Collect directives from ALL prefixes, sort by source line,
    # and run a single unified matching pass.
    checker = FileChecker(match_full_lines=args.match_full_lines)
    all_directives = []
    for prefix in prefixes:
        dirs = checker.parse_check_file(check_content, prefix)
        all_directives.extend(dirs)

    all_directives.sort(key=lambda d: d.lineno)

    if not all_directives:
        print("error: no check strings found with any prefix",
              file=sys.stderr)
        sys.exit(1)

    result = checker.run(all_directives, input_content)
    sys.exit(result)


if __name__ == '__main__':
    main()
