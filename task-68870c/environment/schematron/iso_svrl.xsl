<?xml version="1.0" encoding="UTF-8"?>
<!--
  Minimal ISO Schematron to SVRL compiler (XSLT 1.0).
  Supports: sch:schema, sch:title, sch:pattern(@id), sch:rule(@context),
            sch:assert(@test, @id, text content).

  Usage (two-stage):
    Step 1 - Compile:  xsltproc iso_svrl.xsl rules.sch > compiled.xsl
    Step 2 - Validate: xsltproc compiled.xsl document.xml > svrl_report.xml

  The SVRL report contains svrl:failed-assert elements for each assertion
  that did not hold. Parse with xmlstarlet or similar.

-->
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:sch="http://purl.oclc.org/dsdl/schematron"
    xmlns:axsl="http://www.w3.org/1999/XSL/TransformAlias"
    xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
    exclude-result-prefixes="sch">

  <xsl:namespace-alias stylesheet-prefix="axsl" result-prefix="xsl"/>
  <xsl:output method="xml" indent="yes" encoding="UTF-8"/>

  <xsl:template match="/">
    <xsl:apply-templates select="sch:schema"/>
  </xsl:template>

  <xsl:template match="sch:schema">
    <axsl:stylesheet version="1.0">
      <axsl:output method="xml" indent="yes" encoding="UTF-8"/>
      <axsl:template match="/">
        <svrl:schematron-output>
          <xsl:apply-templates select="sch:pattern"/>
        </svrl:schematron-output>
      </axsl:template>
    </axsl:stylesheet>
  </xsl:template>

  <xsl:template match="sch:pattern">
    <svrl:active-pattern>
      <xsl:if test="@id">
        <xsl:attribute name="id">
          <xsl:value-of select="@id"/>
        </xsl:attribute>
      </xsl:if>
    </svrl:active-pattern>
    <xsl:apply-templates select="sch:rule"/>
  </xsl:template>

  <xsl:template match="sch:rule">
    <axsl:for-each>
      <xsl:attribute name="select">
        <xsl:value-of select="@context"/>
      </xsl:attribute>
      <svrl:fired-rule>
        <xsl:attribute name="context">
          <xsl:value-of select="@context"/>
        </xsl:attribute>
      </svrl:fired-rule>
      <xsl:apply-templates select="sch:assert"/>
    </axsl:for-each>
  </xsl:template>

  <xsl:template match="sch:assert">
    <axsl:if>
      <xsl:attribute name="test">
        <xsl:text>not(</xsl:text>
        <xsl:value-of select="@test"/>
        <xsl:text>)</xsl:text>
      </xsl:attribute>
      <svrl:failed-assert>
        <xsl:attribute name="test">
          <xsl:value-of select="@test"/>
        </xsl:attribute>
        <xsl:if test="@id">
          <xsl:attribute name="id">
            <xsl:value-of select="@id"/>
          </xsl:attribute>
        </xsl:if>
        <svrl:text>
          <xsl:value-of select="normalize-space(.)"/>
        </svrl:text>
      </svrl:failed-assert>
    </axsl:if>
  </xsl:template>

</xsl:stylesheet>
