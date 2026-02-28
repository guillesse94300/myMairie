@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   ALL : URL + Guide + Update_Casimir + Deploy
echo ============================================
echo.

cd /d "%~dp0"

:: 1. Scan URLs - creation des .md
echo [1/4] URL - Scan des URLs...
call "%~dp0URL.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 1.
    pause
    exit /b 1
)
echo.

:: 2. Copie du Guide utilisateur vers static (pour la popup du site)
echo [2/4] Guide utilisateur - Copie docs\Guide-utilisateurs.md vers static\...
if exist "%~dp0docs\Guide-utilisateurs.md" (
    copy /Y "%~dp0docs\Guide-utilisateurs.md" "%~dp0static\Guide-utilisateurs.md" >nul
    echo   OK.
) else (
    echo   ATTENTION : docs\Guide-utilisateurs.md introuvable.
)
echo.

:: 3. Reindex base Casimir
echo [3/4] Update_Casimir - Reindex...
call "%~dp0Update_Casimir.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 3.
    pause
    exit /b 1
)
echo.

:: 4. Deploy ^(git + Streamlit^)
echo [4/4] Deploy...
call "%~dp0deploy.bat" -q
if errorlevel 1 (
    echo ERREUR a l'etape 4.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   ALL termine avec succes.
echo ============================================
pause
