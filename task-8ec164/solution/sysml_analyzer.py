#!/usr/bin/env python3
"""
SysML v2 Model Analysis Pipeline

"""

import re
import json
import math
import os
import sys
import sqlite3

G0 = 9.80665


# ===================================================================
# MODEL REPRESENTATION
# ===================================================================

class ModelElement:
    """Represents a parsed SysML v2 model element."""

    def __init__(self, kind, name, type_name=None, id_str=None):
        self.kind = kind
        self.name = name
        self.type_name = type_name
        self.id_str = id_str
        self.attributes = {}
        self.children = []
        self.derivations = []
        self.specializes = None

    def find_child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def find_recursive(self, name):
        for c in self.children:
            if c.name == name:
                return c
            found = c.find_recursive(name)
            if found:
                return found
        return None

    def get_total_mass(self):
        child_parts = [c for c in self.children if c.kind == 'part']
        if child_parts:
            return sum(c.get_total_mass() for c in child_parts)
        return self.attributes.get('mass', 0.0)

    def get_mass_tree(self):
        child_parts = [c for c in self.children if c.kind == 'part']
        if child_parts:
            result = {
                'mass': sum(c.get_total_mass() for c in child_parts),
                'children': {}
            }
            for c in child_parts:
                result['children'][c.name] = c.get_mass_tree()
            return result
        return {'mass': self.attributes.get('mass', 0.0)}

    def find_consumable_mass(self):
        total = 0.0
        if self.attributes.get('isConsumable', False):
            total += self.attributes.get('mass', 0.0)
        for c in self.children:
            total += c.find_consumable_mass()
        return total

    def sum_attr(self, attr_name):
        total = self.attributes.get(attr_name, 0.0)
        for c in self.children:
            total += c.sum_attr(attr_name)
        return total

    def find_propulsive_stage(self):
        for c in self.children:
            if c.type_name == 'PropulsiveStage' or \
               'specificImpulse' in c.attributes:
                return c
        return None


# ===================================================================
# PARSER
# ===================================================================

def strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def extract_brace_body(lines, start_line):
    depth = 0
    body_lines = []
    for i in range(start_line, len(lines)):
        line = lines[i]
        for ch in line:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return '\n'.join(body_lines), i
        if i > start_line:
            body_lines.append(line)
    return '\n'.join(body_lines), len(lines) - 1


def parse_block(text, parent):
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or line == '}':
            i += 1
            continue

        # --- part usage: part name : Type { ---
        m = re.match(
            r'(?:abstract\s+)?part\s+(\w+)\s*(?::\s*(\w+))?\s*\{', line)
        if m and 'def' not in line.split('{')[0].split('part')[1].split(
                m.group(1))[0]:
            elem = ModelElement('part', m.group(1), m.group(2))
            body, end = extract_brace_body(lines, i)
            parse_block(body, elem)
            parent.children.append(elem)
            i = end + 1
            continue

        # --- part def: part def Name :> Parent { ---
        m = re.match(
            r'(?:abstract\s+)?part\s+def\s+(\w+)\s*(?::>\s*(\w+))?\s*\{',
            line)
        if m:
            elem = ModelElement('part_def', m.group(1), m.group(2))
            body, end = extract_brace_body(lines, i)
            parse_block(body, elem)
            parent.children.append(elem)
            i = end + 1
            continue

        # --- package ---
        m = re.match(r'package\s+(\w+)\s*\{', line)
        if m:
            elem = ModelElement('package', m.group(1))
            body, end = extract_brace_body(lines, i)
            parse_block(body, elem)
            parent.children.append(elem)
            i = end + 1
            continue

        # --- requirement def ---
        m = re.match(r'requirement\s+def\s+(\w+)\s*\{', line)
        if m:
            elem = ModelElement('requirement_def', m.group(1))
            body, end = extract_brace_body(lines, i)
            parse_block(body, elem)
            parent.children.append(elem)
            i = end + 1
            continue

        # --- requirement specialization: requirement name :> parent { ---
        m = re.match(r"requirement\s+(\w+)\s*:>\s*(\w+)\s*\{", line)
        if m:
            elem = ModelElement('requirement', m.group(1))
            elem.specializes = m.group(2)
            body, end = extract_brace_body(lines, i)
            parse_block(body, elem)
            parent.children.append(elem)
            i = end + 1
            continue

        # --- requirement usage: requirement name : Type id 'ID' { ---
        m = re.match(
            r"requirement\s+(\w+)\s*(?::\s*(\w+))?\s*(?:id\s+'([^']+)')?"
            r"\s*\{",
            line)
        if m:
            elem = ModelElement('requirement', m.group(1), m.group(2),
                                m.group(3))
            body, end = extract_brace_body(lines, i)
            parse_block(body, elem)
            parent.children.append(elem)
            i = end + 1
            continue

        # --- attribute with value ---
        m = re.match(
            r'attribute\s+(?:redefines\s+)?(\w+)\s*(?::\s*\w+)?\s*='
            r'\s*([^;]+);',
            line)
        if m:
            name = m.group(1)
            raw = m.group(2).strip()
            try:
                parent.attributes[name] = float(raw)
            except ValueError:
                if raw.lower() == 'true':
                    parent.attributes[name] = True
                elif raw.lower() == 'false':
                    parent.attributes[name] = False
                else:
                    parent.attributes[name] = raw
            i += 1
            continue

        # --- satisfy statement ---
        m = re.match(r'satisfy\s+(\w+)\s+by\s+([^;]+);', line)
        if m:
            elem = ModelElement('satisfy', m.group(1))
            elem.attributes['target'] = m.group(2).strip()
            parent.children.append(elem)
            i += 1
            continue

        # --- derive requirement ---
        m = re.match(r'derive\s+requirement\s+(\w+)\s*;', line)
        if m:
            parent.derivations.append(m.group(1))
            i += 1
            continue

        # --- skip any unknown block ---
        if '{' in line:
            _, end = extract_brace_body(lines, i)
            i = end + 1
            continue

        i += 1


def parse_sysml_files(model_dir):
    all_text = ""
    for fname in sorted(os.listdir(model_dir)):
        if fname.endswith('.sysml'):
            with open(os.path.join(model_dir, fname)) as f:
                all_text += f.read() + "\n"
    all_text = strip_comments(all_text)
    root = ModelElement('root', '_root')
    parse_block(all_text, root)
    return root


# ===================================================================
# ANALYSIS
# ===================================================================

def compute_delta_v(isp, m_initial, m_final):
    if isp <= 0 or m_initial <= 0 or m_final <= 0:
        return 0.0
    return isp * G0 * math.log(m_initial / m_final)


def collect_requirements(root):
    reqs = {}
    for c in root.children:
        if c.kind == 'requirement' and c.id_str:
            reqs[c.id_str] = c
        reqs.update(collect_requirements(c))
    return reqs


def collect_satisfy_links(root):
    links = {}
    for c in root.children:
        if c.kind == 'satisfy':
            links[c.name] = c.attributes.get('target', '')
        links.update(collect_satisfy_links(c))
    return links


def collect_derivation_chains(root):
    chains = {}
    for c in root.children:
        if c.kind == 'requirement' and c.derivations:
            chains[c.name] = list(c.derivations)
        chains.update(collect_derivation_chains(c))
    return chains


def analyze(root):
    selene = root.find_recursive('seleneSystem')
    if not selene:
        print("ERROR: seleneSystem not found in model", file=sys.stderr)
        sys.exit(1)

    tv = selene.find_child('transferVehicle')
    lander = selene.find_child('lander')

    # ----- Mass Rollup -----
    mass_rollup = {'seleneSystem': selene.get_mass_tree()}
    system_total = selene.get_total_mass()

    # ----- Delta-V Budget -----
    tv_prop = tv.find_propulsive_stage() if tv else None
    tv_isp = tv_prop.attributes.get('specificImpulse', 0.0) \
        if tv_prop else 0.0
    tv_consumable = tv.find_consumable_mass() if tv else 0.0
    tv_m_initial = system_total
    tv_m_final = system_total - tv_consumable
    tv_dv = compute_delta_v(tv_isp, tv_m_initial, tv_m_final)

    ln_total = lander.get_total_mass() if lander else 0.0
    ln_prop = lander.find_propulsive_stage() if lander else None
    ln_isp = ln_prop.attributes.get('specificImpulse', 0.0) \
        if ln_prop else 0.0
    ln_consumable = lander.find_consumable_mass() if lander else 0.0
    ln_m_initial = ln_total
    ln_m_final = ln_total - ln_consumable
    ln_dv = compute_delta_v(ln_isp, ln_m_initial, ln_m_final)

    delta_v_budget = {
        'transferVehicle': {
            'specificImpulse': tv_isp,
            'initialMass': tv_m_initial,
            'finalMass': tv_m_final,
            'deltaV': tv_dv,
        },
        'lander': {
            'specificImpulse': ln_isp,
            'initialMass': ln_m_initial,
            'finalMass': ln_m_final,
            'deltaV': ln_dv,
        },
        'totalDeltaV': tv_dv + ln_dv,
    }

    # ----- Power Budget -----
    tv_gen = tv.sum_attr('powerGeneration') if tv else 0.0
    tv_con = tv.sum_attr('powerConsumption') if tv else 0.0
    ln_gen = lander.sum_attr('powerGeneration') if lander else 0.0
    ln_con = lander.sum_attr('powerConsumption') if lander else 0.0

    power_budget = {
        'transferVehicle': {
            'generation': tv_gen,
            'consumption': tv_con,
            'margin': tv_gen - tv_con,
        },
        'lander': {
            'generation': ln_gen,
            'consumption': ln_con,
            'margin': ln_gen - ln_con,
        },
    }

    # ----- Requirements & Traceability -----
    requirements = collect_requirements(root)
    satisfy_links = collect_satisfy_links(root)

    name_to_id = {r.name: rid for rid, r in requirements.items()}

    id_to_target = {}
    for req_name, target_path in satisfy_links.items():
        rid = name_to_id.get(req_name)
        if rid:
            id_to_target[rid] = target_path

    requirements_verification = {}
    traceability = {}

    for rid, req in requirements.items():
        rtype = req.type_name
        target_path = id_to_target.get(rid, '')
        target_name = target_path.split('.')[-1] if target_path else ''

        actual = 0.0
        limit = 0.0

        if rtype == 'TotalMassRequirement':
            limit = req.attributes.get('massLimit', 0.0)
            if target_name:
                t = selene.find_recursive(target_name)
                actual = t.get_total_mass() if t else 0.0
            else:
                actual = system_total
            status = 'PASS' if actual <= limit else 'FAIL'

        elif rtype == 'DryMassRequirement':
            limit = req.attributes.get('dryMassLimit', 0.0)
            t = selene.find_recursive(target_name) if target_name else None
            if t:
                actual = t.get_total_mass() - t.find_consumable_mass()
            status = 'PASS' if actual <= limit else 'FAIL'

        elif rtype == 'DeltaVRequirement':
            limit = req.attributes.get('minDeltaV', 0.0)
            if 'tv' in target_name.lower():
                actual = tv_dv
            elif 'ln' in target_name.lower():
                actual = ln_dv
            status = 'PASS' if actual >= limit else 'FAIL'

        elif rtype == 'PowerMarginRequirement':
            limit = req.attributes.get('minMargin', 0.0)
            if 'tv' in target_name.lower():
                actual = tv_gen - tv_con
            elif 'ln' in target_name.lower():
                actual = ln_gen - ln_con
            status = 'PASS' if actual >= limit else 'FAIL'

        elif rtype == 'PayloadCapacityRequirement':
            limit = req.attributes.get('minPayload', 0.0)
            t = selene.find_recursive(target_name) if target_name else None
            if t:
                actual = t.attributes.get('mass', 0.0)
            status = 'PASS' if actual >= limit else 'FAIL'

        else:
            status = 'FAIL'

        requirements_verification[rid] = {
            'status': status,
            'actual': actual,
            'limit': limit,
        }

        if target_path:
            traceability[rid] = {'satisfiedBy': [target_name]}
        else:
            traceability[rid] = {'satisfiedBy': []}

    # ----- Derivation Chains -----
    derivation_chains = collect_derivation_chains(root)

    return {
        'mass_rollup': mass_rollup,
        'delta_v_budget': delta_v_budget,
        'power_budget': power_budget,
        'requirements_verification': requirements_verification,
        'traceability': traceability,
        'derivation_chains': derivation_chains,
    }


# ===================================================================
# SQLITE DATABASE
# ===================================================================

def create_database(root, db_path):
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''CREATE TABLE parts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id INTEGER,
        type_name TEXT,
        FOREIGN KEY (parent_id) REFERENCES parts(id)
    )''')

    cur.execute('''CREATE TABLE attributes (
        id INTEGER PRIMARY KEY,
        part_id INTEGER NOT NULL,
        attr_name TEXT NOT NULL,
        attr_value REAL NOT NULL,
        FOREIGN KEY (part_id) REFERENCES parts(id)
    )''')

    cur.execute('''CREATE TABLE requirements (
        id INTEGER PRIMARY KEY,
        req_id TEXT NOT NULL,
        name TEXT NOT NULL,
        type_name TEXT
    )''')

    cur.execute('''CREATE TABLE req_attributes (
        id INTEGER PRIMARY KEY,
        requirement_id INTEGER NOT NULL,
        attr_name TEXT NOT NULL,
        attr_value REAL NOT NULL,
        FOREIGN KEY (requirement_id) REFERENCES requirements(id)
    )''')

    cur.execute('''CREATE TABLE satisfy_links (
        id INTEGER PRIMARY KEY,
        req_name TEXT NOT NULL,
        target_path TEXT NOT NULL
    )''')

    cur.execute('''CREATE TABLE derive_links (
        id INTEGER PRIMARY KEY,
        child_req_name TEXT NOT NULL,
        parent_req_name TEXT NOT NULL
    )''')

    # Insert parts
    pid_counter = [0]
    aid_counter = [0]

    def insert_part_tree(elem, parent_id):
        pid_counter[0] += 1
        pid = pid_counter[0]
        cur.execute(
            'INSERT INTO parts VALUES (?, ?, ?, ?)',
            (pid, elem.name, parent_id, elem.type_name))
        for attr_name, attr_val in elem.attributes.items():
            if isinstance(attr_val, bool):
                db_val = 1.0 if attr_val else 0.0
            elif isinstance(attr_val, (int, float)):
                db_val = float(attr_val)
            else:
                continue
            aid_counter[0] += 1
            cur.execute(
                'INSERT INTO attributes VALUES (?, ?, ?, ?)',
                (aid_counter[0], pid, attr_name, db_val))
        for child in elem.children:
            if child.kind == 'part':
                insert_part_tree(child, pid)

    selene = root.find_recursive('seleneSystem')
    if selene:
        insert_part_tree(selene, None)

    # Insert requirements
    requirements = collect_requirements(root)
    req_db_id = 0
    rattr_id = 0
    for rid, req in requirements.items():
        req_db_id += 1
        cur.execute(
            'INSERT INTO requirements VALUES (?, ?, ?, ?)',
            (req_db_id, rid, req.name, req.type_name))
        for attr_name, attr_val in req.attributes.items():
            if isinstance(attr_val, (int, float)) and \
                    not isinstance(attr_val, bool):
                rattr_id += 1
                cur.execute(
                    'INSERT INTO req_attributes VALUES (?, ?, ?, ?)',
                    (rattr_id, req_db_id, attr_name, float(attr_val)))

    # Insert satisfy links
    satisfy_links = collect_satisfy_links(root)
    sl_id = 0
    for req_name, target in satisfy_links.items():
        sl_id += 1
        cur.execute(
            'INSERT INTO satisfy_links VALUES (?, ?, ?)',
            (sl_id, req_name, target))

    # Insert derive links
    derivation_chains = collect_derivation_chains(root)
    dl_id = 0
    for child_name, parents in derivation_chains.items():
        for parent_name in parents:
            dl_id += 1
            cur.execute(
                'INSERT INTO derive_links VALUES (?, ?, ?)',
                (dl_id, child_name, parent_name))

    conn.commit()
    conn.close()


# ===================================================================
# DOT GRAPH
# ===================================================================

def generate_dot(report, dot_path):
    lines = ['digraph traceability {']
    lines.append('    rankdir=LR;')
    lines.append('    node [fontname="Helvetica"];')
    lines.append('')

    rv = report['requirements_verification']
    tr = report['traceability']

    for rid in sorted(rv.keys()):
        data = rv[rid]
        safe_id = rid.replace('-', '_')
        status = data['status']
        is_gap = len(tr.get(rid, {}).get('satisfiedBy', [])) == 0

        fillcolor = 'green' if status == 'PASS' else 'red'
        attrs = [
            f'label="{rid}"',
            'shape=diamond',
            'style=filled',
            f'fillcolor={fillcolor}',
        ]
        if is_gap:
            attrs.append('penwidth=3.0')
            attrs.append('xlabel="GAP"')

        lines.append(f'    {safe_id} [{" ".join(attrs)}];')

    lines.append('')

    components = set()
    for rid_key, data in tr.items():
        for comp in data.get('satisfiedBy', []):
            components.add(comp)

    for comp in sorted(components):
        lines.append(
            f'    {comp} [label="{comp}" shape=box '
            f'style=filled fillcolor=lightblue];')

    lines.append('')

    for rid in sorted(tr.keys()):
        safe_rid = rid.replace('-', '_')
        for comp in tr[rid].get('satisfiedBy', []):
            lines.append(f'    {safe_rid} -> {comp};')

    lines.append('}')

    with open(dot_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


# ===================================================================
# MAIN
# ===================================================================

def main():
    model_dir = '/app/model'
    report_path = '/app/analysis_report.json'
    db_path = '/app/selene_model.db'
    dot_path = '/app/traceability.dot'

    root = parse_sysml_files(model_dir)
    report = analyze(root)

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {report_path}")

    create_database(root, db_path)
    print(f"Database written to {db_path}")

    generate_dot(report, dot_path)
    print(f"DOT graph written to {dot_path}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
