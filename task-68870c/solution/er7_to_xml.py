#!/usr/bin/env python3
"""
Convert HL7v2 ER7 (pipe-delimited) message to XML representation.

Output XML structure:
  <HL7Message>
    <MSH>
      <MSH.1>|</MSH.1>
      <MSH.2>^~\\&amp;</MSH.2>
      <MSH.3><MSH.3.1>SENDAPP</MSH.3.1></MSH.3>
      ...
    </MSH>
    <PID>
      <PID.3>
        <PID.3.1>MRN001</PID.3.1>
        <PID.3.4>HOSP_A</PID.3.4>
      </PID.3>
      ...
    </PID>
  </HL7Message>

Components always as <SEG.N.M> sub-elements.
Repetitions produce sibling <SEG.N> elements.
Empty fields are omitted.
"""

import sys
import re
import xml.etree.ElementTree as ET


def parse_and_convert(msg_file):
    with open(msg_file, 'r') as f:
        raw = f.read()

    lines = re.split(r'\r\n|\r|\n', raw.strip())
    lines = [l for l in lines if l.strip()]

    if not lines or not lines[0].startswith('MSH'):
        return None

    msh_line = lines[0]
    if len(msh_line) < 9:
        return None

    field_sep = msh_line[3]
    enc_chars = msh_line[4:8]
    comp_sep = enc_chars[0] if len(enc_chars) >= 1 else '^'
    rep_sep = enc_chars[1] if len(enc_chars) >= 2 else '~'

    root = ET.Element('HL7Message')

    for line in lines:
        parts = line.split(field_sep)
        seg_name = parts[0]
        seg_elem = ET.SubElement(root, seg_name)

        if seg_name == 'MSH':
            # MSH.1 = field separator (raw, no components)
            f1 = ET.SubElement(seg_elem, 'MSH.1')
            f1.text = field_sep
            # MSH.2 = encoding characters (raw, no components)
            f2 = ET.SubElement(seg_elem, 'MSH.2')
            f2.text = enc_chars
            # MSH.3+ : parts[2] = MSH.3, parts[3] = MSH.4, etc.
            for i in range(2, len(parts)):
                field_num = i + 1  # parts[2] -> MSH.3
                _add_field(seg_elem, seg_name, field_num, parts[i],
                           comp_sep, rep_sep)
        else:
            # Non-MSH: parts[1] = SEG.1, parts[2] = SEG.2, etc.
            for i in range(1, len(parts)):
                field_num = i
                _add_field(seg_elem, seg_name, field_num, parts[i],
                           comp_sep, rep_sep)

    return root


def _add_field(seg_elem, seg_name, field_num, raw_value, comp_sep, rep_sep):
    """Add field element(s) with component sub-elements."""
    if not raw_value:
        return  # skip empty fields

    repetitions = raw_value.split(rep_sep)
    for rep in repetitions:
        field_elem = ET.SubElement(seg_elem, f'{seg_name}.{field_num}')
        components = rep.split(comp_sep)
        for j, comp_val in enumerate(components):
            comp_num = j + 1
            comp_elem = ET.SubElement(
                field_elem, f'{seg_name}.{field_num}.{comp_num}')
            comp_elem.text = comp_val if comp_val else None


def main():
    if len(sys.argv) != 2:
        sys.exit(1)

    msg_file = sys.argv[1]
    try:
        root = parse_and_convert(msg_file)
    except Exception:
        sys.exit(1)

    if root is None:
        sys.exit(1)

    tree = ET.ElementTree(root)
    sys.stdout.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    tree.write(sys.stdout, encoding='unicode', xml_declaration=False)


if __name__ == '__main__':
    main()
