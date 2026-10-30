# Installeur Windows du planning des perms

Produit `Installer-Planning-des-perms.exe` (nom fixe, la version est dans les propriétés du fichier) (Inno Setup, sans droits administrateur). Il embarque un Python autonome avec `ortools`, `pyyaml` et `openpyxl`, et le dossier de l'outil (liste fermée de `app/emballer.py`). Spec : `docs/specs/planning-perms-v3-installeur.md`.

## Construire en local

Prérequis : `uv`, Inno Setup 6 (`ISCC.exe`), Python avec Pillow (seulement pour refaire l'icône).

```
python installeur/construire.py              # version lue dans VERSION
python installeur/construire.py --version 0.3.1
python installeur/construire.py --sans-iscc  # s'arrête après build/dist/
```

Résultat : `installeur/build/Installer-Planning-des-perms.exe` (dossier `build/` ignoré par git). Les versions des dépendances viennent du bloc PEP 723 de `app/serveur.py`. La construction dure quelques minutes (compression lzma maximale).

## Tester en local

```
python installeur/tester_installeur.py          # installe dans un dossier temporaire, puis désinstalle
python installeur/tester_installeur.py --reel   # installe à l'emplacement par défaut
```

Le test crée puis supprime les raccourcis du Bureau et du menu Démarrer, lance le serveur sans navigateur, contrôle `/api/etat`, et vérifie la désinstallation. Il refuse de démarrer si un raccourci « Planning des perms » existe déjà.

## Construction automatique (GitHub Actions)

`github/installeur.yml` est prévu pour le dépôt public : le copier dans `.github/workflows/installeur.yml` (l'outil est alors à la racine du dépôt). Il lance les tests, construit l'installeur, l'installe en silencieux pour contrôle, le désinstalle, puis dépose le `.exe` en artefact.

## Publier une version

1. Mettre à jour `VERSION` et committer.
2. Créer et pousser l'étiquette : `git tag v0.3.1 && git push origin v0.3.1`.
3. Le workflow publie le `.exe` dans les Releases, avec la consigne SmartScreen (deux clics) en français.

L'installeur n'est pas signé : Windows affiche un avertissement SmartScreen au premier lancement.

## Icône

`python installeur/icone.py` régénère `icone.ico` (Pillow). Le `.ico` est versionné.
