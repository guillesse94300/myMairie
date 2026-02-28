@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   ALL : URL + Update_Casimir + Deploy
echo ============================================
echo.

cd /d "%~dp0"

:: 1. Scan URLs - creation des .md
echo [1/3] URL - Scan des URLs...
call "%~dp0URL.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 1.
    pause
    exit /b 1
)
echo.

:: 2. Reindex base Casimir
echo [2/3] Update_Casimir - Reindex...
call "%~dp0Update_Casimir.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 2.
    pause
    exit /b 1
)
echo.

:: 3. Deploy ^(git + Streamlit^)
echo [3/3] Deploy...
call "%~dp0deploy.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 3.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   ALL termine avec succes.
echo ============================================
pause
