@echo off
REM Recuperation des URLs (siteweb.txt) pour enrichir Casimir
REM Pour courrier-picard.fr et sites proteges : pip install curl_cffi
echo === Recuperation des sites web ===
echo.
echo Installation des dependances (curl_cffi, playwright)...
python -m pip install curl_cffi playwright -q
python -m playwright install chromium 2>nul
echo.
echo Recuperation des URLs (siteweb.txt)...
python fetch_sites.py
echo.
echo === Termine ===
pause
