#!/usr/bin/env python3
"""
Apply all 7 bug fixes to the protobuf wire codec at /app/.

"""
import re


def fix_file(path, replacements):
    """Read a file, apply a list of (old, new) string replacements, write back."""
    with open(path, "r") as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise RuntimeError(f"Pattern not found in {path}:\n{old!r}")
        content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)


# ==========================================================================
# Fix wire.go — 3 bugs
# ==========================================================================

# Bug 1: DecodeVarint overflow — must reject 10th byte (i==9) >= 2
fix_file("/app/wire.go", [
    # Add overflow check for the 10th byte before accumulating its value.
    (
        """func DecodeVarint(buf []byte) (uint64, int, error) {
\tvar val uint64
\tfor i := 0; i < len(buf) && i < 10; i++ {
\t\tb := buf[i]
\t\tval |= uint64(b&0x7f) << (7 * uint(i))
\t\tif b < 0x80 {
\t\t\treturn val, i + 1, nil
\t\t}
\t}
\tif len(buf) >= 10 {
\t\treturn 0, 0, ErrOverflow
\t}
\treturn 0, 0, ErrTruncated
}""",
        """func DecodeVarint(buf []byte) (uint64, int, error) {
\tvar val uint64
\tfor i := 0; i < len(buf) && i < 10; i++ {
\t\tb := buf[i]
\t\tif i == 9 && b >= 2 {
\t\t\treturn 0, 0, ErrOverflow
\t\t}
\t\tval |= uint64(b&0x7f) << (7 * uint(i))
\t\tif b < 0x80 {
\t\t\treturn val, i + 1, nil
\t\t}
\t}
\tif len(buf) >= 10 {
\t\treturn 0, 0, ErrOverflow
\t}
\treturn 0, 0, ErrTruncated
}"""
    ),

    # Bug 2: DecodeZigZag — XOR with -(n&1), not (n&1)
    (
        "return int64(n>>1) ^ int64(n&1)",
        "return int64(n>>1) ^ (int64(n) << 63 >> 63)",
    ),

    # Bug 3: EncodeFixed64 — BigEndian → LittleEndian
    (
        "binary.BigEndian.PutUint64(buf, v)",
        "binary.LittleEndian.PutUint64(buf, v)",
    ),

    # Bug 3 continued: DecodeFixed64 — BigEndian → LittleEndian
    (
        "return binary.BigEndian.Uint64(buf), 8, nil",
        "return binary.LittleEndian.Uint64(buf), 8, nil",
    ),
])


# ==========================================================================
# Fix codec.go — 3 bugs
# ==========================================================================

# Bug 4: decodePackedValues — must loop through ALL values, not just first
fix_file("/app/codec.go", [
    (
        """func decodePackedValues(field *Field, payload []byte) ([]interface{}, error) {
\tif len(payload) == 0 {
\t\treturn nil, nil
\t}
\tv, _, err := DecodeVarint(payload)
\tif err != nil {
\t\treturn nil, err
\t}
\treturn []interface{}{interpretVarint(field, v)}, nil
}""",
        """func decodePackedValues(field *Field, payload []byte) ([]interface{}, error) {
\tvar values []interface{}
\tpos := 0
\tfor pos < len(payload) {
\t\tswitch field.WireType() {
\t\tcase WireVarint:
\t\t\tv, n, err := DecodeVarint(payload[pos:])
\t\t\tif err != nil {
\t\t\t\treturn nil, err
\t\t\t}
\t\t\tvalues = append(values, interpretVarint(field, v))
\t\t\tpos += n
\t\tcase WireFixed32:
\t\t\tv, n, err := DecodeFixed32(payload[pos:])
\t\t\tif err != nil {
\t\t\t\treturn nil, err
\t\t\t}
\t\t\tvalues = append(values, interpretFixed32(field, v))
\t\t\tpos += n
\t\tcase WireFixed64:
\t\t\tv, n, err := DecodeFixed64(payload[pos:])
\t\t\tif err != nil {
\t\t\t\treturn nil, err
\t\t\t}
\t\t\tvalues = append(values, interpretFixed64(field, v))
\t\t\tpos += n
\t\tdefault:
\t\t\treturn nil, fmt.Errorf("unsupported packed wire type: %d", field.WireType())
\t\t}
\t}
\treturn values, nil
}"""
    ),

    # Bug 5: Group decode — implement instead of returning error
    (
        """\tcase WireStartGroup:
\t\treturn nil, 0, fmt.Errorf("wire type SGROUP not implemented")""",
        """\tcase WireStartGroup:
\t\tif field.Schema == nil {
\t\t\treturn nil, 0, fmt.Errorf("no schema for group field %s", field.Name)
\t\t}
\t\tmsg, consumed, err := decodeGroup(field.Number, field.Schema, data)
\t\tif err != nil {
\t\t\treturn nil, 0, err
\t\t}
\t\treturn msg, consumed, nil"""
    ),

    # Bug 6: skipField and skipGroup — need field number for groups.
    # First fix skipField signature and SGROUP case.
    (
        """func skipField(wireType int, data []byte) (int, error) {
\tswitch wireType {
\tcase WireVarint:
\t\t_, n, err := DecodeVarint(data)
\t\treturn n, err
\tcase WireFixed32:
\t\tif len(data) < 4 {
\t\t\treturn 0, ErrTruncated
\t\t}
\t\treturn 4, nil
\tcase WireFixed64:
\t\tif len(data) < 8 {
\t\t\treturn 0, ErrTruncated
\t\t}
\t\treturn 8, nil
\tcase WireLengthDelim:
\t\t_, n, err := DecodeBytes(data)
\t\treturn n, err
\tcase WireStartGroup:
\t\treturn skipGroup(data)
\tcase WireEndGroup:
\t\treturn 0, ErrBadGroup
\tdefault:
\t\treturn 0, fmt.Errorf("%w: %d", ErrInvalidWire, wireType)
\t}
}

func skipGroup(data []byte) (int, error) {
\treturn 0, fmt.Errorf("cannot skip groups")
}""",
        """func skipField(wireType int, fieldNum uint32, data []byte) (int, error) {
\tswitch wireType {
\tcase WireVarint:
\t\t_, n, err := DecodeVarint(data)
\t\treturn n, err
\tcase WireFixed32:
\t\tif len(data) < 4 {
\t\t\treturn 0, ErrTruncated
\t\t}
\t\treturn 4, nil
\tcase WireFixed64:
\t\tif len(data) < 8 {
\t\t\treturn 0, ErrTruncated
\t\t}
\t\treturn 8, nil
\tcase WireLengthDelim:
\t\t_, n, err := DecodeBytes(data)
\t\treturn n, err
\tcase WireStartGroup:
\t\treturn skipGroup(fieldNum, data)
\tcase WireEndGroup:
\t\treturn 0, ErrBadGroup
\tdefault:
\t\treturn 0, fmt.Errorf("%w: %d", ErrInvalidWire, wireType)
\t}
}

func skipGroup(fieldNum uint32, data []byte) (int, error) {
\tpos := 0
\tfor pos < len(data) {
\t\tfn, wt, n, err := DecodeTag(data[pos:])
\t\tif err != nil {
\t\t\treturn 0, err
\t\t}
\t\tpos += n
\t\tif wt == WireEndGroup {
\t\t\tif fn != fieldNum {
\t\t\t\treturn 0, ErrBadGroup
\t\t\t}
\t\t\treturn pos, nil
\t\t}
\t\tsn, err := skipField(wt, fn, data[pos:])
\t\tif err != nil {
\t\t\treturn 0, err
\t\t}
\t\tpos += sn
\t}
\treturn 0, ErrTruncated
}

func decodeGroup(fieldNum uint32, schema *Schema, data []byte) (map[string]interface{}, int, error) {
\tresult := make(map[string]interface{})
\tpos := 0
\tfor pos < len(data) {
\t\tfn, wt, n, err := DecodeTag(data[pos:])
\t\tif err != nil {
\t\t\treturn nil, 0, err
\t\t}
\t\tpos += n
\t\tif wt == WireEndGroup {
\t\t\tif fn != fieldNum {
\t\t\t\treturn nil, 0, ErrBadGroup
\t\t\t}
\t\t\treturn result, pos, nil
\t\t}
\t\tfield := schema.FieldByNumber(fn)
\t\tif field == nil {
\t\t\tsn, err := skipField(wt, fn, data[pos:])
\t\t\tif err != nil {
\t\t\t\treturn nil, 0, err
\t\t\t}
\t\t\tpos += sn
\t\t\tcontinue
\t\t}
\t\tval, consumed, err := decodeFieldValue(field, wt, data[pos:])
\t\tif err != nil {
\t\t\treturn nil, 0, err
\t\t}
\t\tpos += consumed
\t\tif field.Repeated {
\t\t\texisting, ok := result[field.Name]
\t\t\tif !ok {
\t\t\t\tresult[field.Name] = []interface{}{val}
\t\t\t} else {
\t\t\t\tresult[field.Name] = append(existing.([]interface{}), val)
\t\t\t}
\t\t} else {
\t\t\tresult[field.Name] = val
\t\t}
\t}
\treturn nil, 0, ErrTruncated
}"""
    ),

    # Fix the call site in Decode that uses the old skipField signature
    (
        """\t\t\tskipN, err := skipField(wireType, data[pos:])""",
        """\t\t\tskipN, err := skipField(wireType, fieldNum, data[pos:])""",
    ),

    # Fix group encoding support
    (
        """\t\t} else if field.Type == TypeGroup {
\t\t\treturn nil, fmt.Errorf("group encoding not supported")
\t\t} else {""",
        """\t\t} else if field.Type == TypeGroup {
\t\t\tif field.Schema == nil {
\t\t\t\treturn nil, fmt.Errorf("field %s: no schema for group", field.Name)
\t\t\t}
\t\t\tm, ok := val.(map[string]interface{})
\t\t\tif !ok {
\t\t\t\treturn nil, fmt.Errorf("field %s: expected object for group", field.Name)
\t\t\t}
\t\t\tinnerBytes, err := Encode(field.Schema, m)
\t\t\tif err != nil {
\t\t\t\treturn nil, err
\t\t\t}
\t\t\tresult = append(result, EncodeTag(field.Number, WireStartGroup)...)
\t\t\tresult = append(result, innerBytes...)
\t\t\tresult = append(result, EncodeTag(field.Number, WireEndGroup)...)
\t\t} else {""",
    ),
])


# ==========================================================================
# Fix merge.go — 1 bug
# ==========================================================================

# Bug 7: Submessage merge — must recursively merge, not replace
fix_file("/app/merge.go", [
    (
        """\t\t} else if field.Type == TypeMessage {
\t\t\t// Submessage: should recursively merge but currently replaces.
\t\t\tresult[k] = v""",
        """\t\t} else if field.Type == TypeMessage && field.Schema != nil {
\t\t\texisting, exists := result[k]
\t\t\tif exists {
\t\t\t\texistingMap, eok := existing.(map[string]interface{})
\t\t\t\tnewMap, nok := v.(map[string]interface{})
\t\t\t\tif eok && nok {
\t\t\t\t\tresult[k] = Merge(field.Schema, existingMap, newMap)
\t\t\t\t} else {
\t\t\t\t\tresult[k] = v
\t\t\t\t}
\t\t\t} else {
\t\t\t\tresult[k] = v
\t\t\t}""",
    ),
])

print("All 7 fixes applied successfully.")
