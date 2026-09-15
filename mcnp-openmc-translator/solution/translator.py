#!/usr/bin/env python3
"""MCNP to OpenMC XML translator for ICSBEP criticality benchmarks."""

import re
import sys
import os
import xml.etree.ElementTree as ET


# ============================================================
# Lookup tables
# ============================================================

ELEMENTS = {
    1: 'H', 2: 'He', 3: 'Li', 4: 'Be', 5: 'B', 6: 'C', 7: 'N', 8: 'O',
    9: 'F', 10: 'Ne', 11: 'Na', 12: 'Mg', 13: 'Al', 14: 'Si', 15: 'P',
    16: 'S', 17: 'Cl', 18: 'Ar', 19: 'K', 20: 'Ca', 21: 'Sc', 22: 'Ti',
    23: 'V', 24: 'Cr', 25: 'Mn', 26: 'Fe', 27: 'Co', 28: 'Ni', 29: 'Cu',
    30: 'Zn', 31: 'Ga', 32: 'Ge', 33: 'As', 34: 'Se', 35: 'Br', 36: 'Kr',
    37: 'Rb', 38: 'Sr', 39: 'Y', 40: 'Zr', 41: 'Nb', 42: 'Mo', 43: 'Tc',
    44: 'Ru', 45: 'Rh', 46: 'Pd', 47: 'Ag', 48: 'Cd', 49: 'In', 50: 'Sn',
    51: 'Sb', 52: 'Te', 53: 'I', 54: 'Xe', 55: 'Cs', 56: 'Ba', 57: 'La',
    58: 'Ce', 59: 'Pr', 60: 'Nd', 61: 'Pm', 62: 'Sm', 63: 'Eu', 64: 'Gd',
    65: 'Tb', 66: 'Dy', 67: 'Ho', 68: 'Er', 69: 'Tm', 70: 'Yb', 71: 'Lu',
    72: 'Hf', 73: 'Ta', 74: 'W', 75: 'Re', 76: 'Os', 77: 'Ir', 78: 'Pt',
    79: 'Au', 80: 'Hg', 81: 'Tl', 82: 'Pb', 83: 'Bi', 84: 'Po', 85: 'At',
    86: 'Rn', 87: 'Fr', 88: 'Ra', 89: 'Ac', 90: 'Th', 91: 'Pa', 92: 'U',
    93: 'Np', 94: 'Pu', 95: 'Am', 96: 'Cm', 97: 'Bk', 98: 'Cf',
}

THERMAL_SCATTERING = {
    'lwtr': 'c_H_in_H2O',
    'hwtr': 'c_D_in_D2O',
    'grph': 'c_Graphite',
    'poly': 'c_H_in_CH2',
    'benz': 'c_H_in_C6H6',
    'be': 'c_Be_in_Be',
    'bemetal': 'c_Be_in_Be',
    'zr-h': 'c_Zr_in_ZrH',
    'h-zr': 'c_H_in_ZrH',
}

SURFACE_MAP = {
    'so': ('sphere', lambda a: [0.0, 0.0, 0.0, float(a[0])]),
    's':  ('sphere', lambda a: [float(a[0]), float(a[1]), float(a[2]), float(a[3])]),
    'sx': ('sphere', lambda a: [float(a[0]), 0.0, 0.0, float(a[1])]),
    'sy': ('sphere', lambda a: [0.0, float(a[0]), 0.0, float(a[1])]),
    'sz': ('sphere', lambda a: [0.0, 0.0, float(a[0]), float(a[1])]),
    'cz': ('z-cylinder', lambda a: [0.0, 0.0, float(a[0])]),
    'cx': ('x-cylinder', lambda a: [0.0, 0.0, float(a[0])]),
    'cy': ('y-cylinder', lambda a: [0.0, 0.0, float(a[0])]),
    'c/z': ('z-cylinder', lambda a: [float(a[0]), float(a[1]), float(a[2])]),
    'pz': ('z-plane', lambda a: [float(a[0])]),
    'px': ('x-plane', lambda a: [float(a[0])]),
    'py': ('y-plane', lambda a: [float(a[0])]),
    'p':  ('plane', lambda a: [float(a[0]), float(a[1]), float(a[2]), float(a[3])]),
}


def zaid_to_nuclide(zaid_str):
    """Convert MCNP ZAID (e.g. '92235.80c') to OpenMC nuclide name (e.g. 'U235')."""
    zaid_int = int(zaid_str.split('.')[0])
    z = zaid_int // 1000
    a = zaid_int % 1000
    return f"{ELEMENTS[z]}{a}"


def format_coeff(val):
    """Format a coefficient value as a string."""
    if val == int(val):
        return f"{int(val)}."
    return str(val)


# ============================================================
# MCNP Input Parser
# ============================================================

class MCNPParser:
    def __init__(self, filepath):
        with open(filepath) as f:
            self.raw_lines = f.readlines()
        self.title = ''
        self.cells = []
        self.surfaces = []
        self.materials = {}       # mat_id -> [{'name': str, 'ao': float}, ...]
        self.thermal_sab = {}     # mat_id -> sab_name
        self.kcode = None
        self.ksrc = None
        self._parse()

    def _parse(self):
        """Parse the MCNP input into sections and extract data."""
        self.title = self.raw_lines[0].strip() if self.raw_lines else ''

        # Collect non-comment, non-title lines
        lines = []
        for line in self.raw_lines[1:]:
            stripped = line.rstrip('\n')
            # Skip comment lines (c or C in column 1)
            if stripped and stripped[0].lower() == 'c' and (
                    len(stripped) == 1 or not stripped[1].isalpha()):
                continue
            lines.append(stripped)

        # Split into sections by blank lines
        sections = []
        current = []
        for line in lines:
            if line.strip() == '':
                if current:
                    sections.append(current)
                    current = []
            else:
                current.append(line)
        if current:
            sections.append(current)

        if len(sections) < 3:
            # Some inputs may have only 2 explicit sections
            # Try to re-split based on content detection
            if len(sections) == 2:
                sections.append([])

        # Join continuation lines within each section
        cell_lines = self._join_continuations(sections[0]) if len(sections) > 0 else []
        surf_lines = self._join_continuations(sections[1]) if len(sections) > 1 else []
        data_lines = self._join_continuations(sections[2]) if len(sections) > 2 else []

        self._parse_cells(cell_lines)
        self._parse_surfaces(surf_lines)
        self._parse_data(data_lines)

    def _join_continuations(self, lines):
        """Join continuation lines (lines starting with whitespace) to previous line."""
        joined = []
        for line in lines:
            if line and line[0] == ' ' and joined:
                joined[-1] = joined[-1] + ' ' + line.strip()
            else:
                joined.append(line.strip())
        return joined

    def _parse_cells(self, lines):
        """Parse cell cards."""
        for line in lines:
            if not line:
                continue
            # Remove inline comments ($)
            line = line.split('$')[0].strip()
            if not line:
                continue

            # Extract importance
            imp_match = re.search(r'imp:n=(\d+)', line, re.IGNORECASE)
            importance = int(imp_match.group(1)) if imp_match else 1
            if imp_match:
                line = line[:imp_match.start()].strip()

            tokens = line.split()
            if len(tokens) < 2:
                continue

            cell_id = int(tokens[0])
            mat_id = int(tokens[1])

            if mat_id == 0:
                density = 0.0
                region = ' '.join(tokens[2:]).strip()
            else:
                density = float(tokens[2])
                region = ' '.join(tokens[3:]).strip()

            self.cells.append({
                'id': cell_id,
                'material': mat_id,
                'density': density,
                'region': region,
                'importance': importance,
            })

    def _parse_surfaces(self, lines):
        """Parse surface cards."""
        for line in lines:
            if not line:
                continue
            line = line.split('$')[0].strip()
            if not line:
                continue

            tokens = line.split()
            if len(tokens) < 3:
                continue

            surf_id = int(tokens[0])
            surf_type = tokens[1].lower()
            args = tokens[2:]

            self.surfaces.append({
                'id': surf_id,
                'type': surf_type,
                'args': args,
            })

    def _parse_data(self, lines):
        """Parse data cards (materials, kcode, ksrc, mt)."""
        for line in lines:
            if not line:
                continue
            line_stripped = line.split('$')[0].strip()
            if not line_stripped:
                continue
            lower = line_stripped.lower()

            if lower.startswith('kcode'):
                tokens = line_stripped.split()
                self.kcode = {
                    'particles': int(float(tokens[1])),
                    'keff_guess': float(tokens[2]),
                    'inactive': int(float(tokens[3])),
                    'batches': int(float(tokens[4])),
                }
            elif lower.startswith('ksrc'):
                tokens = line_stripped.split()
                self.ksrc = [float(t) for t in tokens[1:4]]
            elif re.match(r'^mt\d+', lower):
                mt_match = re.match(r'mt(\d+)\s+(\S+)', line_stripped, re.IGNORECASE)
                if mt_match:
                    mat_id = int(mt_match.group(1))
                    lib = mt_match.group(2)
                    lib_base = lib.split('.')[0]
                    sab_name = THERMAL_SCATTERING.get(lib_base, lib_base)
                    self.thermal_sab[mat_id] = sab_name
            elif re.match(r'^m\d+', lower):
                mat_match = re.match(r'm(\d+)\s+(.*)', line_stripped, re.IGNORECASE)
                if mat_match:
                    mat_id = int(mat_match.group(1))
                    data = mat_match.group(2)
                    tokens = data.split()
                    nuclides = []
                    i = 0
                    while i < len(tokens) - 1:
                        zaid = tokens[i]
                        # Skip non-ZAID tokens
                        if '.' not in zaid:
                            i += 1
                            continue
                        fraction = float(tokens[i + 1])
                        name = zaid_to_nuclide(zaid)
                        nuclides.append({'name': name, 'ao': fraction})
                        i += 2
                    self.materials[mat_id] = nuclides

    def get_boundary_surfaces(self):
        """Determine which surfaces are outer boundaries from void cells (imp:n=0)."""
        boundary_ids = set()
        for cell in self.cells:
            if cell['importance'] == 0 and cell['material'] == 0:
                region = cell['region']
                # Extract all surface IDs from region expression
                # Handle union (:) and parentheses
                surface_ids = re.findall(r'-?\d+', region)
                for sid_str in surface_ids:
                    boundary_ids.add(abs(int(sid_str)))
        return boundary_ids

    # ============================================================
    # XML Generators
    # ============================================================

    def write_geometry(self, output_dir):
        """Generate geometry.xml."""
        root = ET.Element('geometry')
        boundary_ids = self.get_boundary_surfaces()

        for surf in self.surfaces:
            elem = ET.SubElement(root, 'surface')
            elem.set('id', str(surf['id']))

            openmc_type, coeff_func = SURFACE_MAP[surf['type']]
            elem.set('type', openmc_type)

            coeffs = coeff_func(surf['args'])
            elem.set('coeffs', ' '.join(format_coeff(c) for c in coeffs))

            if surf['id'] in boundary_ids:
                elem.set('boundary', 'vacuum')

        for cell in self.cells:
            if cell['importance'] == 0:
                continue  # skip outer void cells

            elem = ET.SubElement(root, 'cell')
            elem.set('id', str(cell['id']))

            if cell['material'] == 0:
                elem.set('material', 'void')
            else:
                elem.set('material', str(cell['material']))

            elem.set('region', cell['region'])

        tree = ET.ElementTree(root)
        ET.indent(tree, space='  ')
        os.makedirs(output_dir, exist_ok=True)
        tree.write(os.path.join(output_dir, 'geometry.xml'),
                   xml_declaration=True, encoding='unicode')

    def write_materials(self, output_dir):
        """Generate materials.xml."""
        root = ET.Element('materials')

        for mat_id in sorted(self.materials.keys()):
            mat_elem = ET.SubElement(root, 'material')
            mat_elem.set('id', str(mat_id))

            dens = ET.SubElement(mat_elem, 'density')
            dens.set('units', 'sum')

            for nuc in self.materials[mat_id]:
                nuc_elem = ET.SubElement(mat_elem, 'nuclide')
                nuc_elem.set('name', nuc['name'])
                nuc_elem.set('ao', f"{nuc['ao']:.6g}")

            if mat_id in self.thermal_sab:
                sab_elem = ET.SubElement(mat_elem, 'sab')
                sab_elem.set('name', self.thermal_sab[mat_id])

        tree = ET.ElementTree(root)
        ET.indent(tree, space='  ')
        os.makedirs(output_dir, exist_ok=True)
        tree.write(os.path.join(output_dir, 'materials.xml'),
                   xml_declaration=True, encoding='unicode')

    def write_settings(self, output_dir):
        """Generate settings.xml."""
        root = ET.Element('settings')

        rm = ET.SubElement(root, 'run_mode')
        rm.text = 'eigenvalue'

        if self.kcode:
            p = ET.SubElement(root, 'particles')
            p.text = str(self.kcode['particles'])

            b = ET.SubElement(root, 'batches')
            b.text = str(self.kcode['batches'])

            i = ET.SubElement(root, 'inactive')
            i.text = str(self.kcode['inactive'])

        if self.ksrc:
            source = ET.SubElement(root, 'source')
            source.set('strength', '1.0')
            space = ET.SubElement(source, 'space')
            space.set('type', 'point')
            params = ET.SubElement(space, 'parameters')
            params.text = ' '.join(str(v) for v in self.ksrc)

        tree = ET.ElementTree(root)
        ET.indent(tree, space='  ')
        os.makedirs(output_dir, exist_ok=True)
        tree.write(os.path.join(output_dir, 'settings.xml'),
                   xml_declaration=True, encoding='unicode')


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.mcnp> <output_dir>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2]

    parser = MCNPParser(input_file)
    parser.write_geometry(output_dir)
    parser.write_materials(output_dir)
    parser.write_settings(output_dir)

    n_surfs = len(parser.surfaces)
    n_cells = len([c for c in parser.cells if c['importance'] > 0])
    n_mats = len(parser.materials)
    print(f"Translated {input_file} -> {output_dir}/ "
          f"({n_surfs} surfaces, {n_cells} cells, {n_mats} materials)")


if __name__ == '__main__':
    main()
