@echo off
REM Mise a jour de la connaissance de Casimir : sites web + reindexation
echo === Mise a jour Casimir ===
echo.
echo 1. Recuperation des sites web (siteweb.txt)...
python fetch_sites.py
if errorlevel 1 (
    echo Erreur lors du fetch.
    pause
    exit /b 1
)
echo.
echo 2. Reindexation (PDFs + .md)...
python ingest.py
echo.
echo === Termine ===
pause
