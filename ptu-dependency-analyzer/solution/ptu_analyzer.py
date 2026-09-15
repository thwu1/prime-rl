#!/usr/bin/env python3
"""
PTU Analyzer -- Analyzes clang-repl incremental compilation sessions.

Parses C++ code snippets (Partial Translation Units), builds a cross-PTU
dependency graph based on symbol definitions and references, and answers
structural queries about the graph.
"""


import sys
import re
import json
from collections import defaultdict, deque

import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser

# -- Tree-sitter initialization --

CPP_LANG = Language(tscpp.language())
_parser = Parser()
_parser.language = CPP_LANG


# -- Session file parsing --

def parse_session(path):
    """Parse a session file into {ptu_id: code_string}."""
    with open(path) as f:
        content = f.read()
    ptus = {}
    parts = re.split(r"#=== PTU (\d+) ===#\n?", content)
    for i in range(1, len(parts), 2):
        ptu_id = int(parts[i])
        ptus[ptu_id] = parts[i + 1]
    return ptus


# -- Symbol extraction --

def extract_definitions(root, code):
    """Extract top-level / namespace-scope symbol definitions from an AST.

    Uses tree-sitter for structured extraction, plus a regex fallback for
    using-declarations where the alias name is a primitive_type keyword
    (e.g. size_t) that tree-sitter cannot parse in type_alias_declaration.
    """
    defs = set()
    if root.type == "translation_unit":
        for child in root.children:
            _defs_from_node(child, defs)
    # Regex fallback for using-declarations that tree-sitter may misparse
    for m in re.finditer(r'\busing\s+(\w+)\s*=', code):
        defs.add(m.group(1))
    return defs


def _defs_from_node(node, defs):
    """Recursively extract definitions from a single top-level node."""
    ntype = node.type

    if ntype == "namespace_definition":
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                _defs_from_node(child, defs)

    elif ntype == "template_declaration":
        for child in node.children:
            if child.type != "template_parameter_list":
                _defs_from_node(child, defs)

    elif ntype in ("struct_specifier", "class_specifier", "enum_specifier"):
        name = node.child_by_field_name("name")
        if name:
            defs.add(name.text.decode())

    elif ntype in ("type_alias_declaration", "alias_declaration"):
        name = node.child_by_field_name("name")
        if name:
            defs.add(name.text.decode())

    elif ntype == "function_definition":
        declarator = node.child_by_field_name("declarator")
        if declarator:
            fname = _func_name(declarator)
            if fname:
                defs.add(fname)

    elif ntype == "declaration":
        for child in node.children:
            if child.type in (
                "struct_specifier",
                "class_specifier",
                "enum_specifier",
            ):
                _defs_from_node(child, defs)
            elif child.type in ("type_alias_declaration", "alias_declaration"):
                _defs_from_node(child, defs)
            else:
                vname = _decl_name(child)
                if vname:
                    defs.add(vname)


def _func_name(declarator):
    """Extract function name from a function_declarator."""
    if declarator.type == "function_declarator":
        inner = declarator.child_by_field_name("declarator")
        if inner and inner.type == "identifier":
            return inner.text.decode()
    return None


def _decl_name(node):
    """Extract variable name from a declarator-like node."""
    ntype = node.type
    if ntype == "identifier":
        return node.text.decode()
    if ntype == "init_declarator":
        d = node.child_by_field_name("declarator")
        if d:
            return _decl_name(d)
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode()
    if ntype == "function_declarator":
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode()
    if ntype in ("pointer_declarator", "reference_declarator"):
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode()
    return None


def collect_identifiers(root):
    """Collect all type_identifier, identifier, and primitive_type tokens.

    Excludes field_identifier (member access / field declarations) and
    namespace_identifier nodes, which naturally filters out member
    references and namespace qualifiers.

    primitive_type is included because user code may redefine names like
    size_t that tree-sitter classifies as primitive_type.  Built-in
    primitives (int, double, ...) are harmlessly collected since they
    never appear in the symbol table.
    """
    names = set()
    _walk_ids(root, names)
    return names


def _walk_ids(node, names):
    if node.type == "type_identifier":
        names.add(node.text.decode())
    elif node.type == "identifier":
        names.add(node.text.decode())
    elif node.type == "primitive_type":
        names.add(node.text.decode())
    # field_identifier and namespace_identifier are deliberately excluded
    for child in node.children:
        _walk_ids(child, names)


# -- Dependency graph construction --

def build_graph(ptus):
    """Build dependency graph.

    Returns (deps, rdeps, all_ids) where deps/rdeps map ptu_id -> set of ids.
    """
    defined = {}
    all_idents = {}

    for pid in sorted(ptus):
        code = ptus[pid]
        tree = _parser.parse(bytes(code, "utf-8"))
        defined[pid] = extract_definitions(tree.root_node, code)
        # Tree-sitter identifier collection
        ts_idents = collect_identifiers(tree.root_node)
        # Raw regex tokenization as fallback — catches references that
        # tree-sitter might drop inside ERROR nodes during error recovery
        clean = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        clean = re.sub(r'//.*', '', clean)
        clean = re.sub(r'"[^"]*"', '', clean)
        clean = re.sub(r"'[^']*'", '', clean)
        raw_tokens = set(re.findall(r'\b([A-Za-z_]\w*)\b', clean))
        all_idents[pid] = ts_idents | raw_tokens

    # Global symbol table: name -> earliest defining PTU
    symtab = {}
    for pid in sorted(ptus):
        for name in defined[pid]:
            if name not in symtab:
                symtab[name] = pid

    deps = defaultdict(set)
    rdeps = defaultdict(set)

    for pid in sorted(ptus):
        for name in all_idents[pid]:
            if name in symtab:
                src = symtab[name]
                if src != pid:
                    deps[pid].add(src)
                    rdeps[src].add(pid)

    return deps, rdeps, sorted(ptus)


# -- Query implementations --

def cmd_deps(deps, pid):
    return {"deps": sorted(deps.get(pid, set()))}


def cmd_rdeps(rdeps, pid):
    return {"rdeps": sorted(rdeps.get(pid, set()))}


def cmd_undo_cascade(rdeps, pid):
    cascade = set()
    queue = deque([pid])
    while queue:
        cur = queue.popleft()
        for r in rdeps.get(cur, set()):
            if r not in cascade:
                cascade.add(r)
                queue.append(r)
    return {"cascade": sorted(cascade)}


def cmd_minimal_replay(deps, pid):
    needed = set()
    queue = deque([pid])
    while queue:
        cur = queue.popleft()
        if cur not in needed:
            needed.add(cur)
            for d in deps.get(cur, set()):
                if d not in needed:
                    queue.append(d)
    return {"replay": sorted(needed)}


def cmd_dead_ptus(rdeps, all_ids):
    return {"dead": [p for p in all_ids if not rdeps.get(p, set())]}


def cmd_critical_path(deps, all_ids):
    memo = {}

    def longest(pid):
        if pid in memo:
            return memo[pid]
        dep_list = sorted(deps.get(pid, set()))
        if not dep_list:
            memo[pid] = (1, [pid])
            return memo[pid]
        best_len = 0
        best_path = []
        for d in dep_list:
            dlen, dpath = longest(d)
            if dlen > best_len or (dlen == best_len and dpath < best_path):
                best_len = dlen
                best_path = dpath
        memo[pid] = (best_len + 1, best_path + [pid])
        return memo[pid]

    best_len = 0
    best_path = []
    for pid in all_ids:
        plen, ppath = longest(pid)
        if plen > best_len or (plen == best_len and ppath < best_path):
            best_len = plen
            best_path = ppath
    return {"path": best_path, "length": best_len}


def cmd_compilation_tiers(deps, all_ids):
    """Compute topological layering of the dependency DAG.

    Tier 0 contains PTUs with no dependencies.
    Tier k contains PTUs whose longest dependency chain has k edges.
    """
    levels = {}

    def compute_level(pid):
        if pid in levels:
            return levels[pid]
        dep_set = deps.get(pid, set())
        if not dep_set:
            levels[pid] = 0
            return 0
        levels[pid] = max(compute_level(d) for d in dep_set) + 1
        return levels[pid]

    for pid in all_ids:
        compute_level(pid)

    if not levels:
        return {"tiers": []}

    max_level = max(levels.values())
    tiers = []
    for lv in range(max_level + 1):
        tier = sorted(p for p in all_ids if levels[p] == lv)
        tiers.append(tier)

    return {"tiers": tiers}


# -- Main --

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 ptu_analyzer.py <session> <command> [arg]",
              file=sys.stderr)
        sys.exit(1)

    session_file = sys.argv[1]
    command = sys.argv[2]

    ptus = parse_session(session_file)
    deps, rdeps, all_ids = build_graph(ptus)

    handlers = {
        "deps":              lambda: cmd_deps(deps, int(sys.argv[3])),
        "rdeps":             lambda: cmd_rdeps(rdeps, int(sys.argv[3])),
        "undo-cascade":      lambda: cmd_undo_cascade(rdeps, int(sys.argv[3])),
        "minimal-replay":    lambda: cmd_minimal_replay(deps, int(sys.argv[3])),
        "dead-ptus":         lambda: cmd_dead_ptus(rdeps, all_ids),
        "critical-path":     lambda: cmd_critical_path(deps, all_ids),
        "compilation-tiers": lambda: cmd_compilation_tiers(deps, all_ids),
    }

    if command not in handlers:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(handlers[command]()))


if __name__ == "__main__":
    main()
