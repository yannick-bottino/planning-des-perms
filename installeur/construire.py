"""Construit l'installeur Windows du planning des perms (spec V3, V3-1 et V3-14).

Étapes : (1) dist/python : CPython autonome (uv) + dépendances de app/serveur.py ;
(2) dist/planning-perms : fichiers de app/emballer.py ; (3) contrôles d'import ; (4) ISCC.

Usage : python construire.py [--version X.Y.Z] [--sans-iscc] [--iscc CHEMIN] [--python 3.12]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
# Racine de l'outil : skills/planning-perms ici, racine du dépôt dans le dépôt public.
OUTIL = ICI.parent
BUILD = ICI / "build"
DIST = BUILD / "dist"
VERSION_PYTHON = "3.12"


def dependances() -> list[str]:
    """Lit le bloc PEP 723 de app/serveur.py : source unique des versions."""
    texte = (OUTIL / "app" / "serveur.py").read_text(encoding="utf-8")
    m = re.search(r"^# /// script\s*\n((?:#.*\n)+?)# ///", texte, re.M)
    if not m:
        sys.exit("Bloc PEP 723 introuvable dans app/serveur.py")
    bloc = "\n".join(ligne[1:].strip() for ligne in m.group(1).splitlines())
    m2 = re.search(r"dependencies\s*=\s*\[(.*?)\]", bloc, re.S)
    deps = re.findall(r'"([^"]+)"', m2.group(1)) if m2 else []
    if not deps:
        sys.exit("Aucune dépendance lue dans app/serveur.py")
    return deps


def lancer(cmd: list, **kw) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        sys.exit(f"Échec (code {r.returncode}) : {cmd[0]}")
    return r


def trouver_uv() -> str:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
    if not Path(uv).is_file():
        sys.exit("uv introuvable (https://docs.astral.sh/uv/)")
    return uv


def long(p: Path) -> str:
    """Préfixe long de Windows : les chemins du dépôt dépassent parfois 260 caractères."""
    pre = "\\\\?\\"
    p = str(Path(p).resolve())
    return p if p.startswith(pre) or os.name != "nt" else pre + p


def construire_python(uv: str, version_py: str, deps: list[str]) -> None:
    """Assemble l'interpréteur dans un dossier temporaire court, puis le copie dans dist/."""
    with tempfile.TemporaryDirectory(prefix="pp-") as tmp:
        tmp = Path(tmp)
        lancer([uv, "python", "install", version_py, "--install-dir", tmp / "uv"])
        dossiers = [d for d in (tmp / "uv").iterdir() if d.is_dir() and (d / "python.exe").is_file()]
        if not dossiers:
            sys.exit("Interpréteur uv introuvable après installation")
        court = tmp / "py"
        shutil.copytree(dossiers[0], court)
        if not (court / "pythonw.exe").is_file():
            sys.exit("pythonw.exe absent de l'interpréteur copié")
        for marqueur in court.rglob("EXTERNALLY-MANAGED"):
            marqueur.unlink()
        lancer([uv, "pip", "install", "--python", court / "python.exe", "--no-cache", *deps])
        alleger(court)
        # Caches recompilés après l'allègement : sans eux, le premier lancement chez la famille
        # recompile toute la bibliothèque (plusieurs dizaines de secondes). « unchecked-hash » :
        # valables quelles que soient les dates des fichiers posés par l'installeur.
        subprocess.run([court / "python.exe", "-m", "compileall", "-q", "-j", "0",
                        "--invalidation-mode", "unchecked-hash", court / "Lib"], check=False)
        shutil.copytree(long(court), long(DIST / "python"))


def alleger(python: Path) -> None:
    """Retire caches et tests (sûrs) pour réduire la taille."""
    avant = taille(python)
    for p in list(python.rglob("__pycache__")):
        shutil.rmtree(p, ignore_errors=True)
    lib = python / "Lib"
    for rel in ("test", "idlelib", "turtledemo"):
        shutil.rmtree(lib / rel, ignore_errors=True)
    for nom in ("tests", "test"):
        for p in list((lib / "site-packages").rglob(nom)):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
    print(f"  allègement : {avant / 1e6:.0f} Mo -> {taille(python) / 1e6:.0f} Mo")


def copier_outil() -> int:
    sys.path.insert(0, str(OUTIL / "app"))
    import emballer
    cible = DIST / "planning-perms"
    liste = emballer.fichiers()
    for p in liste:
        dest = cible / p.relative_to(emballer.SKILL)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    return len(liste)


def controler() -> None:
    py = DIST / "python" / "python.exe"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    lancer([py, "-c", "import ortools, yaml, openpyxl; print('imports tiers OK', ortools.__version__)"], env=env)
    code = ("import sys; sys.path.insert(0, 'app'); import moteurs, parcours, reglages, serveur; "
            "from ortools.sat.python import cp_model; m = cp_model.CpModel(); x = m.new_bool_var('x'); "
            "m.add(x == 1); s = cp_model.CpSolver(); assert s.solve(m) == cp_model.OPTIMAL; print('app + CP-SAT OK')")
    lancer([py, "-c", code], cwd=DIST / "planning-perms", env=env)


def taille(dossier: Path) -> int:
    return sum(f.stat().st_size for f in dossier.rglob("*") if f.is_file())


def trouver_iscc(arg: str | None) -> str:
    candidats = [arg, os.environ.get("ISCC"), shutil.which("ISCC"),
                 str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
                 str(Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"),
                 str(Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe")]
    for c in candidats:
        if c and Path(c).is_file():
            return c
    sys.exit("ISCC.exe introuvable (Inno Setup 6) : option --iscc, variable ISCC ou PATH")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", help="défaut : contenu du fichier VERSION")
    ap.add_argument("--sans-iscc", action="store_true", help="s'arrêter après dist/")
    ap.add_argument("--iscc", help="chemin de ISCC.exe")
    ap.add_argument("--python", default=VERSION_PYTHON, help=f"version de CPython (défaut {VERSION_PYTHON})")
    args = ap.parse_args(argv)
    version = (args.version or (ICI / "VERSION").read_text(encoding="utf-8").strip()).lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+([.-][0-9A-Za-z.]+)?", version):
        sys.exit(f"Version invalide : {version!r}")

    debut = time.time()
    deps = dependances()
    print(f"Version {version}, dépendances : {', '.join(deps)}")
    if DIST.exists():
        shutil.rmtree(long(DIST))
    DIST.mkdir(parents=True)
    print("1/4 Python autonome")
    construire_python(trouver_uv(), args.python, deps)
    print("2/4 Fichiers de l'outil")
    print(f"  {copier_outil()} fichiers")
    print("3/4 Contrôles")
    controler()
    print(f"dist : {taille(DIST) / 1e6:.0f} Mo ({DIST})")
    if args.sans_iscc:
        print(f"Terminé en {time.time() - debut:.0f} s (sans ISCC)")
        return 0
    print("4/4 Inno Setup")
    iscc = trouver_iscc(args.iscc)
    # ISCC refuse les chemins de plus de 260 caractères : jonction courte vers build/ si nécessaire.
    racine, jonction = BUILD, None
    if os.name == "nt" and len(str(DIST)) > 100:
        jonction = Path(tempfile.gettempdir()) / f"pp-build-{os.getpid()}"
        lancer(["cmd", "/c", "mklink", "/J", jonction, BUILD], stdout=subprocess.DEVNULL)
        racine = jonction
    try:
        lancer([iscc, f"/DVersion={version}", f"/DDist={racine / 'dist'}", f"/DSortie={racine}",
                "/Q", "planning-perms.iss"], cwd=ICI)
    finally:
        if jonction is not None and jonction.exists():
            os.rmdir(jonction)  # retire la jonction seule, jamais le contenu
    exe = BUILD / "Installer-Planning-des-perms.exe"
    if not exe.is_file():
        sys.exit("Installeur non produit")
    print(f"Installeur : {exe} ({exe.stat().st_size / 1e6:.1f} Mo)")
    print(f"Terminé en {time.time() - debut:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
