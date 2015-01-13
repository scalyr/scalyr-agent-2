@ECHO OFF

IF {%1}=={} (
    ECHO Usage: %0 [ProductName]
    EXIT /B 1
)

DEL %1.wixobj %1.wixpdb %1.msi build.log
