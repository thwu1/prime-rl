<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:atom="http://www.w3.org/2005/Atom"
    xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
    xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
  <xsl:output method="text" encoding="UTF-8"/>
  <xsl:strip-space elements="*"/>
  <xsl:template match="/">
    <xsl:for-each select="atom:feed/atom:entry">
      <xsl:variable name="p" select="atom:content/m:properties"/>
      <xsl:value-of select="substring($p/d:NEW_DATE,1,10)"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_1MONTH"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_2MONTH"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_3MONTH"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_4MONTH"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_6MONTH"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_1YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_2YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_3YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_5YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_7YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_10YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_20YEAR"/>
      <xsl:text>,</xsl:text><xsl:value-of select="$p/d:BC_30YEAR"/>
      <xsl:text>&#10;</xsl:text>
    </xsl:for-each>
  </xsl:template>
</xsl:stylesheet>
