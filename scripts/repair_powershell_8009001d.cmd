@echo off
setlocal EnableExtensions

echo ============================================================
echo PowerShell 8009001d repair helper
echo Run this file as Administrator from normal CMD or Windows Terminal.
echo ============================================================
echo.

echo [1/7] Basic environment check
echo USERPROFILE=%USERPROFILE%
echo HOMEDRIVE=%HOMEDRIVE%
echo HOMEPATH=%HOMEPATH%
echo APPDATA=%APPDATA%
echo LOCALAPPDATA=%LOCALAPPDATA%
echo PATH=%PATH%
echo.

echo [2/7] Testing Windows PowerShell without profile
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$PSVersionTable.PSVersion; 'PowerShell basic test OK'"
if %ERRORLEVEL% EQU 0 goto pwsh_ok

echo.
echo PowerShell still fails. Continuing with Windows image repair.
echo.

echo [3/7] Running DISM RestoreHealth
DISM.exe /Online /Cleanup-Image /RestoreHealth

echo.
echo [4/7] Running SFC scan
sfc /scannow

echo.
echo [5/7] Clearing PowerShell command analysis cache
if exist "%LOCALAPPDATA%\Microsoft\Windows\PowerShell\CommandAnalysis" (
  del /q "%LOCALAPPDATA%\Microsoft\Windows\PowerShell\CommandAnalysis\*" 2>nul
)

echo.
echo [6/7] Temporarily disabling user PowerShell profiles
if exist "%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1" (
  ren "%USERPROFILE%\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1" "Microsoft.PowerShell_profile.ps1.disabled"
)
if exist "%USERPROFILE%\Documents\PowerShell\Microsoft.PowerShell_profile.ps1" (
  ren "%USERPROFILE%\Documents\PowerShell\Microsoft.PowerShell_profile.ps1" "Microsoft.PowerShell_profile.ps1.disabled"
)

echo.
echo [7/7] Retesting Windows PowerShell
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$PSVersionTable.PSVersion; 'PowerShell repair test OK'"
if %ERRORLEVEL% EQU 0 goto pwsh_ok

echo.
echo ============================================================
echo PowerShell is still failing.
echo Next manual steps:
echo 1. Restart Windows.
echo 2. Run Windows Update.
echo 3. Try installing PowerShell 7 from Microsoft Store or winget.
echo 4. If only Codex fails but normal PowerShell works, restart Codex and check its shell/environment settings.
echo ============================================================
pause
exit /b 1

:pwsh_ok
echo.
echo ============================================================
echo PowerShell basic startup is OK now.
echo Restart Codex/Desktop app, then retry the command tool.
echo ============================================================
pause
exit /b 0
