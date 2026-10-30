import datetime
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from export_xlsx import appliquer_arbitrages, ecrire_xlsx, main  # noqa: E402
from solve import (  # noqa: E402
    construire_planning, creneaux_avec_familles, empreinte, evaluer, lire_contraintes,
)

LUNDI = date(2026, 11, 2)
NOMS = ["ALMA", "BRUNO", "CLEO", "DANTE", "ELIO", "FANNY"]


def faire_sondage(jours_par_semaine=((0, 1), (0,)), dispo="oui") -> dict:
    """Sondage synthétique : semaine 1 lundi+mardi, semaine 2 lundi seul (mardi fermé)."""
    creneaux = []
    for s, jours in enumerate(jours_par_semaine):
        lundi = LUNDI + timedelta(weeks=s)
        for j in jours:
            d = lundi + timedelta(days=j)
            for demi in ("M", "A"):
                creneaux.append({"id": f"{d.isoformat()}_{demi}", "date": d.isoformat(),
                                 "demi": demi, "semaine": lundi.isoformat(),
                                 "semaine_iso": d.isocalendar().week})
    ids = [c["id"] for c in creneaux]
    return {"poll_id": "test", "titre": "Planning test", "creneaux": creneaux,
            "familles": [{"nom": n, "nom_brut": n, "dispos": {i: dispo for i in ids}} for n in NOMS],
            "commentaires": []}


def faire_planning(sondage: dict, brut: dict | None, paires: list[tuple]) -> tuple[dict, dict]:
    """Planning manuel à partir de paires (famille, créneau). Renvoie (planning, contraintes)."""
    contraintes = lire_contraintes(brut, sondage)
    aff = [{"famille": f, "creneau": c, "dispo": "oui", "origine": "solveur"} for f, c in paires]
    res = evaluer(sondage, contraintes, aff)
    return ({"poll_id": "test", "titre": "Planning test", "empreinte": empreinte(sondage, contraintes),
             "solveur": {}, "creneaux": creneaux_avec_familles(sondage, aff), "affectations": aff,
             "bilan": res["bilan"], "alertes": res["alertes"]}, contraintes)


def cellules(ws, col: int) -> dict:
    return {r: ws.cell(r, col).value for r in range(1, ws.max_row + 1) if ws.cell(r, col).value}


def test_onglets_et_ordre(tmp_path):
    s = faire_sondage()
    p, _ = faire_planning(s, None, [("ALMA", "2026-11-02_M")])
    ecrire_xlsx(p, tmp_path / "a.xlsx")
    wb = load_workbook(tmp_path / "a.xlsx")
    assert wb.sheetnames == ["SEMAINE 45", "SEMAINE 46"]
    assert wb["SEMAINE 45"]["A1"].value == "SEMAINE 45"
    assert wb["SEMAINE 45"]["A2"].value is None


def test_positions_date_matin_amidi(tmp_path):
    s = faire_sondage()
    p, _ = faire_planning(s, None, [("ALMA", "2026-11-02_M"), ("BRUNO", "2026-11-02_M"),
                                    ("CLEO", "2026-11-02_A")])
    ecrire_xlsx(p, tmp_path / "a.xlsx")
    ws = load_workbook(tmp_path / "a.xlsx")["SEMAINE 45"]
    assert ws["A3"].value == "LUNDI" and ws["D3"].value == "MATIN"
    assert ws["K3"].value == "8h30" and ws["AE3"].value == "18h30"
    assert ws["AF3"].value == "Nb h" and ws["AG3"].value == "Nb h réelles"
    assert ws["A3"].font.bold and ws["D3"].font.bold
    assert isinstance(ws["A4"].value, datetime.datetime)
    assert ws["A4"].value == datetime.datetime(2026, 11, 2)
    assert ws["A4"].number_format == "dd/mm"
    assert (ws["D4"].value, ws["D5"].value) == ("ALMA", "BRUNO")
    assert ws["A7"].value == "Nb prév" and ws["A8"].value == "enfants"
    assert ws["D8"].value == "A-MIDI" and ws["D9"].value == "CLEO"
    assert ws["A14"].value == "MARDI" and ws["A15"].value.day == 3
    assert ws["F61"].value is None
    bas = cellules(ws, 6)
    assert list(bas.values()) == ["Heures/enfants", "Heures/contrat"]


def test_jour_ferme_sans_bloc(tmp_path):
    s = faire_sondage()
    p, _ = faire_planning(s, None, [])
    ecrire_xlsx(p, tmp_path / "a.xlsx")
    ws = load_workbook(tmp_path / "a.xlsx")["SEMAINE 46"]
    jours = [v for v in cellules(ws, 1).values() if v in ("LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI")]
    assert jours == ["LUNDI"]


def test_bloc_agrandi_au_dela_du_gabarit(tmp_path):
    s = faire_sondage()
    paires = [(n, "2026-11-02_M") for n in NOMS[:5]] + [("ALMA", "2026-11-02_A")]
    p, _ = faire_planning(s, None, paires)
    ecrire_xlsx(p, tmp_path / "a.xlsx")
    ws = load_workbook(tmp_path / "a.xlsx")["SEMAINE 45"]
    assert [ws.cell(r, 4).value for r in range(4, 9)] == NOMS[:5]
    assert ws["D9"].value == "A-MIDI" and ws["D10"].value == "ALMA"
    suivant = [r for r, v in cellules(ws, 1).items() if v == "MARDI"][0]
    assert suivant == 3 + 2 + 5 + 4 + 1   # en-tête + date/matin(5) + A-MIDI + 4 lignes + vide


def test_compatibilite_skill_perm_creche(tmp_path):
    """Logique de l'étape 3 du skill, avec le seul correctif sur le type de la date."""
    pd = pytest.importorskip("pandas")
    s = faire_sondage()
    paires = [("ALMA", "2026-11-02_M"), ("BRUNO", "2026-11-02_M"), ("ALMA", "2026-11-09_A"),
              ("CLEO", "2026-11-03_A"), ("BRUNO", "2026-11-03_M")]
    p, _ = faire_planning(s, None, paires)
    chemin = tmp_path / "a.xlsx"
    ecrire_xlsx(p, chemin)

    def extract_perms(filepath, child_name):
        xls = pd.ExcelFile(filepath)
        perms = []
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet, header=None)
            current_date, current_section = None, None
            for _, row in df.iterrows():
                if pd.notna(row[0]):
                    val = row[0]
                    if isinstance(val, (pd.Timestamp, datetime.datetime)):
                        current_date = val.date()
                if pd.notna(row[3]):
                    val3 = str(row[3]).strip()
                    if val3 in ("MATIN", "A-MIDI"):
                        current_section = val3
                        continue
                    if val3.upper() == child_name.upper() and current_date:
                        perms.append((current_date, current_section, sheet))
        return perms

    assert extract_perms(chemin, "ALMA") == [
        (date(2026, 11, 2), "MATIN", "SEMAINE 45"), (date(2026, 11, 9), "A-MIDI", "SEMAINE 46")]
    assert extract_perms(chemin, "CLEO") == [(date(2026, 11, 3), "A-MIDI", "SEMAINE 45")]


def test_arbitrage_ajouter_retirer_et_origine():
    s = faire_sondage()
    p, c = faire_planning(s, None, [("ALMA", "2026-11-02_M"), ("BRUNO", "2026-11-02_A")])
    arb = {"empreinte": p["empreinte"], "changements": [
        {"action": "ajouter", "famille": "CLEO", "creneau": "2026-11-02_M"},
        {"action": "retirer", "famille": "ALMA", "creneau": "2026-11-02_M"}]}
    final = appliquer_arbitrages(p, arb, s, c)
    par = {(a["famille"], a["creneau"]): a["origine"] for a in final["affectations"]}
    assert par == {("BRUNO", "2026-11-02_A"): "solveur", ("CLEO", "2026-11-02_M"): "arbitrage"}
    matin = next(x for x in final["creneaux"] if x["id"] == "2026-11-02_M")
    assert matin["familles"] == ["CLEO"]
    assert final["bilan"]["CLEO"]["total"] == 1 and final["bilan"]["ALMA"]["total"] == 0


def test_arbitrage_erreurs():
    s = faire_sondage()
    p, c = faire_planning(s, None, [("ALMA", "2026-11-02_M")])
    base = {"empreinte": p["empreinte"]}
    with pytest.raises(ValueError, match="empreinte"):
        appliquer_arbitrages(p, {"empreinte": "autre", "changements": []}, s, c)
    with pytest.raises(ValueError, match="pas affectée"):
        appliquer_arbitrages(p, {**base, "changements": [
            {"action": "retirer", "famille": "BRUNO", "creneau": "2026-11-02_M"}]}, s, c)
    with pytest.raises(ValueError, match="déjà affectée"):
        appliquer_arbitrages(p, {**base, "changements": [
            {"action": "ajouter", "famille": "ALMA", "creneau": "2026-11-02_M"}]}, s, c)


def test_alerte_d_apres_ajout_hors_dispo():
    s = faire_sondage()
    s["familles"][1]["dispos"]["2026-11-02_M"] = "non"        # BRUNO indisponible
    p, c = faire_planning(s, None, [("ALMA", "2026-11-02_M")])
    arb = {"empreinte": p["empreinte"], "changements": [
        {"action": "ajouter", "famille": "BRUNO", "creneau": "2026-11-02_M"}]}
    final = appliquer_arbitrages(p, arb, s, c)
    d = [a for a in final["alertes"] if a["code"] == "D"]
    assert len(d) == 1 and d[0]["famille"] == "BRUNO"


def test_cli_de_bout_en_bout(tmp_path, capsys):
    yaml_txt = "cible_hebdo: 1\n"
    s = faire_sondage()
    (tmp_path / "sondage.json").write_text(json.dumps(s), encoding="utf-8")
    (tmp_path / "c.yaml").write_text(yaml_txt, encoding="utf-8")
    c = lire_contraintes({"cible_hebdo": 1}, s)
    plan = construire_planning(s, c, temps_max=10)
    (tmp_path / "p.json").write_text(json.dumps(plan), encoding="utf-8")
    base = ["--planning", str(tmp_path / "p.json"), "--out", str(tmp_path / "o.xlsx")]
    assert main(base) == 0
    assert load_workbook(tmp_path / "o.xlsx").sheetnames == ["SEMAINE 45", "SEMAINE 46"]
    # sans sondage ni contraintes : erreur claire, pas de traceback
    (tmp_path / "arb.json").write_text(json.dumps({"empreinte": plan["empreinte"], "changements": []}))
    assert main(base + ["--arbitrages", str(tmp_path / "arb.json")]) == 1
    assert "--sondage" in capsys.readouterr().err
    sortie = ["--sondage", str(tmp_path / "sondage.json"), "--contraintes", str(tmp_path / "c.yaml"),
              "--planning-final", str(tmp_path / "final.json")]
    assert main(base + ["--arbitrages", str(tmp_path / "arb.json")] + sortie) == 0
    final = json.loads((tmp_path / "final.json").read_text(encoding="utf-8"))
    assert set(final) == set(plan)
    # empreinte différente : erreur
    (tmp_path / "arb.json").write_text(json.dumps({"empreinte": "x", "changements": []}))
    assert main(base + ["--arbitrages", str(tmp_path / "arb.json")] + sortie) == 1
    assert "empreinte" in capsys.readouterr().err
