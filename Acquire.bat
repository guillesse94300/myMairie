@echo off
chcp 65001 >/dev/null
setlocal enabledelayedexpansion

cd /d "%~dp0"

:MENU
cls
echo ============================================
echo   ACQUIRE - Phase 1 : Acquisition des docs
echo ============================================
echo.
echo   1.  Sites web   (site_url.txt  -^> source/)
echo   2.  Oise Mag.   (oise.fr       -^> source/pdf/)
echo   3.  Digipad     (Chateau       -^> source/pdf/)
echo   4.  PDF Search  (DuckDuckGo    -^> source/pdf/)
echo   5.  Tout        (1 + 2 + 3 + 4)
echo.
echo   0.  Quitter
echo.
set "CHOIX="
set /p CHOIX="  Votre choix : "
echo.

if "%CHOIX%"=="1" goto SITES
if "%CHOIX%"=="2" goto OISE
if "%CHOIX%"=="3" goto DIGIPAD
if "%CHOIX%"=="4" goto GOOGLE
if "%CHOIX%"=="5" goto ALL
if "%CHOIX%"=="0" goto FIN

echo   Choix invalide. Recommencez.
timeout /t 1 /nobreak >/dev/null
goto MENU

:: --- 1. Sites web ---
:SITES
echo --- Sites web (site_url.txt -> source/) ---
echo.
python acquire.py
if errorlevel 1 echo   ATTENTION : des erreurs se sont produites.
goto RETOUR

:: --- 2. Oise Magazines ---
:OISE
echo --- Magazines Oise (-> source/pdf/) ---
echo.
python download_oise_magazines.py -o source/pdf
if errorlevel 1 echo   ATTENTION : des erreurs se sont produites.
goto RETOUR

:: --- 3. Digipad ---
:DIGIPAD
echo --- Fiches Digipad Chateau (-> source/pdf/) ---
echo.
python download_digipad.py -o source/pdf
if errorlevel 1 echo   ATTENTION : des erreurs se sont produites.
goto RETOUR

:: --- 4. Google PDF ---
:GOOGLE
echo --- Recherche Google PDF (-> source/pdf/) ---
echo.
python google_pdf_download.py
goto RETOUR

:: --- 5. Tout ---
:ALL
echo ============================================
echo [1/4] Sites web (site_url.txt -> source/)
echo ============================================
echo.
python acquire.py
if errorlevel 1 (
    echo   ATTENTION : erreurs lors de acquire.py.
) else (
    echo   OK.
)
echo.

echo ============================================
echo [2/4] Oise Magazines (-> source/pdf/)
echo ============================================
echo.
python download_oise_magazines.py -o source/pdf
if errorlevel 1 (
    echo   ATTENTION : erreurs lors de download_oise_magazines.py.
) else (
    echo   OK.
)
echo.

echo ============================================
echo [3/4] Digipad Chateau (-> source/pdf/)
echo ============================================
echo.
python download_digipad.py -o source/pdf
if errorlevel 1 (
    echo   ATTENTION : erreurs lors de download_digipad.py.
) else (
    echo   OK.
)
echo.

echo ============================================
echo [4/4] Google PDF
echo ============================================
echo.
set "GTERMS="
set /p GTERMS="  Termes de recherche (laisser vide pour passer) : "
if "!GTERMS!"=="" (
    echo   Recherche Google ignoree.
) else (
    python google_pdf_download.py !GTERMS! -o source/pdf
    if errorlevel 1 echo   ATTENTION : erreurs lors de google_pdf_download.py.
)
echo.
goto RETOUR

:: --- Retour menu ---
:RETOUR
echo.
echo ============================================
echo   Termine.
echo ============================================
echo.
set "REP="
set /p REP="  Retourner au menu ? [O/n] "
if /i "!REP!"=="n" goto FIN
goto MENU

:FIN
echo.
echo   Au revoir.
