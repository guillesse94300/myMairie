@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Update_Casimir - Indexation des .md
echo   input/ -^> vector_db/
echo ============================================
echo.

cd /d "%~dp0"

:: Indexation depuis input/*.md (les .md sont deja la)
echo Indexation  input/ -^> vector_db/
echo.
python ingest.py --md-dir input/ --md-only
if errorlevel 1 (
    echo ERREUR indexation.
    if not "%~1"=="-q" pause
    exit /b 1
)
echo   OK.
echo.

:: Stats vote
echo Extraction stats vote (stats.json)...
python stats_extract.py 2>nul
if errorlevel 1 echo   ATTENTION : echec stats_extract.py
echo.

:: Commit + push vector_db
if exist "%~dp0vector_db" (
    git status >nul 2>&1
    if not errorlevel 1 (
        echo Commit vector_db...
        git add -f "%~dp0vector_db\documents.pkl"
        git add -f "%~dp0vector_db\embeddings.npy"
        git add -f "%~dp0vector_db\metadata.pkl"
        git add -f "%~dp0vector_db\stats.json"
        git diff --cached --quiet -- vector_db
        if errorlevel 1 (
            git commit -m "vector_db: reindex depuis input/*.md"
            if not errorlevel 1 (
                echo   Commit effectue.
                if not "%~1"=="-q" (
                    set PUSH_NOW=
                    set /p PUSH_NOW="Pousser sur GitHub maintenant ? (o/n) [o] : "
                    if "!PUSH_NOW!"=="" set PUSH_NOW=o
                    if /i "!PUSH_NOW:~0,1!"=="o" (
                        echo   Pull + Push en cours...
                        git pull origin main --rebase --autostash 2>nul
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
echo   Termine. Pour ajouter de nouvelles
echo   sources : relancer acquire.bat puis
echo   transform.bat avant update_casimir.bat
echo ============================================
echo.
if not "%~1"=="-q" pause
