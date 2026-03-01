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

:: 2. Copie Guide utilisateur + doc technique vers static (pour les popups du site)
echo [2/4] Documentation - Copie docs\ vers static\...
if exist "%~dp0docs\Guide-utilisateurs.md" (
    copy /Y "%~dp0docs\Guide-utilisateurs.md" "%~dp0static\Guide-utilisateurs.md" >nul
    echo   Guide-utilisateurs.md OK.
) else (
    echo   ATTENTION : docs\Guide-utilisateurs.md introuvable.
)
if exist "%~dp0docs\Architecture-technique.md" (
    copy /Y "%~dp0docs\Architecture-technique.md" "%~dp0static\Architecture-technique.md" >nul
    echo   Architecture-technique.md OK.
)
if exist "%~dp0docs\Recherche-et-agent-RAG.md" (
    copy /Y "%~dp0docs\Recherche-et-agent-RAG.md" "%~dp0static\Recherche-et-agent-RAG.md" >nul
    echo   Recherche-et-agent-RAG.md OK.
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
