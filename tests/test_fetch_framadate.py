import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))
import fetch_framadate as ff  # noqa: E402


def charger():
    csv_txt = (FIX / "poll.csv").read_bytes().decode("utf-8")
    html_txt = (FIX / "poll.html").read_bytes().decode("utf-8")
    return ff.construire("abc123", csv_txt, html_txt)


def test_parsing_fixture():
    d = charger()
    assert d["poll_id"] == "abc123"
    assert d["titre"] == "Planning Test"
    assert len(d["creneaux"]) == 10
    assert [f["nom"] for f in d["familles"]] == ["LEA", "ZOE", "BASILE", "ELOISE"]
    assert d["familles"][1]["nom_brut"] == "Zoé"
    c0 = d["creneaux"][0]
    assert c0 == {"id": "2026-11-02_M", "date": "2026-11-02", "demi": "M",
                  "semaine": "2026-11-02", "semaine_iso": 45}
    assert {c["semaine"] for c in d["creneaux"]} == {"2026-11-02", "2026-11-09"}
    assert all(c["date"] != "2026-11-11" for c in d["creneaux"])


def test_ligne_courte_et_vide():
    d = charger()
    eloise = next(f for f in d["familles"] if f["nom"] == "ELOISE")
    assert len(eloise["dispos"]) == 10
    assert eloise["dispos"]["2026-11-02_M"] == "oui"
    assert eloise["dispos"]["2026-11-03_M"] == "vide"
    assert eloise["dispos"]["2026-11-10_A"] == "vide"
    assert len(d["familles"]) == 4  # la ligne vide est ignorée


def test_commentaires():
    d = charger()
    assert len(d["commentaires"]) == 3
    c = d["commentaires"][1]
    assert c["auteur"] == "ZOE" and c["auteur_brut"] == "zoé"
    assert c["date"] == "2026-10-15T16:20"
    assert c["texte"].startswith("Bonjour !\nNous serons en congés")
    multi = d["commentaires"][2]["texte"]
    assert multi.splitlines()[0] == "Salut" and "\n" in multi
    assert d["commentaires"][0]["date"] == "2026-10-11T10:43"


def test_avertissement_auteur_absent():
    d = charger()
    assert any("INCONNU" in w for w in d["avertissements"])


def test_avertissement_doublon():
    csv_txt = ",2026-11-02\n,Matin\nNoé,Yes\nnoe,No\n"
    av: list[str] = []
    ff.parser_csv(csv_txt, av)
    assert any("NOE" in w for w in av)


def test_doublon_fusionne_en_une_famille():
    csv_txt = (",2026-11-02,2026-11-02,2026-11-03\n,Matin,Apres-midi,Matin\n"
               "Noé,Yes,No,\nnoe,No,If need be,Yes\n")
    av: list[str] = []
    _, familles = ff.parser_csv(csv_txt, av)
    assert len(familles) == 1
    noe = familles[0]
    assert noe["nom"] == "NOE" and noe["noms_bruts"] == ["Noé", "noe"]
    assert noe["dispos"] == {"2026-11-02_M": "oui", "2026-11-02_A": "si_besoin",
                             "2026-11-03_M": "oui"}
    assert any("Noé / noe" in w for w in av)


def test_avertissement_zero_commentaire():
    av: list[str] = []
    _, coms = ff.parser_html("<title>Sondage – Framadate</title><p>Comments</p>", av)
    assert coms == [] and any("Aucun commentaire" in w for w in av)


def test_date_illisible_non_bloquante():
    html = ('<article id="comment-1"><header><span>A</span><time>bientot</time></header>'
            '<div><p>x</p></div></article>')
    av: list[str] = []
    _, coms = ff.parser_html(html, av)
    assert coms[0]["date"] == "bientot" and av


def test_dispo_inconnue_csv():
    with pytest.raises(ValueError, match="Peut-etre"):
        ff.parser_csv(",2026-11-02\n,Matin\nNoé,Peut-etre\n", [])


def test_demi_inconnu_csv():
    with pytest.raises(ValueError, match="Soir"):
        ff.parser_csv(",2026-11-02\n,Soir\nNoé,Yes\n", [])


def test_csv_vide():
    with pytest.raises(ValueError):
        ff.parser_csv("", [])


@pytest.mark.parametrize("entree", [
    "https://framadate.org/polls/a1b2c3d4e5f6a7b8c9d0",
    "https://framadate.org/polls/a1b2c3d4e5f6a7b8c9d0.csv",
    "a1b2c3d4e5f6a7b8c9d0",
])
def test_extraire_poll_id(entree):
    assert ff.extraire_poll_id(entree) == "a1b2c3d4e5f6a7b8c9d0"


def test_extraire_poll_id_invalide():
    with pytest.raises(ValueError):
        ff.extraire_poll_id("pas un id !")


def test_cli_hors_ligne(tmp_path):
    out = tmp_path / "sondage.json"
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPTS / "fetch_framadate.py"),
         "--csv", str(FIX / "poll.csv"), "--html", str(FIX / "poll.html"),
         "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_bytes().decode("utf-8"))
    assert data["familles"][3]["nom_brut"] == "éloïse"
    assert "congés" in out.read_bytes().decode("utf-8")  # pas d'échappement ASCII


def test_cli_erreur(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_bytes(",2026-11-02\n,Matin\nNoé,Bof\n".encode("utf-8"))
    code = ff.main(["--csv", str(bad), "--html", str(FIX / "poll.html"),
                    "--out", str(tmp_path / "x.json")])
    assert code == 1
    assert "Bof" in capsys.readouterr().err
