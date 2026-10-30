"""Faux sondages Framadate (CSV + page HTML + contraintes.yaml) pour les cas limites.

Prénoms fictifs uniquement. Même structure que fixtures/poll.csv et poll.html.
Usage : python generateur_sondage.py [dossier]  (défaut : fixtures/cas_limites)
"""
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

DEMIS = {"M": "Matin", "A": "Apres-midi"}
VALEURS = {"oui": "Yes", "non": "No", "si_besoin": "If need be", "vide": ""}

# 22 prénoms fictifs, sans lien avec les familles réelles.
PRENOMS = [
    "Alma", "Basile", "Capucine", "Daphné", "Elio", "Faustine", "Gaspard", "Ilian",
    "Jade", "Kenzo", "Lison", "Mahé", "Octave", "Paloma", "Quitterie", "Sacha",
    "Timéo", "Ulysse", "Victoire", "Wassim", "Yaël", "Zélie",
]


@dataclass
class Cas:
    """Un faux sondage : créneaux, lignes de vote, commentaires et contraintes."""
    nom: str
    titre: str
    creneaux: list[tuple[date, str]]
    lignes: list[tuple[str, dict]] = field(default_factory=list)   # (nom brut, {créneau: dispo})
    commentaires: list[tuple[str, datetime, str]] = field(default_factory=list)
    contraintes: dict = field(default_factory=dict)


def creneaux_du_mois(lundis: list[date], fermes: tuple[date, ...] = ()) -> list[tuple[date, str]]:
    """Lundi à vendredi, matin et après-midi, sans les jours fermés (fériés, ponts)."""
    return [
        (lundi + timedelta(days=j), demi)
        for lundi in lundis for j in range(5) if lundi + timedelta(days=j) not in fermes
        for demi in ("M", "A")
    ]


def dispos_aleatoires(rng: random.Random, creneaux, p_oui=0.55, p_si_besoin=0.0) -> dict:
    """Une réponse par créneau : oui, si_besoin, sinon non ou vide (au hasard)."""
    dispos = {}
    for cr in creneaux:
        t = rng.random()
        if t < p_oui:
            dispos[cr] = "oui"
        elif t < p_oui + p_si_besoin:
            dispos[cr] = "si_besoin"
        else:
            dispos[cr] = rng.choice(("non", "vide"))
    return dispos


def ecrire_csv(cas: Cas) -> str:
    """Export CSV Framadate : deux lignes d'en-tête, puis une ligne par vote."""
    lignes = [
        "," + ",".join(d.isoformat() for d, _ in cas.creneaux),
        "," + ",".join(DEMIS[demi] for _, demi in cas.creneaux),
    ]
    for nom, dispos in cas.lignes:
        lignes.append(nom + "," + ",".join(VALEURS[dispos.get(cr, "vide")] for cr in cas.creneaux))
    return "\n".join(lignes) + "\n\n"


_ARTICLE = """                            <article id="comment-{id}" class="panel panel--rounded flow flow--small">
                    <header class="cols cols--always cols--gap-small text--secondary">
                        <span class="col--extend">
                            {auteur}
                        </span>

                        <a class="anchor--dotted anchor--currentcolor text--small" href="#comment-{id}">
                            <time datetime="{iso}" data-controller="relative-time">
                                {txt}
                            </time>
                        </a>
                    </header>

                    <div class="flow flow--small">
                        {paras}
                    </div>
                </article>
"""


def ecrire_html(cas: Cas) -> str:
    """Page Framadate réduite au titre et aux commentaires (gabarit de fixtures/poll.html)."""
    articles = []
    for i, (auteur, quand, texte) in enumerate(cas.commentaires):
        paras = "\n".join(
            "<p>" + para.replace("\n", "<br />\n") + "</p>" for para in texte.split("\n\n"))
        articles.append(_ARTICLE.format(
            id=200001 + i, auteur=auteur, iso=quand.strftime("%Y-%m-%dT%H:%M:%S+01:00"),
            txt=quand.strftime("%d %b %Y, %H:%M"), paras=paras))
    return f"""<!DOCTYPE html>
<html lang="en-GB">
    <head>
        <meta charset="utf-8">
        <title>{cas.titre} – Framadate</title>
    </head>
    <body>
        <main>
        <div class="wrapper wrapper--small wrapper--center flow flow--large">
            <h2 class="text--primary">Comments</h2>

{"".join(articles)}
        </div>
        </main>
    </body>
</html>"""


def ecrire_yaml(cas: Cas) -> str:
    return yaml.safe_dump(cas.contraintes, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------- les 5 cas

FEV_2027 = [date(2027, 2, 1) + timedelta(weeks=s) for s in range(4)]


def cas_ferie_pont() -> Cas:
    """Jeudi 11/11/2027 férié, vendredi 12 fermé (pont) : 6 créneaux cette semaine-là."""
    lundis = [date(2027, 11, 8) + timedelta(weeks=s) for s in range(4)]
    cas = Cas("ferie_pont", "Planning Novembre", creneaux_du_mois(
        lundis, fermes=(date(2027, 11, 11), date(2027, 11, 12))))
    rng = random.Random(1)
    cas.lignes = [(p, dispos_aleatoires(rng, cas.creneaux)) for p in PRENOMS[:17]]
    cas.commentaires = [("Alma", datetime(2027, 10, 20, 9, 5),
                         "Bonjour, le pont du 12 est bien fermé ?")]
    cas.contraintes = {"cible_hebdo": 1, "plafond_hebdo": 2, "max_parents_par_creneau": 2,
                       "commentaires_non_traduits": ["ALMA : question sur la fermeture du 12/11"]}
    return cas


VACANCES = date(2027, 2, 15)


def cas_vacances() -> Cas:
    """La moitié des 16 familles part la semaine du 15/02 (vacances d'hiver)."""
    cas = Cas("vacances", "Planning Février", creneaux_du_mois(FEV_2027))
    rng = random.Random(2)
    familles = PRENOMS[:16]
    absentes = familles[::2]
    for p in familles:
        dispos = dispos_aleatoires(rng, cas.creneaux)
        for cr in cas.creneaux:
            if cr[0] - timedelta(days=cr[0].weekday()) == VACANCES:
                dispos[cr] = "non" if p in absentes else ("oui" if rng.random() < 0.8 else "non")
        cas.lignes.append((p, dispos))
    cas.commentaires = [
        (p, datetime(2027, 1, 18, 8 + i, 30), "Nous serons en vacances la semaine du 15 février.")
        for i, p in enumerate(absentes)
    ] + [(familles[1], datetime(2027, 1, 19, 12, 0),
          "Nous restons pendant les vacances, nous pouvons faire 2 perms cette semaine-là.")]
    cas.contraintes = {"familles": {
        p: {"absences": [VACANCES.isoformat()], "source": "commentaire : vacances semaine du 15/02"}
        for p in absentes}}
    return cas


VENDREDI_VIDE = (date(2027, 2, 12), "A")
VENDREDI_SI_BESOIN = (date(2027, 2, 19), "A")


def cas_creneau_sans_oui() -> Cas:
    """Personne ne dit oui le vendredi 12/02 après-midi ; le 19/02, un seul « si besoin »."""
    cas = Cas("creneau_sans_oui", "Planning Février", creneaux_du_mois(FEV_2027))
    rng = random.Random(3)
    for i, p in enumerate(PRENOMS[:17]):
        dispos = dispos_aleatoires(rng, cas.creneaux)
        dispos[VENDREDI_VIDE] = rng.choice(("non", "vide"))
        dispos[VENDREDI_SI_BESOIN] = "si_besoin" if i == 0 else "non"
        cas.lignes.append((p, dispos))
    return cas


def cas_mauvaises_reponses() -> Cas:
    """Trop peu de dispos, que des « si besoin », doublon Noé / noe, commentaire sans vote."""
    cas = Cas("mauvaises_reponses", "Planning Février", creneaux_du_mois(FEV_2027))
    rng = random.Random(4)
    cas.lignes = [(p, dispos_aleatoires(rng, cas.creneaux)) for p in PRENOMS[:14]]
    # Capucine (index 2) ne coche que 2 créneaux sur le mois.
    cas.lignes[2] = ("Capucine", {cas.creneaux[0]: "oui", cas.creneaux[13]: "oui"})
    # Gaspard (index 6) ne répond que « si besoin ».
    cas.lignes[6] = ("Gaspard", {cr: "si_besoin" for cr in cas.creneaux})
    # Deux parents de la même famille votent chacun : semaines 1-2, puis semaines 3-4.
    moitie = len(cas.creneaux) // 2
    cas.lignes.append(("Noé", {cr: "oui" for cr in cas.creneaux[:moitie:3]}))
    cas.lignes.append(("noe", {cr: "oui" for cr in cas.creneaux[moitie::3]}))
    cas.commentaires = [
        ("Hortense", datetime(2027, 1, 20, 21, 47),
         "Bonjour,\nnous n'avons pas encore nos plannings, on vous dit vite."),
        ("Noé", datetime(2027, 1, 21, 7, 15), "J'ai voté deux fois par erreur, désolé !"),
    ]
    cas.contraintes = {"commentaires_non_traduits": [
        "HORTENSE (pas de vote) : plannings pas encore connus"]}
    return cas


def cas_nouvelles_familles() -> Cas:
    """22 familles sur 4 semaines : 88 perms pour 40 créneaux à 2 parents, triplets forcés."""
    cas = Cas("nouvelles_familles", "Planning Février", creneaux_du_mois(FEV_2027))
    rng = random.Random(5)
    cas.lignes = [(p, dispos_aleatoires(rng, cas.creneaux, p_oui=0.6)) for p in PRENOMS[:22]]
    return cas


TOUS_LES_CAS = [cas_ferie_pont, cas_vacances, cas_creneau_sans_oui,
                cas_mauvaises_reponses, cas_nouvelles_familles]


def ecrire_cas(cas: Cas, dossier: Path) -> dict[str, Path]:
    """Écrit poll.csv, poll.html et contraintes.yaml dans dossier/<nom du cas>."""
    d = Path(dossier) / cas.nom
    d.mkdir(parents=True, exist_ok=True)
    chemins = {"csv": d / "poll.csv", "html": d / "poll.html", "yaml": d / "contraintes.yaml"}
    for cle, texte in (("csv", ecrire_csv(cas)), ("html", ecrire_html(cas)),
                       ("yaml", ecrire_yaml(cas))):
        chemins[cle].write_bytes(texte.encode("utf-8"))
    return chemins


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dossier = Path(argv[0]) if argv else Path(__file__).resolve().parent / "fixtures" / "cas_limites"
    for fabrique in TOUS_LES_CAS:
        print(ecrire_cas(fabrique(), dossier)["csv"].parent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
