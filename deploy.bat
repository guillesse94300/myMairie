@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Deploiement vers Streamlit Cloud
echo ============================================
echo.
echo   OneDrive : si vector_db ne se met pas a jour sur GitHub, faites clic droit
echo   sur le dossier vector_db ^> Toujours conserver sur cet appareil
echo.

cd /d "%~dp0"

:: Mettre a jour Streamlit (pour st.dialog, etc.)
echo Mise a jour de Streamlit...
python -m pip install -U streamlit
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
echo Fichiers modifies ^(vector_db doit apparaitre si vous venez de reindexer^) :
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

:: OneDrive : forcer les fichiers vector_db a etre bien sur disque avant que git les lise
if exist "%~dp0vector_db" (
    echo Preparation vector_db pour commit ^(OneDrive peut retarder l'ecriture^)...
    git update-index --refresh
    python -c "import os; d=os.path.join(os.getcwd(),'vector_db'); [open(os.path.join(d,f),'rb').read(1) for f in ['documents.pkl','embeddings.npy','metadata.pkl','stats.json'] if os.path.exists(os.path.join(d,f))]"
    timeout /t 2 /nobreak >nul
    echo.
)

:: Stager tous les changements (dont toute la base vectorielle)
git add -A
:: Forcer l'ajout de toute la base vector_db (-f pour etre sur que les derniers fichiers sont pris)
if exist "%~dp0vector_db" (
    echo Inclusion de toute la base vector_db dans le commit...
    git add -f "%~dp0vector_db\documents.pkl"
    git add -f "%~dp0vector_db\embeddings.npy"
    git add -f "%~dp0vector_db\metadata.pkl"
    git add -f "%~dp0vector_db\stats.json"
    git add -f "%~dp0vector_db"
    echo   Fichiers vector_db stages pour commit :
    git status --short vector_db/
    echo   Si aucun M ci-dessus, le dossier vector_db peut etre en "Fichiers a la demande" OneDrive : clic droit vector_db - Toujours conserver sur cet appareil
    echo.
)
if errorlevel 1 (
    echo ERREUR lors du git add.
    pause
    exit /b 1
)

:: Verifier s'il y a quelque chose a committer
git diff --cached --quiet
if not errorlevel 1 (
    echo Aucun changement a committer. Le depot est a jour.
    set FORCE_PUSH=
    set /p FORCE_PUSH="Forcer le push de tous les fichiers pour redeployer l'app ? (o/n) [n] : "
    if /i not "!FORCE_PUSH!"=="o" if /i not "!FORCE_PUSH!"=="oui" (
        echo   Push annule.
        echo.
        if not "%~1"=="-q" pause
        exit /b 0
    )
    echo   Commit vide pour forcer le redeploiement...
    git commit --allow-empty -m "!MSG! ^(redeploiement force^)"
) else (
    :: Committer les changements
    git commit -m "!MSG!"
)
if errorlevel 1 (
    echo ERREUR lors du commit.
    pause
    exit /b 1
)

:: Confirmer le push de tous les fichiers
set CONFIRM_PUSH=
echo.
set /p CONFIRM_PUSH="Pousser vers GitHub ^(dont base vectorielle vector_db^) ? (o/n) [o] : "
if /i "!CONFIRM_PUSH!"=="n" goto skip_push
if /i "!CONFIRM_PUSH!"=="non" goto skip_push
echo.

:: Synchroniser avec le distant avant de pusher
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
exit /b 0

:skip_push
echo   Push annule.
echo.
if not "%~1"=="-q" pause
exit /b 0
