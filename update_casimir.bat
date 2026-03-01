@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   Update_Casimir - Reindex base de connaissance
echo ============================================
echo.

cd /d "%~dp0"

:: Dossier data pour la base SQLite des recherches (IP, timestamp, requête)
if not exist "%~dp0data" mkdir "%~dp0data"

:: ========== QUESTIONS AU DEBUT (sauf en mode -q) ==========
set INDEX_PDFS=0
if not "%~1"=="-q" (
    :: 1. OCR L'ECHO : test disponibilite puis question
    if not defined INGEST_OCR_JOURNAL set INGEST_OCR_JOURNAL=0
    python -c "import sys; sys.path.insert(0,'.'); from ingest import _OCR_AVAILABLE; sys.exit(0 if _OCR_AVAILABLE else 1)" 2>nul
    if errorlevel 1 (
        echo ATTENTION : OCR non disponible. Les PDFs L'ECHO ^(image^) seront ignores.
        echo   pip install easyocr   ^(recommandé, pas de binaire externe^)
        echo   ou Tesseract : https://github.com/UB-Mannheim/tesseract/wiki
        set INGEST_OCR_JOURNAL=0
    ) else (
        echo OCR disponible pour les journaux L'ECHO.
        set OCR_CHOICE=
        set /p OCR_CHOICE="Activer l'OCR pour les journaux L'ECHO ? ^(lent^) (o/n) [n] : "
        if /i "!OCR_CHOICE!"=="o" set INGEST_OCR_JOURNAL=1
        if /i "!OCR_CHOICE!"=="oui" set INGEST_OCR_JOURNAL=1
        if not "!INGEST_OCR_JOURNAL!"=="1" set INGEST_OCR_JOURNAL=0
        if "!INGEST_OCR_JOURNAL!"=="1" (
            echo   OCR journaux : ACTIVE.
        ) else (
            echo   OCR journaux : desactive.
        )
    )
    echo.

    :: 2. Indexation des PDFs (PV, L'ECHO)
    set CHOICE=
    set /p CHOICE="Indexer aussi les PDFs ^(PV conseil municipal, L'ECHO^) ? Sans cela, Casimir ne consulte QUE les sites web. (o/n) [n] : "
    if defined CHOICE if /i "!CHOICE:~0,1!"=="o" set INDEX_PDFS=1
    echo.
    echo --- Démarrage des traitements ^(plus d'intervention requise^) ---
    echo.
) else (
    :: Mode -q : valeurs par defaut (pas d'OCR, pas de PDFs)
    set INGEST_OCR_JOURNAL=0
)

:: Installer les dependances
echo Installation des dependances...
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet groq
echo   OK.
echo.

:: Telecharger les L'ECHO ^(journal^) si possible
echo Telechargement des publications L'ECHO ^(journal^)...
python journal/download_calameo.py
if errorlevel 1 (
    echo   Ignore - Playwright non installe ou echec. Les PDFs existants seront utilises.
) else (
    echo   OK.
)
echo.

:: 1. Indexation des .md et sites web
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

:: 2. Indexation des PDFs si choisi au debut
if "!INDEX_PDFS!"=="1" (
    echo Indexation des PDFs ^(PV, L'ECHO si OCR actif^)...
    python ingest.py
    if errorlevel 1 (
        echo ERREUR lors de l'indexation des PDFs.
        pause
        exit /b 1
    )
    echo   OK.
) else (
    echo PDFs non indexes. Casimir utilise uniquement les .md / sites web.
)
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
