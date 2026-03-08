@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Deploiement vers Streamlit Cloud
echo ============================================
echo.

cd /d "%~dp0"

:: Message de commit automatique (date + heure)
for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do set MSG=Mise a jour %%c-%%b-%%a %%d:%%e

:: Mise a jour Streamlit
echo Mise a jour de Streamlit...
python -m pip install -U streamlit
echo.

:: Dossier data
if not exist "%~dp0data" mkdir "%~dp0data"

:: Date de deploiement
python -c "from datetime import datetime; open('deploy_date.txt','w').write(datetime.now().strftime('%%Y-%%m-%%d %%H:%%M'))"
echo Date de deploiement : !MSG!
echo.

:: Verifier depot git
git status >nul 2>&1
if errorlevel 1 (
    echo ERREUR : Ce dossier n'est pas un depot Git.
    pause
    exit /b 1
)

:: Preparation vector_db (flush OneDrive)
if exist "%~dp0vector_db" (
    git update-index --refresh
    python -c "import os; d=os.path.join(os.getcwd(),'vector_db'); [open(os.path.join(d,f),'rb').read(1) for f in ['documents.pkl','embeddings.npy','metadata.pkl','stats.json'] if os.path.exists(os.path.join(d,f))]" 2>nul
    timeout /t 2 /nobreak >nul
)

:: Désindexer les répertoires lourds s'ils etaient suivis auparavant
:: (le .gitignore empeche qu'ils soient re-ajoutes par git add -A)
git rm -r --cached source\images 2>nul
git rm -r --cached source\pdf    2>nul
git rm -r --cached fetcher_raw   2>nul
:: static/ : trackee intentionnellement (PDFs < 10Mo) — ne pas desindexer

:: Staging : code + source\md + input\*.md + vector_db
echo Staging des fichiers...
git add -A

:: Force-add vector_db (non ignore par defaut, mais on s'assure qu'il est inclus)
if exist "%~dp0vector_db" (
    git add -f "%~dp0vector_db\documents.pkl"
    git add -f "%~dp0vector_db\embeddings.npy"
    git add -f "%~dp0vector_db\metadata.pkl"
    git add -f "%~dp0vector_db\stats.json"
)
echo Fichiers stages :
git status --short
echo.

:: Commit (avec ou sans changements : push par defaut)
git diff --cached --quiet
if not errorlevel 1 (
    git commit --allow-empty -m "!MSG!"
) else (
    git commit -m "!MSG!"
)
if errorlevel 1 (
    echo ERREUR lors du commit.
    pause
    exit /b 1
)

:: Pull puis push
echo Synchronisation avec GitHub...
git pull origin main --rebase --autostash
if errorlevel 1 (
    echo ERREUR lors du pull.
    pause
    exit /b 1
)
echo Push vers GitHub...
git push origin main
if errorlevel 1 (
    echo ERREUR lors du push.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   OK. Streamlit Cloud va se redeployer.
echo   https://share.streamlit.io
echo ============================================
if not "%~1"=="-q" pause
