@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Update_Casimir - Reindex base de connaissance
echo ============================================
echo.

cd /d "%~dp0"
if not exist "%~dp0data" mkdir "%~dp0data"

:: ========== Questions au debut (sauf mode -q) ==========
set INDEX_PDFS=0
if not "%~1"=="-q" (
    set INGEST_OCR_JOURNAL=0
    python -c "import sys; sys.path.insert(0,'.'); from ingest import _OCR_AVAILABLE; sys.exit(0 if _OCR_AVAILABLE else 1)" 2>nul
    if errorlevel 1 (
        echo OCR non disponible - PDFs image ignores.
    ) else (
        set /p OCR_CHOICE="Activer l'OCR pour L'ECHO ^(lent^) ? (o/n) [n] : "
        if /i "!OCR_CHOICE:~0,1!"=="o" set INGEST_OCR_JOURNAL=1
    )
    set /p CHOICE="Indexer les PDFs ^(PV, L'ECHO^) ? (o/n) [n] : "
    if /i "!CHOICE:~0,1!"=="o" set INDEX_PDFS=1
    echo.
) else (
    set INGEST_OCR_JOURNAL=0
)

:: Dependances : une seule fois (marqueur .deps_installed)
if not exist "%~dp0.deps_installed" (
    echo Installation des dependances...
    python -m pip install --quiet -r requirements.txt groq
    echo. > "%~dp0.deps_installed"
    echo   OK.
    echo.
)

:: Telechargement L'ECHO uniquement si on va indexer les PDFs
if "!INDEX_PDFS!"=="1" (
    echo Telechargement L'ECHO...
    python journal/download_calameo.py 2>nul
    if errorlevel 1 echo   Ignore ^(Playwright optionnel^).
    echo.
)

:: Une seule passe d'indexation : .md seul OU .md + PDFs
set INGEST_OCR_JOURNAL=%INGEST_OCR_JOURNAL%
if "!INDEX_PDFS!"=="1" (
    echo Indexation .md + PDFs...
    python ingest.py
) else (
    echo Indexation .md ^(sites web^)...
    python ingest.py --md-only
)
if errorlevel 1 (
    echo ERREUR indexation.
    if not "%~1"=="-q" pause
    exit /b 1
)
echo   OK.
echo.

echo Copie .md vers static...
python copy_md_to_static.py 2>nul
echo.

:: Toujours regenerer stats.json pour qu'il soit a jour avec les PV (sinon il reste ancien sur GitHub)
echo Extraction stats vote ^(stats.json^)...
python stats_extract.py 2>nul
if errorlevel 1 echo   ATTENTION : echec stats_extract.py
echo.

:: Commit systematique de tout vector_db dans git
if exist "%~dp0vector_db" (
    git status >nul 2>&1
    if not errorlevel 1 (
        echo Commit de tous les fichiers vector_db...
        git add -f "%~dp0vector_db\*"
        git add -f "%~dp0vector_db"
        git diff --cached --quiet -- vector_db
        if errorlevel 1 (
            git commit -m "vector_db: reindex documents.pkl embeddings.npy metadata.pkl stats.json"
            if not errorlevel 1 (
                echo   Commit vector_db effectue.
                if not "%~1"=="-q" (
                    set PUSH_NOW=
                    set /p PUSH_NOW="Pousser vector_db sur GitHub maintenant ? (o/n) [o] : "
                    if "!PUSH_NOW!"=="" set PUSH_NOW=o
                    if /i "!PUSH_NOW:~0,1!"=="o" (
                        echo   Pull + Push en cours...
                        git pull origin main --rebase 2>nul
                        git push origin main
                        if not errorlevel 1 (
                            echo   vector_db a jour sur https://github.com/guillesse94300/myMairie/tree/main/vector_db
                        )
                        echo.
                    )
                )
            )
        ) else (
            echo   vector_db deja a jour dans le dernier commit.
        )
        echo.
    )
)

echo ============================================
echo   Reindex termine.
echo ============================================
echo.
echo   Pour deploiement complet ^(date, static^) : lancez  deploy.bat
echo.
if not "%~1"=="-q" pause
