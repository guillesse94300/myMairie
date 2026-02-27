@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   Documents Mairie - Installation et demarrage
echo ============================================
echo.

echo [1/3] Installation des dependances...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet Django>=4.2 numpy sentence-transformers pypdf python-docx
if errorlevel 1 (
    echo ERREUR: echec de l'installation des dependances.
    pause
    exit /b 1
)
echo   OK.
echo.

echo [2/3] Base vectorielle...
if not exist "base_vectorielle\embeddings.npz" (
    echo   Premiere utilisation : construction de la base ^(peut prendre 2-3 min^)...
    python build_vector_store.py
    if errorlevel 1 (
        echo   La base n'a pas pu etre creee. Lancez build_vector_store.py manuellement.
    ) else (
        echo   Base creee.
    )
) else (
    echo   Base deja presente.
)
echo.

echo [3/3] Demarrage du serveur web...
echo.
echo   Ouvrez votre navigateur : http://127.0.0.1:8000/
echo   Arreter le serveur : Ctrl+C puis fermer cette fenetre.
echo.
cd web
python manage.py runserver 8000

pause
