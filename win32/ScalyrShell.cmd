@ECHO OFF
TITLE Scalyr Agent 2
COLOR 02

SETLOCAL
SET PROMPT=Scalyr$G$S

ENDLOCAL

:: ------------------------------
:: To simplify short cut creation, we use this script to also execute the standard
:: commands of start, status, stop based on the incoming argument.  If there is none,
:: then we do run this as a shell down below.
:: ------------------------------
if "%~1"=="status" (
  TITLE Scalyr Agent 2 Detailed Status
  ECHO Executing: scalyr-agent-2 status -v
  ECHO.
  scalyr-agent-2 status -v
) else if "%~1"=="start"  (
  TITLE Starting Scalyr Agent 2
  ECHO Executing: scalyr-agent-2 start
  ECHO.
  scalyr-agent-2 start
) else if "%~1"=="stop"  (
  TITLE Stopping Scalyr Agent 2
  ECHO Executing: scalyr-agent-2 stop
  ECHO.
  scalyr-agent-2 stop
) else (
  GOTO StartShell
)

ECHO.
ECHO.
ECHO Command execution finished.  Closing window.
PAUSE
EXIT


:: ----------------------------------------------------------------------
::
:: ----------------------------------------------------------------------
:StartShell
ECHO Scalyr Agent 2 Shell
ECHO ==================================
ECHO.
ECHO Examples:
ECHO    scalyr-agent-2.exe
ECHO    scalyr-agent-2.exe status
ECHO    scalyr-agent-2.exe status -v
ECHO    scalyr-agent-2.exe start
ECHO    scalyr-agent-2.exe stop
ECHO (type 'exit' to close shell)

CMD /K CD "%Scalyr%"

EXIT
