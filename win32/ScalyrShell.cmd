@ECHO OFF
TITLE Scalyr Agent 2
COLOR 02

SETLOCAL
SET ScalyrRoot=%ProgramFiles(x86)%\Scalyr
SET PROMPT=Scalyr$G$S
GOTO CheckService


:InstallService
:: ----------------------------------------------------------------------
:: Install service on first run
:: ----------------------------------------------------------------------
NET SESSION >nul
IF %ERRORLEVEL% NEQ 0 (
    COLOR 04    
    ECHO Please restart this shell with admin rights
    ECHO --------------------------------------------------
    ECHO From the applications menu; right-click and then
    ECHO select "Run as administator" from the context menu
    ECHO.
    PAUSE
    EXIT 1
) ELSE (
    CD "%ScalyrRoot%"
    MKDIR log lib
    COPY VERSION \Windows\system32\
    IF NOT EXIST agent.json COPY config.tmpl agent.json
    CLS
    ScalyrAgentService.exe --startup=auto install
    PAUSE
)
GOTO StartShell


:: ----------------------------------------------------------------------
:: Verify that ScalyrAgentService has been installed to the registry
:: ----------------------------------------------------------------------
:CheckService
SC QUERY ScalyrAgentService >nul
IF %ERRORLEVEL% EQU 1060 GOTO InstallService
IF %ERRORLEVEL% EQU 0 (GOTO StartShell) ELSE (
    COLOR 04
    ECHO An error occured checking if the ScalyrAgentService is installed
    PAUSE
    EXIT 1
)

:: ----------------------------------------------------------------------
:: 
:: ----------------------------------------------------------------------
:StartShell
SET /P VERSION=<VERSION
CLS
ECHO Scalyr Agent 2 Shell [v%VERSION%]
ECHO ==================================
ECHO.
ECHO Examples:
ECHO    scalyr-agent-2.exe 
ECHO    scalyr-agent-2.exe status
ECHO    scalyr-agent-2.exe status -v
ECHO    scalyr-agent-2.exe start
ECHO    scalyr-agent-2.exe stop
ECHO (type 'exit' to close shell)
CMD /K CD "%ScalyrRoot%"

ENDLOCAL
EXIT 
