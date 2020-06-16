# Copyright 2014-2020 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


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
PAUSE > nul
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
