"""Jeu de données fictif et aides pour les tests Playwright de la page d'arbitrage."""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from render_arbitrage import construire_donnees, generer_page  # noqa: E402
from solve import construire_planning, lire_contraintes  # noqa: E402

LUNDI = date(2026, 11, 2)
NOMS = ["ALMA", "BRUNO", "CLEO", "DAVID", "EMMA", "FELIX", "GINA", "HUGO"]
# Mercredi fermé (aucun créneau), trois semaines : 3 x 4 jours x 2 = 24 créneaux.
JOURS_OUVERTS = (0, 1, 3, 4)
CONTRAINTES_BRUTES = {"familles": {"ALMA": {"absences": ["2026-11-09"]}},
                      "commentaires_non_traduits": ["ALMA : à confirmer"]}


def faire_sondage() -> dict:
    creneaux = []
    for s in range(3):
        lundi = LUNDI + timedelta(weeks=s)
        for j in JOURS_OUVERTS:
            d = lundi + timedelta(days=j)
            for demi in ("M", "A"):
                creneaux.append({"id": f"{d.isoformat()}_{demi}", "date": d.isoformat(), "demi": demi,
                                 "semaine": lundi.isoformat(), "semaine_iso": d.isocalendar().week})
    ids = [c["id"] for c in creneaux]
    dispos = {n: {i: "oui" for i in ids} for n in NOMS}
    dispos["CLEO"]["2026-11-02_M"] = "non"
    dispos["BRUNO"]["2026-11-03_A"] = "si_besoin"
    return {"poll_id": "test", "titre": "Planning fictif", "creneaux": creneaux,
            "familles": [{"nom": n, "nom_brut": n, "dispos": d} for n, d in dispos.items()],
            "commentaires": [{"auteur": "ALMA", "date": "2026-10-15T16:20",
                              "texte": "Absente la semaine du 9/11"}]}


class Jeu:
    """Sondage, contraintes, planning calculé et fichiers écrits dans un dossier."""

    def __init__(self, dossier: Path):
        self.dossier = dossier
        self.sondage = faire_sondage()
        self.contraintes = lire_contraintes(CONTRAINTES_BRUTES, self.sondage)
        self.planning = construire_planning(self.sondage, self.contraintes, temps_max=10)
        self.donnees = construire_donnees(self.planning, self.sondage, self.contraintes)
        self.chemin_sondage = dossier / "sondage.json"
        self.chemin_planning = dossier / "planning.json"
        self.chemin_contraintes = dossier / "contraintes.yaml"
        self.chemin_page = dossier / "arbitrage.html"
        self.chemin_sondage.write_text(json.dumps(self.sondage, ensure_ascii=False), encoding="utf-8")
        self.chemin_planning.write_text(json.dumps(self.planning, ensure_ascii=False), encoding="utf-8")
        self.chemin_contraintes.write_text(yaml.safe_dump(CONTRAINTES_BRUTES, allow_unicode=True),
                                           encoding="utf-8")
        self.chemin_page.write_text(
            generer_page(self.planning, self.sondage, self.contraintes), encoding="utf-8")
        self.url = self.chemin_page.as_uri()

    # ---- lectures sur le planning calculé
    def parents(self, creneau: str) -> list[str]:
        return sorted(a["famille"] for a in self.planning["affectations"] if a["creneau"] == creneau)

    def libelle(self, creneau: str) -> str:
        return self.donnees["libelles"][creneau]

    def creneaux_vides(self) -> list[str]:
        return [c["id"] for c in self.sondage["creneaux"] if not self.parents(c["id"])]

    def creneau_a_un_parent(self) -> str:
        for c in self.sondage["creneaux"]:
            if len(self.parents(c["id"])) == 1:
                return c["id"]
        raise AssertionError("aucun créneau à un seul parent dans le jeu fictif")

    def total(self, famille: str) -> int:
        return sum(1 for a in self.planning["affectations"] if a["famille"] == famille)

    def semaine_de(self, creneau: str) -> str:
        return next(c["semaine"] for c in self.sondage["creneaux"] if c["id"] == creneau)

    def par_semaine(self, famille: str, semaine: str) -> int:
        sem = {c["id"]: c["semaine"] for c in self.sondage["creneaux"]}
        return sum(1 for a in self.planning["affectations"]
                   if a["famille"] == famille and sem[a["creneau"]] == semaine)

    def famille_disponible_hors_creneau(self, creneau: str) -> str:
        """Une famille 'oui' sur ce créneau et pas déjà dessus."""
        deja = set(self.parents(creneau))
        for f in self.sondage["familles"]:
            if f["nom"] not in deja and f["dispos"].get(creneau) == "oui":
                return f["nom"]
        raise AssertionError("aucune famille disponible")


# ---- aides Playwright

def rx(texte: str, debut: str = ""):
    """Regex littérale. Playwright sérialise mal un '/' non échappé dans un motif."""
    return re.compile(debut + re.escape(texte).replace("/", r"\/"))


def case(page, jeu: Jeu, creneau: str):
    """Bouton de la case, repéré par son nom accessible (libellé du créneau)."""
    return page.get_by_role("button", name=rx(jeu.libelle(creneau) + " : ", "^"))


def toutes_les_cases(page):
    return page.get_by_role(
        "button", name=re.compile(r"^(lundi|mardi|mercredi|jeudi|vendredi) \d+\/\d+ (matin|après-midi) : "))


def detail(page):
    return page.get_by_role("region", name="Case sélectionnée")


def alertes(page):
    return page.get_by_role("region", name="Alertes")


def entete(page):
    return page.get_by_role("banner")


def bouton_annuler(page):
    return entete(page).get_by_role("button", name="Annuler le dernier changement")


def ouvrir(page, jeu: Jeu):
    page.goto(jeu.url)
    page.get_by_role("heading", level=1).wait_for()
