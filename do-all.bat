@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   DO-ALL : fetch-urls + reindex + deploy
echo ============================================
echo.

cd /d "%~dp0"

:: 1. Recuperer les URLs (site_url.txt)
echo [1/3] Recuperation des URLs...
call "%~dp0fetch-urls.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 1.
    pause
    exit /b 1
)
echo.

:: 2. Reindex (connaissance Casimir)
echo [2/3] Reindex...
call "%~dp0reindex.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 2.
    pause
    exit /b 1
)
echo.

:: 3. Deploy (git push)
echo [3/3] Deploiement...
call "%~dp0deploy.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 3.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   DO-ALL termine avec succes.
echo ============================================
pause
