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

    <!-- Index components for the 4 explicitly-managed files by their Id so we can also suppress their ComponentRef entries -->
    <xsl:key name="explicit-file-components"
        match="wix:Component[
            wix:File[@Source='$(var.BinFolderSource)\scalyr-agent-2.exe'] or
            wix:File[@Source='$(var.BinFolderSource)\scalyr-agent-2-config.cmd'] or
            wix:File[@Source='$(var.BinFolderSource)\ScalyrAgentService.exe'] or
            wix:File[@Source='$(var.BinFolderSource)\ScalyrShell.cmd']
        ]"
        use="@Id"/>

    <!-- Suppress the Component element itself regardless of where heat places it in the document -->
    <xsl:template match="wix:Component[
            wix:File[@Source='$(var.BinFolderSource)\scalyr-agent-2.exe'] or
            wix:File[@Source='$(var.BinFolderSource)\scalyr-agent-2-config.cmd'] or
            wix:File[@Source='$(var.BinFolderSource)\ScalyrAgentService.exe'] or
            wix:File[@Source='$(var.BinFolderSource)\ScalyrShell.cmd']
        ]"/>

    <!-- Suppress any ComponentRef that references one of the suppressed components -->
    <xsl:template match="wix:ComponentRef[key('explicit-file-components', @Id)]"/>

</xsl:stylesheet>
