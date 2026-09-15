#!/usr/bin/env python3
"""
Compilation error mining pipeline — solution implementation.


Extracts, classifies, and analyzes C/C++ compilation errors from CI logs.
Performs include-dependency analysis and dependency-aware patch minimization.
Cross-validates dependency closures against compiler-generated dependency data.
"""

import re
import os
import json
import subprocess

# ============================================================
# 1. TIMESTAMP AND NOISE HANDLING
# ============================================================

TIMESTAMP_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s?(.*)'
)

NOISE_PATTERNS = [
    re.compile(r'##\['),
    re.compile(r'\[\s*\d+%\]\s*Building'),
    re.compile(r'^make\['),
    re.compile(r'^make:'),
    re.compile(r'\*\*\*'),
    re.compile(r'Configuring done'),
    re.compile(r'Generating done'),
    re.compile(r'Build files have been written'),
    re.compile(r'The CXX compiler identification'),
    re.compile(r'apt-get'),
    re.compile(r'Setting up\s'),
    re.compile(r'^\s*Installing\s'),
    re.compile(r'^\s*Done\.'),
    re.compile(r'^\s*with:\s*$'),
    re.compile(r'^\s*repository:'),
    re.compile(r'^\s*ref:'),
    re.compile(r'Using compiler:'),
    re.compile(r'Build type:'),
    re.compile(r'Process completed'),
]

ERROR_RE = re.compile(
    r'(?P<file>[^\s:]+\.(?:cpp|cc|c|h|hpp|hxx))'
    r':(?P<line>\d+):(?P<col>\d+):\s+error:\s+(?P<message>.+)'
)

WARNING_RE = re.compile(r':\s+warning:')
INCLUDE_TRACE_RE = re.compile(r'In file included from\s+(.+)')
NOTE_RE = re.compile(r':\s+note:\s+')


def strip_timestamp(line):
    """Remove GitHub Actions timestamp prefix."""
    m = TIMESTAMP_RE.match(line)
    return m.group(1) if m else line


def is_noise(line):
    """Check if line is CI noise that should be excluded."""
    for pat in NOISE_PATTERNS:
        if pat.search(line):
            return True
    return False


def is_warning_only(line):
    """Check if line is a warning but not an error."""
    return bool(WARNING_RE.search(line)) and not re.search(r':\s+error:', line)


# ============================================================
# 2. ERROR CLASSIFICATION TAXONOMY
# ============================================================

# Priority ordered: first matching category wins.
# Patterns are designed so that e.g. template-related "no type named"
# messages don't incorrectly match declaration patterns.
TAXONOMY = [
    ('declaration', [
        re.compile(r'was not declared in this scope', re.I),
        re.compile(r'undeclared identifier', re.I),
        re.compile(r'use of undeclared', re.I),
        re.compile(r'undefined reference', re.I),
        re.compile(r'unknown type name', re.I),
        re.compile(r'has not been declared', re.I),
    ]),
    ('type', [
        re.compile(r'invalid conversion', re.I),
        re.compile(r'cannot convert', re.I),
        re.compile(r'incompatible type', re.I),
        re.compile(r'no viable conversion', re.I),
        re.compile(r'cannot initialize', re.I),
        re.compile(r'incomplete type', re.I),
        re.compile(r'invalid operands', re.I),
    ]),
    ('syntax', [
        re.compile(r"expected\s*'[;{})\]]'", re.I),
        re.compile(r'expected expression', re.I),
        re.compile(r'expected\s+(declaration|statement|identifier)', re.I),
        re.compile(r'unexpected token', re.I),
        re.compile(r'extraneous\s', re.I),
    ]),
    ('template', [
        re.compile(
            r"no type named\s+'.*?'\s+in\s+'.*?"
            r"(?:std|iterator|allocator|traits)",
            re.I
        ),
        re.compile(r'template argument', re.I),
        re.compile(r'template parameter', re.I),
        re.compile(r'instantiation of', re.I),
        re.compile(r'iterator_traits', re.I),
    ]),
    ('member', [
        re.compile(r'no member named', re.I),
        re.compile(r'has no member', re.I),
        re.compile(r'is a private member', re.I),
        re.compile(r'is a protected member', re.I),
        re.compile(r'cannot access.*member', re.I),
    ]),
    ('function', [
        re.compile(r'no matching function', re.I),
        re.compile(r'too many arguments', re.I),
        re.compile(r'too few arguments', re.I),
        re.compile(r'no viable overloaded', re.I),
        re.compile(r'ambiguous call', re.I),
    ]),
    ('semantic', [
        re.compile(r'static_assert', re.I),
        re.compile(r'constexpr.*not', re.I),
        re.compile(r'non-constant', re.I),
        re.compile(r'not assignable', re.I),
        re.compile(r'invalid use of', re.I),
    ]),
]


def classify_error(message):
    """Classify an error message using priority-ordered taxonomy."""
    for category, patterns in TAXONOMY:
        for pat in patterns:
            if pat.search(message):
                return category
    return 'unknown'


# ============================================================
# 3. CI PATH HANDLING
# ============================================================

def detect_ci_prefix(lines):
    """Auto-detect the CI path prefix from compiler output."""
    for line in lines:
        m = ERROR_RE.search(line)
        if m:
            filepath = m.group('file')
            pm = re.match(r'(/home/runner/work/[^/]+/)', filepath)
            if pm:
                return pm.group(1)
    return ''


def to_relative(path, ci_prefix):
    """Convert CI absolute path to project-relative path."""
    if ci_prefix and path.startswith(ci_prefix):
        return path[len(ci_prefix):]
    return path


# ============================================================
# 4. LOG EXTRACTION
# ============================================================

def parse_log_file(log_path):
    """Parse a single CI log file and extract structured error records."""
    with open(log_path, encoding='utf-8', errors='replace') as f:
        raw_lines = f.readlines()

    # Strip timestamps from all lines
    lines = [strip_timestamp(line.rstrip('\n\r')) for line in raw_lines]

    # Detect CI path prefix
    ci_prefix = detect_ci_prefix(lines)
    log_name = os.path.basename(log_path)

    errors = []

    for i, line in enumerate(lines):
        # Skip noise and warning-only lines
        if is_noise(line) or is_warning_only(line):
            continue

        m = ERROR_RE.search(line)
        if not m:
            continue

        error_file = to_relative(m.group('file'), ci_prefix)
        error_line = int(m.group('line'))
        error_col = int(m.group('col'))
        error_msg = m.group('message').strip()

        # --- Backward context (up to 20 lines) ---
        include_trace = []
        pre_notes = []
        for j in range(i - 1, max(-1, i - 21), -1):
            if j < 0:
                break
            bwd = lines[j]
            # Stop at previous error or noise boundary
            if ERROR_RE.search(bwd):
                break
            if is_noise(bwd):
                break
            if INCLUDE_TRACE_RE.search(bwd):
                include_trace.insert(0, bwd.strip())
            elif NOTE_RE.search(bwd):
                pre_notes.insert(0, bwd.strip())

        # --- Forward context (up to 15 lines) ---
        post_notes = []
        for j in range(i + 1, min(len(lines), i + 16)):
            fwd = lines[j]
            # Stop at next error or noise boundary
            if ERROR_RE.search(fwd):
                break
            if is_noise(fwd):
                break
            if NOTE_RE.search(fwd):
                post_notes.append(fwd.strip())

        errors.append({
            'file': error_file,
            'line': error_line,
            'column': error_col,
            'message': error_msg,
            'category': classify_error(error_msg),
            'context': {
                'include_trace': include_trace,
                'notes': pre_notes + post_notes,
            },
            'source_logs': [log_name],
        })

    return errors


# ============================================================
# 5. DEDUPLICATION
# ============================================================

def deduplicate_errors(all_errors):
    """Deduplicate errors by (file, line, message). Merge source_logs and context."""
    seen = {}

    for err in all_errors:
        key = (err['file'], err['line'], err['message'])
        if key in seen:
            existing = seen[key]
            # Merge source logs
            for log in err['source_logs']:
                if log not in existing['source_logs']:
                    existing['source_logs'].append(log)
            # Keep richer context
            if not existing['context']['include_trace'] and err['context']['include_trace']:
                existing['context']['include_trace'] = err['context']['include_trace']
            if not existing['context']['notes'] and err['context']['notes']:
                existing['context']['notes'] = err['context']['notes']
        else:
            entry = dict(err)
            entry['source_logs'] = list(err['source_logs'])
            entry['context'] = {
                'include_trace': list(err['context']['include_trace']),
                'notes': list(err['context']['notes']),
            }
            seen[key] = entry

    return list(seen.values())


# ============================================================
# 6. DEPENDENCY GRAPH
# ============================================================

INCLUDE_DIRECTIVE_RE = re.compile(r'^\s*#include\s+"([^"]+)"')


def build_dependency_graph(project_dir):
    """Parse source and header files to build #include dependency graph."""
    project_dir = os.path.abspath(project_dir)

    # Index all C/C++ files by basename for include resolution
    basename_to_relpath = {}
    all_relpaths = set()

    for root, dirs, files in os.walk(project_dir):
        for fname in files:
            if fname.endswith(('.cpp', '.cc', '.c', '.h', '.hpp', '.hxx')):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, project_dir)
                basename_to_relpath[fname] = rel
                all_relpaths.add(rel)

    # Parse #include "..." directives from each file
    graph = {}
    for root, dirs, files in os.walk(project_dir):
        for fname in files:
            if not fname.endswith(('.cpp', '.cc', '.c', '.h', '.hpp', '.hxx')):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, project_dir)

            includes = []
            with open(full, encoding='utf-8', errors='replace') as f:
                for file_line in f:
                    m = INCLUDE_DIRECTIVE_RE.match(file_line)
                    if m:
                        inc_name = m.group(1)
                        # Resolve: first by basename, then by exact relative path
                        if inc_name in basename_to_relpath:
                            resolved = basename_to_relpath[inc_name]
                            if resolved not in includes:
                                includes.append(resolved)
                        elif inc_name in all_relpaths:
                            if inc_name not in includes:
                                includes.append(inc_name)

            graph[rel] = includes

    return graph


def compute_transitive_closure(graph, start):
    """Compute all files transitively reachable from start (including self)."""
    visited = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        for dep in graph.get(node, []):
            if dep not in visited:
                stack.append(dep)
    return visited


# ============================================================
# 7. PATCH PARSING AND MINIMIZATION
# ============================================================

DIFF_HEADER_RE = re.compile(r'^diff --git a/(.+?)\s+b/(.+)')


def parse_patch_files(patch_path):
    """Extract list of modified file paths from unified diff."""
    modified = []
    with open(patch_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = DIFF_HEADER_RE.match(line.strip())
            if m:
                target = m.group(2)
                if target not in modified:
                    modified.append(target)
    return modified


# ============================================================
# 8. COMPILER DEPENDENCY VERIFICATION
# ============================================================

def get_compiler_deps(project_dir, source_file, include_dir):
    """Get the compiler's own dependency list using g++ -MM.

    Returns a list of project-relative paths for all local headers
    that the given source file depends on (directly or transitively).
    """
    try:
        result = subprocess.run(
            ['g++', '-MM', '-I' + include_dir, '-std=c++17', source_file],
            capture_output=True, text=True, timeout=30,
            cwd=project_dir
        )
        if result.returncode != 0:
            return []

        # Parse Makefile-format output: target.o: dep1 dep2 \
        #                                         dep3 dep4
        output = result.stdout.replace('\\\n', ' ')
        parts = output.split(':', 1)
        if len(parts) < 2:
            return []

        deps = parts[1].strip().split()
        # Filter out the source file itself
        rel_deps = []
        for dep in deps:
            dep = dep.strip()
            if not dep:
                continue
            if dep == source_file:
                continue
            rel_deps.append(dep)

        return rel_deps
    except Exception:
        return []


# ============================================================
# 9. MAIN PIPELINE
# ============================================================

def main():
    log_dir = '/app/ci_logs'
    project_dir = '/app/project'
    patch_path = '/app/patches/candidate_fix.patch'
    output_path = '/app/output/report.json'

    # Step 1: Parse all CI log files
    all_errors = []
    for log_file in sorted(os.listdir(log_dir)):
        if log_file.endswith('.log'):
            path = os.path.join(log_dir, log_file)
            errors = parse_log_file(path)
            all_errors.extend(errors)
            print(f"  Parsed {log_file}: {len(errors)} errors")

    print(f"Total raw errors: {len(all_errors)}")

    # Step 2: Deduplicate
    unique_errors = deduplicate_errors(all_errors)
    print(f"Unique errors after dedup: {len(unique_errors)}")

    # Step 3: Build dependency graph from project source
    dep_graph = build_dependency_graph(project_dir)
    print(f"Dependency graph: {len(dep_graph)} files")

    # Step 4: Compute transitive closures for each error file
    error_files = sorted(set(err['file'] for err in unique_errors))
    closures = {}
    for ef in error_files:
        closure = compute_transitive_closure(dep_graph, ef)
        closures[ef] = sorted(closure)
        print(f"  Closure({ef}): {len(closure)} files")

    # Step 5: Parse patch and compute dependency-aware minimization
    patch_files = parse_patch_files(patch_path)
    print(f"Patch modifies {len(patch_files)} files: {patch_files}")

    minimizations = {}
    for ef in error_files:
        closure_set = set(closures[ef])
        minimized = [f for f in patch_files if f in closure_set]
        minimizations[ef] = {
            'original_files': list(patch_files),
            'minimized_files': minimized,
        }
        removed = len(patch_files) - len(minimized)
        print(f"  Minimize({ef}): {len(minimized)}/{len(patch_files)} "
              f"files kept, {removed} removed")

    # Step 6: Get compiler-verified dependencies
    compiler_deps = {}
    include_dir = os.path.join(project_dir, 'include')
    for ef in error_files:
        src_path = os.path.join(project_dir, ef)
        if os.path.exists(src_path):
            deps = get_compiler_deps(project_dir, ef, include_dir)
            compiler_deps[ef] = deps
            print(f"  Compiler deps({ef}): {len(deps)} files")

    # Step 7: Write structured output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    report = {
        'errors': unique_errors,
        'dependency_graph': dep_graph,
        'dependency_closures': closures,
        'compiler_deps': compiler_deps,
        'patch_minimizations': minimizations,
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {output_path}")
    print(f"\nExtracted errors:")
    for err in unique_errors:
        print(f"  [{err['category']:>11s}] {err['file']}:{err['line']} "
              f"- {err['message'][:70]}")
        if err['source_logs']:
            print(f"               logs: {err['source_logs']}")


if __name__ == '__main__':
    main()
