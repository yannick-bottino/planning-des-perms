"""planning.json (+ arbitrages.json) -> planning-<mois>.xlsx (spec section 9)."""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

sys.path.insert(0, str(Path(__file__).resolve().parent))
from solve import (  # noqa: E402
    GRAVITE, charger_contraintes, creneaux_avec_familles, empreinte, evaluer,
)

JOURS_MAJ = ["LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI"]
HEURES = [f"{(510 + 30 * k) // 60}h{(510 + 30 * k) % 60:02d}" for k in range(21)]  # 8h30 à 18h30
COL_D, COL_F, COL_HEURES = 4, 6, 11            # colonnes 1-based : D, F, K
LIGNES_MIN = 4                                  # lignes de prénoms du gabarit par demi-journée
LIBELLE_CODE = {"D": "Règle dure violée", "A1": "Créneau sans parent", "A2": "Trop de parents",
                "A3": "Quota du mois", "A4": "Commentaire non traduit",
                "A6": "Dispo « si besoin »", "A7": "Règle non respectée"}


# ---------------------------------------------------------------- arbitrages

def appliquer_arbitrages(planning: dict, arbitrages: dict, sondage: dict, contraintes: dict) -> dict:
    """Applique les changements dans l'ordre et recalcule bilan et alertes. ValueError si incohérent."""
    if arbitrages.get("empreinte") != planning.get("empreinte"):
        raise ValueError(
            "L'empreinte de arbitrages.json ne correspond pas à planning.json : "
            "le planning a été recalculé depuis l'arbitrage. Refaire l'arbitrage sur le planning actuel.")
    dispos = {f["nom"]: f["dispos"] for f in sondage["familles"]}
    ids = {c["id"] for c in sondage["creneaux"]}
    affectations = [dict(a) for a in planning["affectations"]]
    for i, ch in enumerate(arbitrages.get("changements", []), 1):
        action, fam, cr = ch.get("action"), ch.get("famille"), ch.get("creneau")
        ctx = f"Changement {i} ({action} {fam} {cr})"
        existant = [a for a in affectations if a["famille"] == fam and a["creneau"] == cr]
        if action == "ajouter":
            if fam not in dispos:
                raise ValueError(f"{ctx} : famille inconnue du sondage")
            if cr not in ids:
                raise ValueError(f"{ctx} : créneau inconnu du sondage")
            if existant:
                raise ValueError(f"{ctx} : la famille est déjà affectée sur ce créneau")
            affectations.append({"famille": fam, "creneau": cr,
                                 "dispo": dispos[fam].get(cr, "non"), "origine": "arbitrage"})
        elif action == "retirer":
            if not existant:
                raise ValueError(f"{ctx} : la famille n'est pas affectée sur ce créneau")
            affectations.remove(existant[0])
        else:
            raise ValueError(f"{ctx} : action inconnue (attendu 'ajouter' ou 'retirer')")
    affectations.sort(key=lambda a: (a["famille"], a["creneau"]))
    if empreinte(sondage, contraintes) != planning["empreinte"]:
        raise ValueError("Le sondage et les contraintes fournis ne correspondent pas à planning.json "
                         "(empreinte différente).")
    final = dict(planning)
    resultat = evaluer(sondage, contraintes, affectations)
    final.update(creneaux=creneaux_avec_familles(sondage, affectations), affectations=affectations,
                 bilan=resultat["bilan"], alertes=resultat["alertes"])
    return final


def resume_alertes(alertes: list[dict]) -> str:
    """Texte lisible des alertes, regroupées par code."""
    if not alertes:
        return "Aucune alerte."
    lignes = [f"{len(alertes)} alerte(s) restante(s) :"]
    for code in sorted({a["code"] for a in alertes}):
        groupe = [a for a in alertes if a["code"] == code]
        lignes.append(f"- {code} ({LIBELLE_CODE.get(code, code)}, {GRAVITE[code]}) : {len(groupe)}")
        lignes.extend(f"    {a['message']}" for a in groupe)
    return "\n".join(lignes)


# ---------------------------------------------------------------- xlsx

def _jours_par_semaine(creneaux: list[dict]) -> dict:
    """{(lundi, semaine_iso): {date: {'M': [...], 'A': [...]}}}, jours du planning seulement."""
    semaines: dict = {}
    for c in sorted(creneaux, key=lambda c: c["id"]):
        cle = (c["semaine"], c["semaine_iso"])
        jour = semaines.setdefault(cle, {}).setdefault(c["date"], {"M": [], "A": []})
        jour[c["demi"]] = list(c["familles"])
    return semaines


def _ecrire_bloc(ws, ligne: int, jour: date, matin: list, apres: list) -> int:
    """Écrit un bloc jour à partir de `ligne`. Renvoie la première ligne libre après le bloc."""
    gras = Font(bold=True)
    nm, na = max(LIGNES_MIN, len(matin)), max(LIGNES_MIN, len(apres))
    ws.cell(ligne, 1, JOURS_MAJ[jour.weekday()]).font = gras
    ws.cell(ligne, COL_D, "MATIN").font = gras
    for i, h in enumerate(HEURES):
        ws.cell(ligne, COL_HEURES + i, h)
    ws.cell(ligne, COL_HEURES + len(HEURES), "Nb h")
    ws.cell(ligne, COL_HEURES + len(HEURES) + 1, "Nb h réelles")
    cellule = ws.cell(ligne + 1, 1, datetime(jour.year, jour.month, jour.day))
    cellule.number_format = "dd/mm"
    for i, nom in enumerate(matin):
        ws.cell(ligne + 1 + i, COL_D, nom)
    ws.cell(ligne + 4, 1, "Nb prév")
    ws.cell(ligne + 5, 1, "enfants")
    ws.cell(ligne + 1 + nm, COL_D, "A-MIDI").font = gras
    for i, nom in enumerate(apres):
        ws.cell(ligne + 2 + nm + i, COL_D, nom)
    return ligne + 2 + nm + na + 1


def ecrire_xlsx(planning: dict, chemin: Path) -> None:
    """Écrit un onglet SEMAINE <n> par semaine, dans l'ordre chronologique."""
    wb = Workbook()
    wb.remove(wb.active)
    for (_, iso), jours in sorted(_jours_par_semaine(planning["creneaux"]).items()):
        ws = wb.create_sheet(f"SEMAINE {iso}")
        ws["A1"] = f"SEMAINE {iso}"
        ligne = 3
        for iso_jour, demis in sorted(jours.items()):
            ligne = _ecrire_bloc(ws, ligne, date.fromisoformat(iso_jour), demis["M"], demis["A"])
        ws.cell(ligne + 2, COL_F, "Heures/enfants")
        ws.cell(ligne + 3, COL_F, "Heures/contrat")
        ws.column_dimensions["A"].width = 12
        ws.column_dimensions["D"].width = 16
        ws.column_dimensions["F"].width = 16
        for i in range(len(HEURES)):
            ws.column_dimensions[ws.cell(1, COL_HEURES + i).column_letter].width = 6
    wb.save(chemin)


# ---------------------------------------------------------------- CLI

def _lire_json(chemin: str, nom: str) -> dict:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{nom} invalide : {e}") from None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="planning.json (+ arbitrages.json) -> xlsx")
    ap.add_argument("--planning", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arbitrages")
    ap.add_argument("--sondage")
    ap.add_argument("--contraintes")
    ap.add_argument("--planning-final")
    args = ap.parse_args(argv)
    try:
        planning = _lire_json(args.planning, "planning.json")
        if args.arbitrages:
            if not (args.sondage and args.contraintes):
                raise ValueError("--arbitrages exige --sondage et --contraintes")
            sondage = _lire_json(args.sondage, "sondage.json")
            contraintes = charger_contraintes(Path(args.contraintes), sondage)
            planning = appliquer_arbitrages(
                planning, _lire_json(args.arbitrages, "arbitrages.json"), sondage, contraintes)
            if args.planning_final:
                Path(args.planning_final).write_text(
                    json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
        ecrire_xlsx(planning, Path(args.out))
    except (ValueError, OSError, KeyError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    print(f"Fichier écrit : {args.out}")
    print(resume_alertes(planning["alertes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
