<?xml version="1.0"?>
<xsl:stylesheet
        xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
        xmlns:wix="http://schemas.microsoft.com/wix/2006/wi"
        version="1.0">

    <xsl:output omit-xml-declaration="no" indent="yes"/>
    <xsl:strip-space elements="*"/>

    <xsl:template match="node()|@*">
        <xsl:copy>
            <xsl:apply-templates select="node()|@*"/>
        </xsl:copy>
    </xsl:template>

    <xsl:template
            match="/wix:Wix/wix:Fragment/wix:ComponentGroup/wix:Component[wix:File[@Source='$(var.BinFolderSource)\scalyr-agent-2.exe']]"/>
    <xsl:template
            match="/wix:Wix/wix:Fragment/wix:ComponentGroup/wix:Component[wix:File[@Source='$(var.BinFolderSource)\scalyr-agent-2-config.exe']]"/>
    <xsl:template
            match="/wix:Wix/wix:Fragment/wix:ComponentGroup/wix:Component[wix:File[@Source='$(var.BinFolderSource)\ScalyrAgentService.exe']]"/>
    <xsl:template
            match="/wix:Wix/wix:Fragment/wix:ComponentGroup/wix:Component[wix:File[@Source='$(var.BinFolderSource)\ScalyrShell.cmd']]"/>
</xsl:stylesheet>