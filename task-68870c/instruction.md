Create `/app/validate.sh` — a validator for HL7v2 ER7 (pipe-delimited) messages against IHE Gazelle conformance profiles.

**Invocation:**
```
bash /app/validate.sh <profile_dir> <message_file>
```

`<profile_dir>` contains four files defining a conformance profile:
- `Profile.xml` — message structure, segment/field definitions, datatype references, and value set bindings
- `Constraints.xml` — constraint assertions and conditional usage predicates
- `ValueSets.xml` — enumerated value set definitions and bindings
- `rules.sch` — ISO Schematron rules for cross-field and cross-segment constraints

Two profile sets ship with the environment: `/app/profile/` (ADT^A01) and `/app/profile_ack/` (ACK). Corresponding sample messages are at `/app/messages/` and `/app/messages_ack/`. The validator must work generically with any conformant profile set, not only these two.

An ISO Schematron XSLT stylesheet is at `/app/schematron/iso_svrl.xsl`.

**Output (JSON to stdout):**
```json
{
  "valid": true,
  "errors": [],
  "warnings": []
}
```
Each error entry: `{"category": "<CAT>", "path": "<segment>.<field>[.<component>]", "message": "<description>"}`.

**Error categories:**
- `STRUCTURE` — segment-level violations (missing required segments, forbidden segments present)
- `USAGE` — field/component usage violations (required fields empty, forbidden fields populated, conditional usage from predicate evaluation)
- `CONSTRAINT` — assertion and predicate constraint failures defined in profile specifications
- `VALUESET` — values not in bound value sets (respecting extensibility and NoValidation exclusions)
- `LENGTH` — field values exceeding profile-defined maximum lengths
- `SCHEMATRON` — violations detected by the profile's ISO Schematron rules

**Exit codes:** 0 when valid (no errors), 1 otherwise. Must not crash on malformed input, empty files, or nonexistent paths.
