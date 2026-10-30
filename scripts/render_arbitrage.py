"""planning.json + sondage.json + contraintes.yaml -> arbitrage.html (page autonome, spec section 8)."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve import (  # noqa: E402
    charger_contraintes, empreinte, libelle_creneau, libelle_jour, libelle_semaine,
)

GABARIT = Path(__file__).resolve().parents[1] / "templates" / "arbitrage.html"
MARQUEUR = "__DONNEES__"
# Phrase affichée après « Exporter mes choix ». Le skill renvoie au chat ; l'application V2 passe la sienne.
APRES_EXPORT = "Revenez dans le chat pour la suite."
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def titre_semaine(lundi: str) -> str:
    """Ex. 'Semaine du 2 novembre'."""
    d = date.fromisoformat(lundi)
    return f"Semaine du {d.day} {MOIS[d.month - 1]}"


def construire_donnees(planning: dict, sondage: dict, contraintes: dict,
                       apres_export: str = APRES_EXPORT) -> dict:
    """Objet JSON injecté dans la page. ValueError si les trois fichiers ne vont pas ensemble."""
    if planning.get("empreinte") != empreinte(sondage, contraintes):
        raise ValueError(
            "planning.json ne correspond pas à ce sondage et à ces contraintes "
            "(empreinte différente). Relancez solve.py.")
    creneaux = planning["creneaux"]
    return {
        "planning": {k: planning[k] for k in
                     ("titre", "empreinte", "creneaux", "affectations", "bilan", "alertes")},
        "dispos": {f["nom"]: f["dispos"] for f in sondage["familles"]},
        "quota_mois": {n: c["quota_mois"] for n, c in contraintes["familles"].items()},
        "absences": {n: c["absences"] for n, c in contraintes["familles"].items()},
        "plafond_hebdo": contraintes["plafond_hebdo"],
        "max_parents_par_creneau": contraintes["max_parents_par_creneau"],
        "commentaires": [{"auteur": c["auteur"], "date": c["date"], "texte": c["texte"]}
                         for c in sondage.get("commentaires", [])],
        "libelles": {c["id"]: libelle_creneau(c) for c in creneaux},
        "libelles_jours": {d: libelle_jour(d) for d in sorted({c["date"] for c in creneaux})},
        "libelles_semaines": {s: libelle_semaine(s) for s in sorted({c["semaine"] for c in creneaux})},
        "titres_semaines": {s: titre_semaine(s) for s in sorted({c["semaine"] for c in creneaux})},
        "apres_export": apres_export,
    }


def json_pour_script(donnees: dict) -> str:
    """JSON sûr dans une balise <script type="application/json">."""
    brut = json.dumps(donnees, ensure_ascii=False)
    return brut.replace("</", "<\\/").replace("<!--", "<\\u0021--")


def generer_page(planning: dict, sondage: dict, contraintes: dict,
                 apres_export: str = APRES_EXPORT) -> str:
    """Gabarit + données injectées."""
    gabarit = GABARIT.read_text(encoding="utf-8")
    if gabarit.count(MARQUEUR) != 1:
        raise ValueError(f"Le gabarit doit contenir le marqueur {MARQUEUR} exactement une fois")
    donnees = json_pour_script(construire_donnees(planning, sondage, contraintes, apres_export))
    return gabarit.replace(MARQUEUR, donnees, 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="planning.json -> arbitrage.html")
    ap.add_argument("--planning", required=True)
    ap.add_argument("--sondage", required=True)
    ap.add_argument("--contraintes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        planning = json.loads(Path(args.planning).read_text(encoding="utf-8"))
        sondage = json.loads(Path(args.sondage).read_text(encoding="utf-8"))
        contraintes = charger_contraintes(Path(args.contraintes), sondage)
        page = generer_page(planning, sondage, contraintes)
        Path(args.out).write_text(page, encoding="utf-8")
    except (ValueError, OSError, KeyError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
