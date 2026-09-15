#!/usr/bin/env python3
"""RDLA Scene Graph Analyzer for OpenMoonRay scene description files."""

import sys
import re
import json
from collections import defaultdict

GEOMETRY_TYPES = {
    'RdlMeshGeometry', 'BoxGeometry', 'SphereGeometry',
    'UsdGeometry', 'RdlCurveGeometry', 'VdbGeometry'
}

LIGHT_TYPES = {
    'RectLight', 'SphereLight', 'DiskLight', 'CylinderLight',
    'DistantLight', 'EnvLight', 'SpotLight', 'MeshLight'
}

MATERIAL_TYPES = {
    'DwaBaseMaterial', 'DwaMetalMaterial', 'DwaSolidDielectricMaterial',
    'DwaRefractiveMaterial', 'DwaFabricMaterial', 'DwaSkinMaterial',
    'DwaClearcoatMaterial', 'DwaHairMaterial', 'DwaGlitterMaterial',
    'DwaEmissiveMaterial'
}

TRANSMISSIVE_TYPES = {'DwaSolidDielectricMaterial', 'DwaRefractiveMaterial'}


class RDLATokenizer:
    """Tokenizes RDLA (Lua-based) scene description files."""

    TOKEN_PATTERNS = [
        ('COMMENT', r'--[^\n]*'),
        ('STRING', r'"(?:[^"\\]|\\.)*"'),
        ('NUMBER', r'-?\d+\.?\d*(?:[eE][+-]?\d+)?'),
        ('IDENT', r'[a-zA-Z_]\w*'),
        ('LBRACE', r'\{'),
        ('RBRACE', r'\}'),
        ('LBRACKET', r'\['),
        ('RBRACKET', r'\]'),
        ('LPAREN', r'\('),
        ('RPAREN', r'\)'),
        ('EQUALS', r'='),
        ('COMMA', r','),
        ('STAR', r'\*'),
        ('WS', r'\s+'),
    ]

    def __init__(self, text):
        self.tokens = []
        pattern = '|'.join(f'(?P<{n}>{p})' for n, p in self.TOKEN_PATTERNS)
        for m in re.finditer(pattern, text):
            kind = m.lastgroup
            val = m.group()
            if kind in ('WS', 'COMMENT'):
                continue
            if kind == 'STRING':
                val = val[1:-1].replace('\\"', '"').replace('\\\\', '\\')
            elif kind == 'NUMBER':
                val = float(val) if '.' in val or 'e' in val.lower() else int(val)
            self.tokens.append((kind, val))


class ParseError(Exception):
    pass


class RDLAParser:
    """Parses tokenized RDLA into a scene graph."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.objects = {}
        self.scene_variables = {}
        self.bindings = []
        self.references = []

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return (None, None)

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind):
        if self.pos >= len(self.tokens):
            raise ParseError(f"Expected {kind}, got EOF")
        tk, tv = self.tokens[self.pos]
        if tk != kind:
            raise ParseError(f"Expected {kind}, got {tk} ({tv!r})")
        self.pos += 1
        return tv

    def match(self, kind):
        if self.pos < len(self.tokens) and self.tokens[self.pos][0] == kind:
            v = self.tokens[self.pos][1]
            self.pos += 1
            return v
        return None

    def parse(self):
        while self.pos < len(self.tokens):
            self.parse_declaration()

    def parse_declaration(self):
        type_name = self.expect('IDENT')

        if type_name == 'SceneVariables':
            self.expect('LBRACE')
            attrs = self.parse_attributes()
            self.expect('RBRACE')
            self.scene_variables = {
                k: v for k, v in attrs.items()
                if isinstance(v, (int, float, str, bool))
            }
        else:
            self.expect('LPAREN')
            path = self.expect('STRING')
            self.expect('RPAREN')
            self.expect('LBRACE')

            if type_name == 'Layer':
                entries = self.parse_layer_body(path)
                self.objects[path] = {
                    'type': type_name,
                    'attributes': {},
                    'layer_entries': entries
                }
            else:
                attrs = self.parse_attributes()
                self.objects[path] = {'type': type_name, 'attributes': attrs}
                self._extract_refs(path, attrs)

            self.expect('RBRACE')

    def _extract_refs(self, path, attrs):
        """Extract bindings and references from parsed attributes."""
        for attr_name, val in attrs.items():
            if isinstance(val, dict):
                if val.get('_type') == 'binding':
                    self.bindings.append({
                        'source': path,
                        'attribute': attr_name,
                        'target': val['target']
                    })
                elif val.get('_type') == 'reference':
                    self.references.append({
                        'source': path,
                        'target': val['target']
                    })
            elif isinstance(val, list):
                self._extract_refs_from_list(path, val)

    def _extract_refs_from_list(self, source, items):
        """Recursively extract references from list/table values."""
        for item in items:
            if isinstance(item, dict) and item.get('_type') == 'reference':
                self.references.append({
                    'source': source,
                    'target': item['target']
                })
            elif isinstance(item, list):
                self._extract_refs_from_list(source, item)

    def parse_layer_body(self, layer_path):
        """Parse Layer entries: {GeomRef, "part", MatRef, LightSetRef}, ..."""
        entries = []
        while self.peek()[0] != 'RBRACE':
            self.expect('LBRACE')
            entry = []
            while self.peek()[0] != 'RBRACE':
                val = self.parse_value()
                entry.append(val)
                self.match('COMMA')
                if isinstance(val, dict) and val.get('_type') == 'reference':
                    self.references.append({
                        'source': layer_path,
                        'target': val['target']
                    })
            self.expect('RBRACE')
            entries.append(entry)
            self.match('COMMA')
        return entries

    def parse_attributes(self):
        """Parse ["key"] = value pairs."""
        attrs = {}
        while self.peek()[0] == 'LBRACKET':
            self.expect('LBRACKET')
            name = self.expect('STRING')
            self.expect('RBRACKET')
            self.expect('EQUALS')
            value = self.parse_value()
            attrs[name] = value
            self.match('COMMA')
        return attrs

    def parse_value(self):
        """Parse a single value expression."""
        kind, value = self.peek()

        if kind == 'NUMBER':
            self.advance()
            return value
        elif kind == 'STRING':
            self.advance()
            return value
        elif kind == 'LBRACE':
            return self.parse_table()
        elif kind == 'IDENT':
            if value in ('true', 'false'):
                self.advance()
                return value == 'true'
            elif value == 'bind':
                return self.parse_bind()
            elif value in ('Rgb', 'Vec2', 'Vec3'):
                return self.parse_func_call()
            elif value in ('translate', 'rotate', 'scale'):
                return self.parse_transform_chain()
            else:
                # Object reference: TypeName("path")
                self.advance()
                if self.peek()[0] == 'LPAREN':
                    self.advance()  # consume '('
                    ref_path = self.expect('STRING')
                    self.expect('RPAREN')
                    return {
                        '_type': 'reference',
                        'ref_type': value,
                        'target': ref_path
                    }
                return value
        else:
            raise ParseError(f"Unexpected token {kind} ({value!r})")

    def parse_bind(self):
        """Parse bind(TypeName("/path"))."""
        self.advance()  # consume 'bind'
        self.expect('LPAREN')
        ref_type = self.expect('IDENT')
        self.expect('LPAREN')
        target = self.expect('STRING')
        self.expect('RPAREN')
        self.expect('RPAREN')
        return {'_type': 'binding', 'ref_type': ref_type, 'target': target}

    def parse_func_call(self):
        """Parse Rgb(r,g,b), Vec2(x,y), Vec3(x,y,z)."""
        _, name = self.advance()
        self.expect('LPAREN')
        args = []
        while self.peek()[0] != 'RPAREN':
            args.append(self.parse_value())
            self.match('COMMA')
        self.expect('RPAREN')
        return {'_type': name.lower(), 'values': args}

    def parse_transform_chain(self):
        """Parse translate(...) * rotate(...) * scale(...)."""
        first = self.parse_single_transform()
        transforms = [first]
        while self.peek()[0] == 'STAR':
            self.advance()  # consume '*'
            transforms.append(self.parse_single_transform())
        if len(transforms) == 1:
            return transforms[0]
        return {'_type': 'transform_chain', 'transforms': transforms}

    def parse_single_transform(self):
        """Parse a single transform function call."""
        name = self.expect('IDENT')
        self.expect('LPAREN')
        args = []
        while self.peek()[0] != 'RPAREN':
            args.append(self.parse_value())
            self.match('COMMA')
        self.expect('RPAREN')
        return {'_type': 'transform', 'func': name, 'args': args}

    def parse_table(self):
        """Parse a Lua table: {item1, item2, ...}."""
        self.expect('LBRACE')
        items = []
        while self.peek()[0] != 'RBRACE':
            items.append(self.parse_value())
            self.match('COMMA')
        self.expect('RBRACE')
        return items


def find_cycles(bindings):
    """Find cycles in the directed binding graph using DFS."""
    adj = defaultdict(list)
    for b in bindings:
        adj[b['source']].append(b['target'])

    visited = set()
    rec_stack = set()
    cycles = []

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                idx = path.index(neighbor)
                cycles.append(list(path[idx:]))
        path.pop()
        rec_stack.remove(node)

    for node in list(adj.keys()):
        if node not in visited:
            dfs(node, [])

    return cycles


def find_orphans(objects, bindings, references):
    """Find objects not reachable from Layer or RenderOutput roots."""
    adj = defaultdict(set)
    for ref in references:
        adj[ref['source']].add(ref['target'])
    for b in bindings:
        adj[b['source']].add(b['target'])

    roots = {p for p, o in objects.items()
             if o['type'] in ('Layer', 'RenderOutput')}
    reachable = set(roots)
    queue = list(roots)
    while queue:
        node = queue.pop(0)
        for nbr in adj.get(node, set()):
            if nbr in objects and nbr not in reachable:
                reachable.add(nbr)
                queue.append(nbr)

    return sorted(set(objects.keys()) - reachable)


def validate_parameters(objects):
    """Check rendering parameter constraints."""
    issues = []
    for path, obj in objects.items():
        attrs = obj.get('attributes', {})
        t = obj['type']

        if t in TRANSMISSIVE_TYPES:
            ior = attrs.get('ior')
            if isinstance(ior, (int, float)) and ior < 1.0:
                issues.append({
                    'type': 'invalid_parameter',
                    'object': path,
                    'attribute': 'ior',
                    'value': ior,
                    'constraint': 'must be >= 1.0'
                })

        if t in MATERIAL_TYPES:
            r = attrs.get('roughness')
            if isinstance(r, (int, float)) and (r < 0.0 or r > 1.0):
                issues.append({
                    'type': 'invalid_parameter',
                    'object': path,
                    'attribute': 'roughness',
                    'value': r,
                    'constraint': 'must be in [0.0, 1.0]'
                })

        if t in LIGHT_TYPES:
            intensity = attrs.get('intensity')
            if isinstance(intensity, (int, float)) and intensity <= 0:
                issues.append({
                    'type': 'invalid_parameter',
                    'object': path,
                    'attribute': 'intensity',
                    'value': intensity,
                    'constraint': 'must be > 0'
                })

        if t == 'SphereGeometry':
            rad = attrs.get('radius')
            if isinstance(rad, (int, float)) and rad <= 0:
                issues.append({
                    'type': 'invalid_parameter',
                    'object': path,
                    'attribute': 'radius',
                    'value': rad,
                    'constraint': 'must be > 0'
                })

    return issues


def compute_complexity(objects, scene_vars):
    """Compute render complexity score."""
    G = sum(1 for o in objects.values() if o['type'] in GEOMETRY_TYPES)
    S = scene_vars.get('pixel_samples', 8)
    D = scene_vars.get('max_depth', 5)
    T = sum(1 for o in objects.values() if o['type'] in TRANSMISSIVE_TYPES)
    L = sum(1 for o in objects.values() if o['type'] in LIGHT_TYPES)
    return round(G * S * (D ** 1.5) * (1 + 0.5 * T) * (1 + 0.3 * L), 2)


def analyze(filepath):
    """Analyze an RDLA scene file and return structured results."""
    with open(filepath) as f:
        text = f.read()

    tok = RDLATokenizer(text)
    parser = RDLAParser(tok.tokens)
    parser.parse()

    defined = set(parser.objects.keys())
    issues = []

    # Unresolved references
    for b in parser.bindings:
        if b['target'] not in defined:
            issues.append({
                'type': 'unresolved_reference',
                'source': b['source'],
                'attribute': b['attribute'],
                'target': b['target']
            })

    # Circular dependencies
    for cycle in find_cycles(parser.bindings):
        issues.append({'type': 'circular_dependency', 'cycle': cycle})

    # Parameter validation
    issues.extend(validate_parameters(parser.objects))

    # Orphaned objects
    for orphan in find_orphans(parser.objects, parser.bindings, parser.references):
        issues.append({'type': 'orphaned_object', 'object': orphan})

    return {
        'objects': sorted(
            [{'name': n, 'type': o['type']} for n, o in parser.objects.items()],
            key=lambda x: x['name']
        ),
        'bindings': sorted(
            parser.bindings,
            key=lambda x: (x['source'], x['attribute'])
        ),
        'scene_variables': dict(parser.scene_variables),
        'issues': sorted(
            issues,
            key=lambda x: (x['type'], x.get('object', x.get('source', '')))
        ),
        'complexity_score': compute_complexity(parser.objects, parser.scene_variables)
    }


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 rdla_analyzer.py <scene.rdla>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(analyze(sys.argv[1]), indent=2))
