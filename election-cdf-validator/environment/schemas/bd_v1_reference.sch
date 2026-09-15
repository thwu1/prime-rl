<?xml version="1.0" encoding="UTF-8"?>
<!--
  Intra-format Schematron for Ballot Definition (adapted from NIST SP 1500-20).
  Validates entity references within a single Ballot Definition document.
-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            queryBinding="xslt">

    <xsl:key name="Party" match="//party" use="@id"/>
    <xsl:key name="GpUnit" match="//gpunit" use="@id"/>
    <xsl:key name="Contest" match="//contest" use="@id"/>
    <xsl:key name="Candidate" match="//candidate" use="@id"/>
    <xsl:key name="Selection" match="//contest/selection" use="@id"/>

    <!-- Validate Candidate.PartyId references a defined Party -->
    <sch:pattern id="candidate-party-ref">
        <sch:rule context="//candidate[@party-id]">
            <sch:assert test="key('Party', @party-id)">
                Candidate '<sch:value-of select="@id"/>' references undefined
                PartyId '<sch:value-of select="@party-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>

    <!-- Validate BallotStyle.GpUnitIds references defined GpUnits -->
    <sch:pattern id="ballot-style-gpunit-ref">
        <sch:rule context="//ballot-style">
            <sch:assert test="key('GpUnit', @gpunit-ids)">
                BallotStyle '<sch:value-of select="@id"/>' references undefined
                GpUnit '<sch:value-of select="@gpunit-ids"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>

    <!-- Validate OrderedContest.ContestId references a defined Contest -->
    <sch:pattern id="ordered-contest-ref">
        <sch:rule context="//ordered-contest">
            <sch:assert test="key('Contest', @contest-id)">
                OrderedContest references undefined
                ContestId '<sch:value-of select="@contest-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>

    <!-- Validate CandidateSelection.CandidateIds references defined Candidates -->
    <sch:pattern id="selection-candidate-ref">
        <sch:rule context="//selection/candidate-ref">
            <sch:assert test="key('Candidate', @candidate-id)">
                Selection references undefined
                CandidateId '<sch:value-of select="@candidate-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>
</sch:schema>
