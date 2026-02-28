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

:: OCR des PDFs L'ECHO : desactivé par défaut (très lent). Mettre INGEST_OCR_JOURNAL=1 pour activer.
if not defined INGEST_OCR_JOURNAL set INGEST_OCR_JOURNAL=0
python -c "import sys; sys.path.insert(0,'.'); from ingest import _OCR_AVAILABLE, OCR_JOURNAL; sys.exit(0 if _OCR_AVAILABLE else 1)" 2>nul
if errorlevel 1 (
    echo ATTENTION : OCR non disponible. Les PDFs L'ECHO ^(image^) seront ignores.
    echo   pip install easyocr   ^(recommandé, pas de binaire externe^)
    echo   ou Tesseract : https://github.com/UB-Mannheim/tesseract/wiki
    echo.
) else (
    if "!INGEST_OCR_JOURNAL!"=="1" (
        echo OCR des journaux L'ECHO : ACTIVE. L'indexation peut etre longue.
    ) else (
        echo OCR des journaux L'ECHO : desactive. Les PDFs L'ECHO seront ignores.
        echo   Set INGEST_OCR_JOURNAL=1 pour indexer le contenu des journaux ^(lent^).
    )
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

:: 1. Indexation des .md et sites web en premier
echo Indexation des fichiers .md ^(sites web^)...
set INGEST_OCR_JOURNAL=%INGEST_OCR_JOURNAL%
python ingest.py --md-only
if errorlevel 1 (
    echo ERREUR lors de l'indexation des .md.
    pause
    exit /b 1
)
echo   OK. Base mise a jour avec les sites web.
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

:: 2. Proposer d'indexer aussi les PDFs
echo.
set CHOICE=
set /p CHOICE="Indexer aussi les PDFs ^(PV conseil municipal, L'ECHO^) ? Cela peut prendre du temps. (o/n) [n] : "
if /i "!CHOICE!"=="o" goto do_pdfs
if /i "!CHOICE!"=="oui" goto do_pdfs
echo   PDFs non indexes. Casimir utilise les .md / sites web.
goto index_done

:do_pdfs
echo.
echo Indexation des PDFs ^(PV, L'ECHO si OCR actif^)...
python ingest.py
if errorlevel 1 (
    echo ERREUR lors de l'indexation des PDFs.
    pause
    exit /b 1
)
echo   OK.

:index_done
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
