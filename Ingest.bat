@echo off
setlocal EnableDelayedExpansion

:: ================================================================
::  Ingest.bat -- Installe les dependances (dont Tesseract) et
::                lance python ingest.py
::  Usage: Ingest.bat [--md-only] [--md-dir DIR]
:: ================================================================

set "SCRIPT_DIR=%~dp0"
set "VENV=%SCRIPT_DIR%.venv"
set "TESS64=C:\Program Files\Tesseract-OCR\tesseract.exe"
set "TESS32=C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
set "TESSDATA64=C:\Program Files\Tesseract-OCR\tessdata"
set "TESS_URL=https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
set "FRA_URL=https://github.com/tesseract-ocr/tessdata/raw/main/fra.traineddata"
set "ENG_URL=https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata"

echo.
echo ================================================================
echo   INGEST -- Installation des dependances et indexation
echo ================================================================
echo.

:: -- Environnement virtuel Python --
if exist "%VENV%\Scripts\activate.bat" (
    call "%VENV%\Scripts\activate.bat"
    echo [OK] Environnement virtuel .venv active.
) else (
    echo [INFO] Pas de .venv trouve, utilisation du Python systeme.
)
echo.

:: -- 1/4 - Dependances Python --
echo [1/4] Installation des dependances Python (requirements.txt)...
python -m pip install -q -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERREUR] pip install a echoue. Verifiez votre connexion ou requirements.txt.
    pause
    exit /b 1
)
echo [OK] Dependances Python installees.
echo.

:: -- 2/4 - Playwright chromium --
echo [2/4] Installation du navigateur Playwright (chromium)...
playwright install chromium
if errorlevel 1 python -m playwright install chromium
echo [OK] Playwright chromium pret.
echo.

:: -- 3/4 - Tesseract OCR --
echo [3/4] Verification de Tesseract OCR...

set "TESS_EXE="
if exist "%TESS64%" set "TESS_EXE=%TESS64%"
if exist "%TESS32%" set "TESS_EXE=%TESS32%"
if defined TESS_EXE goto :tess_found

echo [INFO] Tesseract non trouve. Telechargement en cours...
echo        (Necessite d'etre administrateur - clic droit sur le .bat -> Executer en tant qu'admin)
echo        URL : %TESS_URL%
echo.

set "TESS_INSTALLER=%TEMP%\tesseract-installer.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%TESS_URL%' -OutFile '!TESS_INSTALLER!' -UseBasicParsing"
if errorlevel 1 goto :tess_dl_fail

echo [INFO] Installation silencieuse de Tesseract...
"!TESS_INSTALLER!" /S
if errorlevel 1 goto :tess_install_fail

if exist "!TESS_INSTALLER!" del /f /q "!TESS_INSTALLER!"
set "PATH=%PATH%;C:\Program Files\Tesseract-OCR"
set "TESS_EXE=%TESS64%"
echo [OK] Tesseract installe.
goto :check_tessdata

:tess_dl_fail
echo [ERREUR] Telechargement de Tesseract echoue.
echo          Telechargez manuellement : https://github.com/UB-Mannheim/tesseract/wiki
goto :skip_tesseract

:tess_install_fail
echo [ERREUR] Installation echouee (droits admin insuffisants ?).
echo          Relancez le .bat en tant qu'administrateur.
if exist "!TESS_INSTALLER!" del /f /q "!TESS_INSTALLER!"
goto :skip_tesseract

:tess_found
echo [OK] Tesseract deja installe : !TESS_EXE!

:check_tessdata
if not defined TESS_EXE goto :skip_tesseract

if exist "!TESSDATA64!\fra.traineddata" goto :fra_ok
echo [INFO] Telechargement du pack langue francaise (fra.traineddata)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%FRA_URL%' -OutFile '!TESSDATA64!\fra.traineddata' -UseBasicParsing"
if errorlevel 1 goto :fra_fail
echo [OK] Pack langue francaise installe.
goto :fra_ok
:fra_fail
echo [AVERT] Pack francais non telecharge - droits admin requis.
echo         Telechargez fra.traineddata : https://github.com/tesseract-ocr/tessdata
echo         Placez-le dans : !TESSDATA64!\
:fra_ok

if exist "!TESSDATA64!\eng.traineddata" goto :eng_ok
echo [INFO] Telechargement du pack langue anglaise (eng.traineddata)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%ENG_URL%' -OutFile '!TESSDATA64!\eng.traineddata' -UseBasicParsing"
if errorlevel 1 goto :eng_fail
echo [OK] Pack langue anglaise installe.
goto :eng_ok
:eng_fail
echo [AVERT] Pack anglais non telecharge.
:eng_ok

:skip_tesseract
echo.

:: -- 4/4 - Lancement ingest.py --
echo [4/4] Lancement de ingest.py...
echo ----------------------------------------------------------------
echo.
python "%SCRIPT_DIR%ingest.py" %*

echo.
echo ================================================================
echo   Indexation terminee.
echo ================================================================
echo.
pause
endlocal