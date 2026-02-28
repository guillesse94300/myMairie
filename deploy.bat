@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Deploiement vers Streamlit Cloud
echo ============================================
echo.

cd /d "%~dp0"

:: Mettre a jour Streamlit (pour st.dialog, etc.)
echo Mise a jour de Streamlit...
pip install -U streamlit
echo.

:: Dossier data pour la base SQLite des recherches (cree par l'app si absent)
if not exist "%~dp0data" mkdir "%~dp0data"

:: Mettre a jour la date de deploiement (affichee dans l'app)
python -c "from datetime import datetime; open('deploy_date.txt','w').write(datetime.now().strftime('%%Y-%%m-%%d %%H:%%M'))"
echo Date de deploiement mise a jour dans deploy_date.txt
echo.

:: Copie des .md dans static pour la page Sources et Documents
echo Copie des .md dans static...
python copy_md_to_static.py
if errorlevel 1 (
    echo   ATTENTION : echec copy_md_to_static.py
) else (
    echo   OK.
)
echo.

:: Verifier qu'on est dans un depot git
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

:: Verifier s'il y a quelque chose a committer
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

:: Synchroniser avec le distant avant de pusher
echo.
echo Synchronisation avec GitHub...
git pull origin main --rebase
if errorlevel 1 (
    echo ERREUR lors du pull. Resolvez les conflits manuellement.
    pause
    exit /b 1
)

:: Pusher vers GitHub
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
if not "%~1"=="-q" pause
