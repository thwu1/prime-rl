Build a Python command-line tool at `/app/hl7v2_validator.py` that parses HL7 v2 ER7-encoded messages and validates them against an XML conformance profile, producing a structured JSON validation report.

## Input

The tool takes two arguments:

```
python3 /app/hl7v2_validator.py <profile.xml> <message.er7>
```

- `<profile.xml>`: An HL7 v2 conformance profile in XML format (schema defined in `/app/profile_schema.md`).
- `<message.er7>`: A file containing a single HL7 v2 ER7-encoded message (pipe-delimited, `\r\n` or `\n` line endings).

## Conformance Profile Schema

The XML conformance profile at `/app/profiles/` defines message structure, segment definitions, datatype definitions, and field constraints including Usage (R/RE/O/X/W/C/B), Cardinality (Min/Max), and Length (MinLength/MaxLength). The profile supports nested Groups within the message structure. See `/app/profile_schema.md` for the full schema reference.

## Validation Requirements

The validator must detect and report the following categories of structural conformance issues:

1. **Usage violations**: R-usage elements that are missing; X-usage elements that are present; W-usage elements that are present (reported as warnings). Usage checks apply at segment, group, field, and component levels.

2. **Cardinality violations**: Repeating elements (segments within groups, field repetitions) whose occurrence count falls outside the declared Min..Max range.

3. **Length violations**: Primitive field/component values whose character length (after resolving escape sequences like `\F\`, `\S\`, `\R\`, `\E\`, `\T\`) falls outside MinLength..MaxLength.

4. **Invalid lines**: Lines in the message that cannot be parsed as a valid segment (don't start with a 3-character segment identifier followed by the field separator or end-of-line).

5. **Unexpected segments**: Syntactically valid segments whose 3-character ID is not defined anywhere in the profile.

6. **Extra elements**: Fields or components that are populated beyond what the profile defines for that segment/datatype.

7. **Unescaped separators**: Primitive values that contain raw separator characters (component separator `^`, subcomponent separator `&`, repetition separator `~`) without proper escaping.

## Output

Write a JSON report to stdout with the structure:

```json
{
  "valid": false,
  "counts": {
    "usage": 3,
    "cardinality": 1,
    "length": 2,
    "invalid_lines": 0,
    "unexpected_segments": 0,
    "extra": 1,
    "unescaped_separators": 0
  },
  "issues": [
    {
      "category": "usage",
      "severity": "error",
      "path": "PID[1]-1[1]",
      "description": "R-usage Field 'Set ID - PID' (PID-1) is missing"
    }
  ]
}
```

Each issue has: `category` (one of the 7 types), `severity` ("error" or "warning" — W-usage presence is "warning", everything else is "error"), `path` (HL7 location path using the `SEG[i]-f[r].c` notation), and `description`.

The `valid` field is `true` only when there are zero issues of any kind (including warnings).

## Test Profiles and Messages

Sample conformance profiles are in `/app/profiles/`. Sample messages for testing are in `/app/messages/`.