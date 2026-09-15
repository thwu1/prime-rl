"""
Function dependency analyzer for Python projects.
Classifies functions by test-driven reachability through call graphs.
"""

import ast
import os
from collections import deque


def _iter_py_files(directory):
    for root, _, files in os.walk(directory):
        for name in files:
            if name.endswith('.py'):
                yield os.path.join(root, name)


def _relative_module(filepath, project_dir):
    rel = os.path.relpath(filepath, project_dir)
    mod = rel.replace(os.sep, '.').replace('/', '.')
    if mod.endswith('.py'):
        mod = mod[:-3]
    if mod.endswith('.__init__'):
        mod = mod[:-9]
    if mod == '__init__':
        mod = ''
    return mod


def _resolve_absolute_module(module_str, project_dir, package_name):
    if not module_str.startswith(package_name):
        return None
    suffix = module_str[len(package_name):]
    rel = suffix.lstrip('.')
    parts = rel.split('.') if rel else []

    if parts:
        file_path = os.path.join(project_dir, *parts) + '.py'
        if os.path.isfile(file_path):
            return file_path

    init_path = os.path.join(project_dir, *parts, '__init__.py')
    if os.path.isfile(init_path):
        return init_path

    return None


def _get_all_names(filepath):
    with open(filepath) as f:
        tree = ast.parse(f.read(), filepath)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '__all__':
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        return [
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
    return None


def _resolve_name_through_init(name, init_path, project_dir, package_name, visited=None):
    if visited is None:
        visited = set()
    if init_path in visited:
        return None
    visited.add(init_path)

    pkg_module = _relative_module(init_path, project_dir)

    with open(init_path) as f:
        tree = ast.parse(f.read(), init_path)

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ImportFrom):
            continue

        level = node.level or 0
        module = node.module or ''

        if level > 0:
            pkg_parts = pkg_module.split('.') if pkg_module else []
            trim = level - 1
            if trim < len(pkg_parts):
                base_parts = pkg_parts[:len(pkg_parts) - trim]
            else:
                base_parts = []
            if module:
                full_parts = base_parts + module.split('.')
            else:
                full_parts = list(base_parts)
            src_module_str = package_name + '.' + '.'.join(full_parts) if full_parts else package_name
        else:
            src_module_str = module

        src_path = _resolve_absolute_module(src_module_str, project_dir, package_name)
        if src_path is None:
            continue

        is_init = os.path.basename(src_path) == '__init__.py'

        if node.names[0].name == '*':
            if not is_init:
                all_names = _get_all_names(src_path)
                if all_names is not None:
                    if name in all_names:
                        src_rel = _relative_module(src_path, project_dir)
                        return f"{src_rel}.{name}"
                else:
                    with open(src_path) as f:
                        src_tree = ast.parse(f.read(), src_path)
                    for snode in ast.iter_child_nodes(src_tree):
                        if isinstance(snode, ast.FunctionDef) and snode.name == name:
                            src_rel = _relative_module(src_path, project_dir)
                            return f"{src_rel}.{name}"
            else:
                result = _resolve_name_through_init(name, src_path, project_dir, package_name, visited)
                if result:
                    return result
        else:
            for alias in node.names:
                actual_name = alias.name
                exported_name = alias.asname or alias.name
                if exported_name == name:
                    if is_init:
                        result = _resolve_name_through_init(
                            actual_name, src_path, project_dir, package_name, visited
                        )
                        if result:
                            return result
                    else:
                        src_rel = _relative_module(src_path, project_dir)
                        return f"{src_rel}.{actual_name}"

    return None


def _resolve_import_to_qname(full_module_str, name, project_dir, package_name, all_functions):
    path = _resolve_absolute_module(full_module_str, project_dir, package_name)
    if path is None:
        return None

    if os.path.basename(path) == '__init__.py':
        result = _resolve_name_through_init(name, path, project_dir, package_name)
        if result and result in all_functions:
            return result
    else:
        src_rel = _relative_module(path, project_dir)
        qname = f"{src_rel}.{name}"
        if qname in all_functions:
            return qname

    return None


def discover_functions(project_dir):
    functions = {}
    for filepath in _iter_py_files(project_dir):
        if os.path.basename(filepath) == '__init__.py':
            continue
        module = _relative_module(filepath, project_dir)
        with open(filepath) as f:
            try:
                tree = ast.parse(f.read(), filepath)
            except SyntaxError:
                continue
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                qname = f"{module}.{node.name}"
                functions[qname] = {
                    'file': filepath,
                    'lineno': node.lineno,
                    'name': node.name,
                    'module': module,
                }
    return functions


def _build_import_tables(filepath, project_dir, package_name, all_functions):
    with open(filepath) as f:
        tree = ast.parse(f.read(), filepath)

    func_table = {}
    module_table = {}

    file_dir = os.path.dirname(filepath)
    file_pkg_parts = os.path.relpath(file_dir, os.path.dirname(project_dir)).split(os.sep)
    file_pkg = '.'.join(file_pkg_parts)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name.startswith(package_name + '.') or alias.name == package_name:
                    module_table[local] = alias.name

        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            module = node.module or ''

            if level > 0:
                pkg_parts = file_pkg.split('.')
                trim = level - 1
                if trim < len(pkg_parts):
                    base_parts = pkg_parts[:len(pkg_parts) - trim]
                else:
                    base_parts = [pkg_parts[0]]
                if module:
                    full_module = '.'.join(base_parts + module.split('.'))
                else:
                    full_module = '.'.join(base_parts)
            else:
                full_module = module

            if not full_module.startswith(package_name):
                continue

            for alias in node.names:
                actual_name = alias.name
                local_name = alias.asname or alias.name
                resolved = _resolve_import_to_qname(
                    full_module, actual_name, project_dir, package_name, all_functions
                )
                if resolved:
                    func_table[local_name] = resolved

    return func_table, module_table


def build_call_graph(project_dir, package_name, all_functions):
    graph = {qname: set() for qname in all_functions}

    for filepath in _iter_py_files(project_dir):
        if os.path.basename(filepath) == '__init__.py':
            continue

        module = _relative_module(filepath, project_dir)

        with open(filepath) as f:
            try:
                tree = ast.parse(f.read(), filepath)
            except SyntaxError:
                continue

        local_funcs = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                local_funcs.add(node.name)

        func_table, module_table = _build_import_tables(
            filepath, project_dir, package_name, all_functions
        )

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            qname = f"{module}.{node.name}"
            if qname not in graph:
                continue

            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue

                resolved = None

                if isinstance(child.func, ast.Name):
                    call_name = child.func.id
                    if call_name in func_table:
                        resolved = func_table[call_name]
                    elif call_name in local_funcs:
                        candidate = f"{module}.{call_name}"
                        if candidate in all_functions:
                            resolved = candidate

                elif isinstance(child.func, ast.Attribute):
                    if isinstance(child.func.value, ast.Name):
                        obj = child.func.value.id
                        attr = child.func.attr
                        if obj in module_table:
                            mod_path = module_table[obj]
                            if mod_path.startswith(package_name + '.'):
                                rel = mod_path[len(package_name) + 1:]
                                candidate = f"{rel}.{attr}"
                                if candidate in all_functions:
                                    resolved = candidate

                if resolved and resolved != qname and resolved in all_functions:
                    graph[qname].add(resolved)

    return {k: sorted(v) for k, v in graph.items()}


def compute_reachable(graph, entry_points):
    visited = set()
    queue = deque()
    for ep in entry_points:
        if ep in graph and ep not in visited:
            visited.add(ep)
            queue.append(ep)
    while queue:
        current = queue.popleft()
        for neighbor in graph.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


def get_test_entry_points(test_dir, project_dir, package_name, all_functions):
    entries = set()
    for filepath in _iter_py_files(test_dir):
        if not os.path.basename(filepath).startswith('test_'):
            continue
        with open(filepath) as f:
            try:
                tree = ast.parse(f.read(), filepath)
            except SyntaxError:
                continue
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                if not module.startswith(package_name + '.'):
                    continue
                for alias in node.names:
                    resolved = _resolve_import_to_qname(
                        module, alias.name, project_dir, package_name, all_functions
                    )
                    if resolved:
                        entries.add(resolved)
    return entries


def classify(project_dir, package_name, feature_test_dir, base_test_dir):
    all_functions = discover_functions(project_dir)
    graph = build_call_graph(project_dir, package_name, all_functions)

    feature_entries = get_test_entry_points(
        feature_test_dir, project_dir, package_name, all_functions
    )
    base_entries = get_test_entry_points(
        base_test_dir, project_dir, package_name, all_functions
    )

    feature_reachable = compute_reachable(graph, feature_entries)
    base_reachable = compute_reachable(graph, base_entries)

    result = {}
    for func in all_functions:
        in_f = func in feature_reachable
        in_b = func in base_reachable
        if in_f and in_b:
            result[func] = 'shared'
        elif in_f:
            result[func] = 'feature_only'
        elif in_b:
            result[func] = 'base_only'
        else:
            result[func] = 'unused'

    return result
