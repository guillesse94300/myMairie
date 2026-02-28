@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   URL - Scan des URLs ^(site_url.txt^) - creation des .md
echo ============================================
echo.

cd /d "%~dp0"

:: Creer site_url.txt depuis siteweb.txt si absent
if not exist "%~dp0site_url.txt" (
    if exist "%~dp0siteweb.txt" (
        echo site_url.txt absent - copie depuis siteweb.txt
        copy "%~dp0siteweb.txt" "%~dp0site_url.txt" >nul
        echo.
    ) else (
        echo ERREUR : site_url.txt et siteweb.txt absents.
        echo Creez site_url.txt avec une URL par ligne.
        pause
        exit /b 1
    )
)

:: Installer les dependances si necessaire
python -c "import requests, bs4" 2>nul
if errorlevel 1 (
    echo Installation des dependances ^(requests, beautifulsoup4^)...
    python -m pip install --quiet requests beautifulsoup4
    echo   OK.
    echo.
)

echo Lecture des URLs depuis site_url.txt...
python fetch_sites.py
if errorlevel 1 (
    echo ERREUR lors de la recuperation.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Termine. Fichiers .md dans knowledge_sites/
echo ============================================
echo.
if not "%~1"=="-q" pause
