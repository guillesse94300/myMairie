@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Update_Casimir - Pipeline complet
echo   acquire ^> transform ^> ingest
echo ============================================
echo.

cd /d "%~dp0"

:: Dépendances (une seule fois)
if not exist "%~dp0.deps_installed" (
    echo Installation des dependances...
    python -m pip install --quiet -r requirements.txt groq
    echo. > "%~dp0.deps_installed"
    echo   OK.
    echo.
)

:: ── Phase 1 : Acquisition ─────────────────────────────────────────────────────
echo [1/3] Acquisition  site_url.txt → source/
echo.
python acquire.py
if errorlevel 1 (
    echo ERREUR acquisition.
    if not "%~1"=="-q" pause
    exit /b 1
)
echo.

:: ── Phase 2 : Transformation ──────────────────────────────────────────────────
echo [2/3] Transformation  source/ + static/ → input/
echo.
python transform.py
if errorlevel 1 (
    echo ERREUR transformation.
    if not "%~1"=="-q" pause
    exit /b 1
)
echo.

:: ── Phase 3 : Indexation ──────────────────────────────────────────────────────
echo [3/3] Indexation  input/ → vector_db/
echo.
python ingest.py --md-dir input/ --md-only
if errorlevel 1 (
    echo ERREUR indexation.
    if not "%~1"=="-q" pause
    exit /b 1
)
echo   OK.
echo.

:: Stats vote (toujours à jour)
echo Extraction stats vote (stats.json)...
python stats_extract.py 2>nul
if errorlevel 1 echo   ATTENTION : echec stats_extract.py
echo.

:: Commit vector_db dans git
if exist "%~dp0vector_db" (
    git status >nul 2>&1
    if not errorlevel 1 (
        echo Commit vector_db...
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
                        echo.
                    )
                )
            )
        ) else (
            echo   vector_db deja a jour.
        )
        echo.
    )
)

echo ============================================
echo   Pipeline termine.
echo   source/   = artefacts bruts
echo   input/    = .md prets pour Casimir
echo   vector_db = index vectoriel
echo ============================================
echo.
if not "%~1"=="-q" pause
