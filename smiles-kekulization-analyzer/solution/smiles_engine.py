#!/usr/bin/env python3
"""
SMILES analyzer: parser, validator, and molecular analysis tool.
No cheminformatics library dependencies.
"""

import sys
import json
import hashlib
from collections import defaultdict

VALENCE_TABLE = {
    'B': [3], 'C': [4], 'N': [3, 5], 'O': [2],
    'P': [3, 5], 'S': [2, 4, 6], 'F': [1],
    'Cl': [1], 'Br': [1], 'I': [1],
}

ATOMIC_NUM = {
    'H': 1, 'He': 2, 'Li': 3, 'Be': 4, 'B': 5, 'C': 6, 'N': 7, 'O': 8,
    'F': 9, 'Ne': 10, 'Na': 11, 'Mg': 12, 'Al': 13, 'Si': 14, 'P': 15,
    'S': 16, 'Cl': 17, 'Ar': 18, 'K': 19, 'Ca': 20, 'Ti': 22, 'Cr': 24,
    'Mn': 25, 'Fe': 26, 'Co': 27, 'Ni': 28, 'Cu': 29, 'Zn': 30, 'As': 33,
    'Se': 34, 'Br': 35, 'Ag': 47, 'Sn': 50, 'I': 53, 'Pt': 78, 'Au': 79,
}

ORGANIC_SUBSET = {'B', 'C', 'N', 'O', 'P', 'S', 'F', 'Cl', 'Br', 'I'}
AROMATIC_MAP = {'b': 'B', 'c': 'C', 'n': 'N', 'o': 'O', 'p': 'P', 's': 'S'}


class SmilesError(Exception):
    def __init__(self, etype, msg):
        self.etype = etype
        super().__init__(msg)


class Atom:
    def __init__(self, element, aromatic=False, charge=0, isotope=0,
                 hcount=None, bracket=False):
        self.element = element
        self.aromatic = aromatic
        self.charge = charge
        self.isotope = isotope
        self.hcount = hcount
        self.bracket = bracket
        self.idx = 0
        self.implicit_h = 0
        self.nbrs = []


class Bond:
    def __init__(self, a1, a2, order=1, arom=False):
        self.a1 = a1
        self.a2 = a2
        self.order = order
        self.arom = arom


class Mol:
    def __init__(self):
        self.atoms = []
        self.bonds = []

    def add_atom(self, atom):
        atom.idx = len(self.atoms)
        self.atoms.append(atom)
        return atom.idx

    def add_bond(self, a1, a2, order=1, arom=False):
        for ni, _ in self.atoms[a1].nbrs:
            if ni == a2:
                raise SmilesError("syntax", "Duplicate bond")
        b = Bond(a1, a2, order, arom)
        bi = len(self.bonds)
        self.bonds.append(b)
        self.atoms[a1].nbrs.append((a2, bi))
        self.atoms[a2].nbrs.append((a1, bi))
        return bi


def _parse_bracket(content):
    i, n = 0, len(content)
    if n == 0:
        raise SmilesError("syntax", "Empty bracket atom")

    isotope = 0
    while i < n and content[i].isdigit():
        isotope = isotope * 10 + int(content[i])
        i += 1

    if i >= n:
        raise SmilesError("syntax", "No element in bracket")

    aromatic = False
    if content[i] == '*':
        elem = '*'
        i += 1
    elif content[i].islower():
        aromatic = True
        c0 = content[i]
        i += 1
        if i < n and content[i].islower():
            elem = c0.upper() + content[i]
            i += 1
        else:
            elem = c0.upper()
    elif content[i].isupper():
        elem = content[i]
        i += 1
        if i < n and content[i].islower():
            elem += content[i]
            i += 1
    else:
        raise SmilesError("syntax", f"Bad bracket element")

    # Chirality - consume but ignore
    if i < n and content[i] == '@':
        i += 1
        if i < n and content[i] == '@':
            i += 1
        # Consume chirality class (TH, AL, SP, TB, OH) if present
        if i + 1 < n and content[i:i + 2] in ('TH', 'AL', 'SP', 'TB', 'OH'):
            i += 2
        # Consume chirality number
        while i < n and content[i].isdigit():
            i += 1

    # H count
    hcount = 0
    if i < n and content[i] == 'H':
        i += 1
        if i < n and content[i].isdigit():
            hcount = 0
            while i < n and content[i].isdigit():
                hcount = hcount * 10 + int(content[i])
                i += 1
        else:
            hcount = 1

    # Charge
    charge = 0
    if i < n and content[i] in '+-':
        sign = 1 if content[i] == '+' else -1
        i += 1
        if i < n and content[i].isdigit():
            cv = 0
            while i < n and content[i].isdigit():
                cv = cv * 10 + int(content[i])
                i += 1
            charge = sign * cv
        else:
            charge = sign
            while i < n and content[i] == ('+' if sign > 0 else '-'):
                charge += sign
                i += 1

    return Atom(elem, aromatic=aromatic, charge=charge, isotope=isotope,
                hcount=hcount, bracket=True)


def _resolve_bond(bchar, a1, a2):
    if bchar == '=':
        return 2, False
    if bchar == '#':
        return 3, False
    if bchar == '-':
        return 1, False
    if bchar == ':':
        return 1, True
    # Implicit
    if a1.aromatic and a2.aromatic:
        return 1, True
    return 1, False


def parse(smi):
    smi = smi.strip()
    if not smi:
        raise SmilesError("syntax", "Empty SMILES")

    mol = Mol()
    stack = []
    prev = -1
    pend = None
    rings = {}
    i, n = 0, len(smi)

    while i < n:
        c = smi[i]

        if c == '(':
            if prev < 0:
                raise SmilesError("syntax", "Branch at start")
            stack.append((prev, pend))
            pend = None
            i += 1

        elif c == ')':
            if not stack:
                raise SmilesError("syntax", "Unmatched ')'")
            prev, pend = stack.pop()
            i += 1

        elif c in '-=#!/\\:':
            if c in '/\\':
                pend = '-'
            else:
                pend = c
            i += 1

        elif c == '.':
            prev = -1
            pend = None
            i += 1

        elif c == '[':
            j = smi.find(']', i)
            if j < 0:
                raise SmilesError("syntax", "Unmatched '['")
            atom = _parse_bracket(smi[i + 1:j])
            ai = mol.add_atom(atom)
            if prev >= 0:
                o, ar = _resolve_bond(pend, mol.atoms[prev], atom)
                mol.add_bond(prev, ai, o, ar)
            prev = ai
            pend = None
            i = j + 1

        elif c in AROMATIC_MAP:
            atom = Atom(AROMATIC_MAP[c], aromatic=True)
            ai = mol.add_atom(atom)
            if prev >= 0:
                o, ar = _resolve_bond(pend, mol.atoms[prev], atom)
                mol.add_bond(prev, ai, o, ar)
            prev = ai
            pend = None
            i += 1

        elif c.isupper():
            if c == 'C' and i + 1 < n and smi[i + 1] == 'l':
                elem = 'Cl'
                i += 2
            elif c == 'B' and i + 1 < n and smi[i + 1] == 'r':
                elem = 'Br'
                i += 2
            else:
                elem = c
                i += 1
            if elem not in ORGANIC_SUBSET:
                raise SmilesError("syntax", f"Unknown atom '{elem}'")
            atom = Atom(elem)
            ai = mol.add_atom(atom)
            if prev >= 0:
                o, ar = _resolve_bond(pend, mol.atoms[prev], atom)
                mol.add_bond(prev, ai, o, ar)
            prev = ai
            pend = None

        elif c.isdigit() or c == '%':
            if prev < 0:
                raise SmilesError("syntax", "Ring closure before atom")
            if c == '%':
                if i + 2 >= n or not smi[i + 1].isdigit() or not smi[i + 2].isdigit():
                    raise SmilesError("syntax", "Bad %nn ring closure")
                rn = int(smi[i + 1:i + 3])
                i += 3
            else:
                rn = int(c)
                i += 1
            if rn in rings:
                other, obond = rings.pop(rn)
                rb = pend if pend is not None else obond
                o, ar = _resolve_bond(rb, mol.atoms[other], mol.atoms[prev])
                mol.add_bond(other, prev, o, ar)
                pend = None
            else:
                rings[rn] = (prev, pend)
                pend = None

        else:
            raise SmilesError("syntax", f"Unexpected char '{c}'")

    if stack:
        raise SmilesError("syntax", f"{len(stack)} unclosed branch(es)")
    if rings:
        raise SmilesError("syntax", f"{len(rings)} unclosed ring(s)")
    if pend is not None:
        raise SmilesError("syntax", "Trailing bond symbol")

    return mol


def compute_implicit_h(mol):
    for atom in mol.atoms:
        if atom.bracket:
            atom.implicit_h = atom.hcount if atom.hcount is not None else 0
            continue

        if atom.element not in VALENCE_TABLE:
            atom.implicit_h = 0
            continue

        bsum = 0
        for _, bi in atom.nbrs:
            bond = mol.bonds[bi]
            bsum += 1 if bond.arom else bond.order

        allowed = sorted(VALENCE_TABLE[atom.element])
        target = None
        for v in allowed:
            if v >= bsum:
                target = v
                break

        if target is None:
            atom.implicit_h = 0
            continue

        h = target - bsum
        if atom.aromatic and h > 0:
            h -= 1
        atom.implicit_h = max(0, h)


def check_valence(mol):
    for atom in mol.atoms:
        if atom.bracket or atom.aromatic:
            continue
        if atom.element not in VALENCE_TABLE:
            continue
        bsum = 0
        for _, bi in atom.nbrs:
            bsum += mol.bonds[bi].order
        if not any(v >= bsum for v in VALENCE_TABLE[atom.element]):
            raise SmilesError("valence",
                              f"Atom {atom.idx} ({atom.element}) exceeds valence")


def check_kekulize(mol):
    arom_idx = {a.idx for a in mol.atoms if a.aromatic}
    if not arom_idx:
        return True

    visited = set()
    components = []
    for start in arom_idx:
        if start in visited:
            continue
        comp = []
        q = [start]
        while q:
            u = q.pop()
            if u in visited:
                continue
            visited.add(u)
            comp.append(u)
            for v, bi in mol.atoms[u].nbrs:
                if v in arom_idx and v not in visited and mol.bonds[bi].arom:
                    q.append(v)
        components.append(comp)

    for comp in components:
        if not _can_kekulize(mol, comp):
            raise SmilesError("kekulization", "Cannot kekulize aromatic system")
    return True


def _can_kekulize(mol, comp):
    comp_set = set(comp)
    needs = set()

    for idx in comp:
        atom = mol.atoms[idx]
        bsum = 0
        for _, bi in atom.nbrs:
            bond = mol.bonds[bi]
            bsum += 1 if bond.arom else bond.order

        if atom.bracket:
            h = atom.hcount if atom.hcount is not None else 0
            if atom.element in VALENCE_TABLE:
                target = None
                for v in sorted(VALENCE_TABLE[atom.element]):
                    if v >= bsum + h:
                        target = v
                        break
                if target is None:
                    return False
                deficit = target - bsum - h
                if deficit == 1:
                    needs.add(idx)
                elif deficit > 1:
                    return False
            # Unknown bracket element: assume satisfied
        else:
            if atom.element not in VALENCE_TABLE:
                continue
            allowed = sorted(VALENCE_TABLE[atom.element])
            target = None
            for v in allowed:
                if v >= bsum:
                    target = v
                    break
            if target is None:
                return False
            raw_h = target - bsum
            if raw_h > 0:
                needs.add(idx)

    if len(needs) % 2 != 0:
        return False
    if not needs:
        return True

    adj = defaultdict(list)
    for idx in comp:
        for v, bi in mol.atoms[idx].nbrs:
            if v in comp_set and mol.bonds[bi].arom:
                adj[idx].append(v)

    return _find_matching(list(needs), adj, needs)


def _find_matching(needs_list, adj, needs_set):
    if not needs_list:
        return True
    match = {}

    def backtrack(idx):
        if idx >= len(needs_list):
            return True
        u = needs_list[idx]
        if u in match:
            return backtrack(idx + 1)
        for v in adj[u]:
            if v in needs_set and v not in match:
                match[u] = v
                match[v] = u
                if backtrack(idx + 1):
                    return True
                del match[u]
                del match[v]
        return False

    return backtrack(0)


def molecular_formula(mol):
    counts = defaultdict(int)
    for atom in mol.atoms:
        counts[atom.element] += 1
        if atom.implicit_h > 0:
            counts['H'] += atom.implicit_h

    if not counts:
        return ""

    parts = []
    if 'C' in counts:
        parts.append(('C', counts.pop('C')))
        if 'H' in counts:
            parts.append(('H', counts.pop('H')))
        for elem in sorted(counts):
            parts.append((elem, counts[elem]))
    else:
        for elem in sorted(counts):
            parts.append((elem, counts[elem]))

    return ''.join(e + (str(c) if c > 1 else '') for e, c in parts)


def tautomer_hash(mol):
    n = len(mol.atoms)
    if n == 0:
        return "0000000000000000_0"

    h_pool = 0
    charge_pool = 0
    for atom in mol.atoms:
        charge_pool += atom.charge
        if atom.element != 'C':
            h_pool += atom.implicit_h

    proto_h = h_pool - charge_pool

    # Build modified labels: carbon keeps implicit_h, non-carbon gets 0
    labels = []
    adj_list = [[] for _ in range(n)]

    for atom in mol.atoms:
        anum = ATOMIC_NUM.get(atom.element, 0)
        ch = atom.implicit_h if atom.element == 'C' else 0
        labels.append(anum * 1000 + ch)

    for bond in mol.bonds:
        adj_list[bond.a1].append(bond.a2)
        adj_list[bond.a2].append(bond.a1)

    # 4 rounds of Morgan refinement
    for _ in range(4):
        new_labels = []
        for i in range(n):
            nbr_labels = sorted(labels[j] for j in adj_list[i])
            combined = str(labels[i]) + '|' + ','.join(str(x) for x in nbr_labels)
            h = int(hashlib.md5(combined.encode()).hexdigest()[:8], 16)
            new_labels.append(h)
        labels = new_labels

    # Canonical representation
    order = sorted(range(n), key=lambda i: labels[i])
    rank = [0] * n
    for r, i in enumerate(order):
        rank[i] = r

    sorted_labels = [labels[i] for i in order]
    sorted_edges = []
    for bond in mol.bonds:
        r1, r2 = rank[bond.a1], rank[bond.a2]
        sorted_edges.append((min(r1, r2), max(r1, r2)))
    sorted_edges.sort()

    rep = str(sorted_labels) + '|' + str(sorted_edges)
    h = hashlib.sha256(rep.encode()).hexdigest()[:16]
    return f"{h}_{proto_h}"


def analyze(smi):
    result = {
        "smiles": smi,
        "valid": False,
        "error_type": None,
        "num_heavy_atoms": None,
        "implicit_hydrogens": None,
        "molecular_formula": None,
        "kekulizable": None,
        "tautomer_hash": None,
    }

    try:
        mol = parse(smi)
        compute_implicit_h(mol)
        check_valence(mol)
        check_kekulize(mol)

        result["valid"] = True
        result["num_heavy_atoms"] = len(mol.atoms)
        result["implicit_hydrogens"] = [a.implicit_h for a in mol.atoms]
        result["molecular_formula"] = molecular_formula(mol)
        has_arom = any(a.aromatic for a in mol.atoms)
        result["kekulizable"] = True if has_arom else None
        result["tautomer_hash"] = tautomer_hash(mol)

    except SmilesError as e:
        result["error_type"] = e.etype

    return result


def main():
    for line in sys.stdin:
        smi = line.strip()
        if smi:
            print(json.dumps(analyze(smi)))


if __name__ == "__main__":
    main()
