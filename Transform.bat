@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0"

:: ============================================================
::  Calcul du timestamp pour le nom du fichier de log
:: ============================================================
for /f "tokens=*" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TIMESTAMP=%%i
set "LOG_DIR=%~dp0logs"
set "LOG_FILE=%LOG_DIR%\transform_%TIMESTAMP%.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:MENU
cls
echo ============================================================
echo   TRANSFORM - Phase 2 : source/ + static/ ^-^> input/
echo ============================================================
echo.
echo   1.  Images    (source/images/    ^-^> input/  OCR)
echo   2.  Markdown  (source/md/        ^-^> input/  nettoyage)
echo             +   (static/*.md       ^-^> input/  leger)
echo   3.  PDFs      (source/pdf/       ^-^> input/  extraction/OCR)
echo             +   (static/**/*.pdf   ^-^> input/  extraction/OCR)
echo   4.  Tout      (1 + 2 + 3)
echo.
echo   F.  Mode --force  (retraiter tout, ignorer le cache)
echo   S.  Sans static/  (ignorer les fichiers de static/)
echo.
echo   0.  Quitter
echo.
echo   Log courant : %LOG_FILE%
echo.
set "CHOIX="
set /p CHOIX="  Votre choix : "
echo.

:: Options speciales
set "OPT_FORCE="
set "OPT_NO_STATIC="

if /i "!CHOIX!"=="F" (
    set "OPT_FORCE=--force"
    echo   [Mode --force active]
    timeout /t 1 /nobreak >nul
    goto MENU
)
if /i "!CHOIX!"=="S" (
    set "OPT_NO_STATIC=--no-static"
    echo   [Mode --no-static active]
    timeout /t 1 /nobreak >nul
    goto MENU
)

if "!CHOIX!"=="1" goto IMAGES
if "!CHOIX!"=="2" goto MARKDOWN
if "!CHOIX!"=="3" goto PDFS
if "!CHOIX!"=="4" goto ALL
if "!CHOIX!"=="0" goto FIN

echo   Choix invalide. Recommencez.
timeout /t 1 /nobreak >nul
goto MENU


:: ============================================================
::  1. Images
:: ============================================================
:IMAGES
echo ============================================================
echo   [1/1] Images  (source/images/ -^> input/)
echo ============================================================
echo.
python "%~dp0transform.py" --only images !OPT_FORCE! !OPT_NO_STATIC! --log "!LOG_FILE!"
set "RC=!errorlevel!"
echo.
if !RC! NEQ 0 (
    echo   ATTENTION : des erreurs se sont produites ^(code !RC!^).
) else (
    echo   OK.
)
goto RETOUR


:: ============================================================
::  2. Markdown
:: ============================================================
:MARKDOWN
echo ============================================================
echo   [1/1] Markdown  (source/md/ + static/*.md -^> input/)
echo ============================================================
echo.
python "%~dp0transform.py" --only md !OPT_FORCE! !OPT_NO_STATIC! --log "!LOG_FILE!"
set "RC=!errorlevel!"
echo.
if !RC! NEQ 0 (
    echo   ATTENTION : des erreurs se sont produites ^(code !RC!^).
) else (
    echo   OK.
)
goto RETOUR


:: ============================================================
::  3. PDFs
:: ============================================================
:PDFS
echo ============================================================
echo   [1/1] PDFs  (source/pdf/ + static/**/*.pdf -^> input/)
echo ============================================================
echo.
python "%~dp0transform.py" --only pdf !OPT_FORCE! !OPT_NO_STATIC! --log "!LOG_FILE!"
set "RC=!errorlevel!"
echo.
if !RC! NEQ 0 (
    echo   ATTENTION : des erreurs se sont produites ^(code !RC!^).
) else (
    echo   OK.
)
goto RETOUR


:: ============================================================
::  4. Tout
:: ============================================================
:ALL
echo ============================================================
echo   [1/3] Images
echo ============================================================
echo.
python "%~dp0transform.py" --only images !OPT_FORCE! !OPT_NO_STATIC! --log "!LOG_FILE!"
if !errorlevel! NEQ 0 (
    echo   ATTENTION : erreurs sur les images.
) else (
    echo   OK.
)
echo.

echo ============================================================
echo   [2/3] Markdown
echo ============================================================
echo.
python "%~dp0transform.py" --only md !OPT_FORCE! !OPT_NO_STATIC! --log "!LOG_FILE!"
if !errorlevel! NEQ 0 (
    echo   ATTENTION : erreurs sur les markdowns.
) else (
    echo   OK.
)
echo.

echo ============================================================
echo   [3/3] PDFs
echo ============================================================
echo.
python "%~dp0transform.py" --only pdf !OPT_FORCE! !OPT_NO_STATIC! --log "!LOG_FILE!"
if !errorlevel! NEQ 0 (
    echo   ATTENTION : erreurs sur les PDFs.
) else (
    echo   OK.
)
goto RETOUR


:: ============================================================
::  Retour menu
:: ============================================================
:RETOUR
echo.
echo ============================================================
echo   Termine.
echo   Log enregistre dans :
echo   %LOG_FILE%
echo ============================================================
echo.
set "REP="
set /p REP="  Retourner au menu ? [O/n] "
if /i "!REP!"=="n" goto FIN
goto MENU

:FIN
echo.
echo   Au revoir.
endlocal
