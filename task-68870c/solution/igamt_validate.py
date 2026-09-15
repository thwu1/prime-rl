#!/usr/bin/env python3
"""
HL7v2 ER7 Message Validator — IGAMT model-based validation only.

Validates HL7v2 messages in ER7 (pipe-delimited) format against
IHE Gazelle IGAMT-format conformance profiles (Profile.xml,
Constraints.xml, ValueSets.xml).

Outputs JSON report to stdout. Exit 0 if valid, 1 if invalid.
"""

import sys
import os
import json
import re
import xml.etree.ElementTree as ET


class HL7Message:
    """Parsed HL7v2 ER7 message."""

    def __init__(self, raw_text):
        self.raw = raw_text
        self.segments = []
        self.field_sep = '|'
        self.comp_sep = '^'
        self.rep_sep = '~'
        self.esc_char = '\\'
        self.sub_sep = '&'
        self._parse(raw_text)

    def _parse(self, text):
        lines = re.split(r'\r\n|\r|\n', text.strip())
        lines = [l for l in lines if l.strip()]
        if not lines:
            raise ValueError("Empty message")
        msh_line = lines[0]
        if not msh_line.startswith('MSH'):
            raise ValueError("Message must start with MSH segment")
        if len(msh_line) < 9:
            raise ValueError("MSH segment too short")
        self.field_sep = msh_line[3]
        enc_chars = msh_line[4:8]
        if len(enc_chars) >= 1:
            self.comp_sep = enc_chars[0]
        if len(enc_chars) >= 2:
            self.rep_sep = enc_chars[1]
        if len(enc_chars) >= 3:
            self.esc_char = enc_chars[2]
        if len(enc_chars) >= 4:
            self.sub_sep = enc_chars[3]
        for line in lines:
            seg_name = line.split(self.field_sep)[0]
            if seg_name == 'MSH':
                fields = self._parse_msh_fields(line)
            else:
                fields = self._parse_fields(line)
            self.segments.append(Segment(seg_name, fields))

    def _parse_msh_fields(self, line):
        parts = line.split(self.field_sep)
        fields = []
        fields.append(Field(self.field_sep, self.comp_sep, self.sub_sep, self.rep_sep))
        fields.append(Field(self.comp_sep + self.rep_sep + self.esc_char + self.sub_sep,
                           self.comp_sep, self.sub_sep, self.rep_sep))
        for i in range(2, len(parts)):
            fields.append(Field(parts[i], self.comp_sep, self.sub_sep, self.rep_sep))
        return fields

    def _parse_fields(self, line):
        parts = line.split(self.field_sep)
        fields = []
        for i in range(1, len(parts)):
            fields.append(Field(parts[i], self.comp_sep, self.sub_sep, self.rep_sep))
        return fields


class Field:
    def __init__(self, raw_value, comp_sep='^', sub_sep='&', rep_sep='~'):
        self.raw = raw_value
        self.repetitions = []
        if raw_value:
            reps = raw_value.split(rep_sep)
            for rep in reps:
                components = []
                comp_parts = rep.split(comp_sep)
                for cp in comp_parts:
                    sub_parts = cp.split(sub_sep)
                    components.append(sub_parts)
                self.repetitions.append(components)

    def is_empty(self):
        return not self.raw or self.raw.strip() == ''

    def get_component(self, comp_idx, sub_idx=0, rep_idx=0):
        try:
            return self.repetitions[rep_idx][comp_idx][sub_idx]
        except (IndexError, TypeError):
            return ''

    def get_first_component_value(self):
        return self.get_component(0, 0, 0)

    def num_repetitions(self):
        return len(self.repetitions)


class Segment:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields

    def get_field(self, field_num):
        idx = field_num - 1
        if 0 <= idx < len(self.fields):
            return self.fields[idx]
        return Field('', '^', '&', '~')

    def field_count(self):
        return len(self.fields)


class Profile:
    def __init__(self, profile_path):
        tree = ET.parse(profile_path)
        self.root = tree.getroot()
        self.segments = {}
        self.datatypes = {}
        self.message = None
        self._parse()

    def _parse(self):
        segments_elem = self.root.find('Segments')
        if segments_elem is not None:
            for seg_elem in segments_elem:
                seg_id = seg_elem.attrib.get('ID')
                seg_name = seg_elem.attrib.get('Name')
                fields = []
                for field_elem in seg_elem:
                    if field_elem.tag == 'Field':
                        fields.append(field_elem.attrib)
                self.segments[seg_id] = {
                    'name': seg_name,
                    'fields': fields,
                    'id': seg_id
                }
        datatypes_elem = self.root.find('Datatypes')
        if datatypes_elem is not None:
            for dt_elem in datatypes_elem:
                dt_id = dt_elem.attrib.get('ID')
                components = []
                for comp_elem in dt_elem:
                    if comp_elem.tag == 'Component':
                        components.append(comp_elem.attrib)
                self.datatypes[dt_id] = {
                    'name': dt_elem.attrib.get('Name'),
                    'components': components,
                    'id': dt_id
                }
        msgs = self.root.find('Messages')
        if msgs is not None:
            msg_elem = msgs.find('Message')
            if msg_elem is not None:
                self.message = {
                    'id': msg_elem.attrib.get('ID'),
                    'name': msg_elem.attrib.get('Name'),
                    'elements': self._parse_message_elements(msg_elem)
                }

    def _parse_message_elements(self, msg_elem):
        elements = []
        for child in msg_elem:
            if child.tag == 'Segment':
                elements.append({
                    'type': 'segment',
                    'ref': child.attrib.get('Ref'),
                    'usage': child.attrib.get('Usage', 'O'),
                    'min': int(child.attrib.get('Min', '0')),
                    'max': child.attrib.get('Max', '1'),
                })
            elif child.tag == 'Group':
                elements.append({
                    'type': 'group',
                    'name': child.attrib.get('Name'),
                    'usage': child.attrib.get('Usage', 'O'),
                    'min': int(child.attrib.get('Min', '0')),
                    'max': child.attrib.get('Max', '1'),
                    'elements': self._parse_message_elements(child),
                })
        return elements

    def get_segment_name(self, ref_id):
        seg = self.segments.get(ref_id)
        return seg['name'] if seg else None


class Constraints:
    def __init__(self, constraints_path):
        tree = ET.parse(constraints_path)
        self.root = tree.getroot()
        self.datatype_predicates = {}
        self.segment_predicates = {}
        self.message_predicates = {}
        self.datatype_constraints = {}
        self.message_constraints = {}
        self._parse()

    def _parse(self):
        preds = self.root.find('Predicates')
        if preds is not None:
            self._parse_predicate_section(preds, 'Datatype', self.datatype_predicates)
            self._parse_predicate_section(preds, 'Segment', self.segment_predicates)
            self._parse_predicate_section(preds, 'Message', self.message_predicates)
        cons = self.root.find('Constraints')
        if cons is not None:
            self._parse_constraint_section(cons, 'Datatype', self.datatype_constraints)
            self._parse_constraint_section(cons, 'Message', self.message_constraints)

    def _parse_predicate_section(self, preds_elem, section_name, target_dict):
        section = preds_elem.find(section_name)
        if section is None:
            return
        for by_id in section.findall('ByID'):
            elem_id = by_id.attrib.get('ID')
            pred_list = []
            for pred in by_id.findall('Predicate'):
                pred_list.append({
                    'id': pred.attrib.get('ID'),
                    'target': pred.attrib.get('Target'),
                    'true_usage': pred.attrib.get('TrueUsage'),
                    'false_usage': pred.attrib.get('FalseUsage'),
                    'description': pred.findtext('Description', ''),
                    'condition': self._parse_condition(pred.find('Condition')),
                })
            target_dict[elem_id] = pred_list

    def _parse_condition(self, cond_elem):
        if cond_elem is None:
            return None
        for child in cond_elem:
            return self._parse_condition_node(child)
        return None

    def _parse_condition_node(self, node):
        if node is None:
            return None
        tag = node.tag
        if tag == 'Presence':
            return {'type': 'presence', 'path': node.attrib.get('Path')}
        elif tag == 'PlainText':
            return {
                'type': 'plaintext',
                'path': node.attrib.get('Path'),
                'text': node.attrib.get('Text'),
                'ignore_case': node.attrib.get('IgnoreCase', 'false').lower() == 'true'
            }
        elif tag == 'StringList':
            return {
                'type': 'stringlist',
                'path': node.attrib.get('Path'),
                'csv': node.attrib.get('CSV', '').split(',')
            }
        elif tag == 'Format':
            return {
                'type': 'format',
                'path': node.attrib.get('Path'),
                'regex': node.attrib.get('Regex')
            }
        elif tag == 'AND':
            children = [self._parse_condition_node(c) for c in node]
            children = [c for c in children if c is not None]
            return {'type': 'and', 'children': children}
        elif tag == 'OR':
            children = [self._parse_condition_node(c) for c in node]
            children = [c for c in children if c is not None]
            return {'type': 'or', 'children': children}
        elif tag == 'NOT':
            for child in node:
                return {'type': 'not', 'child': self._parse_condition_node(child)}
        elif tag == 'IMPLY':
            children = [self._parse_condition_node(c) for c in node]
            children = [c for c in children if c is not None]
            if len(children) >= 2:
                return {'type': 'imply', 'antecedent': children[0], 'consequent': children[1]}
        return None

    def _parse_constraint_section(self, cons_elem, section_name, target_dict):
        section = cons_elem.find(section_name)
        if section is None:
            return
        for by_id in section.findall('ByID'):
            elem_id = by_id.attrib.get('ID')
            constraint_list = []
            for constraint in by_id.findall('Constraint'):
                assertion = constraint.find('Assertion')
                constraint_list.append({
                    'id': constraint.attrib.get('ID'),
                    'target': constraint.attrib.get('Target'),
                    'description': constraint.findtext('Description', ''),
                    'assertion': self._parse_condition_node(assertion[0]) if assertion is not None and len(assertion) > 0 else None,
                })
            target_dict[elem_id] = constraint_list


class ValueSets:
    def __init__(self, valuesets_path):
        tree = ET.parse(valuesets_path)
        self.root = tree.getroot()
        self.no_validation = set()
        self.value_sets = {}
        self._parse()

    def _parse(self):
        nv = self.root.find('NoValidation')
        if nv is not None:
            for bi in nv.findall('BindingIdentifier'):
                self.no_validation.add(bi.text.strip() if bi.text else '')
        vsd = self.root.find('ValueSetDefinitions')
        if vsd is not None:
            for vs in vsd.findall('ValueSetDefinition'):
                bid = vs.attrib.get('BindingIdentifier')
                extensibility = vs.attrib.get('Extensibility', 'Open')
                values = set()
                for ve in vs.findall('ValueElement'):
                    values.add(ve.attrib.get('Value', ''))
                self.value_sets[bid] = {
                    'values': values,
                    'extensibility': extensibility,
                    'name': vs.attrib.get('Name', '')
                }

    def should_validate(self, binding_id):
        return binding_id not in self.no_validation

    def get_allowed_values(self, binding_id):
        vs = self.value_sets.get(binding_id)
        if vs:
            return vs['values']
        return None


class ValidationError:
    def __init__(self, category, path, message):
        self.category = category
        self.path = path
        self.message = message

    def to_dict(self):
        return {
            'category': self.category,
            'path': self.path,
            'message': self.message
        }


class Validator:
    def __init__(self, profile, constraints, value_sets):
        self.profile = profile
        self.constraints = constraints
        self.value_sets = value_sets
        self.errors = []
        self.warnings = []

    def validate(self, message):
        self.errors = []
        self.warnings = []
        self._validate_structure(message)
        self._validate_fields(message)
        self._validate_constraints(message)
        return len(self.errors) == 0

    def _add_error(self, category, path, message):
        self.errors.append(ValidationError(category, path, message))

    def _add_warning(self, category, path, message):
        self.warnings.append(ValidationError(category, path, message))

    def _validate_structure(self, message):
        if self.profile.message is None:
            return
        expected = self.profile.message['elements']
        actual_segments = list(message.segments)
        self._match_structure(expected, actual_segments, 0)

    def _match_structure(self, expected_elements, actual_segments, seg_idx):
        for elem in expected_elements:
            if elem['type'] == 'segment':
                seg_idx = self._match_segment_element(elem, actual_segments, seg_idx)
            elif elem['type'] == 'group':
                seg_idx = self._match_group_element(elem, actual_segments, seg_idx)
        return seg_idx

    def _match_segment_element(self, elem, actual_segments, seg_idx):
        ref = elem['ref']
        usage = elem['usage']
        min_count = elem['min']
        max_str = elem['max']
        seg_name = self.profile.get_segment_name(ref)
        if seg_name is None:
            return seg_idx
        count = 0
        max_count = float('inf') if max_str == '*' else int(max_str)
        while seg_idx < len(actual_segments) and count < max_count:
            if actual_segments[seg_idx].name == seg_name:
                count += 1
                seg_idx += 1
            else:
                break
        if usage == 'R' and count < min_count:
            self._add_error('STRUCTURE', seg_name,
                           f"Required segment {seg_name} missing (min={min_count}, found={count})")
        elif usage == 'X' and count > 0:
            self._add_error('STRUCTURE', seg_name,
                           f"Segment {seg_name} is not allowed (Usage=X) but found {count} instance(s)")
        return seg_idx

    def _match_group_element(self, elem, actual_segments, seg_idx):
        usage = elem['usage']
        max_str = elem['max']
        max_count = float('inf') if max_str == '*' else int(max_str)
        group_elements = elem['elements']
        count = 0
        while seg_idx < len(actual_segments) and count < max_count:
            first_elem = group_elements[0] if group_elements else None
            if first_elem is None:
                break
            first_seg_name = self.profile.get_segment_name(first_elem['ref']) if first_elem['type'] == 'segment' else None
            if first_seg_name and actual_segments[seg_idx].name == first_seg_name:
                seg_idx = self._match_structure(group_elements, actual_segments, seg_idx)
                count += 1
            else:
                break
        return seg_idx

    def _validate_fields(self, message):
        for seg in message.segments:
            seg_def = self._find_segment_def(seg.name)
            if seg_def is None:
                continue
            self._validate_segment_fields(seg, seg_def)

    def _find_segment_def(self, seg_name):
        if self.profile.message is None:
            return None
        for elem in self._flatten_elements(self.profile.message['elements']):
            if elem['type'] == 'segment':
                ref = elem['ref']
                seg_def = self.profile.segments.get(ref)
                if seg_def and seg_def['name'] == seg_name:
                    return seg_def
        return None

    def _flatten_elements(self, elements):
        for elem in elements:
            yield elem
            if elem['type'] == 'group':
                yield from self._flatten_elements(elem['elements'])

    def _validate_segment_fields(self, segment, seg_def):
        seg_predicates = self.constraints.segment_predicates.get(seg_def['id'], [])
        usage_overrides = {}
        for pred in seg_predicates:
            target = pred['target']
            condition = pred['condition']
            if condition is not None:
                result = self._evaluate_segment_condition(condition, segment)
                resolved_usage = pred['true_usage'] if result else pred['false_usage']
                field_idx = self._parse_target_field_index(target)
                if field_idx is not None:
                    usage_overrides[field_idx] = resolved_usage

        for i, field_def in enumerate(seg_def['fields']):
            field_num = i + 1
            field = segment.get_field(field_num)
            usage = field_def.get('Usage', 'O')
            if field_num in usage_overrides:
                usage = usage_overrides[field_num]
            field_name = field_def.get('Name', f'field {field_num}')
            if usage == 'R' and field.is_empty():
                self._add_error('USAGE', f"{segment.name}.{field_num}",
                               f"Required field {field_name} is empty")
            elif usage == 'X' and not field.is_empty():
                self._add_error('USAGE', f"{segment.name}.{field_num}",
                               f"Field {field_name} must not be present (Usage=X)")
            if not field.is_empty():
                max_len = field_def.get('MaxLength')
                if max_len:
                    max_len = int(max_len)
                    if max_len > 0 and len(field.raw) > max_len:
                        self._add_error('LENGTH', f"{segment.name}.{field_num}",
                                       f"Field {field_name} exceeds max length {max_len} (actual={len(field.raw)})")
            if not field.is_empty():
                binding = field_def.get('Binding')
                if binding and self.value_sets.should_validate(binding):
                    self._validate_value_set(segment.name, field_num, field, binding)
            if not field.is_empty():
                dt_id = field_def.get('Datatype')
                if dt_id:
                    self._validate_datatype_components(segment.name, field_num, field, dt_id)

    def _validate_value_set(self, seg_name, field_num, field, binding, comp_idx=None):
        allowed = self.value_sets.get_allowed_values(binding)
        if allowed is None:
            return
        for rep_idx in range(field.num_repetitions()):
            if comp_idx is not None:
                val = field.get_component(comp_idx, 0, rep_idx)
            else:
                val = field.get_component(0, 0, rep_idx)
            if val and val not in allowed:
                path = f"{seg_name}.{field_num}"
                if comp_idx is not None:
                    path += f".{comp_idx + 1}"
                self._add_error('VALUESET', path,
                               f"Value '{val}' not in value set {binding} (allowed: {sorted(allowed)})")

    def _validate_datatype_components(self, seg_name, field_num, field, dt_id):
        dt_def = self.profile.datatypes.get(dt_id)
        if dt_def is None or not dt_def['components']:
            return
        for rep_idx in range(field.num_repetitions()):
            for comp_idx, comp_def in enumerate(dt_def['components']):
                comp_val = field.get_component(comp_idx, 0, rep_idx)
                comp_usage = comp_def.get('Usage', 'O')
                if comp_usage == 'R' and not comp_val:
                    self._add_error('USAGE', f"{seg_name}.{field_num}.{comp_idx + 1}",
                                   f"Required component {comp_def.get('Name', '')} is empty")
                elif comp_usage == 'X' and comp_val:
                    self._add_error('USAGE', f"{seg_name}.{field_num}.{comp_idx + 1}",
                                   f"Component {comp_def.get('Name', '')} must not be present (Usage=X)")
                if comp_val:
                    comp_binding = comp_def.get('Binding')
                    if comp_binding and self.value_sets.should_validate(comp_binding):
                        allowed = self.value_sets.get_allowed_values(comp_binding)
                        if allowed is not None and comp_val not in allowed:
                            self._add_error('VALUESET', f"{seg_name}.{field_num}.{comp_idx + 1}",
                                           f"Component value '{comp_val}' not in value set {comp_binding}")
                if comp_val:
                    comp_dt_id = comp_def.get('Datatype')
                    if comp_dt_id:
                        self._validate_datatype_constraint(seg_name, field_num, comp_idx, field, comp_dt_id, rep_idx)

    def _validate_datatype_constraint(self, seg_name, field_num, comp_idx, field, dt_id, rep_idx=0):
        dt_constraints = self.constraints.datatype_constraints.get(dt_id, [])
        for constraint in dt_constraints:
            assertion = constraint.get('assertion')
            if assertion is None:
                continue
            if assertion['type'] == 'plaintext':
                path = assertion.get('path', '')
                expected_text = assertion.get('text', '')
                ignore_case = assertion.get('ignore_case', False)
                actual_val = self._resolve_dt_path(path, field, comp_idx, rep_idx)
                if actual_val is not None:
                    matches = (actual_val.lower() == expected_text.lower()) if ignore_case else (actual_val == expected_text)
                    if not matches:
                        self._add_error('CONSTRAINT', f"{seg_name}.{field_num}.{comp_idx + 1}",
                                       f"{constraint['description']} (found '{actual_val}')")

    def _resolve_dt_path(self, path, field, parent_comp_idx, rep_idx):
        match = re.match(r'(\d+)\[(\d+)\]', path)
        if match:
            sub_comp = int(match.group(1)) - 1
            val = field.get_component(sub_comp, 0, rep_idx)
            return val
        elif path == '.':
            return field.get_component(parent_comp_idx, 0, rep_idx)
        return None

    def _validate_constraints(self, message):
        if self.profile.message is None:
            return
        msg_id = self.profile.message['id']
        msg_constraints = self.constraints.message_constraints.get(msg_id, [])
        for constraint in msg_constraints:
            assertion = constraint.get('assertion')
            if assertion is None:
                continue
            self._evaluate_message_assertion(assertion, constraint, message)
        self._validate_all_datatype_constraints(message)

    def _validate_all_datatype_constraints(self, message):
        for seg in message.segments:
            seg_def = self._find_segment_def(seg.name)
            if seg_def is None:
                continue
            for i, field_def in enumerate(seg_def['fields']):
                field_num = i + 1
                field = seg.get_field(field_num)
                if field.is_empty():
                    continue
                dt_id = field_def.get('Datatype')
                if dt_id and dt_id in self.constraints.datatype_constraints:
                    for constraint in self.constraints.datatype_constraints[dt_id]:
                        assertion = constraint.get('assertion')
                        if assertion is None:
                            continue
                        if assertion['type'] == 'plaintext':
                            path = assertion.get('path', '')
                            expected = assertion.get('text', '')
                            ignore_case = assertion.get('ignore_case', False)
                            actual = self._resolve_dt_path(path, field, 0, 0)
                            if actual is not None:
                                matches = (actual.lower() == expected.lower()) if ignore_case else (actual == expected)
                                if not matches:
                                    self._add_error('CONSTRAINT',
                                                   f"{seg.name}.{field_num}",
                                                   f"{constraint['description']} (found '{actual}')")
                        elif assertion['type'] == 'format':
                            path = assertion.get('path', '')
                            regex = assertion.get('regex', '')
                            actual = self._resolve_dt_path(path, field, 0, 0)
                            if actual is None and path == '.':
                                actual = field.get_first_component_value()
                            if actual and regex:
                                if not re.fullmatch(regex, actual):
                                    self._add_error('CONSTRAINT',
                                                   f"{seg.name}.{field_num}",
                                                   f"{constraint['description']} (value '{actual}' doesn't match format)")

    def _evaluate_message_assertion(self, assertion, constraint, message):
        if assertion['type'] == 'plaintext':
            path = assertion.get('path', '')
            expected = assertion.get('text', '')
            ignore_case = assertion.get('ignore_case', False)
            actual = self._resolve_message_path(path, message)
            if actual is not None:
                matches = (actual.lower() == expected.lower()) if ignore_case else (actual == expected)
                if not matches:
                    readable_path = self._message_path_to_readable(path, message)
                    self._add_error('CONSTRAINT', readable_path,
                                   f"{constraint['description']} (found '{actual}')")

    def _resolve_message_path(self, path, message):
        parts = path.split('.')
        if len(parts) < 2:
            return None
        seg_match = re.match(r'(\d+)\[(\d+)\]', parts[0])
        if not seg_match:
            return None
        seg_pos = int(seg_match.group(1))
        seg_inst = int(seg_match.group(2))
        target_seg = self._get_segment_at_position(seg_pos)
        if target_seg is None:
            return None
        instances = [s for s in message.segments if s.name == target_seg]
        if seg_inst > len(instances) or seg_inst < 1:
            return None
        seg = instances[seg_inst - 1]
        field_match = re.match(r'(\d+)\[(\d+)\]', parts[1])
        if not field_match:
            return None
        field_num = int(field_match.group(1))
        field = seg.get_field(field_num)
        if len(parts) == 2:
            return field.get_first_component_value()
        comp_match = re.match(r'(\d+)\[(\d+)\]', parts[2])
        if not comp_match:
            return None
        comp_num = int(comp_match.group(1))
        return field.get_component(comp_num - 1)

    def _get_segment_at_position(self, position):
        if self.profile.message is None:
            return None
        flat = list(self._flatten_segment_elements(self.profile.message['elements']))
        if 1 <= position <= len(flat):
            ref = flat[position - 1]
            return self.profile.get_segment_name(ref)
        return None

    def _flatten_segment_elements(self, elements):
        for elem in elements:
            if elem['type'] == 'segment':
                yield elem['ref']
            elif elem['type'] == 'group':
                yield from self._flatten_segment_elements(elem['elements'])

    def _message_path_to_readable(self, path, message):
        parts = path.split('.')
        if len(parts) < 2:
            return path
        seg_match = re.match(r'(\d+)\[(\d+)\]', parts[0])
        if not seg_match:
            return path
        seg_pos = int(seg_match.group(1))
        seg_name = self._get_segment_at_position(seg_pos) or f"SEG{seg_pos}"
        field_match = re.match(r'(\d+)\[(\d+)\]', parts[1])
        field_num = field_match.group(1) if field_match else '?'
        result = f"{seg_name}.{field_num}"
        if len(parts) > 2:
            comp_match = re.match(r'(\d+)\[(\d+)\]', parts[2])
            comp_num = comp_match.group(1) if comp_match else '?'
            result += f".{comp_num}"
        return result

    def _evaluate_segment_condition(self, condition, segment):
        if condition is None:
            return False
        ctype = condition['type']
        if ctype == 'presence':
            path = condition.get('path', '')
            return self._check_segment_presence(path, segment)
        elif ctype == 'plaintext':
            path = condition.get('path', '')
            text = condition.get('text', '')
            ignore_case = condition.get('ignore_case', False)
            val = self._resolve_segment_path(path, segment)
            if val is None:
                return False
            return (val.lower() == text.lower()) if ignore_case else (val == text)
        elif ctype == 'stringlist':
            path = condition.get('path', '')
            csv = condition.get('csv', [])
            val = self._resolve_segment_path(path, segment)
            if val is None:
                return False
            return val in csv
        elif ctype == 'and':
            return all(self._evaluate_segment_condition(c, segment) for c in condition.get('children', []))
        elif ctype == 'or':
            return any(self._evaluate_segment_condition(c, segment) for c in condition.get('children', []))
        elif ctype == 'not':
            child = condition.get('child')
            return not self._evaluate_segment_condition(child, segment) if child else False
        return False

    def _check_segment_presence(self, path, segment):
        match = re.match(r'(\d+)\[([*\d]+)\]', path)
        if not match:
            return False
        field_num = int(match.group(1))
        field = segment.get_field(field_num)
        return not field.is_empty()

    def _resolve_segment_path(self, path, segment):
        match = re.match(r'(\d+)\[([*\d]+)\]', path)
        if not match:
            return None
        field_num = int(match.group(1))
        field = segment.get_field(field_num)
        if field.is_empty():
            return None
        return field.get_first_component_value()

    def _parse_target_field_index(self, target):
        match = re.match(r'(\d+)\[(\d+)\]', target)
        if match:
            return int(match.group(1))
        return None

    def get_report(self):
        return {
            'valid': len(self.errors) == 0,
            'errors': [e.to_dict() for e in self.errors],
            'warnings': [w.to_dict() for w in self.warnings],
        }


def main():
    if len(sys.argv) != 3:
        print(json.dumps({
            'valid': False,
            'errors': [{'category': 'PARSE', 'path': '', 'message': 'Usage: igamt_validate.py <profile_dir> <message_file>'}],
            'warnings': []
        }))
        sys.exit(1)

    profile_dir = sys.argv[1]
    message_file = sys.argv[2]

    if not os.path.isdir(profile_dir):
        print(json.dumps({
            'valid': False,
            'errors': [{'category': 'PARSE', 'path': '', 'message': f'Profile directory not found: {profile_dir}'}],
            'warnings': []
        }))
        sys.exit(1)

    if not os.path.isfile(message_file):
        print(json.dumps({
            'valid': False,
            'errors': [{'category': 'PARSE', 'path': '', 'message': f'Message file not found: {message_file}'}],
            'warnings': []
        }))
        sys.exit(1)

    try:
        profile = Profile(os.path.join(profile_dir, 'Profile.xml'))
        constraints = Constraints(os.path.join(profile_dir, 'Constraints.xml'))
        value_sets = ValueSets(os.path.join(profile_dir, 'ValueSets.xml'))
    except Exception as e:
        print(json.dumps({
            'valid': False,
            'errors': [{'category': 'PARSE', 'path': '', 'message': f'Failed to parse profile: {e}'}],
            'warnings': []
        }))
        sys.exit(1)

    try:
        with open(message_file, 'r') as f:
            raw_message = f.read()
        message = HL7Message(raw_message)
    except Exception as e:
        print(json.dumps({
            'valid': False,
            'errors': [{'category': 'PARSE', 'path': '', 'message': f'Failed to parse message: {e}'}],
            'warnings': []
        }))
        sys.exit(1)

    validator = Validator(profile, constraints, value_sets)
    validator.validate(message)

    # Deduplicate errors
    seen = set()
    unique_errors = []
    for err in validator.errors:
        key = (err.category, err.path, err.message)
        if key not in seen:
            seen.add(key)
            unique_errors.append(err)
    validator.errors = unique_errors

    report = validator.get_report()
    print(json.dumps(report, indent=2))
    sys.exit(0 if report['valid'] else 1)


if __name__ == '__main__':
    main()
