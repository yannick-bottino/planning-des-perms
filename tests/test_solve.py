import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from solve import (  # noqa: E402
    construire_planning, evaluer, libelle_creneau, lire_contraintes, main,
)

LUNDI = date(2026, 11, 2)


def faire_sondage(familles: dict, semaines: int = 1, jours=(0, 1), demis=("M",)) -> dict:
    """Sondage synthétique. `familles` : nom -> {id de créneau: dispo} (absent = non)."""
    creneaux = []
    for s in range(semaines):
        lundi = LUNDI + timedelta(weeks=s)
        for j in jours:
            d = lundi + timedelta(days=j)
            for demi in demis:
                creneaux.append({
                    "id": f"{d.isoformat()}_{demi}", "date": d.isoformat(), "demi": demi,
                    "semaine": lundi.isoformat(), "semaine_iso": d.isocalendar().week,
                })
    ids = [c["id"] for c in creneaux]
    return {
        "poll_id": "test", "titre": "Planning test", "creneaux": creneaux,
        "familles": [
            {"nom": nom, "nom_brut": nom, "dispos": {i: d.get(i, "non") for i in ids}}
            for nom, d in familles.items()
        ],
        "commentaires": [],
    }


def partout(sondage: dict, valeur="oui") -> dict:
    return {c["id"]: valeur for c in sondage["creneaux"]}


def resoudre(sondage: dict, brut: dict | None = None) -> dict:
    return construire_planning(sondage, lire_contraintes(brut, sondage), temps_max=10)


def codes(planning: dict) -> list[str]:
    return [a["code"] for a in planning["alertes"]]


def perms(planning: dict, famille: str) -> list[str]:
    return [a["creneau"] for a in planning["affectations"] if a["famille"] == famille]


def test_planning_simple_sans_alerte():
    base = faire_sondage({"ALMA": {}, "BRUNO": {}})
    s = faire_sondage({"ALMA": partout(base), "BRUNO": partout(base)})
    p = resoudre(s)
    assert p["alertes"] == []
    assert p["solveur"]["statut"] == "OPTIMAL"
    assert {f: b["total"] for f, b in p["bilan"].items()} == {"ALMA": 1, "BRUNO": 1}
    assert [len(c["familles"]) for c in p["creneaux"]] == [1, 1]


def test_rattrapage_apres_semaine_sans_dispo():
    base = faire_sondage({"ALMA": {}}, semaines=2)
    sem2 = {c["id"]: "oui" for c in base["creneaux"] if c["semaine"] != LUNDI.isoformat()}
    s = faire_sondage({"ALMA": sem2, "BRUNO": partout(base)}, semaines=2)
    p = resoudre(s)
    assert p["bilan"]["ALMA"]["total"] == 2 and p["bilan"]["BRUNO"]["total"] == 2
    assert p["bilan"]["ALMA"]["par_semaine"] == {"2026-11-02": 0, "2026-11-09": 2}
    assert "A3" not in codes(p) and "D" not in codes(p) and "A1" not in codes(p)


def test_quota_impossible_donne_a3_et_un_planning():
    base = faire_sondage({"ALMA": {}})
    un_seul = {base["creneaux"][0]["id"]: "oui"}
    s = faire_sondage({"ALMA": un_seul, "BRUNO": partout(base)})
    p = resoudre(s, {"familles": {"alma": {"quota_mois": 3}}})
    assert p["bilan"]["ALMA"]["total"] == 1
    a3 = [a for a in p["alertes"] if a["code"] == "A3"]
    assert [a["famille"] for a in a3] == ["ALMA"]
    assert "ALMA" in a3[0]["message"] and a3[0]["gravite"] == "orange"


def test_creneau_que_personne_ne_peut_prendre():
    base = faire_sondage({"ALMA": {}})
    premier, second = (c["id"] for c in base["creneaux"])
    s = faire_sondage({"ALMA": {premier: "oui"}, "BRUNO": {premier: "oui"}})
    p = resoudre(s, {"familles": {"ALMA": {"quota_mois": 0}, "BRUNO": {"quota_mois": 1}}})
    a1 = [a for a in p["alertes"] if a["code"] == "A1"]
    assert [a["creneau"] for a in a1] == [second]
    assert a1[0]["gravite"] == "rouge"
    assert a1[0]["message"] == "Créneau sans parent : mardi 3/11 matin"


def test_absence_respectee():
    base = faire_sondage({"ALMA": {}}, semaines=2)
    s = faire_sondage({"ALMA": partout(base), "BRUNO": partout(base)}, semaines=2)
    p = resoudre(s, {"familles": {"ALMA": {"absences": ["2026-11-02"]}}})
    assert all(c.startswith("2026-11-1") or c.startswith("2026-11-09") for c in perms(p, "ALMA"))
    assert p["bilan"]["ALMA"]["quota_mois"] == 1  # 2 semaines - 1 absence
    assert p["bilan"]["ALMA"]["total"] == 1
    assert "D" not in codes(p)


def test_au_moins_respecte_quand_possible():
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": partout(base), "BRUNO": partout(base)})
    contraintes = {"familles": {"ALMA": {"au_moins": {"n": 1, "parmi": [{"jour": "mardi"}]}}}}
    p = resoudre(s, contraintes)
    assert perms(p, "ALMA") == ["2026-11-03_M"]
    assert "A7" not in codes(p)


def test_au_moins_impossible_donne_a7():
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": {"2026-11-02_M": "oui"}, "BRUNO": partout(base)})
    contraintes = {"familles": {"ALMA": {"au_moins": {"n": 1, "parmi": [{"jour": "mardi"}]}}}}
    p = resoudre(s, contraintes)
    a7 = [a for a in p["alertes"] if a["code"] == "A7"]
    assert [a["famille"] for a in a7] == ["ALMA"] and a7[0]["gravite"] == "jaune"


def test_preference_satisfaite_ou_signalee():
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": partout(base), "BRUNO": partout(base)})
    pref = {"familles": {"ALMA": {"preferences": [{"jour": "mardi", "poids": 3}]}}}
    assert perms(resoudre(s, pref), "ALMA") == ["2026-11-03_M"]
    s2 = faire_sondage({"ALMA": {"2026-11-02_M": "oui"}, "BRUNO": partout(base)})
    assert "A7" in codes(resoudre(s2, pref))


def test_si_besoin_utilise_seulement_si_necessaire():
    base = faire_sondage({"ALMA": {}})
    lundi, mardi = (c["id"] for c in base["creneaux"])
    # Alternative "oui" disponible : pas de si_besoin.
    s = faire_sondage({"ALMA": {lundi: "si_besoin", mardi: "oui"}, "BRUNO": partout(base)})
    p = resoudre(s)
    assert "A6" not in codes(p) and perms(p, "ALMA") == [mardi]
    # Aucune alternative : si_besoin utilisé, alerte grise.
    s = faire_sondage({"ALMA": {lundi: "si_besoin"}, "BRUNO": {mardi: "oui"}})
    p = resoudre(s)
    a6 = [a for a in p["alertes"] if a["code"] == "A6"]
    assert [a["creneau"] for a in a6] == [lundi] and a6[0]["gravite"] == "gris"
    assert p["affectations"][0]["dispo"] == "si_besoin"


def test_commentaire_non_traduit_donne_a4():
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": partout(base), "BRUNO": partout(base)})
    p = resoudre(s, {"commentaires_non_traduits": ["ALMA : à confirmer"]})
    assert codes(p) == ["A4"] and "ALMA : à confirmer" in p["alertes"][0]["message"]


def test_determinisme():
    base = faire_sondage({"ALMA": {}}, semaines=3, jours=(0, 1, 2), demis=("M", "A"))
    s = faire_sondage({n: partout(base) for n in ("ALMA", "BRUNO", "CLEO", "DORA")},
                      semaines=3, jours=(0, 1, 2), demis=("M", "A"))
    p1, p2 = resoudre(s), resoudre(s)
    for p in (p1, p2):
        p["solveur"].pop("duree_s")
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)
    assert len(p1["empreinte"]) == 64


def test_format_planning():
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": partout(base, "si_besoin"), "BRUNO": partout(base)})
    p = resoudre(s)
    assert list(p) == ["poll_id", "titre", "empreinte", "solveur", "creneaux",
                       "affectations", "bilan", "alertes"]
    assert set(p["solveur"]) == {"statut", "score", "duree_s", "ortools"}
    assert set(p["creneaux"][0]) == {"id", "date", "demi", "semaine", "semaine_iso", "familles"}
    assert set(p["affectations"][0]) == {"famille", "creneau", "dispo", "origine"}
    assert set(p["bilan"]["ALMA"]) == {"quota_mois", "total", "par_semaine"}


def test_evaluer_detecte_violations_dures():
    base = faire_sondage({"ALMA": {}}, jours=(0,), demis=("M", "A"))
    matin, apres = (c["id"] for c in base["creneaux"])
    s = faire_sondage({"ALMA": {matin: "oui"}, "BRUNO": {}}, jours=(0,), demis=("M", "A"))
    c = lire_contraintes(None, s)
    aff = [{"famille": "ALMA", "creneau": matin}, {"famille": "ALMA", "creneau": apres},
           {"famille": "BRUNO", "creneau": matin}]
    msgs = [a["message"] for a in evaluer(s, c, aff)["alertes"] if a["code"] == "D"]
    assert any("BRUNO" in m and "pas disponible" in m and "lundi 2/11 matin" in m for m in msgs)
    assert any("ALMA" in m and "pas disponible" in m and "après-midi" in m for m in msgs)
    assert any("ALMA" in m and "même jour" in m for m in msgs)


def test_evaluer_detecte_plafond_et_absence():
    base = faire_sondage({"ALMA": {}}, semaines=2, jours=(0, 1, 2))
    s = faire_sondage({"ALMA": partout(base)}, semaines=2, jours=(0, 1, 2))
    c = lire_contraintes({"familles": {"ALMA": {"absences": ["2026-11-09"]}}}, s)
    ids = [x["id"] for x in s["creneaux"]]
    aff = [{"famille": "ALMA", "creneau": i} for i in ids[:3] + ids[3:4]]
    regles = [a["regle"] for a in evaluer(s, c, aff)["alertes"] if a["code"] == "D"]
    assert sorted(regles) == ["D2", "D4"]


def test_libelle_creneau():
    cr = {"date": "2026-11-02", "demi": "A"}
    assert libelle_creneau(cr) == "lundi 2/11 après-midi"


# ---- CLI

def ecrire(tmp_path, sondage: dict, yaml_txt: str):
    (tmp_path / "s.json").write_text(json.dumps(sondage), encoding="utf-8")
    (tmp_path / "c.yaml").write_text(yaml_txt, encoding="utf-8")
    return ["--sondage", str(tmp_path / "s.json"), "--contraintes", str(tmp_path / "c.yaml"),
            "--out", str(tmp_path / "p.json")]


def test_cli_succes_et_determinisme(tmp_path, capsys):
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": partout(base), "BRUNO": partout(base)})
    args = ecrire(tmp_path, s, "familles:\n  alma: {quota_mois: 1}\n")
    assert main(args) == 0
    p1 = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert main(args + ["--temps-max", "5"]) == 0
    p2 = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    for p in (p1, p2):
        p["solveur"].pop("duree_s")
    assert p1 == p2


@pytest.mark.parametrize("yaml_txt,fragment", [
    ("familles:\n  INCONNUE: {quota_mois: 1}\n", "INCONNUE"),
    ("familles:\n  ALMA: {absences: ['2026-12-21']}\n", "2026-12-21"),
    ("familles:\n  ALMA: {preferences: [{creneau: '2026-11-04_M'}]}\n", "2026-11-04_M"),
    ("familles: [\n", "invalide"),
])
def test_cli_erreurs_attendues(tmp_path, capsys, yaml_txt, fragment):
    base = faire_sondage({"ALMA": {}})
    s = faire_sondage({"ALMA": partout(base)})
    assert main(ecrire(tmp_path, s, yaml_txt)) == 1
    err = capsys.readouterr().err
    assert err.startswith("Erreur") and fragment in err and "Traceback" not in err
    assert not (tmp_path / "p.json").exists()


def test_cli_fichier_absent(tmp_path, capsys):
    code = main(["--sondage", str(tmp_path / "x.json"), "--contraintes", str(tmp_path / "y.yaml"),
                 "--out", str(tmp_path / "p.json")])
    assert code == 1 and "Traceback" not in capsys.readouterr().err
