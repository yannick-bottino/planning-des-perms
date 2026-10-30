"""Assistants (Claude, ChatGPT) : détection, état de connexion, installation, connexion (spec V3, critère 2).

Tous les programmes sont de faux exécutables (faux_assistants.py) : ni vrai installeur, ni vraie connexion.
"""
import json
import os
import sys
import time

import pytest

import assistants


def attendre(assistant, statut, delai=30):
    """Attend que le travail de l'assistant atteigne `statut`. Renvoie son état public."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        travail = assistants.etat_travail(assistant)
        if travail and travail["statut"] == statut:
            return travail
        time.sleep(0.1)
    pytest.fail(f"{assistant} : statut {statut!r} non atteint, dernier état {assistants.etat_travail(assistant)}")


def attendre_champ(assistant, champ, delai=20):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        travail = assistants.etat_travail(assistant)
        if travail and travail[champ]:
            return travail
        time.sleep(0.1)
    pytest.fail(f"{assistant} : champ {champ!r} jamais renseigné")


# ---------------------------------------------------------------- détection (V3-7)

def test_variable_d_environnement_impose_l_executable(poste):
    assert assistants.commande("claude") is None
    poste.installer("claude")
    assert assistants.commande("claude") == str(poste.exe["claude"])


def test_variable_renseignee_mais_absente_n_ouvre_pas_le_path(poste, monkeypatch):
    monkeypatch.setattr(assistants.shutil, "which", lambda nom: "C:/ailleurs/" + nom)
    assert assistants.commande("codex") is None


def test_chemin_et_emplacements_connus(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANNING_PERMS_CLAUDE", raising=False)
    monkeypatch.delenv("PLANNING_PERMS_CODEX", raising=False)
    monkeypatch.setattr(assistants.shutil, "which", lambda nom: None)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert assistants.commande("claude") is None and assistants.commande("codex") is None
    # Claude : %USERPROFILE%\.local\bin
    claude = assistants.chemins_connus("claude")[0]
    claude.parent.mkdir(parents=True)
    claude.write_bytes(b"")
    assert assistants.commande("claude") == str(claude)
    # Codex : dossier de l'installeur officiel, nom exact seulement (liste fermée : pas de codex*.exe)
    dossier = tmp_path / "local" / "Programs" / "OpenAI" / "Codex" / "bin"
    dossier.mkdir(parents=True)
    (dossier / "codex-cli.exe").write_bytes(b"")
    assert assistants.commande("codex") is None
    (dossier / "codex.exe").write_bytes(b"")
    assert assistants.commande("codex") == str(dossier / "codex.exe")
    # Le PATH passe avant les emplacements connus.
    monkeypatch.setattr(assistants.shutil, "which", lambda nom: "C:/path/" + nom)
    assert assistants.commande("claude") == "C:/path/claude"


def test_path_rafraichi_apres_installation(tmp_path, monkeypatch):
    """Le PATH du processus ne bouge pas après l'installation : l'emplacement connu suffit."""
    monkeypatch.delenv("PLANNING_PERMS_CLAUDE", raising=False)
    monkeypatch.setattr(assistants.shutil, "which", lambda nom: None)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    exe = tmp_path / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert assistants.commande("claude") == str(exe)


# ---------------------------------------------------------------- état de connexion (V3-7, V3-11)

def test_claude_non_connecte(poste):
    poste.installer("claude")
    assert assistants.etat_connexion("claude") == {"connecte": False, "abonnement": None}


def test_claude_connecte_ne_garde_que_l_abonnement(poste):
    poste.installer("claude")
    poste.connecter("claude", "team")
    etat = assistants.etat_connexion("claude")
    assert etat == {"connecte": True, "abonnement": "team"}
    assert "exemple.invalid" not in json.dumps(etat)


def test_abonnement_gratuit_refuse(poste):
    poste.installer("claude")
    poste.connecter("claude", "free")
    etat = assistants.etat_connexion("claude")
    assert etat["connecte"] and not assistants.abonnement_ok("claude", etat["abonnement"])
    assert assistants.abonnement_ok("claude", "pro") and assistants.abonnement_ok("claude", "enterprise")
    assert assistants.abonnement_ok("claude", None) and assistants.abonnement_ok("codex", None)
    assert "Pro, Max, Team ou Enterprise" in assistants.message_gratuit("claude")


def test_codex_connecte_selon_le_code_de_sortie(poste):
    poste.installer("codex")
    assert assistants.etat_connexion("codex") == {"connecte": False, "abonnement": None}
    poste.connecter("codex", "")
    assert assistants.etat_connexion("codex") == {"connecte": True, "abonnement": None}


def test_assistant_absent_n_est_pas_connecte(poste):
    assert assistants.etat_connexion("claude")["connecte"] is False
    etat = assistants.etat_assistants()
    assert etat["claude"] == {"nom": "Claude", "installe": False, "connecte": None, "abonnement_ok": None, "travail": None}
    assert etat["codex"]["nom"] == "ChatGPT"


def test_etat_public_sans_courriel_ni_organisation(poste):
    poste.installer("claude")
    poste.connecter("claude", "team")
    texte = json.dumps(assistants.etat_assistants())
    assert "exemple.invalid" not in texte and "Creche Fictive" not in texte
    assert json.loads(texte)["claude"] == {"nom": "Claude", "installe": True, "connecte": True,
                                           "abonnement_ok": True, "travail": None}


def test_etat_rapide_n_interroge_pas_la_connexion(poste):
    poste.installer("claude")
    poste.connecter("claude")
    assert assistants.etat_assistants(rapide=True)["claude"]["connecte"] is None


# ---------------------------------------------------------------- texte venant d'un programme (V3-12)

@pytest.mark.parametrize("lien", [
    "https://claude.com/cai/oauth/authorize?code=true&state=abc",
    "https://claude.ai/login",
    "https://console.anthropic.com/x",
    "https://auth.openai.com/oauth/authorize?client_id=x",
    "https://chatgpt.com/auth/device",
    "https://help.openai.com:443/fr",
])
def test_liens_autorises(lien):
    assert assistants.lien_autorise(lien)


@pytest.mark.parametrize("lien", [
    "http://claude.com/clair",
    "https://evil.example/claude.com",
    "https://claude.com.evil.example/",
    "https://notclaude.com/",
    "https://claude.com@evil.example/",
    "https://user:mdp@claude.com/",
    "https://claude.com:8443/",
    "https://evil.com\\.claude.ai/x",
    "https://evil.com%2F.claude.ai/x",
    "https://claude.ai%40evil.example/",
    "javascript:alert(1)",
    "ftp://claude.com/",
    "https://claude.com/avec espace",
    "https://claude.com/\nretour",
    "",
])
def test_liens_refuses(lien):
    assert not assistants.lien_autorise(lien)


def test_liens_extraits_d_une_ligne():
    ligne = "visit: https://claude.com/cai/oauth/authorize?x=1, ou https://evil.example/z et http://claude.com/"
    assert assistants.liens_autorises(ligne) == ["https://claude.com/cai/oauth/authorize?x=1"]


def test_codes_ansi_et_controles_retires():
    brut = "\x1b[1m\x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\x1b]8;;http://x\x07 \x07\x00fin"
    assert assistants.nettoyer(brut) == "https://auth.openai.com/codex/device fin"
    assert assistants.nettoyer("   \x1b[94mPVRM-K4VLO\x1b[0m\r\n") == "PVRM-K4VLO"


# ---------------------------------------------------------------- installation (V3-8)

def test_installation_en_tache_de_fond(poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "1")
    debut = time.monotonic()
    travail = assistants.installer("claude")
    assert time.monotonic() - debut < 1 and travail["statut"] == "en_cours" and travail["type"] == "installation"
    assert assistants.travail_en_cours("claude") and not assistants.travail_en_cours("codex")
    fin = attendre("claude", "termine")
    assert fin["message"] == "Installation terminée."
    assert assistants.commande("claude") == str(poste.exe["claude"])
    assert not assistants.travail_en_cours()


def test_un_seul_travail_a_la_fois_par_assistant(poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "20")
    assistants.installer("claude")
    with pytest.raises(assistants.ErreurAssistant) as e:
        assistants.installer("claude")
    assert e.value.conflit
    assistants.installer("codex")  # l'autre assistant n'est pas bloqué
    assistants.tout_annuler()


def test_installation_deja_faite_refusee(poste):
    poste.installer("claude")
    with pytest.raises(assistants.ErreurAssistant, match="déjà installé"):
        assistants.installer("claude")


def test_installation_en_echec(poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_ECHEC", "1")
    assistants.installer("codex")
    fin = attendre("codex", "echec")
    assert "n'a pas abouti" in fin["message"] and "Download failed" not in fin["message"]


def test_installation_qui_ne_cree_pas_le_programme_est_un_echec(poste, monkeypatch):
    monkeypatch.setenv("PLANNING_PERMS_INSTALLEUR_CLAUDE", json.dumps([sys.executable, "-c", "pass"]))
    assistants.installer("claude")
    assert "n'a pas abouti" in attendre("claude", "echec")["message"]


def test_installation_annulee_arrete_le_processus(poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "60")
    assistants.installer("claude")
    processus = assistants.TRAVAUX["claude"].processus
    assert processus.poll() is None
    assert assistants.annuler("claude")["statut"] == "annule"
    assert processus.poll() is not None
    assert not assistants.travail_en_cours()


def test_installation_trop_longue_est_arretee(poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "60")
    monkeypatch.setattr(assistants, "DELAI_INSTALLATION_S", 1)
    assistants.installer("claude")
    fin = attendre("claude", "echec")
    assert "délai" in fin["message"].lower()
    assert assistants.TRAVAUX["claude"].processus.poll() is not None


def test_commande_d_installation_imposee_illisible(poste, monkeypatch):
    monkeypatch.setenv("PLANNING_PERMS_INSTALLEUR_CLAUDE", "pas du json")
    with pytest.raises(assistants.ErreurAssistant, match="illisible"):
        assistants.installer("claude")


@pytest.mark.skipif(sys.platform != "win32", reason="installation PowerShell : Windows seulement")
def test_installation_officielle_lancee_cachee(monkeypatch, tmp_path):
    """Sans commande imposée : PowerShell caché, script officiel, pas de droits admin (rien n'est lancé ici)."""
    monkeypatch.delenv("PLANNING_PERMS_INSTALLEUR_CLAUDE", raising=False)
    monkeypatch.delenv("PLANNING_PERMS_INSTALLEUR_CODEX", raising=False)
    args = assistants.commande_installation("claude")
    # Chemin absolu de System32 : pas de powershell.exe trouvé par hasard dans le PATH.
    assert args[0].lower().endswith(r"system32\windowspowershell\v1.0\powershell.exe") and os.path.isabs(args[0])
    assert args[1:6] == ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"]
    assert args[6] == "irm https://claude.ai/install.ps1 | iex"
    assert assistants.commande_installation("codex")[6] == "irm https://chatgpt.com/codex/install.ps1 | iex"
    assert assistants.SANS_FENETRE == 0x08000000


# ---------------------------------------------------------------- connexion (V3-9, V3-10)

def test_connexion_claude_lien_filtre_et_code_transmis(poste):
    poste.installer("claude")
    assistants.connecter("claude")
    travail = attendre_champ("claude", "lien")
    assert travail["statut"] == "en_cours" and travail["type"] == "connexion"
    # Le premier lien autorisé est gardé ; l'autre site et le lien non sécurisé sont ignorés.
    assert travail["lien"] == "https://claude.com/cai/oauth/authorize?code=true&state=abc"
    assistants.envoyer_code("claude", "  abc-123  ")
    fin = attendre("claude", "termine")
    assert fin["message"] == "Connexion réussie." and poste.code_recu() == "abc-123"
    assert assistants.etat_connexion("claude")["connecte"]


def test_connexion_claude_abonnement_gratuit(poste, monkeypatch):
    monkeypatch.setenv("FAUX_ABONNEMENT", "free")
    poste.installer("claude")
    assistants.connecter("claude")
    attendre_champ("claude", "lien")
    assistants.envoyer_code("claude", "x")
    fin = attendre("claude", "echec")
    assert "gratuit" in fin["message"] and "Pro, Max, Team ou Enterprise" in fin["message"]


def test_connexion_claude_qui_echoue(poste, monkeypatch):
    monkeypatch.setenv("FAUX_LOGIN_ECHEC", "1")
    monkeypatch.setenv("FAUX_LOGIN_DELAI", "0.2")
    poste.installer("claude")
    assistants.connecter("claude")
    assert "n'a pas abouti" in attendre("claude", "echec")["message"]


def test_connexion_codex_navigateur(poste, monkeypatch):
    monkeypatch.setenv("FAUX_LOGIN_DELAI", "1")
    poste.installer("codex")
    assistants.connecter("codex", "navigateur")
    travail = attendre_champ("codex", "lien")
    # Le lien arrive après une ligne vide, et « http://localhost:1455 » n'est pas retenu.
    assert travail["lien"] == "https://auth.openai.com/oauth/authorize?client_id=x&state=y"
    assert travail["code"] is None
    attendre("codex", "termine")
    assert assistants.etat_connexion("codex")["connecte"]


def test_connexion_codex_code_a_usage_unique(poste, monkeypatch):
    monkeypatch.setenv("FAUX_LOGIN_DELAI", "3")
    poste.installer("codex")
    assistants.connecter("codex", "code")
    travail = attendre_champ("codex", "code")
    assert travail["code"] == "PVRM-K4VLO"
    assert travail["lien"] == "https://auth.openai.com/codex/device"
    assert travail["methode"] == "code"
    attendre("codex", "termine")


def test_connexion_exige_l_assistant_installe(poste):
    with pytest.raises(assistants.ErreurAssistant, match="pas installé"):
        assistants.connecter("claude")


def test_connexion_methode_ou_assistant_inconnus(poste):
    poste.installer("claude")
    with pytest.raises(assistants.ErreurAssistant, match="Méthode"):
        assistants.connecter("claude", "telepathie")
    with pytest.raises(assistants.ErreurAssistant, match="inconnu"):
        assistants.connecter("gemini")


@pytest.mark.parametrize("code", ["", "   ", "avec espace", "a\nb", "x" * 3000, None, 12])
def test_code_illisible_refuse(poste, code):
    poste.installer("claude")
    assistants.connecter("claude")
    attendre_champ("claude", "lien")
    with pytest.raises(assistants.ErreurAssistant):
        assistants.envoyer_code("claude", code)
    assistants.annuler("claude")


def test_code_sans_connexion_en_cours(poste):
    poste.installer("claude")
    with pytest.raises(assistants.ErreurAssistant, match="Aucune connexion") as e:
        assistants.envoyer_code("claude", "abc")
    assert e.value.conflit


def test_connexion_annulee(poste):
    poste.installer("claude")
    assistants.connecter("claude")
    attendre_champ("claude", "lien")
    processus = assistants.TRAVAUX["claude"].processus
    assert assistants.annuler("claude")["statut"] == "annule"
    assert processus.poll() is not None
    # Une nouvelle connexion est possible ensuite.
    assistants.connecter("claude")
    assert assistants.etat_travail("claude")["statut"] == "en_cours"
    assistants.tout_annuler()


def test_annuler_sans_travail_ne_fait_rien(poste):
    assert assistants.annuler("claude") is None


@pytest.mark.skipif(sys.platform != "win32", reason="PATH de l'installeur : Windows seulement")
def test_installation_met_system32_en_tete_du_path(poste, monkeypatch, tmp_path):
    """Le script Codex appelle `tar` : celui de Windows doit passer avant un `tar` de Git Bash."""
    sortie = tmp_path / "path.txt"
    monkeypatch.setenv("PLANNING_PERMS_INSTALLEUR_CODEX", json.dumps(
        [sys.executable, "-c", "import os,sys;open(sys.argv[1],'w').write(os.environ['PATH']+'|'+os.environ.get('CODEX_NON_INTERACTIVE',''))",
         str(sortie)]))
    monkeypatch.setenv("PATH", r"C:\Program Files\Git\usr\bin" + os.pathsep + os.environ["PATH"])
    assistants.installer("codex")
    attendre("codex", "echec")  # le faux installeur ne crée pas codex : seul l'environnement compte ici
    chemin, _, non_interactif = sortie.read_text(encoding="utf-8").rpartition("|")
    systeme = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32")
    assert chemin.split(os.pathsep)[0].lower() == systeme.lower()
    assert non_interactif == "1"
