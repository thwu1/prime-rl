<?xml version="1.0" encoding="UTF-8"?>
<!--
  Cross-CDF Schematron rules for NIST SP 1500-series election data validation.
  Validates referential integrity between Ballot Definition, Cast Vote Records,
  and Election Results Reporting sections of a merged XML document.

  Uses xsl:key to index BD entities and sch:assert with key() lookups to verify
  that CVR and ERR references resolve against the authoritative BD registry.
-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            queryBinding="xslt">

  <!-- Ballot Definition entity keys -->
  <xsl:key name="bd-contest" match="//contest" use="@id"/>
  <xsl:key name="bd-selection" match="//contest/selection" use="@id"/>
  <xsl:key name="bd-gpunit" match="//gpunit" use="@id"/>
  <xsl:key name="bd-candidate" match="//candidate" use="@id"/>
  <xsl:key name="bd-party" match="//party" use="@id"/>

  <!-- CVR -> BD: ContestId references must resolve -->
  <sch:pattern id="cvr-to-bd-contests">
    <sch:rule context="//cast-vote-records/cvr/contest-vote">
      <sch:assert test="key('bd-contest', @contest-id)">
        CVR references undefined ContestId '<sch:value-of select="@contest-id"/>' in record '<sch:value-of select="../@unique-id"/>'
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- CVR -> BD: ContestSelectionId references must resolve -->
  <sch:pattern id="cvr-to-bd-selections">
    <sch:rule context="//cast-vote-records/cvr/contest-vote/selection-vote">
      <sch:assert test="key('bd-selection', @selection-id)">
        CVR references undefined ContestSelectionId '<sch:value-of select="@selection-id"/>' in record '<sch:value-of select="../../@unique-id"/>'
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- CVR -> BD: BallotStyleUnitId (GpUnit) references must resolve -->
  <sch:pattern id="cvr-to-bd-gpunits">
    <sch:rule context="//cast-vote-records/cvr[@gpunit-id]">
      <sch:assert test="key('bd-gpunit', @gpunit-id)">
        CVR references undefined GpUnit '<sch:value-of select="@gpunit-id"/>' in record '<sch:value-of select="@unique-id"/>'
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ERR -> BD: Contest references must resolve -->
  <sch:pattern id="err-to-bd-contests">
    <sch:rule context="//election-results/result-contest">
      <sch:assert test="key('bd-contest', @id)">
        ERR references undefined ContestId '<sch:value-of select="@id"/>'
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ERR -> BD: Party references must resolve -->
  <sch:pattern id="err-to-bd-parties">
    <sch:rule context="//election-results/result-party">
      <sch:assert test="key('bd-party', @id)">
        ERR references undefined PartyId '<sch:value-of select="@id"/>'
      </sch:assert>
    </sch:rule>
  </sch:pattern>

  <!-- ERR -> BD: CandidateId references must resolve -->
  <sch:pattern id="err-to-bd-candidates">
    <sch:rule context="//election-results/result-contest/result-selection/candidate-ref">
      <sch:assert test="key('bd-candidate', @candidate-id)">
        ERR references undefined CandidateId '<sch:value-of select="@candidate-id"/>' in contest '<sch:value-of select="../../@id"/>'
      </sch:assert>
    </sch:rule>
  </sch:pattern>

</sch:schema>
