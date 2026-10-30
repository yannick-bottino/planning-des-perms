"""Logique des étapes : lien, résumé, aller-retour règles/contraintes, passerelle d'arbitrage (critère 6)."""
import re
from pathlib import Path

import pytest
import yaml

from outils_app import FIXTURES, SKILL

import fetch_framadate
import parcours
from solve import lire_contraintes


def sondage_de(dossier: Path) -> dict:
    return fetch_framadate.construire("x", (dossier / "poll.csv").read_text(encoding="utf-8"),
                                      (dossier / "poll.html").read_text(encoding="utf-8"))


@pytest.fixture
def sondage():
    return sondage_de(FIXTURES)


# Couvre les quatre types de règle, les deux formes de préférence, un `parmi` à plusieurs
# filtres et un poids omis. Prénoms fictifs.
COMPLET = {
    "plafond_hebdo": 2,
    "familles": {
        "Léa": {"au_moins": {"n": 1, "parmi": [{"jour": "lundi", "demi": "M"}, {"jour": "mercredi"}]},
                "preferences": [{"creneau": "2026-11-03_M", "poids": 5}, {"jour": "mardi"}],
                "source": "Léa : lundi matin ou mercredi"},
        "ZOE": {"absences": ["2026-11-09"], "quota_mois": 2, "source": "zoé : congés"},
        "basile": {"quota_mois": 0},
    },
    "commentaires_non_traduits": ["INCONNU : absents du 11 au 13"],
}


# ---------------------------------------------------------------- aller-retour (critère 6)

def aller_retour(brut, sondage):
    return parcours.contraintes_depuis_regles(parcours.regles_depuis_contraintes(brut), sondage)


def test_aller_retour_fixture_complete(sondage):
    assert lire_contraintes(aller_retour(COMPLET, sondage), sondage) == lire_contraintes(COMPLET, sondage)


@pytest.mark.parametrize("cas", sorted(p.name for p in (FIXTURES / "cas_limites").iterdir()))
def test_aller_retour_fixtures_v1(cas):
    dossier = FIXTURES / "cas_limites" / cas
    s = sondage_de(dossier)
    brut = yaml.safe_load((dossier / "contraintes.yaml").read_text(encoding="utf-8")) or {}
    assert lire_contraintes(aller_retour(brut, s), s) == lire_contraintes(brut, s)


def test_lignes_produites(sondage):
    lignes = parcours.regles_depuis_contraintes(COMPLET)
    types = [(r["famille"], r["type"]) for r in lignes["regles"]]
    assert types == [("LEA", "au_moins"), ("LEA", "preference"), ("LEA", "preference"),
                     ("ZOE", "absence"), ("ZOE", "quota"), ("BASILE", "quota")]
    assert lignes["regles"][0]["parmi"] == ["lundi:M", "mercredi"]
    assert lignes["regles"][1]["cible"] == "2026-11-03_M"
    assert lignes["regles"][2] == {"famille": "LEA", "type": "preference", "cible": "mardi",
                                   "poids": 1, "source": "Léa : lundi matin ou mercredi"}
    assert lignes["reglages"] == {"cible_hebdo": 1, "plafond_hebdo": 2, "max_parents_par_creneau": 2}
    assert lignes["non_traduits"] == ["INCONNU : absents du 11 au 13"]


def test_sources_dedoublonnees(sondage):
    brut = aller_retour(COMPLET, sondage)
    assert brut["familles"]["LEA"]["source"] == "Léa : lundi matin ou mercredi"
    lignes = parcours.regles_depuis_contraintes(COMPLET)
    lignes["regles"][1]["source"] = "autre commentaire"
    assert parcours.contraintes_depuis_regles(lignes, sondage)["familles"]["LEA"]["source"] == \
        "Léa : lundi matin ou mercredi | autre commentaire"


@pytest.mark.parametrize("regle,attendu", [
    ({"famille": "", "type": "quota", "quota": 1}, "famille"),
    ({"famille": "NOBODY", "type": "quota", "quota": 1}, "pas dans le sondage"),
    ({"famille": "LEA", "type": "", "quota": 1}, "type de règle"),
    ({"famille": "LEA", "type": "absence", "semaine": "2026-12-07"}, "semaine"),
    ({"famille": "LEA", "type": "quota", "quota": -1}, "nombre"),
    ({"famille": "LEA", "type": "quota", "quota": "deux"}, "nombre"),
    ({"famille": "LEA", "type": "au_moins", "n": 1, "parmi": []}, "Cochez"),
    ({"famille": "LEA", "type": "au_moins", "n": 0, "parmi": ["lundi"]}, "1 ou plus"),
    ({"famille": "LEA", "type": "preference", "cible": ""}, "jour ou le créneau"),
])
def test_ligne_invalide(sondage, regle, attendu):
    with pytest.raises(parcours.ErreurRegle) as e:
        parcours.contraintes_depuis_regles({"regles": [{"famille": "ZOE", "type": "quota", "quota": 1}, regle]}, sondage)
    assert e.value.index == 1 and attendu in str(e.value)


def test_doublons_refuses(sondage):
    for regles in ([{"famille": "LEA", "type": "quota", "quota": 1}, {"famille": "LEA", "type": "quota", "quota": 2}],
                   [{"famille": "LEA", "type": "au_moins", "parmi": ["lundi"]},
                    {"famille": "LEA", "type": "au_moins", "parmi": ["mardi"]}],
                   [{"famille": "LEA", "type": "absence", "semaine": "2026-11-09"},
                    {"famille": "LEA", "type": "absence", "semaine": "2026-11-09"}]):
        with pytest.raises(parcours.ErreurRegle) as e:
            parcours.contraintes_depuis_regles({"regles": regles}, sondage)
        assert e.value.index == 1


def test_quota_saisi_en_texte_accepte(sondage):
    brut = parcours.contraintes_depuis_regles(
        {"regles": [{"famille": "LEA", "type": "quota", "quota": "3"}]}, sondage)
    assert brut["familles"]["LEA"]["quota_mois"] == 3


def test_validation_v1_remonte(sondage):
    # Filtre qui ne couvre aucun créneau (aucun vendredi dans la fixture) : erreur V1.
    with pytest.raises(parcours.ErreurRegle, match="aucun créneau"):
        parcours.valider_regles({"regles": [{"famille": "LEA", "type": "preference", "cible": "vendredi"}]}, sondage)


def test_reglage_invalide(sondage):
    with pytest.raises(parcours.ErreurRegle, match="max_parents_par_creneau"):
        parcours.contraintes_depuis_regles({"regles": [], "reglages": {"max_parents_par_creneau": 0}}, sondage)


def test_non_traduits_vides_ignores(sondage):
    brut = parcours.contraintes_depuis_regles({"regles": [], "non_traduits": ["  ", "à voir"]}, sondage)
    assert brut == {"commentaires_non_traduits": ["à voir"]}


# ---------------------------------------------------------------- étapes 1 et 2

@pytest.mark.parametrize("lien,attendu", [
    ("https://framadate.org/polls/AbC123", ("AbC123", "https://framadate.org/polls/AbC123.csv")),
    ("framadate.org/polls/AbC123/admin", ("AbC123", "https://framadate.org/polls/AbC123.csv")),
    ("https://framadate.org/polls/AbC123.csv", ("AbC123", "https://framadate.org/polls/AbC123.csv")),
    ("https://date.exemple.fr/sub/polls/Xy9?x=1", ("Xy9", "https://date.exemple.fr/sub/polls/Xy9.csv")),
    ("http://127.0.0.1:5000/polls/Test1", ("Test1", "http://127.0.0.1:5000/polls/Test1.csv")),
])
def test_adresses_sondage(lien, attendu):
    pid, csv, page = parcours.adresses_sondage(lien)
    assert (pid, csv) == attendu and page == csv.removesuffix(".csv")


@pytest.mark.parametrize("lien", ["", "https://framadate.org/", "http://framadate.org/polls/Abc",
                                  "ftp://framadate.org/polls/Abc"])
def test_adresses_sondage_refusees(lien):
    with pytest.raises(ValueError):
        parcours.adresses_sondage(lien)


def test_mois_du_sondage():
    s = {"creneaux": [{"date": "2026-10-30"}, {"date": "2026-11-02"}, {"date": "2026-11-03"}]}
    assert parcours.mois_du_sondage(s) == "2026-11"
    s = {"creneaux": [{"date": "2026-10-30"}, {"date": "2026-11-02"}]}
    assert parcours.mois_du_sondage(s) == "2026-10"
    with pytest.raises(ValueError):
        parcours.mois_du_sondage({"creneaux": []})


def test_resumer(sondage):
    r = parcours.resumer(sondage)
    assert r["familles"] == ["BASILE", "ELOISE", "LEA", "ZOE"]
    assert r["nb_creneaux"] == 10 and len(r["semaines"]) == 2
    assert r["jours_fermes"] == ["jeudi 5/11", "vendredi 6/11"]
    assert {"famille": "ELOISE", "semaine": "Semaine du 9 novembre"} in r["sans_dispo"]
    assert len(r["commentaires"]) == 3


def test_options(sondage):
    o = parcours.options(sondage)
    assert [f["valeur"] for f in o["filtres"]][:3] == ["lundi", "lundi:M", "lundi:A"]
    assert o["creneaux"][0] == {"valeur": "2026-11-02_M", "libelle": "lundi 2/11 matin"}
    assert o["nb_semaines"] == 2


def test_regles_sans_reponse(sondage):
    for f in sondage["familles"]:
        if f["nom"] == "BASILE":
            f["dispos"] = {k: "non" for k in f["dispos"]}
    lignes = parcours.regles_sans_reponse(sondage, [])
    assert [(r["famille"], r["quota"]) for r in lignes] == [("BASILE", 0)]
    assert parcours.regles_sans_reponse(sondage, [{"famille": "BASILE", "type": "quota", "quota": 2}]) == []


# ---------------------------------------------------------------- passerelle d'arbitrage

def test_gabarit_respecte_le_contrat_de_la_passerelle():
    """Contrat V1 sur lequel repose la passerelle (V2-18). Casse si le gabarit change d'export."""
    gabarit = (SKILL / "templates" / "arbitrage.html").read_text(encoding="utf-8")
    assert re.search(r"<head[^>]*>", gabarit, re.I)
    assert "arbitrages.json" in gabarit
    assert "createObjectURL" in gabarit
    assert 'id="btn-export"' in gabarit or re.search(r"<button[^>]*>[^<]*Export", gabarit)


def test_page_arbitrage_contient_la_passerelle_en_tete(sondage):
    contraintes = lire_contraintes({}, sondage)
    planning = parcours.calculer(sondage, contraintes)
    page = parcours.page_arbitrage(planning, sondage, contraintes)
    tete = page.index("<head")
    assert page.index(parcours.PASSERELLE) > tete
    assert page.index(parcours.PASSERELLE) < page.index('<script type="application/json"')


def test_page_arbitrage_sans_head(monkeypatch, sondage):
    monkeypatch.setattr(parcours, "generer_page", lambda *a, **k: "<html><body></body></html>")
    with pytest.raises(ValueError, match="head"):
        parcours.page_arbitrage({}, sondage, {})


def test_bilan(sondage):
    contraintes = lire_contraintes({}, sondage)
    planning = parcours.calculer(sondage, contraintes)
    b = parcours.bilan(planning, sondage)
    assert {f["famille"] for f in b["familles"]} == {"BASILE", "ELOISE", "LEA", "ZOE"}
    assert b["regle_dure_violee"] is False
    r = parcours.resumer_calcul(planning)
    assert r["a_deux"] + r["a_un"] + r["vides"] + r["a_trois_ou_plus"] == 10


def test_absences_dedoublonnees():
    lignes = parcours.regles_depuis_contraintes({"familles": {"ZOE": {"absences": ["2026-11-09", "2026-11-09"]}}})
    assert [r["semaine"] for r in lignes["regles"]] == ["2026-11-09"]


def test_emballage_liste_fermee():
    import emballer
    noms = {p.relative_to(SKILL).as_posix() for p in emballer.fichiers()}
    assert {"lancer.bat", "lancer.sh", "app/serveur.py", "app/static/app.js", "scripts/solve.py",
            "templates/arbitrage.html", "references/regles-affectation.md"} <= noms
    assert not any(n.startswith("tests/") or n.endswith((".json", ".yaml", ".pyc", ".xlsx")) for n in noms)


def test_passerelle_accuse_reception_avant_envoi():
    assert parcours.PASSERELLE.index('"arbitrage-recu"') < parcours.PASSERELLE.index("blob.text()")
