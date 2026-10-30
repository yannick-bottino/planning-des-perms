@echo off
rem Planning des permanences : lance l'application locale (spec V2, decision V2-1).
rem Aucun droit administrateur : uv s'installe dans le profil de l'utilisateur.
setlocal
chcp 65001 >nul
title Planning des permanences
cd /d "%~dp0"
if not exist "app\serveur.py" (
  echo.
  echo Le dossier de l'application est incomplet.
  echo Si vous avez ouvert le fichier zip, faites d'abord un clic droit sur le zip,
  echo choisissez "Extraire tout", puis lancez lancer.bat depuis le dossier extrait.
  echo.
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
set "UV="
for %%U in (uv.exe) do set "UV=%%~$PATH:U"
if not defined UV if defined UV_INSTALL_DIR if exist "%UV_INSTALL_DIR%\uv.exe" set "UV=%UV_INSTALL_DIR%\uv.exe"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV goto lancer

echo Premiere utilisation : installation de l'outil uv, sans droits administrateur...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if defined UV_INSTALL_DIR if exist "%UV_INSTALL_DIR%\uv.exe" set "UV=%UV_INSTALL_DIR%\uv.exe"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV (
  echo.
  echo L'installation de uv a echoue. Voir LISEZMOI-APPLICATION.txt, partie "En cas de probleme".
  echo.
  pause
  exit /b 1
)

:lancer
echo Cette fenetre fait tourner l'outil : allez dans Chrome, et ne fermez pas cette fenetre.
echo Demarrage de l'application. La premiere fois, la preparation prend une a deux minutes.
"%UV%" run --script "app\serveur.py"
if errorlevel 1 (
  echo.
  echo L'application s'est arretee sur une erreur. Le message ci-dessus aide a comprendre.
  echo.
  pause
)
endlocal
