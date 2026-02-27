@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Deploiement vers Streamlit Cloud
echo ============================================
echo.

cd /d "%~dp0"

:: Vérifier qu'on est dans un dépôt git
git status >nul 2>&1
if errorlevel 1 (
    echo ERREUR : Ce dossier n'est pas un depot Git.
    pause
    exit /b 1
)

:: Afficher les fichiers modifiés
echo Fichiers modifies :
git status --short
echo.

:: Demander un message de commit
set /p MSG="Message de commit (Entree = mise a jour automatique) : "
if "!MSG!"=="" (
    for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do (
        set MSG=Mise a jour %%c-%%b-%%a %%d:%%e
    )
)

echo.
echo Message : !MSG!
echo.

:: Stager tous les changements
git add -A
if errorlevel 1 (
    echo ERREUR lors du git add.
    pause
    exit /b 1
)

:: Vérifier s'il y a quelque chose à committer
git diff --cached --quiet
if not errorlevel 1 (
    echo Aucun changement a committer. Le depot est a jour.
    echo.
    pause
    exit /b 0
)

:: Committer
git commit -m "!MSG!"
if errorlevel 1 (
    echo ERREUR lors du commit.
    pause
    exit /b 1
)

:: Pusher vers GitHub
echo.
echo Push vers GitHub (origin main)...
git push origin main
if errorlevel 1 (
    echo ERREUR lors du push. Verifiez votre connexion et vos droits GitHub.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   OK ! Streamlit Cloud va se redeployer
echo   automatiquement dans quelques instants.
echo   https://share.streamlit.io
echo ============================================
echo.
pause
