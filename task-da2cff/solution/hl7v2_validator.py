#!/usr/bin/env python3
"""
HL7 v2 ER7 Message Conformance Validator.

Parses an HL7 v2 ER7-encoded message and validates it against an XML
conformance profile, producing a JSON validation report.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

class Separators:
    def __init__(self, field='|', component='^', repetition='~',
                 escape='\\', subcomponent='&'):
        self.fs = field
        self.cs = component
        self.rs = repetition
        self.esc = escape
        self.ss = subcomponent

    def resolve_escapes(self, raw):
        """Resolve HL7 escape sequences to compute display length."""
        if self.esc not in raw:
            return raw
        result = raw
        result = result.replace(f'{self.esc}F{self.esc}', self.fs)
        result = result.replace(f'{self.esc}S{self.esc}', self.cs)
        result = result.replace(f'{self.esc}R{self.esc}', self.rs)
        result = result.replace(f'{self.esc}E{self.esc}', self.esc)
        result = result.replace(f'{self.esc}T{self.esc}', self.ss)
        return result

    def has_unescaped(self, raw):
        """Check if a primitive value contains unescaped separator chars."""
        # Remove all escape sequences first
        cleaned = raw
        for seq in [f'{self.esc}F{self.esc}', f'{self.esc}S{self.esc}',
                    f'{self.esc}R{self.esc}', f'{self.esc}E{self.esc}',
                    f'{self.esc}T{self.esc}']:
            cleaned = cleaned.replace(seq, '')
        # Also remove any other escape sequences like \Xhh\ etc.
        cleaned = re.sub(re.escape(self.esc) + r'[^' + re.escape(self.esc) + r']*' + re.escape(self.esc), '', cleaned)
        # Now check for raw separators
        for sep in [self.cs, self.ss, self.rs]:
            if sep in cleaned:
                return True
        return False


class ProfileModel:
    """In-memory representation of a conformance profile."""
    def __init__(self, xml_path):
        tree = ET.parse(xml_path)
        self.root = tree.getroot()
        self.datatypes = {}
        self.segments = {}
        self.message = None
        self._parse()

    def _parse(self):
        # Parse datatypes
        dt_elem = self.root.find('Datatypes')
        if dt_elem is not None:
            for dt in dt_elem.findall('Datatype'):
                dt_id = dt.get('ID')
                components = []
                for comp in dt.findall('Component'):
                    components.append({
                        'name': comp.get('Name'),
                        'datatype': comp.get('Datatype'),
                        'usage': comp.get('Usage', 'O'),
                        'min_length': self._parse_length(comp.get('MinLength', '0')),
                        'max_length': self._parse_length(comp.get('MaxLength', '*')),
                    })
                self.datatypes[dt_id] = {
                    'id': dt_id,
                    'name': dt.get('Name'),
                    'description': dt.get('Description', ''),
                    'components': components,
                    'is_primitive': len(components) == 0,
                }

        # Parse segments
        seg_elem = self.root.find('Segments')
        if seg_elem is not None:
            for seg in seg_elem.findall('Segment'):
                seg_id = seg.get('ID')
                fields = []
                for field in seg.findall('Field'):
                    fields.append({
                        'name': field.get('Name'),
                        'datatype': field.get('Datatype'),
                        'usage': field.get('Usage', 'O'),
                        'min': int(field.get('Min', '0')),
                        'max': self._parse_max(field.get('Max', '1')),
                        'min_length': self._parse_length(field.get('MinLength', '0')),
                        'max_length': self._parse_length(field.get('MaxLength', '*')),
                        'item_no': field.get('ItemNo', ''),
                    })
                self.segments[seg_id] = {
                    'id': seg_id,
                    'name': seg.get('Name'),
                    'description': seg.get('Description', ''),
                    'fields': fields,
                }

        # Parse message structure
        msgs = self.root.find('Messages')
        if msgs is not None:
            msg = msgs.find('Message')
            if msg is not None:
                self.message = {
                    'id': msg.get('ID'),
                    'type': msg.get('Type'),
                    'event': msg.get('Event'),
                    'structure': self._parse_structure(msg),
                }

    def _parse_structure(self, elem):
        """Recursively parse message structure (segments and groups)."""
        children = []
        for child in elem:
            if child.tag == 'Segment':
                children.append({
                    'type': 'segment',
                    'ref': child.get('Ref'),
                    'usage': child.get('Usage', 'O'),
                    'min': int(child.get('Min', '0')),
                    'max': self._parse_max(child.get('Max', '1')),
                })
            elif child.tag == 'Group':
                children.append({
                    'type': 'group',
                    'name': child.get('Name'),
                    'usage': child.get('Usage', 'O'),
                    'min': int(child.get('Min', '0')),
                    'max': self._parse_max(child.get('Max', '*')),
                    'structure': self._parse_structure(child),
                })
        return children

    @staticmethod
    def _parse_max(val):
        if val == '*':
            return float('inf')
        return int(val)

    @staticmethod
    def _parse_length(val):
        if val == '*' or val is None:
            return float('inf')
        try:
            return int(val)
        except ValueError:
            return float('inf')

    def get_all_segment_ids(self):
        return set(self.segments.keys())

    def is_primitive(self, datatype_id):
        if datatype_id not in self.datatypes:
            return True
        return self.datatypes[datatype_id]['is_primitive']


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ER7Parser:
    """Parse an ER7-encoded HL7 v2 message into structured data."""

    def __init__(self, raw_text):
        self.lines = []
        self.separators = Separators()
        self.parsed_segments = []
        self.invalid_lines = []
        self._parse(raw_text)

    def _parse(self, raw_text):
        # Normalize line endings
        text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
        raw_lines = [l for l in text.split('\n') if l.strip()]

        if not raw_lines:
            return

        # Find MSH line
        msh_idx = None
        for i, line in enumerate(raw_lines):
            if line.startswith('MSH'):
                msh_idx = i
                break

        if msh_idx is None:
            # All lines are invalid
            for i, line in enumerate(raw_lines):
                self.invalid_lines.append((i + 1, line))
            return

        # Lines before MSH are invalid
        for i in range(msh_idx):
            self.invalid_lines.append((i + 1, raw_lines[i]))

        msh_line = raw_lines[msh_idx]
        # MSH-1 is the field separator (char at position 3)
        self.separators.fs = msh_line[3]
        # MSH-2 is encoding characters
        enc_end = msh_line.index(self.separators.fs, 4)
        enc_chars = msh_line[4:enc_end]
        if len(enc_chars) >= 1:
            self.separators.cs = enc_chars[0]
        if len(enc_chars) >= 2:
            self.separators.rs = enc_chars[1]
        if len(enc_chars) >= 3:
            self.separators.esc = enc_chars[2]
        if len(enc_chars) >= 4:
            self.separators.ss = enc_chars[3]

        # Parse remaining lines starting from MSH
        seg_id_pattern = re.compile(r'^[A-Z][A-Z0-9]{2}')
        for i in range(msh_idx, len(raw_lines)):
            line = raw_lines[i]
            line_num = i + 1
            # Check if it's a valid segment line
            if len(line) < 3:
                self.invalid_lines.append((line_num, line))
                continue
            seg_id_match = seg_id_pattern.match(line)
            if not seg_id_match:
                self.invalid_lines.append((line_num, line))
                continue
            seg_id = seg_id_match.group(0)
            # Must be followed by field separator or end of line
            rest = line[3:]
            if rest and rest[0] != self.separators.fs:
                self.invalid_lines.append((line_num, line))
                continue

            # Parse fields
            if seg_id == 'MSH':
                # MSH is special: MSH-1 is the field separator itself
                # Fields after MSH| are MSH-2 onwards
                field_parts = line[4:].split(self.separators.fs)
                fields = [self.separators.fs] + field_parts
            else:
                if rest:
                    field_parts = rest[1:].split(self.separators.fs)
                    fields = field_parts
                else:
                    fields = []

            self.parsed_segments.append({
                'id': seg_id,
                'fields': fields,
                'line_num': line_num,
                'raw': line,
            })


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ConformanceValidator:
    def __init__(self, profile: ProfileModel, parser: ER7Parser):
        self.profile = profile
        self.parser = parser
        self.sep = parser.separators
        self.issues = []

    def validate(self):
        self.issues = []
        self._check_invalid_lines()
        self._check_unexpected_segments()

        # Match segments to message structure
        if self.profile.message:
            seg_list = list(self.parser.parsed_segments)
            self._validate_structure(
                self.profile.message['structure'],
                seg_list,
                0,
                ''
            )

        return self._build_report()

    def _add_issue(self, category, severity, path, description):
        self.issues.append({
            'category': category,
            'severity': severity,
            'path': path,
            'description': description,
        })

    # -- Invalid lines --
    def _check_invalid_lines(self):
        for line_num, content in self.parser.invalid_lines:
            self._add_issue(
                'invalid_lines', 'error',
                f'Line:{line_num}',
                f"Invalid line at position {line_num}: '{content}'"
            )

    # -- Unexpected segments --
    def _check_unexpected_segments(self):
        known_ids = self.profile.get_all_segment_ids()
        for seg in self.parser.parsed_segments:
            if seg['id'] not in known_ids:
                self._add_issue(
                    'unexpected_segments', 'error',
                    f"{seg['id']}",
                    f"Unexpected segment {seg['id']} at line {seg['line_num']} "
                    f"is not defined in the profile"
                )

    # -- Structure validation --
    def _validate_structure(self, structure_def, segments, seg_idx, parent_path):
        """Recursively validate message structure. Returns the next seg_idx to process."""
        idx = seg_idx
        for struct_item in structure_def:
            if struct_item['type'] == 'segment':
                idx = self._validate_segment_in_structure(
                    struct_item, segments, idx, parent_path)
            elif struct_item['type'] == 'group':
                idx = self._validate_group_in_structure(
                    struct_item, segments, idx, parent_path)
        return idx

    def _get_head_segment_ids(self, struct_item):
        """Get the set of segment IDs that can start this structure item."""
        if struct_item['type'] == 'segment':
            return {struct_item['ref']}
        elif struct_item['type'] == 'group':
            # The head of a group is the head of its first child
            if struct_item['structure']:
                return self._get_head_segment_ids(struct_item['structure'][0])
        return set()

    def _get_all_segment_ids_in_structure(self, struct_items):
        """Get all segment IDs that can appear within a list of structure items."""
        ids = set()
        for item in struct_items:
            if item['type'] == 'segment':
                ids.add(item['ref'])
            elif item['type'] == 'group':
                ids.update(self._get_all_segment_ids_in_structure(
                    item['structure']))
        return ids

    def _validate_segment_in_structure(self, struct_item, segments, seg_idx, parent_path):
        """Validate a segment reference within the message structure."""
        ref = struct_item['ref']
        usage = struct_item['usage']
        min_count = struct_item['min']
        max_count = struct_item['max']

        # Count how many consecutive segments match this ref
        count = 0
        idx = seg_idx
        while idx < len(segments) and segments[idx]['id'] == ref:
            count += 1
            seg_instance = segments[idx]
            seg_path = f"{ref}[{count}]"

            # Check X-usage presence
            if usage == 'X':
                self._add_issue(
                    'usage', 'error', seg_path,
                    f"X-usage Segment '{self.profile.segments.get(ref, {}).get('description', ref)}' "
                    f"({ref}) is present but forbidden"
                )
            elif usage == 'W':
                self._add_issue(
                    'usage', 'warning', seg_path,
                    f"W-usage Segment '{self.profile.segments.get(ref, {}).get('description', ref)}' "
                    f"({ref}) is present but withdrawn"
                )

            # Validate fields within the segment (skip if X usage)
            if usage != 'X' and ref in self.profile.segments:
                self._validate_segment_fields(seg_instance, ref, count)

            idx += 1

        # Check R-usage absence
        if count == 0 and usage == 'R':
            self._add_issue(
                'usage', 'error', f"{ref}[1]",
                f"R-usage Segment '{self.profile.segments.get(ref, {}).get('description', ref)}' "
                f"({ref}) is missing"
            )

        # Cardinality checks (only if element is not X-usage)
        if usage != 'X' and count > 0:
            if count < min_count:
                self._add_issue(
                    'cardinality', 'error',
                    f"{ref}[{count}]",
                    f"Segment {ref} count ({count}) below minimum ({min_count})"
                )
            if count > max_count:
                self._add_issue(
                    'cardinality', 'error',
                    f"{ref}[{count}]",
                    f"Segment {ref} count ({count}) exceeds maximum ({int(max_count) if max_count != float('inf') else '*'})"
                )

        return idx

    def _validate_group_in_structure(self, struct_item, segments, seg_idx, parent_path):
        """Validate a group within the message structure."""
        group_name = struct_item['name']
        usage = struct_item['usage']
        min_count = struct_item['min']
        max_count = struct_item['max']
        structure = struct_item['structure']

        head_ids = self._get_head_segment_ids(struct_item)
        all_ids = self._get_all_segment_ids_in_structure(structure)

        count = 0
        idx = seg_idx

        while idx < len(segments):
            # Check if current segment can start this group
            if segments[idx]['id'] not in head_ids:
                break
            count += 1
            group_path = f"{group_name}[{count}]"

            if usage == 'X':
                self._add_issue(
                    'usage', 'error', group_path,
                    f"X-usage Group '{group_name}' is present but forbidden"
                )
                # Still need to consume the segments belonging to this group
                while idx < len(segments) and segments[idx]['id'] in all_ids:
                    idx += 1
                continue

            # Recursively validate the group's structure
            idx = self._validate_structure(structure, segments, idx, group_path)

        # Check R-usage absence
        if count == 0 and usage == 'R':
            self._add_issue(
                'usage', 'error', f"{group_name}[1]",
                f"R-usage Group '{group_name}' is missing"
            )

        # Cardinality
        if usage != 'X' and count > 0:
            if count < min_count:
                self._add_issue(
                    'cardinality', 'error',
                    f"{group_name}[{count}]",
                    f"Group {group_name} count ({count}) below minimum ({min_count})"
                )
            if count > max_count:
                self._add_issue(
                    'cardinality', 'error',
                    f"{group_name}[{count}]",
                    f"Group {group_name} count ({count}) exceeds maximum "
                    f"({int(max_count) if max_count != float('inf') else '*'})"
                )

        return idx

    # -- Field-level validation --
    def _validate_segment_fields(self, seg_instance, seg_id, seg_instance_num):
        """Validate fields within a parsed segment instance."""
        seg_def = self.profile.segments.get(seg_id)
        if not seg_def:
            return

        fields = seg_instance['fields']
        field_defs = seg_def['fields']
        seg_path = f"{seg_id}[{seg_instance_num}]"

        # For MSH, field index 0 is MSH-1 (field separator)
        # field index 1 is MSH-2 (encoding chars), etc.
        for f_idx, field_def in enumerate(field_defs):
            field_num = f_idx + 1
            field_name = field_def['name']
            field_usage = field_def['usage']
            field_dt = field_def['datatype']
            f_min = field_def['min']
            f_max = field_def['max']
            f_min_len = field_def['min_length']
            f_max_len = field_def['max_length']

            # Skip MSH-1 and MSH-2 validation (they define separators)
            if seg_id == 'MSH' and field_num <= 2:
                continue

            # Get raw field value(s)
            if f_idx < len(fields):
                raw_field = fields[f_idx]
            else:
                raw_field = ''

            # Split by repetition separator
            if raw_field:
                repetitions = raw_field.split(self.sep.rs)
            else:
                repetitions = []

            is_empty = (len(repetitions) == 0 or
                        all(r.strip() == '' for r in repetitions))

            # Usage checks
            if is_empty and field_usage == 'R':
                self._add_issue(
                    'usage', 'error',
                    f"{seg_path}-{field_num}[1]",
                    f"R-usage Field '{field_name}' ({seg_id}-{field_num}) is missing"
                )
            elif not is_empty and field_usage == 'X':
                self._add_issue(
                    'usage', 'error',
                    f"{seg_path}-{field_num}[1]",
                    f"X-usage Field '{field_name}' ({seg_id}-{field_num}) is present but forbidden"
                )
            elif not is_empty and field_usage == 'W':
                self._add_issue(
                    'usage', 'warning',
                    f"{seg_path}-{field_num}[1]",
                    f"W-usage Field '{field_name}' ({seg_id}-{field_num}) is present but withdrawn"
                )

            if is_empty:
                continue

            # Cardinality check on repetitions
            rep_count = len(repetitions)
            if rep_count < f_min:
                self._add_issue(
                    'cardinality', 'error',
                    f"{seg_path}-{field_num}[{rep_count}]",
                    f"Field {seg_id}-{field_num} repetition count ({rep_count}) "
                    f"below minimum ({f_min})"
                )
            if rep_count > f_max:
                self._add_issue(
                    'cardinality', 'error',
                    f"{seg_path}-{field_num}[{rep_count}]",
                    f"Field {seg_id}-{field_num} repetition count ({rep_count}) "
                    f"exceeds maximum ({int(f_max) if f_max != float('inf') else '*'})"
                )

            # Validate each repetition
            for r_idx, rep_val in enumerate(repetitions):
                rep_num = r_idx + 1
                field_path = f"{seg_path}-{field_num}[{rep_num}]"
                if not rep_val.strip():
                    continue
                self._validate_field_value(
                    rep_val, field_dt, field_path,
                    f_min_len, f_max_len, field_name,
                    f"{seg_id}-{field_num}")

        # Check for extra fields beyond what the profile defines
        if len(fields) > len(field_defs):
            for extra_idx in range(len(field_defs), len(fields)):
                if fields[extra_idx].strip():
                    field_num = extra_idx + 1
                    self._add_issue(
                        'extra', 'error',
                        f"{seg_path}-{field_num}[1]",
                        f"Extra field at position {field_num} in segment {seg_id} "
                        f"is not defined in the profile"
                    )

    def _validate_field_value(self, raw_val, datatype_id, path,
                              min_length, max_length, field_name, field_path):
        """Validate a single field value against its datatype."""
        if datatype_id == '-':
            # Withdrawn datatype
            return

        dt_def = self.profile.datatypes.get(datatype_id)

        if dt_def is None or dt_def['is_primitive']:
            # Primitive: check length and unescaped separators
            self._check_primitive_value(
                raw_val, path, min_length, max_length, field_name, field_path)
            return

        # Composite: split by component separator and validate each
        components = raw_val.split(self.sep.cs)
        comp_defs = dt_def['components']

        for c_idx, comp_def in enumerate(comp_defs):
            comp_num = c_idx + 1
            comp_name = comp_def['name']
            comp_usage = comp_def['usage']
            comp_dt = comp_def['datatype']
            comp_min_len = comp_def['min_length']
            comp_max_len = comp_def['max_length']
            comp_path = f"{path}.{comp_num}"

            if c_idx < len(components):
                comp_val = components[c_idx]
            else:
                comp_val = ''

            is_empty = comp_val.strip() == ''

            # Component usage checks
            if is_empty and comp_usage == 'R':
                self._add_issue(
                    'usage', 'error', comp_path,
                    f"R-usage Component '{comp_name}' ({field_path}.{comp_num}) is missing"
                )
            elif not is_empty and comp_usage == 'X':
                self._add_issue(
                    'usage', 'error', comp_path,
                    f"X-usage Component '{comp_name}' ({field_path}.{comp_num}) "
                    f"is present but forbidden"
                )
            elif not is_empty and comp_usage == 'W':
                self._add_issue(
                    'usage', 'warning', comp_path,
                    f"W-usage Component '{comp_name}' ({field_path}.{comp_num}) "
                    f"is present but withdrawn"
                )

            if is_empty:
                continue

            # Recurse into sub-datatype (for components that are composite)
            sub_dt = self.profile.datatypes.get(comp_dt)
            if sub_dt and not sub_dt['is_primitive']:
                # Sub-components split by subcomponent separator
                sub_comps = comp_val.split(self.sep.ss)
                sub_comp_defs = sub_dt['components']
                for sc_idx, sc_def in enumerate(sub_comp_defs):
                    sc_path = f"{comp_path}.{sc_idx + 1}"
                    if sc_idx < len(sub_comps):
                        sc_val = sub_comps[sc_idx]
                    else:
                        sc_val = ''

                    sc_empty = sc_val.strip() == ''
                    if sc_empty and sc_def['usage'] == 'R':
                        self._add_issue(
                            'usage', 'error', sc_path,
                            f"R-usage Sub-component '{sc_def['name']}' is missing"
                        )
                    elif not sc_empty and sc_def['usage'] == 'X':
                        self._add_issue(
                            'usage', 'error', sc_path,
                            f"X-usage Sub-component '{sc_def['name']}' "
                            f"is present but forbidden"
                        )
                    elif not sc_empty and sc_def['usage'] == 'W':
                        self._add_issue(
                            'usage', 'warning', sc_path,
                            f"W-usage Sub-component '{sc_def['name']}' "
                            f"is present but withdrawn"
                        )

                    if not sc_empty:
                        self._check_primitive_value(
                            sc_val, sc_path,
                            sc_def['min_length'], sc_def['max_length'],
                            sc_def['name'],
                            f"{field_path}.{comp_num}.{sc_idx + 1}")

                # Extra sub-components
                if len(sub_comps) > len(sub_comp_defs):
                    for ex_idx in range(len(sub_comp_defs), len(sub_comps)):
                        if sub_comps[ex_idx].strip():
                            self._add_issue(
                                'extra', 'error',
                                f"{comp_path}.{ex_idx + 1}",
                                f"Extra sub-component at position {ex_idx + 1} "
                                f"in {field_path}.{comp_num}"
                            )
            else:
                # Primitive component
                self._check_primitive_value(
                    comp_val, comp_path,
                    comp_min_len, comp_max_len,
                    comp_name, f"{field_path}.{comp_num}")

        # Extra components
        if len(components) > len(comp_defs):
            for ex_idx in range(len(comp_defs), len(components)):
                if components[ex_idx].strip():
                    self._add_issue(
                        'extra', 'error',
                        f"{path}.{ex_idx + 1}",
                        f"Extra component at position {ex_idx + 1} "
                        f"in {field_path} beyond profile definition"
                    )

    def _check_primitive_value(self, raw_val, path, min_length, max_length,
                               field_name, field_path):
        """Check length and unescaped separators for a primitive value."""
        # Resolve escape sequences for length calculation
        resolved = self.sep.resolve_escapes(raw_val)
        val_len = len(resolved)

        if min_length != float('inf') and val_len < min_length and min_length > 0:
            self._add_issue(
                'length', 'error', path,
                f"Value length ({val_len}) for '{field_name}' ({field_path}) "
                f"is below minimum ({int(min_length)})"
            )
        if max_length != float('inf') and val_len > max_length:
            self._add_issue(
                'length', 'error', path,
                f"Value length ({val_len}) for '{field_name}' ({field_path}) "
                f"exceeds maximum ({int(max_length)})"
            )

        # Check for unescaped separators in primitive values
        if self.sep.has_unescaped(raw_val):
            self._add_issue(
                'unescaped_separators', 'error', path,
                f"Unescaped separator in '{field_name}' ({field_path})"
            )

    # -- Report --
    def _build_report(self):
        counts = {
            'usage': 0,
            'cardinality': 0,
            'length': 0,
            'invalid_lines': 0,
            'unexpected_segments': 0,
            'extra': 0,
            'unescaped_separators': 0,
        }
        for issue in self.issues:
            cat = issue['category']
            if cat in counts:
                counts[cat] += 1

        return {
            'valid': len(self.issues) == 0,
            'counts': counts,
            'issues': self.issues,
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <profile.xml> <message.er7>",
              file=sys.stderr)
        sys.exit(1)

    profile_path = sys.argv[1]
    message_path = sys.argv[2]

    with open(message_path, 'r') as f:
        raw_message = f.read()

    profile = ProfileModel(profile_path)
    parser = ER7Parser(raw_message)
    validator = ConformanceValidator(profile, parser)
    report = validator.validate()

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
