"""Construit le zip remis à la famille planning (spec V2, décision V2-5).

Usage : python app/emballer.py --out <chemin du zip>
Contenu : une liste fermée de dossiers et de fichiers du skill (DOSSIERS, FICHIERS), sans tests ni caches.
"""
import argparse
import sys
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
RACINE = "planning-permanences"
# Liste fermée : rien d'autre (données de test, sondage.json, .venv, .env) ne part dans le zip.
DOSSIERS = {"app": {".py", ".html", ".css", ".js"}, "scripts": {".py"},
            "references": {".md"}, "templates": {".html"}}
FICHIERS = ["lancer.bat", "lancer.sh", "LISEZMOI-APPLICATION.txt", "SKILL.md", "requirements.txt"]


def fichiers() -> list[Path]:
    choisis = [SKILL / f for f in FICHIERS if (SKILL / f).is_file()]
    for dossier, extensions in DOSSIERS.items():
        choisis += [p for p in (SKILL / dossier).rglob("*")
                    if p.is_file() and p.suffix in extensions and "__pycache__" not in p.parts]
    return sorted(choisis)


def emballer(sortie: Path) -> int:
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        for p in fichiers():
            nom = f"{RACINE}/{p.relative_to(SKILL).as_posix()}"
            info = zipfile.ZipInfo.from_file(p, nom)
            info.compress_type = zipfile.ZIP_DEFLATED
            if p.suffix == ".sh":
                info.external_attr = 0o755 << 16
            donnees = p.read_bytes()
            if p.suffix == ".sh":
                donnees = donnees.replace(b"\r\n", b"\n")
            elif p.suffix == ".bat":
                donnees = donnees.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            z.writestr(info, donnees)
    return len(fichiers())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Zip de l'application pour la famille planning")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    n = emballer(Path(args.out))
    print(f"{args.out} : {n} fichiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
