<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:ospf="urn:ietf:params:xml:ns:ospf-routing"
  xmlns:meta="urn:ietf:params:xml:ns:query-metadata"
  exclude-result-prefixes="ospf meta">

  <xsl:output method="xml" indent="yes" encoding="UTF-8"/>
  <xsl:strip-space elements="*"/>

  <xsl:template match="/">
    <ospf-queries network="{/ospf:routing-queries/@network}" version="1.0">
      <metadata>
        <description>OSPF routing queries across backbone, stub, NSSA, and regular areas</description>
        <total-queries>
          <xsl:value-of select="count(//ospf:query[@enabled='true'])"/>
        </total-queries>
      </metadata>
      <query-set>
        <xsl:apply-templates select="//ospf:query[@enabled='true']">
          <xsl:sort select="@id"/>
        </xsl:apply-templates>
      </query-set>
    </ospf-queries>
  </xsl:template>

  <xsl:template match="ospf:query">
    <query id="{@id}" router="{@source-router}" destination="{@target-prefix}">
      <xsl:attribute name="note">
        <xsl:value-of select="ancestor::ospf:area-queries/@area-type"/>
        <xsl:text> </xsl:text>
        <xsl:value-of select="@meta:category"/>
      </xsl:attribute>
    </query>
  </xsl:template>

</xsl:stylesheet>
