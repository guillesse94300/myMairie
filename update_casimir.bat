@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Update_Casimir - Reindex base de connaissance
echo ============================================
echo.

cd /d "%~dp0"

:: Installer les dependances
echo Installation des dependances...
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet groq
echo   OK.
echo.

:: Verifier qu'un OCR est disponible pour les PDFs L'ECHO ^(image^)
python -c "import sys; sys.path.insert(0,'.'); from ingest import _OCR_AVAILABLE; sys.exit(0 if _OCR_AVAILABLE else 1)" 2>nul
if errorlevel 1 (
    echo ATTENTION : OCR non disponible. Les PDFs L'ECHO ^(image^) seront ignores.
    echo   pip install easyocr   ^(recommandé, pas de binaire externe^)
    echo   ou Tesseract : https://github.com/UB-Mannheim/tesseract/wiki
    echo.
) else (
    echo OCR OK pour les PDFs L'ECHO ^(EasyOCR ou Tesseract^).
    echo.
)

:: Telecharger les L'ECHO ^(journal^) si possible
echo Telechargement des publications L'ECHO ^(journal^)...
python journal/download_calameo.py
if errorlevel 1 (
    echo   Ignore - Playwright non installe ou echec. Les PDFs existants seront utilises.
) else (
    echo   OK.
)
echo.

:: Indexation des PDFs + .md ^(connaissance Casimir^)
echo Indexation des PDFs ^(PV + L'ECHO^) + sites web ^(.md^)...
python ingest.py
if errorlevel 1 (
    echo ERREUR lors de l'indexation.
    pause
    exit /b 1
)
echo   OK.
echo.

:: Extraction des statistiques de vote si absentes
if not exist "%~dp0vector_db\stats.json" (
    echo Extraction des statistiques de vote...
    python stats_extract.py
    if errorlevel 1 (
        echo ERREUR lors de l'extraction des statistiques.
        pause
        exit /b 1
    )
    echo   OK.
    echo.
)

echo ============================================
echo   Reindex termine.
echo ============================================
echo.
if not "%~1"=="-q" pause
