#!/bin/sh
# Planning des permanences : lance l'application locale (macOS, Linux). Spec V2, décision V2-1.
# Aucun droit administrateur : uv s'installe dans le profil de l'utilisateur.
cd "$(dirname "$0")" || exit 1
if [ ! -f app/serveur.py ]; then
  echo "Le dossier de l'application est incomplet : décompressez d'abord le zip."
  exit 1
fi
UV=$(command -v uv 2>/dev/null)
if [ -z "$UV" ] && [ -n "$UV_INSTALL_DIR" ] && [ -x "$UV_INSTALL_DIR/uv" ]; then UV="$UV_INSTALL_DIR/uv"; fi
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"; fi
if [ -z "$UV" ]; then
  echo "Première utilisation : installation de l'outil uv, sans droits administrateur..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "L'installation de uv a échoué (voir LISEZMOI-APPLICATION.txt)."; exit 1; }
  if [ -n "$UV_INSTALL_DIR" ] && [ -x "$UV_INSTALL_DIR/uv" ]; then UV="$UV_INSTALL_DIR/uv"; else UV="$HOME/.local/bin/uv"; fi
fi
echo "Démarrage de l'application. La première fois, la préparation prend une à deux minutes."
exec "$UV" run --script app/serveur.py
