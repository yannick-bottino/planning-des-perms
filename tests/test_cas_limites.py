"""Cas limites : faux sondages Framadate passés par fetch_framadate.py puis solve.py."""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))
import fetch_framadate as ff  # noqa: E402
import generateur_sondage as gen  # noqa: E402
import solve  # noqa: E402

FIGES = TESTS / "fixtures" / "cas_limites"


def executer(fabrique, tmp_path: Path) -> dict:
    """Génère le cas, lance les deux scripts en ligne de commande, relit les sorties."""
    chemins = gen.ecrire_cas(fabrique(), tmp_path)
    sondage_json, planning_json = tmp_path / "sondage.json", tmp_path / "planning.json"
    assert ff.main(["--csv", str(chemins["csv"]), "--html", str(chemins["html"]),
                    "--out", str(sondage_json)]) == 0
    debut = time.monotonic()
    assert solve.main(["--sondage", str(sondage_json), "--contraintes", str(chemins["yaml"]),
                       "--out", str(planning_json)]) == 0
    duree = time.monotonic() - debut
    sondage = json.loads(sondage_json.read_text(encoding="utf-8"))
    planning = json.loads(planning_json.read_text(encoding="utf-8"))
    contraintes = solve.charger_contraintes(chemins["yaml"], sondage)
    return {"sondage": sondage, "planning": planning, "contraintes": contraintes,
            "duree": duree}


@pytest.fixture(scope="module")
def resultats(tmp_path_factory):
    return {f.__name__: executer(f, tmp_path_factory.mktemp(f.__name__)) for f in gen.TOUS_LES_CAS}


def alertes(r: dict, code: str) -> list[dict]:
    return [a for a in r["planning"]["alertes"] if a["code"] == code]


def ecarts_quota(r: dict) -> dict:
    return {f: (b["total"], b["quota_mois"]) for f, b in r["planning"]["bilan"].items()
            if b["total"] != b["quota_mois"]}


def par_semaine(r: dict, semaine: str) -> dict:
    return {f: b["par_semaine"][semaine] for f, b in r["planning"]["bilan"].items()}


# ---------------------------------------------------------------- règles communes

NOMS = [f.__name__ for f in gen.TOUS_LES_CAS]


@pytest.mark.parametrize("cas", NOMS)
def test_planning_rendu_optimal_et_rapide(resultats, cas):
    r = resultats[cas]
    p = r["planning"]
    assert p["affectations"] and len(p["creneaux"]) == len(r["sondage"]["creneaux"])
    assert p["solveur"]["statut"] == "OPTIMAL"
    assert p["solveur"]["duree_s"] < 10 and r["duree"] < 10


@pytest.mark.parametrize("cas", NOMS)
def test_aucune_violation_dure(resultats, cas):
    r = resultats[cas]
    recalcul = solve.evaluer(r["sondage"], r["contraintes"], r["planning"]["affectations"])
    assert [a for a in recalcul["alertes"] if a["code"] == "D"] == []
    assert recalcul["alertes"] == r["planning"]["alertes"]


@pytest.mark.parametrize("cas, attendu", [
    ("cas_ferie_pont", {"A4": 1}),
    ("cas_vacances", {}),
    ("cas_creneau_sans_oui", {"A1": 1, "A6": 1}),
    ("cas_mauvaises_reponses", {"A3": 1, "A4": 1, "A6": 4}),
    ("cas_nouvelles_familles", {"A2": 8}),
])
def test_alertes_attendues(resultats, cas, attendu):
    assert Counter(a["code"] for a in resultats[cas]["planning"]["alertes"]) == attendu


@pytest.mark.parametrize("cas", [n for n in NOMS if n != "cas_mauvaises_reponses"])
def test_quotas_tenus(resultats, cas):
    assert ecarts_quota(resultats[cas]) == {}


# ---------------------------------------------------------------- 1. férié et pont

def test_ferie_pont_reporte_les_perms(resultats):
    r = resultats["cas_ferie_pont"]
    s1 = par_semaine(r, "2027-11-08")
    assert len([c for c in r["sondage"]["creneaux"] if c["semaine"] == "2027-11-08"]) == 6
    assert not {c["date"] for c in r["sondage"]["creneaux"]} & {"2027-11-11", "2027-11-12"}
    sans_perm = [f for f, n in s1.items() if n == 0]
    # 6 créneaux à 2 parents au plus : 12 perms pour 17 familles.
    assert sum(s1.values()) == 12 and len(sans_perm) == 5
    for f in sans_perm:
        assert 2 in r["planning"]["bilan"][f]["par_semaine"].values()
    assert all(len(c["familles"]) in (1, 2) for c in r["planning"]["creneaux"])


# ---------------------------------------------------------------- 2. vacances

def test_vacances_absentes_epargnees_presentes_doublent(resultats):
    r = resultats["cas_vacances"]
    sem = gen.VACANCES.isoformat()
    s = par_semaine(r, sem)
    absentes = {f for f, cf in r["contraintes"]["familles"].items() if sem in cf["absences"]}
    assert len(absentes) == 8
    assert all(s[f] == 0 and r["planning"]["bilan"][f]["quota_mois"] == 3 for f in absentes)
    presentes = set(s) - absentes
    assert sum(s[f] for f in presentes) >= 10   # les 10 créneaux de la semaine sont tenus
    assert len([f for f in presentes if s[f] == 2]) >= 2
    assert all(c["familles"] for c in r["planning"]["creneaux"] if c["semaine"] == sem)


# ---------------------------------------------------------------- 3. créneau sans oui

def test_creneau_sans_oui_signale_et_planning_complet(resultats):
    r = resultats["cas_creneau_sans_oui"]
    vide = "2027-02-12_A"
    assert [a["creneau"] for a in alertes(r, "A1")] == [vide]
    vides = [c["id"] for c in r["planning"]["creneaux"] if not c["familles"]]
    assert vides == [vide]
    # Le 19/02 après-midi, le seul « si besoin » est utilisé et signalé.
    a6 = alertes(r, "A6")
    assert [(a["creneau"], a["famille"]) for a in a6] == [("2027-02-19_A", "ALMA")]


# ---------------------------------------------------------------- 4. mauvaises réponses

def test_mauvaises_reponses(resultats):
    r = resultats["cas_mauvaises_reponses"]
    s, p = r["sondage"], r["planning"]
    # Doublon Noé / noe : une seule famille, dispos des deux lignes réunies.
    noms = [f["nom"] for f in s["familles"]]
    assert noms.count("NOE") == 1 and len(noms) == 15
    assert any("Noé / noe" in w for w in s["avertissements"])
    assert all(n == 1 for n in p["bilan"]["NOE"]["par_semaine"].values())
    # Trop peu de dispos : A3, avec toutes ses dispos utilisées.
    assert ecarts_quota(r) == {"CAPUCINE": (2, 4)}
    assert [a["famille"] for a in alertes(r, "A3")] == ["CAPUCINE"]
    # Que des « si besoin » : quota tenu, une alerte A6 par perm.
    assert {a["famille"] for a in alertes(r, "A6")} == {"GASPARD"}
    assert p["bilan"]["GASPARD"]["total"] == 4
    # Commentaire d'une famille qui n'a pas voté : avertissement puis A4.
    assert any("HORTENSE" in w for w in s["avertissements"])
    assert "HORTENSE" in alertes(r, "A4")[0]["message"]


def test_solveur_refuse_un_sondage_avec_doublon():
    s = {"creneaux": [{"id": "2027-02-01_M", "date": "2027-02-01", "demi": "M",
                       "semaine": "2027-02-01"}],
         "familles": [{"nom": "NOE", "dispos": {}}, {"nom": "NOE", "dispos": {}}]}
    with pytest.raises(ValueError, match="NOE"):
        solve.lire_contraintes({}, s)


# ---------------------------------------------------------------- 5. nouvelles familles

def test_nouvelles_familles_triplets_au_minimum(resultats):
    r = resultats["cas_nouvelles_familles"]
    tailles = [len(c["familles"]) for c in r["planning"]["creneaux"]]
    assert len(r["sondage"]["familles"]) == 22 and len(tailles) == 40
    # 22 x 4 = 88 perms pour 40 créneaux x 2 = 80 places : 8 parents en trop au minimum.
    assert sum(tailles) == 88 and min(tailles) >= 1
    assert sorted(t for t in tailles if t > 2) == [3] * 8   # 8 triplets, aucun créneau à 4
    assert len(alertes(r, "A2")) == 8


# ---------------------------------------------------------------- fixtures figées

@pytest.mark.parametrize("fabrique", gen.TOUS_LES_CAS, ids=NOMS)
def test_fixtures_figees_a_jour(fabrique, tmp_path):
    """Les fichiers commités sous fixtures/cas_limites sont ceux du générateur."""
    cas = fabrique()
    for chemin in gen.ecrire_cas(cas, tmp_path).values():
        fige = (FIGES / cas.nom / chemin.name).read_bytes().replace(b"\r\n", b"\n")  # autocrlf
        assert fige == chemin.read_bytes()
