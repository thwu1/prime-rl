#!/usr/bin/env python3
"""
Analyze slang AST JSON output to extract comprehensive design metrics.

Parses the AST JSON produced by `slang --ast-json` and extracts:
- Top module name and instantiation hierarchy
- Port counts per module (inputs vs outputs)
- Elaborated parameter values per instance
- Generate block structure (name, iteration count)
- FSM state encodings (localparam states in modules)
- Memory array declarations (name, depth, width)
"""

import json
import sys
import os
import re
import glob


def load_ast(path):
    with open(path) as f:
        return json.load(f)


def parse_verilog_literal(s):
    """Parse Verilog integer literal like 3'd0, 8'hFF, 4'b1010 → int."""
    m = re.match(r"\d+'[sS]?([bBdDoOhH])([0-9a-fA-F_]+)$", s.strip())
    if not m:
        return None
    base_char = m.group(1).lower()
    digits = m.group(2).replace('_', '').lower()
    if 'x' in digits or 'z' in digits:
        return None
    base_map = {'b': 2, 'o': 8, 'd': 10, 'h': 16}
    try:
        return int(digits, base_map.get(base_char, 10))
    except ValueError:
        return None


def get_constant_value(node, depth=0):
    """Robustly extract integer constant from an AST expression node.

    Handles: plain ints, string ints, Verilog literals, nested expression
    trees with Conversion/operand wrappers, and various key names used
    across slang versions.
    """
    if depth > 15:
        return None
    if isinstance(node, bool):
        return None
    if isinstance(node, int):
        return node
    if isinstance(node, float):
        return int(node)
    if isinstance(node, str):
        s = node.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return int(s, 0)
        except (ValueError, TypeError):
            pass
        v = parse_verilog_literal(s)
        if v is not None:
            return v
        return None
    if isinstance(node, dict):
        # Try direct scalar value keys first
        for key in ("value", "constantValue", "constant", "val",
                     "intValue", "integer", "constValue"):
            v = node.get(key)
            if v is not None:
                result = get_constant_value(v, depth + 1)
                if result is not None:
                    return result
        # Try expression-tree traversal keys
        for key in ("operand", "expression", "expr", "from",
                     "argument", "arg", "left", "body", "conversion"):
            v = node.get(key)
            if v is not None:
                result = get_constant_value(v, depth + 1)
                if result is not None:
                    return result
    return None


def extract_param_value(param_node):
    """Extract the elaborated integer value from a Parameter AST node."""
    # Try initializer expression tree first
    for key in ("initializer", "init", "defaultValue", "default"):
        v = param_node.get(key)
        if v is not None:
            result = get_constant_value(v)
            if result is not None:
                return result
    # Fallback: try direct value on parameter node itself
    return get_constant_value(param_node)


def is_param_kind(kind_str):
    """Check if the AST kind string represents a parameter declaration."""
    return kind_str in ("Parameter", "Specparam", "TypeParameter",
                        "Localparam", "LocalParam") or "Param" in kind_str


def parse_array_dimensions(type_str):
    """Parse array dimensions from slang type string → (width, depth)."""
    if not isinstance(type_str, str):
        return None, None

    # type[H:L] $[H2:L2] ($ separates packed/unpacked in slang)
    m = re.search(r'\[(\d+):(\d+)\]\s*\$\s*\[(\d+):(\d+)\]', type_str)
    if m:
        return (abs(int(m.group(1)) - int(m.group(2))) + 1,
                abs(int(m.group(3)) - int(m.group(4))) + 1)

    # type[H:L] $[N]
    m = re.search(r'\[(\d+):(\d+)\]\s*\$\s*\[(\d+)\]', type_str)
    if m:
        return (abs(int(m.group(1)) - int(m.group(2))) + 1, int(m.group(3)))

    # type[H:L][H2:L2] (no $ separator)
    brackets = re.findall(r'\[(\d+):(\d+)\]', type_str)
    if len(brackets) >= 2:
        return (abs(int(brackets[0][0]) - int(brackets[0][1])) + 1,
                abs(int(brackets[1][0]) - int(brackets[1][1])) + 1)

    # type[H:L][N]
    m = re.search(r'\[(\d+):(\d+)\]\[(\d+)\]', type_str)
    if m:
        return (abs(int(m.group(1)) - int(m.group(2))) + 1, int(m.group(3)))

    return None, None


def find_fsm_from_source(design_path="/opt/soc_design"):
    """Fallback: parse Verilog/SV source files for localparam FSM states.

    Only invoked when AST-based extraction fails. Searches all .v/.sv files
    for localparam declarations with small integer values that form FSM
    state encodings (>= 3 such params in a single module).
    """
    fsm_states = {}
    for ext in ('**/*.v', '**/*.sv'):
        for filepath in glob.glob(os.path.join(design_path, ext), recursive=True):
            try:
                with open(filepath) as f:
                    content = f.read()
            except (IOError, OSError):
                continue

            mod_match = re.search(r'\bmodule\s+(\w+)', content)
            if not mod_match:
                continue
            mod_name = mod_match.group(1)

            params = {}
            for m in re.finditer(
                r'\blocalparam\b\s+(?:\w+\s+)*(\w+)\s*=\s*'
                r"(\d+'[sS]?[bBdDoOhH][0-9a-fA-F_]+|\d+)",
                content
            ):
                pname = m.group(1)
                pval_str = m.group(2).strip()
                pval = parse_verilog_literal(pval_str)
                if pval is None:
                    try:
                        pval = int(pval_str)
                    except ValueError:
                        continue
                params[pname] = pval

            small = {k: v for k, v in params.items()
                     if isinstance(v, int) and 0 <= v <= 31}
            if len(small) >= 3:
                fsm_states[mod_name] = small

    return fsm_states


def analyze_ast(ast):
    """Main analysis: traverse elaborated AST to extract design metrics."""
    hierarchy = {}
    module_ports = {}
    instance_params = {}
    generate_blocks = {}
    fsm_states = {}
    memory_arrays = {}
    top_module = None
    instance_count = 0

    def process_instance(inst_node, depth=0):
        nonlocal instance_count, top_module

        name = inst_node.get("name", "")
        def_name = inst_node.get("definitionName", "")
        if not def_name:
            body = inst_node.get("body", {})
            if isinstance(body, dict):
                def_name = body.get("name", body.get("definitionName", name))

        if depth == 0:
            top_module = def_name or name

        body = inst_node.get("body", inst_node)
        members = body.get("members", []) if isinstance(body, dict) else []

        # --- Port counting ---
        if def_name and def_name not in module_ports:
            inputs = outputs = 0
            for m in members:
                if not isinstance(m, dict):
                    continue
                mk = m.get("kind", "")
                if "Port" in mk:
                    d = m.get("direction", "").lower()
                    if d == "in":
                        inputs += 1
                    elif d == "out":
                        outputs += 1
                    elif d == "inout":
                        inputs += 1
            if inputs or outputs:
                module_ports[def_name] = {"inputs": inputs, "outputs": outputs}

        # --- Generate blocks ---
        if def_name and def_name not in generate_blocks:
            gen_list = []
            for m in members:
                if not isinstance(m, dict):
                    continue
                mk = m.get("kind", "")
                if "GenerateBlockArray" in mk:
                    gn = m.get("name", "")
                    ch = m.get("members", m.get("blocks", m.get("entries", [])))
                    bc = 0
                    if isinstance(ch, list):
                        bc = sum(1 for c in ch if isinstance(c, dict)
                                 and "GenerateBlock" in c.get("kind", "")
                                 and "Array" not in c.get("kind", ""))
                        if not bc:
                            bc = sum(1 for c in ch if isinstance(c, dict))
                    if gn and bc:
                        gen_list.append({"name": gn, "count": bc})
                elif "GenerateBlock" in mk and "Array" not in mk:
                    for im in (m.get("members", []) if isinstance(m.get("members"), list) else []):
                        if isinstance(im, dict) and "GenerateBlockArray" in im.get("kind", ""):
                            gn = im.get("name", "")
                            ch = im.get("members", im.get("blocks", []))
                            bc = sum(1 for c in ch if isinstance(c, dict)) if isinstance(ch, list) else 0
                            if gn and bc:
                                gen_list.append({"name": gn, "count": bc})
            if gen_list:
                generate_blocks[def_name] = gen_list

        # --- FSM state extraction (localparams) ---
        if def_name and def_name not in fsm_states:
            local_params = {}

            # Strategy 1: Parameter members with isLocal flag
            for m in members:
                if not isinstance(m, dict):
                    continue
                if not is_param_kind(m.get("kind", "")):
                    continue
                is_local = any(m.get(k, False) for k in
                               ("isLocal", "isLocalParam", "isLocalparam", "local"))
                is_port = m.get("isPort", False)
                if is_local and not is_port:
                    pn = m.get("name", "")
                    pv = extract_param_value(m)
                    if pn and pv is not None:
                        local_params[pn] = pv

            # Strategy 2: all non-port parameters (isLocal might be missing)
            if not local_params:
                for m in members:
                    if not isinstance(m, dict):
                        continue
                    if not is_param_kind(m.get("kind", "")):
                        continue
                    if m.get("isPort", False):
                        continue
                    pn = m.get("name", "")
                    pv = extract_param_value(m)
                    if pn and pv is not None:
                        local_params[pn] = pv

            # Apply FSM heuristic: >= 3 small-valued params
            small = {k: v for k, v in local_params.items()
                     if isinstance(v, int) and 0 <= v <= 31}
            if len(small) >= 3:
                fsm_states[def_name] = small

        # --- Memory array extraction ---
        if def_name and def_name not in memory_arrays:
            arr_list = []
            for m in members:
                if not isinstance(m, dict):
                    continue
                if m.get("kind", "") not in ("Variable", "Net"):
                    continue
                vn = m.get("name", "")
                ti = m.get("type", "")
                w, d = None, None

                if isinstance(ti, str):
                    w, d = parse_array_dimensions(ti)

                if (w is None or d is None) and isinstance(ti, dict):
                    ts = ti.get("toString", ti.get("name", ""))
                    if isinstance(ts, str):
                        w, d = parse_array_dimensions(ts)

                if d is None:
                    for dk in ("dimensions", "fixedRange", "unpacked",
                               "arrayRange", "range"):
                        di = m.get(dk)
                        if di is None:
                            continue
                        if isinstance(di, dict):
                            d = abs(int(di.get("left", di.get("high", 0)))
                                    - int(di.get("right", di.get("low", 0)))) + 1
                        elif isinstance(di, list) and di:
                            x = di[0]
                            if isinstance(x, dict):
                                d = abs(int(x.get("left", x.get("high", 0)))
                                        - int(x.get("right", x.get("low", 0)))) + 1
                            elif isinstance(x, int):
                                d = x
                        break

                if w is None and isinstance(ti, str):
                    rm = re.search(r'\[(\d+):(\d+)\]', ti)
                    if rm:
                        w = abs(int(rm.group(1)) - int(rm.group(2))) + 1

                if vn and w is not None and d is not None:
                    arr_list.append({"name": vn, "depth": d, "width": w})

            if arr_list:
                memory_arrays[def_name] = arr_list

        # --- Child instances and parameter overrides ---
        child_mods = []
        for m in members:
            if not isinstance(m, dict) or m.get("kind") != "Instance":
                continue
            cn = m.get("name", "")
            cd = m.get("definitionName", "")
            if not cd:
                cb = m.get("body", {})
                if isinstance(cb, dict):
                    cd = cb.get("name", cn)
            if cd:
                child_mods.append(cd)
            instance_count += 1

            # Extract parameter overrides for this instance
            params = {}
            cb = m.get("body", m)
            if isinstance(cb, dict):
                for cm in cb.get("members", []):
                    if not isinstance(cm, dict):
                        continue
                    if not is_param_kind(cm.get("kind", "")):
                        continue
                    is_local = any(cm.get(k, False) for k in
                                   ("isLocal", "isLocalParam", "isLocalparam"))
                    if is_local:
                        continue
                    pn = cm.get("name", "")
                    pv = extract_param_value(cm)
                    if pn and pv is not None:
                        params[pn] = pv

            if cn and params:
                instance_params[cn] = params

            process_instance(m, depth + 1)

        if def_name and child_mods:
            hierarchy[def_name] = sorted(child_mods)

    # Find and process root instances
    root_members = ast.get("members", [])
    if not root_members:
        design = ast.get("design", ast)
        if isinstance(design, dict):
            root_members = design.get("members", [])

    for m in root_members:
        if isinstance(m, dict) and m.get("kind") == "Instance":
            process_instance(m, depth=0)

    # Fallback port counting via InstanceBody search
    if not module_ports:
        def find_all(node, kind, results=None):
            if results is None:
                results = []
            if isinstance(node, dict):
                if node.get("kind") == kind:
                    results.append(node)
                for v in node.values():
                    find_all(v, kind, results)
            elif isinstance(node, list):
                for item in node:
                    find_all(item, kind, results)
            return results

        for ib in find_all(ast, "InstanceBody"):
            ib_name = ib.get("name", "")
            ins = outs = 0
            for m in ib.get("members", []):
                if isinstance(m, dict) and "Port" in m.get("kind", ""):
                    d = m.get("direction", "").lower()
                    if d == "in":
                        ins += 1
                    elif d == "out":
                        outs += 1
            if ins or outs:
                module_ports[ib_name] = {"inputs": ins, "outputs": outs}

    # FSM fallback: parse source files if AST extraction found nothing
    if not fsm_states:
        print("  [INFO] AST-based FSM extraction found no states, "
              "falling back to source parsing...", file=sys.stderr)
        fsm_states = find_fsm_from_source()

    return {
        "top_module": top_module or "soc_top",
        "total_instances": instance_count,
        "hierarchy": hierarchy,
        "module_ports": module_ports,
        "instance_params": instance_params,
        "generate_blocks": generate_blocks,
        "fsm_states": fsm_states,
        "memory_arrays": memory_arrays,
    }


def main():
    ast_path = "/app/ast.json"
    output_path = "/app/analysis.json"

    if not os.path.isfile(ast_path):
        print(f"ERROR: {ast_path} not found. Run slang with --ast-json first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Loading AST from {ast_path}...")
    ast = load_ast(ast_path)

    print("Analyzing AST...")
    result = analyze_ast(ast)

    print(f"Writing results to {output_path}...")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, sort_keys=False)

    print("Analysis complete.")
    print(f"  Top module: {result['top_module']}")
    print(f"  Total instances: {result['total_instances']}")
    print(f"  Hierarchy: {json.dumps(result['hierarchy'])}")
    print(f"  Module ports: {json.dumps(result['module_ports'])}")
    print(f"  Instance params: {json.dumps(result['instance_params'])}")
    print(f"  Generate blocks: {json.dumps(result['generate_blocks'])}")
    print(f"  FSM states: {json.dumps(result['fsm_states'])}")
    print(f"  Memory arrays: {json.dumps(result['memory_arrays'])}")


if __name__ == "__main__":
    main()
