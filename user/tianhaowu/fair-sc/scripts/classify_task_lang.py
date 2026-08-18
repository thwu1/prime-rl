#!/usr/bin/env python3
"""Classify a terminal-bench task by the PRIMARY programming language the solver
writes/edits. Signal priority (most reliable first):

  1. code files in solution/  (the reference answer — definitive)
  2. code targets written by solution/solve.sh heredocs (`cat > x.py`)
  3. code source files in environment/  (the code the solver edits/builds)
  4. interpreter/compiler invoked in solve.sh (python3, gcc, cargo, ...)
  5. language hints in task.toml tags/category
  -> else "shell/systems" (genuine ops / build-orchestration with no code written)

Key fix vs the naive heredoc-only method: build/edit-source tasks (e.g. a C solver
compiled via `make`, or a Python file patched in place) put their language in the
solution/ or environment/ *source files*, not in a solve.sh heredoc. We read those.
When several real languages are present we pick the most distinctive one (the C in a
C+Python task is the defining challenge), with shell/Python as the low-priority floor.

Usage: classify_task_lang.py <dataset.jsonl>   # prints language distribution
       (dataset lines are {"Path": "/.../task_dir"})
"""
import json, os, re, sys, glob
from collections import Counter

# whitelist: extension -> language (only real code counts; data/assets are ignored)
CODE_EXT = {
    '.py': 'Python', '.pyx': 'Python', '.c': 'C', '.h': 'C', '.cpp': 'C++', '.cc': 'C++',
    '.cxx': 'C++', '.hpp': 'C++', '.cu': 'C++', '.rs': 'Rust', '.go': 'Go', '.java': 'Java',
    '.rb': 'Ruby', '.js': 'JavaScript', '.mjs': 'JavaScript', '.ts': 'TypeScript',
    '.r': 'R', '.R': 'R', '.ml': 'OCaml', '.mli': 'OCaml', '.cbl': 'COBOL', '.cob': 'COBOL',
    '.v': 'Coq', '.scm': 'Scheme', '.rkt': 'Scheme', '.lisp': 'Lisp', '.clj': 'Clojure',
    '.hs': 'Haskell', '.f90': 'Fortran', '.f': 'Fortran', '.jl': 'Julia', '.php': 'PHP',
    '.pl': 'Perl', '.lua': 'Lua', '.scala': 'Scala', '.kt': 'Kotlin', '.cs': 'C#',
    '.swift': 'Swift', '.asm': 'Assembly', '.s': 'Assembly', '.sql': 'SQL',
    '.ttl': 'SPARQL', '.sparql': 'SPARQL', '.rq': 'SPARQL', '.red': 'Redcode', '.vim': 'Vim',
    '.tex': 'LaTeX', '.sh': 'Shell', '.bash': 'Shell',
}
# distinctive-first: when a task mixes languages, the earlier one is the defining challenge.
PRIORITY = ['Coq', 'COBOL', 'Scheme', 'Lisp', 'Clojure', 'Redcode', 'Haskell', 'Fortran',
            'Rust', 'OCaml', 'Go', 'Java', 'Scala', 'Kotlin', 'Swift', 'C#', 'Assembly',
            'C++', 'C', 'CUDA', 'Ruby', 'Perl', 'PHP', 'Lua', 'SQL', 'SPARQL', 'R',
            'TypeScript', 'JavaScript', 'Vim', 'LaTeX', 'Python', 'Shell']
PRANK = {l: i for i, l in enumerate(PRIORITY)}

# files that are harness/build, not the solution language
SKIP_NAMES = {'solve.sh', 'test.sh', 'run-tests.sh', 'run_tests.sh', 'test_outputs.py',
              'conftest.py', 'setup.sh', 'Makefile', 'makefile', 'CMakeLists.txt', 'plot.gp'}
TAG_LANG = {'rust': 'Rust', 'c-toolchain': 'C', 'cpp': 'C++', 'c++': 'C++', 'golang': 'Go',
            'ocaml': 'OCaml', 'coq': 'Coq', 'cobol': 'COBOL', 'scheme': 'Scheme',
            'haskell': 'Haskell', 'fortran': 'Fortran', 'java': 'Java', 'sparql': 'SPARQL'}


def _code_langs(files):
    out = Counter()
    for f in files:
        b = os.path.basename(f)
        if b in SKIP_NAMES or '/tests/' in f or b.startswith('test_'):
            continue
        e = os.path.splitext(f)[1]
        if e in CODE_EXT:
            out[CODE_EXT[e]] += 1
    return out


def _pick(langs):
    """Highest-priority (most distinctive) language present."""
    real = [l for l in langs if l != 'Shell']
    pool = real or list(langs)
    return min(pool, key=lambda l: PRANK.get(l, 999)) if pool else None


def classify(task_dir):
    if 'polyglot' in os.path.basename(task_dir).lower():
        return 'Polyglot'
    # 1. solution/ reference code (definitive)
    sol = _code_langs(glob.glob(f"{task_dir}/solution/**/*", recursive=True))
    if sol:
        return _pick(sol)
    # 2. solve.sh heredoc write-targets
    sh = ''
    p = f"{task_dir}/solution/solve.sh"
    if os.path.exists(p):
        try:
            sh = open(p, errors='ignore').read()
        except Exception:
            sh = ''
    hd = Counter()
    for m in re.finditer(r'>\s*\S+(\.[A-Za-z0-9]+)', sh):
        e = m.group(1)
        if e in CODE_EXT and CODE_EXT[e] != 'Shell':
            hd[CODE_EXT[e]] += 1
    if hd:
        return _pick(hd)
    # 3. environment/ source code (the code the solver edits/builds)
    env = _code_langs(glob.glob(f"{task_dir}/environment/**/*", recursive=True))
    if env:
        return _pick(env)
    # 4. interpreter/compiler in solve.sh
    for pat, lang in [('coqc', 'Coq'), ('cobc', 'COBOL'), (r'cargo\b', 'Rust'), ('rustc', 'Rust'),
                      ('gfortran', 'Fortran'), (r'Rscript\b', 'R'), ('guile', 'Scheme'),
                      (r'g\+\+', 'C++'), (r'clang\+\+', 'C++'), (r'ocaml', 'OCaml'),
                      (r'\bnode\b', 'JavaScript'), (r'go build', 'Go'), (r'go run', 'Go'),
                      ('javac', 'Java'), (r'\bgcc\b', 'C'), (r'\bclang\b', 'C'),
                      ('python3', 'Python'), (r'\bpython\b', 'Python')]:
        if re.search(pat, sh):
            return lang
    # 5. task.toml tag hints
    tt = f"{task_dir}/task.toml"
    if os.path.exists(tt):
        low = open(tt, errors='ignore').read().lower()
        for tag, lang in TAG_LANG.items():
            if tag in low:
                return lang
    return 'Shell/systems'


def main():
    ds = sys.argv[1]
    paths = list(dict.fromkeys(json.loads(l)['Path'] for l in open(ds) if l.strip()))
    c = Counter(classify(d) for d in paths)
    tot = sum(c.values())
    print(f"{len(paths)} unique tasks")
    for L, n in c.most_common():
        print(f"  {L:14} {n:6}  {n/tot*100:5.1f}%")


if __name__ == '__main__':
    main()
