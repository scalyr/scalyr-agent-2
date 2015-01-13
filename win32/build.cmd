@ECHO OFF

IF NOT DEFINED WIX (
    ECHO The WIX toolset does not appear to be installed.
    ECHO See http://wixtoolset.org
    EXIT /B 1
)


:: ----------------------------------------------------------------------
:: Prepare build environment
:: ----------------------------------------------------------------------
SETLOCAL
SET ProductName=ScalyrService
SET BuildDir=build\install
SET BuildLog=%BuildDir%\build.log
SET PATH=%WIX%\bin;%PATH%
SET /P VERSION=<VERSION
SET /P UPGRADECODE=<win32\UPGRADECODE

:Clean
ECHO [*] Cleaning intermediate and installer output file(s)
IF EXIST build      RMDIR /s /q build && ECHO ... removing 'build' directory
IF EXIST dist       RMDIR /s /q dist && ECHO ... removing 'dist' directory
IF EXIST py2exe.log             DEL py2exe.log && ECHO ... deleting 'py2exe.log'
IF EXIST config\config.tmpl     DEL config\config.tmpl && ECHO ... deleting 'config.tmpl'
IF EXIST certs\ca_certs.crt     DEL certs\ca_certs.crt && ECHO ... deleting 'ca_certs.crt'



:: ----------------------------------------------------------------------
:: Change '\n' to '\r\n' for windows platform text editors
:: ----------------------------------------------------------------------
python win32\fixlines.py config\agent.json > config\config.tmpl



:: ----------------------------------------------------------------------
:: 
:: ----------------------------------------------------------------------
python win32\fixlines.py certs\addtrust_external_ca_root.pem > certs\ca_certs.crt
python win32\fixlines.py certs\scalyr_agent_ca_root.pem >> certs\ca_certs.crt


:: ----------------------------------------------------------------------
:: 
:: ----------------------------------------------------------------------
:Py2Exe
ECHO [*] Compile distributable binary components
python setup.py py2exe >py2exe.log
IF %ERRORLEVEL% GTR 0 (
    ECHO [-] Failed to compile distributable binaries with Py2Exe
    ECHO [-] Use the 'type' or 'more' command to view py2exe.log
    EXIT /B 1
)



:: ----------------------------------------------------------------------
:: Compile and link the MSI installation package
:: ----------------------------------------------------------------------
:Install
IF NOT EXIST %BuildDir% MKDIR %BuildDir%

:BuildInstall
ECHO [*] Compile installation package contents
candle -nologo -out %BuildDir%\%ProductName%.wixobj -dVERSION=%VERSION% -dUPGRADECODE=%UPGRADECODE% win32\%ProductName%.wxs >%BuildLog%
IF %ERRORLEVEL% GTR 0 (
    ECHO [-] Failed to compile package
    TYPE %BuildLog%
    EXIT /B 1
)


:LinkInstall
ECHO [*] Link installation package
light -nologo -out %BuildDir%\%ProductName%_%VERSION%.msi %BuildDir%\%ProductName%.wixobj >%BuildLog%
IF %ERRORLEVEL% GTR 0 (
    ECHO [-] Failed to link installation package
    TYPE %BuildLog%
    EXIT /B 1
)


:: ----------------------------------------------------------------------
:: Verify installer binary was created
:: ----------------------------------------------------------------------
IF EXIST %BuildDir%\%ProductName%_%VERSION%.msi (
    ECHO [*] Successfully created %ProductName%.msi
    START %BuildDir%
)
ENDLOCAL
EXIT /B 0
