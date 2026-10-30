import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render_arbitrage import (  # noqa: E402
    GABARIT, construire_donnees, generer_page, main,
)
from solve import construire_planning, lire_contraintes  # noqa: E402

LUNDI = date(2026, 11, 2)
INJECTION = "Bonjour </script><img src=x onerror=alert(1)> et <!-- piège -->"


def faire_sondage(commentaire: str = "Absente la semaine du 9/11") -> dict:
    """Sondage synthétique : 2 semaines, lundi et mardi, matin et après-midi, 3 familles."""
    creneaux = []
    for s in range(2):
        lundi = LUNDI + timedelta(weeks=s)
        for j in (0, 1):
            d = lundi + timedelta(days=j)
            for demi in ("M", "A"):
                creneaux.append({"id": f"{d.isoformat()}_{demi}", "date": d.isoformat(),
                                 "demi": demi, "semaine": lundi.isoformat(),
                                 "semaine_iso": d.isocalendar().week})
    ids = [c["id"] for c in creneaux]
    dispos = {nom: {i: "oui" for i in ids} for nom in ("ALMA", "BRUNO", "CLEO")}
    dispos["CLEO"]["2026-11-02_M"] = "non"
    dispos["BRUNO"]["2026-11-03_A"] = "si_besoin"
    return {"poll_id": "test", "titre": "Planning test", "creneaux": creneaux,
            "familles": [{"nom": n, "nom_brut": n, "dispos": d} for n, d in dispos.items()],
            "commentaires": [{"auteur": "ALMA", "date": "2026-10-15T16:20", "texte": commentaire}]}


BRUT = {"familles": {"ALMA": {"absences": ["2026-11-09"]}},
        "commentaires_non_traduits": ["ALMA : à confirmer"]}


def fabriquer(commentaire: str = "Absente la semaine du 9/11"):
    sondage = faire_sondage(commentaire)
    contraintes = lire_contraintes(BRUT, sondage)
    return sondage, contraintes, construire_planning(sondage, contraintes, temps_max=10)


def extraire_json(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="donnees">(.*?)</script>', page, re.S)
    assert m, "balise de données absente"
    return json.loads(m.group(1))


def test_page_generee_et_json_relu():
    sondage, contraintes, planning = fabriquer()
    page = generer_page(planning, sondage, contraintes)
    d = extraire_json(page)
    attendues = {"planning", "dispos", "quota_mois", "absences", "plafond_hebdo",
                 "max_parents_par_creneau", "commentaires", "libelles", "libelles_jours",
                 "libelles_semaines", "titres_semaines"}
    assert attendues <= set(d)
    assert set(d["planning"]) == {"titre", "empreinte", "creneaux", "affectations", "bilan", "alertes"}
    assert d["libelles"]["2026-11-02_M"] == "lundi 2/11 matin"
    assert d["titres_semaines"]["2026-11-09"] == "Semaine du 9 novembre"
    assert d["quota_mois"] == {"ALMA": 1, "BRUNO": 2, "CLEO": 2}
    assert d["commentaires"][0]["auteur"] == "ALMA"
    assert "__DONNEES__" not in page


def test_aucune_ressource_externe():
    sondage, contraintes, planning = fabriquer()
    page = generer_page(planning, sondage, contraintes)
    assert not re.search(r"https?://", page)
    assert "<link" not in page
    assert not re.search(r"\bsrc\s*=", page)
    assert "fetch(" not in page and "@import" not in page


def test_commentaire_malveillant_ne_casse_pas_linjection():
    sondage, contraintes, planning = fabriquer(INJECTION)
    page = generer_page(planning, sondage, contraintes)
    modele = GABARIT.read_text(encoding="utf-8")
    assert page.count("</script>") == modele.count("</script>")
    assert "</script><img" not in page and "<!--" not in page
    assert extraire_json(page)["commentaires"][0]["texte"] == INJECTION


def test_empreinte_differente_refusee():
    sondage, contraintes, planning = fabriquer()
    planning["empreinte"] = "autre"
    with pytest.raises(ValueError, match="empreinte"):
        construire_donnees(planning, sondage, contraintes)


def test_cli(tmp_path, capsys):
    sondage, contraintes, planning = fabriquer()
    (tmp_path / "planning.json").write_text(json.dumps(planning), encoding="utf-8")
    (tmp_path / "sondage.json").write_text(json.dumps(sondage), encoding="utf-8")
    (tmp_path / "c.yaml").write_text(
        'familles:\n  ALMA:\n    absences: ["2026-11-09"]\n'
        'commentaires_non_traduits:\n  - "ALMA : à confirmer"\n', encoding="utf-8")
    args = ["--planning", str(tmp_path / "planning.json"), "--sondage", str(tmp_path / "sondage.json"),
            "--contraintes", str(tmp_path / "c.yaml"), "--out", str(tmp_path / "a.html")]
    assert main(args) == 0
    assert (tmp_path / "a.html").stat().st_size > 5000
    args[1] = str(tmp_path / "absent.json")
    assert main(args) == 1
    assert "Erreur" in capsys.readouterr().err


# ---------------------------------------------------------------- logique JS (node)

JS_TESTS = r"""
const fs = require("fs");
const D = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const base = D.planning.affectations.map((a) => cle(a.famille, a.creneau));
const sortie = {};
const regles = (cles) => calculer(D, cles).alertes.filter((a) => a.code === "D").map((a) => a.regle);

// ajout hors dispo -> alerte D3
const hors = calculer(D, base.concat([cle("CLEO", "2026-11-02_M")])).alertes
  .filter((a) => a.code === "D" && a.regle === "D3" && a.famille === "CLEO");
sortie.horsDispo = hors.length;
sortie.horsDispoRouge = graviteCase(calculer(D, base.concat([cle("CLEO", "2026-11-02_M")])).alertes, "2026-11-02_M");

// retrait qui vide une case -> A1
const premier = D.planning.creneaux.find((c) => base.some((k) => decouper(k).creneau === c.id));
const reste = base.filter((k) => decouper(k).creneau !== premier.id);
sortie.a1Avant = calculer(D, base).alertes.filter((a) => a.code === "A1" && a.creneau === premier.id).length;
sortie.a1Apres = calculer(D, reste).alertes.filter((a) => a.code === "A1" && a.creneau === premier.id).length;

// ajout puis retrait -> 0 changement net ; un seul ajout -> 1
const k = cle("BRUNO", "2026-11-02_A");
const avec = base.includes(k) ? base : base.concat([k]);
sortie.netsVide = changementsNets(base, avec.filter((x) => x !== k || base.includes(k))).length;
sortie.netsUn = changementsNets(base, base.concat([cle("CLEO", "2026-11-03_M")]));
sortie.netsRetrait = changementsNets(base, base.slice(1)).map((c) => c.action);

// D1, D2, D4, A2, A3
sortie.d1 = regles([cle("ALMA", "2026-11-02_M"), cle("ALMA", "2026-11-02_A")]).includes("D1");
sortie.d2 = regles([cle("BRUNO", "2026-11-02_M"), cle("BRUNO", "2026-11-03_M"), cle("BRUNO", "2026-11-02_A")]).includes("D2");
sortie.d4 = regles([cle("ALMA", "2026-11-09_M")]).includes("D4");
sortie.a2 = calculer(D, ["ALMA", "BRUNO", "CLEO"].map((f) => cle(f, "2026-11-03_M"))).alertes.some((a) => a.code === "A2");
sortie.a3 = calculer(D, []).alertes.filter((a) => a.code === "A3").length;

// cohérence avec les alertes Python du planning de départ (A1, A2, A3, A6)
const sig = (al) => al.filter((a) => ["A1", "A2", "A3", "A6", "D"].includes(a.code))
  .map((a) => [a.code, a.creneau || null, a.famille || null].join("/")).sort();
sortie.jsAlertes = sig(calculer(D, base).alertes);
sortie.pyAlertes = sig(D.planning.alertes);
console.log(JSON.stringify(sortie));
"""


def lancer_js(tmp_path):
    """Extrait le bloc CORE du gabarit et l'exécute avec node. Renvoie le dict de sortie."""
    modele = GABARIT.read_text(encoding="utf-8")
    m = re.search(r"/\* CORE:BEGIN \*/(.*?)/\* CORE:END \*/", modele, re.S)
    assert m, "bloc CORE introuvable"
    sondage, contraintes, planning = fabriquer()
    (tmp_path / "donnees.json").write_text(
        json.dumps(construire_donnees(planning, sondage, contraintes)), encoding="utf-8")
    (tmp_path / "test.js").write_text(m.group(1) + JS_TESTS, encoding="utf-8")
    r = subprocess.run(["node", str(tmp_path / "test.js"), str(tmp_path / "donnees.json")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent : logique JS non testée")
def test_logique_js(tmp_path):
    s = lancer_js(tmp_path)
    assert s["horsDispo"] == 1 and s["horsDispoRouge"] == "rouge"
    assert s["a1Avant"] == 0 and s["a1Apres"] == 1
    assert s["netsVide"] == 0
    assert s["netsUn"] == [{"action": "ajouter", "famille": "CLEO", "creneau": "2026-11-03_M"}]
    assert s["netsRetrait"] == ["retirer"]
    assert s["d1"] and s["d2"] and s["d4"] and s["a2"]
    assert s["a3"] == 3
    assert s["jsAlertes"] == s["pyAlertes"]


def test_texte_apres_export_par_defaut_et_personnalise():
    sondage, contraintes, planning = fabriquer()
    assert construire_donnees(planning, sondage, contraintes)["apres_export"] ==         "Revenez dans le chat pour la suite."
    page = generer_page(planning, sondage, contraintes, apres_export="L'application continue.")
    assert extraire_json(page)["apres_export"] == "L'application continue."
    gabarit = GABARIT.read_text(encoding="utf-8")
    assert "D.apres_export" in gabarit and "Claude n'a pas pu" not in gabarit
