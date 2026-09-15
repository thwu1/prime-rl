Two healthcare systems are merging their HL7 v2 ORU_R01 message exchange interfaces. Each system enforces a different conformance profile defining structural and field-level constraints on messages. After the merge, the unified interface must accept only messages that conform to both profiles simultaneously.

Each conformance profile is distributed as a multi-file XML package using XInclude directives under the `urn:hl7-org:v2:conformance` namespace. The master profile documents are at `/app/profiles/system_a/profile.xml` and `/app/profiles/system_b/profile.xml`. Each master document references subordinate fragment files (`message_structure.xml` for the message hierarchy and `segment_definitions.xml` for field-level constraints) via `xi:include` elements that must be resolved before the profiles can be processed.

A corpus of HL7 v2 ER7-encoded test messages is at `/app/messages/`.

An XML Schema Definition (XSD) for the reconciled output format is at `/app/schemas/conformance_profile.xsd`.

The environment provides `xmllint`, `xsltproc`, and `xmlstarlet` for XML processing.

Produce two output files:

**`/app/output/reconciled_profile.xml`** -- A conformance profile in the `urn:hl7-org:v2:conformance` namespace that represents the tightest set of constraints a message must satisfy to be valid under both input profiles. Where constraints from the two profiles are irreconcilable (e.g., one profile requires a field while the other forbids it), the reconciled profile must resolve conservatively: it must never accept a message that either input profile would reject. The reconciled profile must validate against the XSD at `/app/schemas/conformance_profile.xsd`.

**`/app/output/assessment.json`** -- A JSON object keyed by message filename, where each value contains three boolean fields `system_a`, `system_b`, and `reconciled` indicating whether the message conforms to each respective profile.

Example entry:
```json
{
  "sample.hl7": {"system_a": true, "system_b": false, "reconciled": false}
}
```