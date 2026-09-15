<?xml version="1.0" encoding="UTF-8"?>
<!-- ADT^A01 Cross-field and cross-segment Schematron rules.
     These encode contextual constraints that IGAMT model-based
     validation cannot express.

-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron">
  <sch:title>ADT^A01 Cross-field Validation Rules</sch:title>

  <sch:pattern id="inpatient-location">
    <sch:rule context="//PV1[PV1.2 = 'I']">
      <sch:assert test="PV1.3 and string-length(normalize-space(PV1.3)) &gt; 0"
                  id="sch-adt-001">Inpatient (PV1.2='I') must have Assigned Patient Location (PV1.3) populated [path:PV1.3]</sch:assert>
    </sch:rule>
  </sch:pattern>

  <sch:pattern id="pid-assigning-authority">
    <sch:rule context="//PID/PID.3[string-length(normalize-space(PID.3.1)) &gt; 0]">
      <sch:assert test="PID.3.4 and string-length(normalize-space(PID.3.4)) &gt; 0"
                  id="sch-adt-002">Patient Identifier with ID must have Assigning Authority (PID.3.4) [path:PID.3.4]</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
