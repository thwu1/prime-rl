<?xml version="1.0" encoding="UTF-8"?>
<!-- ACK Cross-segment Schematron rules.
     These encode contextual constraints that IGAMT model-based
     validation cannot express.

-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron">
  <sch:title>ACK Cross-segment Validation Rules</sch:title>

  <sch:pattern id="error-ack-requires-err">
    <sch:rule context="/HL7Message[MSA/MSA.1 = 'AE' or MSA/MSA.1 = 'AR']">
      <sch:assert test="ERR" id="sch-ack-001">Error/reject acknowledgment (MSA.1 is AE or AR) must include ERR segment [path:ERR]</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
