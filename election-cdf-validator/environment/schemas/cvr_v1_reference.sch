<?xml version="1.0" encoding="UTF-8"?>
<!--
  Intra-format Schematron for Cast Vote Records (adapted from NIST SP 1500-103).
  Validates entity references within a single CVR document.
-->
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            queryBinding="xslt">

    <!-- Keys for CVR-internal entity definitions -->
    <xsl:key name="Contest" match="//election/contest" use="@id"/>
    <xsl:key name="ContestSelection" match="//election/contest/selection" use="@id"/>
    <xsl:key name="GpUnit" match="//gpunit" use="@id"/>
    <xsl:key name="ReportingDevice" match="//reporting-device" use="@id"/>
    <xsl:key name="CVRSnapshot" match="//cvr/snapshot" use="@id"/>

    <!-- CVRContest.ContestId must reference a defined Contest -->
    <sch:pattern id="cvr-contest-ref">
        <sch:rule context="//cvr-contest">
            <sch:assert test="key('Contest', @contest-id)">
                CVRContest references undefined
                ContestId '<sch:value-of select="@contest-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>

    <!-- CVRContestSelection.ContestSelectionId must reference a defined Selection -->
    <sch:pattern id="cvr-selection-ref">
        <sch:rule context="//cvr-contest-selection">
            <sch:assert test="key('ContestSelection', @selection-id)">
                CVRContestSelection references undefined
                ContestSelectionId '<sch:value-of select="@selection-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>

    <!-- CVR.CurrentSnapshotId must reference a defined Snapshot -->
    <sch:pattern id="cvr-snapshot-ref">
        <sch:rule context="//cvr[@current-snapshot-id]">
            <sch:assert test="key('CVRSnapshot', @current-snapshot-id)">
                CVR references undefined
                CurrentSnapshotId '<sch:value-of select="@current-snapshot-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>

    <!-- CVR.BallotStyleUnitId must reference a defined GpUnit -->
    <sch:pattern id="cvr-gpunit-ref">
        <sch:rule context="//cvr[@gpunit-id]">
            <sch:assert test="key('GpUnit', @gpunit-id)">
                CVR references undefined
                BallotStyleUnitId '<sch:value-of select="@gpunit-id"/>'
            </sch:assert>
        </sch:rule>
    </sch:pattern>
</sch:schema>
