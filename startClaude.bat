@echo off
cd /d "%~dp0"

echo ============================================
echo  Comptes Rendus Conseil Municipal Pierrefonds
echo ============================================
echo.

REM Verification que Python est installe
python --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR : Python n'est pas installe ou pas dans le PATH.
    pause
    exit /b 1
)

REM Installation des dependances si necessaire
if not exist "%~dp0.deps_installed" (
    echo Installation des dependances...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERREUR lors de l'installation des dependances.
        pause
        exit /b 1
    )
    echo. > "%~dp0.deps_installed"
    echo Dependances installees.
    echo.
)

REM Indexation des PDFs si la base n'existe pas encore
if not exist "%~dp0vector_db" (
    echo Base vectorielle non trouvee. Indexation des PDFs en cours...
    echo Cela peut prendre 5 a 10 minutes la premiere fois.
    echo.
    python ingest.py
    if errorlevel 1 (
        echo ERREUR lors de l'indexation.
        pause
        exit /b 1
    )
    echo.
    echo Indexation terminee !
    echo.
)

REM Extraction des statistiques si stats.json absent
if not exist "%~dp0vector_db\stats.json" (
    echo Extraction des statistiques de vote en cours...
    python stats_extract.py
    if errorlevel 1 (
        echo ERREUR lors de l'extraction des statistiques.
        pause
        exit /b 1
    )
    echo.
)

REM Lancement de l'interface Streamlit
echo Lancement de l'interface de recherche...
echo Ouvrez votre navigateur sur : http://localhost:8501
echo.
echo Pour quitter : appuyez sur Ctrl+C dans cette fenetre.
echo.
python -m streamlit run app.py
