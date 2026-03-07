@echo off
setlocal

rem Dossier du script = racine du repo
set "REPO_DIR=%~dp0"
set "DATA_DIR=%REPO_DIR%data"

rem Créer le dossier data si besoin
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

rem Paramètres d'accès
set "ADMIN_TOKEN=pierrefonds_admin_2026"
set "APP_URL=https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app"

echo Calcul du timestamp...
for /f "usebackq tokens=1-4 delims=/: " %%a in (`powershell -NoLogo -Command "Get-Date -Format 'yyyy MM dd HHmmss'"`) do (
    set "YYYY=%%a"
    set "MM=%%b"
    set "DD=%%c"
    set "HHMMSS=%%d"
)

set "TS=%YYYY%%MM%%DD%-%HHMMSS%"
set "OUT_FILE=%DATA_DIR%\searches-%TS%.txt"

echo Récupération de la base des recherches (via PowerShell)...
powershell -NoLogo -Command ^
  "$url = '%APP_URL%/?admin=%ADMIN_TOKEN%&export_searches=1'; " ^
  "$out = '%OUT_FILE%'; " ^
  "Invoke-WebRequest -Uri $url -OutFile $out"

if errorlevel 1 (
    echo Echec du telechargement.
) else (
    echo Snapshot enregistre dans "%OUT_FILE%".
)

endlocal
pause

