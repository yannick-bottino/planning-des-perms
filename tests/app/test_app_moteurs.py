"""Moteurs d'IA : consigne, validation, nouvel essai, sauvetage, mode manuel (critères 5 et 9)."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from outils_app import FIXTURES, REPONSE_IA

import fetch_framadate
import moteurs

ICI = Path(__file__).resolve().parent


@pytest.fixture
def sondage():
    return fetch_framadate.construire("Test1", (FIXTURES / "poll.csv").read_text(encoding="utf-8"),
                                      (FIXTURES / "poll.html").read_text(encoding="utf-8"))


class FauxMoteur:
    nom = "deepseek"

    def __init__(self, reponses):
        self.reponses, self.appels = list(reponses), []

    def appeler(self, messages):
        self.appels.append([dict(m) for m in messages])
        r = self.reponses[min(len(self.appels), len(self.reponses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r


# ---------------------------------------------------------------- consigne

def test_consigne_reprend_les_references_v1():
    texte = moteurs.consigne_systeme()
    regles = (moteurs.REFERENCES / "regles-affectation.md").read_text(encoding="utf-8")
    assert moteurs.section(regles, "Traduire un commentaire en règle") in texte
    assert "quota_mois" in texte and "commentaires_non_traduits" in texte and "JSON" in texte


def test_donnees_sondage_listent_familles_lundis_creneaux(sondage):
    d = json.loads(moteurs.donnees_sondage(sondage))
    assert d["familles"] == ["BASILE", "ELOISE", "LEA", "ZOE"]
    assert d["semaines_lundis"] == ["2026-11-02", "2026-11-09"]
    assert "2026-11-02_M" in d["creneaux"]
    assert d["familles_sans_aucune_dispo_ces_semaines"]["ELOISE"] == ["2026-11-09"]
    assert len(d["commentaires"]) == 3


def test_section_absente():
    with pytest.raises(ValueError):
        moteurs.section("## A\ntexte", "B")


@pytest.mark.parametrize("texte", [
    json.dumps(REPONSE_IA),
    "Voici :\n```json\n" + json.dumps(REPONSE_IA) + "\n```\nBonne journée",
])
def test_extraire_json(texte):
    assert moteurs.extraire_json(texte) == REPONSE_IA


@pytest.mark.parametrize("texte", ["pas de json", "[1, 2]", "{ cassé"])
def test_extraire_json_refuse(texte):
    with pytest.raises(ValueError):
        moteurs.extraire_json(texte)


# ---------------------------------------------------------------- proposer

def test_reponse_valable_du_premier_coup(sondage):
    m = FauxMoteur([json.dumps(REPONSE_IA)])
    r = moteurs.proposer(m, sondage)
    assert (r["manuel"], r["essais"], r["brut"]) == (False, 1, REPONSE_IA)
    assert m.appels[0][0]["role"] == "system"


def test_nouvel_essai_avec_le_message_d_erreur(sondage):
    faux = {"familles": {"INCONNUE": {"quota_mois": 1}}}
    m = FauxMoteur([json.dumps(faux), json.dumps(REPONSE_IA)])
    r = moteurs.proposer(m, sondage)
    assert (r["manuel"], r["essais"]) == (False, 2)
    second = m.appels[1]
    assert second[-2] == {"role": "assistant", "content": json.dumps(faux)}
    assert "INCONNUE" in second[-1]["content"] and "absente du sondage" in second[-1]["content"]


def test_deux_echecs_gardent_les_familles_valables(sondage):
    mixte = {"familles": {"LEA": REPONSE_IA["familles"]["LEA"],
                          "INCONNUE": {"quota_mois": 1, "source": "Inconnue : une seule perm"},
                          "ZOE": {"absences": ["2026-12-25"], "source": "zoé : Noël"}},
             "commentaires_non_traduits": ["déjà là"], "plafond_hebdo": -1}
    m = FauxMoteur([json.dumps(mixte)])
    r = moteurs.proposer(m, sondage)
    assert not r["manuel"] and r["essais"] == 2 and "en partie" in r["message"]
    assert list(r["brut"]["familles"]) == ["LEA"]
    assert "plafond_hebdo" not in r["brut"]
    nt = r["brut"]["commentaires_non_traduits"]
    assert nt[0] == "déjà là"
    assert any(t.startswith("INCONNUE : Inconnue : une seule perm") for t in nt)
    assert any(t.startswith("ZOE : zoé : Noël") and "semaine d'absence inconnue" in t for t in nt)


def test_deux_reponses_illisibles_donnent_le_mode_manuel(sondage):
    m = FauxMoteur(["Je ne sais pas."])
    r = moteurs.proposer(m, sondage)
    assert r["manuel"] and r["brut"] == {} and r["essais"] == 2
    assert "à la main" in r["message"]


def test_moteur_injoignable_donne_le_mode_manuel_sans_nouvel_essai(sondage):
    m = FauxMoteur([moteurs.ErreurMoteur("DeepSeek est injoignable.")])
    r = moteurs.proposer(m, sondage)
    assert r["manuel"] and len(m.appels) == 1 and r["message"].startswith("DeepSeek est injoignable.")


def test_types_invalides_dans_la_reponse(sondage):
    m = FauxMoteur([json.dumps({"familles": [], "commentaires_non_traduits": "texte"})])
    r = moteurs.proposer(m, sondage)
    assert r["manuel"] or r["brut"] == {}


# ---------------------------------------------------------------- DeepSeek

def test_deepseek_envoie_cle_modele_et_format(sondage, deepseek):
    r = moteurs.proposer(moteurs.MoteurDeepSeek("sk-abc"), sondage)
    assert not r["manuel"]
    req = deepseek.requetes[0]
    assert req["auth"] == "Bearer sk-abc"
    assert req["corps"]["model"] == "deepseek-chat"
    assert req["corps"]["response_format"] == {"type": "json_object"}
    assert req["corps"]["temperature"] == 0 and req["corps"]["max_tokens"] == moteurs.MAX_JETONS


@pytest.mark.parametrize("code,attendu", [(401, "refusée"), (402, "crédit"), (429, "saturé"), (500, "500")])
def test_deepseek_erreurs_http_traduites_sans_corps(sondage, deepseek, code, attendu):
    deepseek.reponses = [code]
    r = moteurs.proposer(moteurs.MoteurDeepSeek("sk-secret-42"), sondage)
    assert r["manuel"] and attendu in r["message"] and "sk-secret-42" not in r["message"]


def test_deepseek_sans_cle(sondage):
    r = moteurs.proposer(moteurs.MoteurDeepSeek(""), sondage)
    assert r["manuel"] and "Aucune clé" in r["message"]


def test_deepseek_injoignable(sondage, monkeypatch):
    monkeypatch.setenv("PLANNING_PERMS_DEEPSEEK_URL", "http://127.0.0.1:9/chat/completions")
    r = moteurs.proposer(moteurs.MoteurDeepSeek("sk-x"), sondage)
    assert r["manuel"] and "injoignable" in r["message"]


# ---------------------------------------------------------------- Claude Code (faux exécutable)

@pytest.fixture
def faux_claude(tmp_path, monkeypatch):
    """Faux `claude` : un .cmd sous Windows (comme une installation npm), un script sh ailleurs."""
    if sys.platform == "win32":
        exe = tmp_path / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{ICI / "faux_claude.py"}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "claude"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{ICI / "faux_claude.py"}" "$@"\n')
        exe.chmod(0o755)
    journal, reponses = tmp_path / "journal.jsonl", tmp_path / "reponses.json"
    monkeypatch.setenv("PLANNING_PERMS_CLAUDE", str(exe))
    monkeypatch.setenv("FAUX_CLAUDE_JOURNAL", str(journal))
    monkeypatch.setenv("FAUX_CLAUDE_REPONSES", str(reponses))

    def regler(liste):
        reponses.write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")

    def appels():
        return [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else []
    return regler, appels


def test_claude_reponse_valable(sondage, faux_claude, tmp_path):
    regler, appels = faux_claude
    regler([json.dumps(REPONSE_IA, ensure_ascii=False)])
    r = moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)
    assert not r["manuel"] and r["brut"] == REPONSE_IA
    (appel,) = appels()
    assert appel["args"][:3] == ["-p", "--output-format", "json"]
    assert "--tools" in appel["args"] and "--strict-mcp-config" in appel["args"]
    # Accents transmis intacts dans les deux sens (UTF-8 sur stdin et stdout).
    assert "Nous serons en congés la semaine du 9 novembre" in appel["consigne"]


def test_claude_nouvel_essai_rejoue_la_conversation(sondage, faux_claude, tmp_path):
    regler, appels = faux_claude
    regler(["pas du json", json.dumps(REPONSE_IA)])
    r = moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)
    assert r["essais"] == 2 and not r["manuel"]
    second = appels()[1]["consigne"]
    assert "Ta réponse précédente :\npas du json" in second and "refusée par le programme" in second


def test_claude_en_erreur(sondage, faux_claude, tmp_path):
    regler, _ = faux_claude
    regler(["ERREUR"])
    r = moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)
    assert r["manuel"] and "connecté" in r["message"]


def test_claude_trop_lent_est_arrete(sondage, faux_claude, tmp_path, monkeypatch):
    regler, _ = faux_claude
    regler(["LENT"])
    monkeypatch.setattr(moteurs, "DELAI_CLAUDE_S", 3)
    debut = time.monotonic()
    r = moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)
    assert r["manuel"] and "à temps" in r["message"]
    assert time.monotonic() - debut < 30


def test_claude_absent(sondage, monkeypatch, tmp_path):
    monkeypatch.setattr(moteurs, "commande_claude", lambda: None)
    r = moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)
    assert r["manuel"] and "pas installé" in r["message"]


# ---------------------------------------------------------------- Codex / ChatGPT (faux exécutable)

@pytest.fixture
def faux_codex(poste, tmp_path, monkeypatch):
    """Faux `codex exec` installé ; `regler` fixe ses réponses, `appels` relit son journal."""
    poste.installer("codex")
    journal, reponses = tmp_path / "journal-codex.jsonl", tmp_path / "reponses-codex.json"
    monkeypatch.setenv("FAUX_CODEX_JOURNAL", str(journal))
    monkeypatch.setenv("FAUX_CODEX_REPONSES", str(reponses))

    def regler(liste):
        reponses.write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")

    def appels():
        return [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else []
    return regler, appels


def test_codex_reponse_lue_dans_le_fichier_de_sortie(sondage, faux_codex, tmp_path):
    regler, appels = faux_codex
    regler([json.dumps(REPONSE_IA, ensure_ascii=False)])
    dossier = tmp_path / "mois"
    dossier.mkdir()
    r = moteurs.proposer(moteurs.MoteurCodex(dossier), sondage)
    # La réponse vient du fichier -o, pas de la sortie standard (qui contient du bruit de progression).
    assert not r["manuel"] and r["brut"] == REPONSE_IA
    assert r["message"].startswith("Règles proposées par ChatGPT.")
    (appel,) = appels()
    args = appel["args"]
    assert args[:2] == ["exec", "-"]
    for drapeau in ("--skip-git-repo-check", "--ephemeral", "--ignore-user-config"):
        assert drapeau in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--color") + 1] == "never"
    assert args[args.index("-o") + 1].endswith("reponse.txt")
    # Consigne lue sur l'entrée standard, accents intacts, dossier courant = dossier du mois.
    assert "Nous serons en congés la semaine du 9 novembre" in appel["consigne"]
    # Dossier de travail : un dossier jetable vide, jamais le dossier du mois.
    assert args[args.index("-C") + 1] == appel["cwd"]
    assert Path(appel["cwd"]).resolve() != dossier.resolve() and Path(appel["cwd"]).name == "travail"
    assert not Path(appel["cwd"]).exists()  # supprimé après l'appel


def test_codex_nouvel_essai_rejoue_la_conversation(sondage, faux_codex, tmp_path):
    regler, appels = faux_codex
    regler(["pas du json", json.dumps(REPONSE_IA)])
    r = moteurs.proposer(moteurs.MoteurCodex(tmp_path), sondage)
    assert r["essais"] == 2 and not r["manuel"]
    assert "Ta réponse précédente :\npas du json" in appels()[1]["consigne"]


def test_codex_en_erreur(sondage, faux_codex, tmp_path):
    regler, _ = faux_codex
    regler(["ERREUR"])
    r = moteurs.proposer(moteurs.MoteurCodex(tmp_path), sondage)
    assert r["manuel"] and "connecté" in r["message"]


def test_codex_trop_lent_est_arrete(sondage, faux_codex, tmp_path, monkeypatch):
    regler, _ = faux_codex
    regler(["LENT"])
    monkeypatch.setattr(moteurs, "DELAI_CODEX_S", 3)
    debut = time.monotonic()
    r = moteurs.proposer(moteurs.MoteurCodex(tmp_path), sondage)
    assert r["manuel"] and "à temps" in r["message"]
    assert time.monotonic() - debut < 30


def test_codex_absent(sondage, monkeypatch, tmp_path):
    monkeypatch.setattr(moteurs, "commande_codex", lambda: None)
    r = moteurs.proposer(moteurs.MoteurCodex(tmp_path), sondage)
    assert r["manuel"] and "pas installé" in r["message"]


# ---------------------------------------------------------------- moteurs réels

@pytest.mark.reel
@pytest.mark.skipif(not shutil.which("claude"), reason="Claude Code absent")
def test_reel_claude_code(sondage, tmp_path, monkeypatch):
    monkeypatch.delenv("PLANNING_PERMS_CLAUDE", raising=False)
    r = moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)
    assert not r["manuel"], r["message"]
    familles = r["brut"].get("familles") or {}
    # ZOE annonce une absence la semaine du 9 novembre : la règle attendue.
    assert "2026-11-09" in (familles.get("ZOE") or {}).get("absences", []), r["brut"]


@pytest.mark.reel
@pytest.mark.skipif(not os.environ.get("DEEPSEEK_API_KEY"), reason="DEEPSEEK_API_KEY absente")
def test_reel_deepseek(sondage, monkeypatch):
    monkeypatch.delenv("PLANNING_PERMS_DEEPSEEK_URL", raising=False)
    r = moteurs.proposer(moteurs.MoteurDeepSeek(os.environ["DEEPSEEK_API_KEY"]), sondage)
    assert not r["manuel"], r["message"]
    assert "2026-11-09" in ((r["brut"].get("familles") or {}).get("ZOE") or {}).get("absences", []), r["brut"]


def test_reglages_generaux_jamais_pris_de_l_ia(sondage):
    reponse = dict(REPONSE_IA, max_parents_par_creneau=3, plafond_hebdo=3)
    r = moteurs.proposer(FauxMoteur([json.dumps(reponse)]), sondage)
    assert not r["manuel"] and r["essais"] == 1
    assert "max_parents_par_creneau" not in r["brut"] and "plafond_hebdo" not in r["brut"]
    nt = r["brut"]["commentaires_non_traduits"]
    assert "Réglage général proposé par l'IA, non appliqué : max_parents_par_creneau = 3" in nt
    assert REPONSE_IA["commentaires_non_traduits"][0] in nt


def test_absence_citee_deux_fois_acceptee(sondage):
    reponse = {"familles": {"ZOE": {"absences": ["2026-11-09", "2026-11-09"], "source": "zoé"}}}
    r = moteurs.proposer(FauxMoteur([json.dumps(reponse)]), sondage)
    assert r["essais"] == 1 and r["brut"]["familles"]["ZOE"]["absences"] == ["2026-11-09", "2026-11-09"]


def test_arret_de_l_outil_tue_l_ia_en_cours(sondage, faux_claude, tmp_path):
    """« Fermer l'outil » pendant un appel à l'IA : le processus est arrêté, l'appel se termine vite."""
    import threading
    regler, appels = faux_claude
    regler(["LENT"])
    resultat = {}
    fil = threading.Thread(target=lambda: resultat.update(r=moteurs.proposer(moteurs.MoteurClaude(tmp_path), sondage)))
    fil.start()
    fin = time.monotonic() + 20
    while time.monotonic() < fin and not (appels() and moteurs.EN_COURS):
        time.sleep(0.1)
    processus = next(iter(moteurs.EN_COURS))
    debut = time.monotonic()
    moteurs.tuer_moteurs()
    fil.join(timeout=20)
    assert not fil.is_alive() and time.monotonic() - debut < 20
    assert processus.poll() is not None and not moteurs.EN_COURS
    assert resultat["r"]["manuel"]
