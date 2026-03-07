@echo off
setlocal

REM Lancer les tests unitaires de Casimir
REM - installe pytest si besoin
REM - exécute les tests pour les questions d'exemple de l'agent

cd /d "%~dp0"
echo [TEST] Dossier courant : %CD%

echo [TEST] Installation / mise à jour de pytest...
python -m pip install --quiet pytest
if errorlevel 1 (
    echo [TEST] ERREUR : impossible d'installer pytest. Verifiez votre installation de Python.
    goto end
)

echo [TEST] Lancement des tests...
python -m pytest tests\test_casimir_agent_examples.py -q

:end
echo.
echo [TEST] Terminé. Appuyez sur une touche pour fermer.
pause >nul

