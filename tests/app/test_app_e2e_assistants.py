"""Premier lancement, arrêt et présence dans un vrai navigateur (spec V3, critère 3), avec de faux claude et codex.

Aucun vrai installeur, aucune vraie connexion : les programmes simulés sont dans faux_assistants.py.
"""
import json
import re
import time
import urllib.error
import urllib.request

import pytest

from test_app_e2e import capturer, chromium, page  # noqa: F401 (fixtures du module voisin)

pytestmark = pytest.mark.e2e
sync_api = pytest.importorskip("playwright.sync_api")

QUESTION = "Vous avez un abonnement Claude, ChatGPT, ou une clé DeepSeek ?"


def ouvrir_premier_lancement(page, appli):
    page.goto(appli.url + "/")
    sync_api.expect(page.get_by_role("group", name=QUESTION)).to_be_visible()


def moteur_enregistre(appli):
    return appli.get_json("/api/etat")[1]["moteur"]


def test_premier_lancement_claude_installation_et_connexion(page, appli, poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "1")
    ouvrir_premier_lancement(page, appli)
    # Les deux conditions payantes sont dites avant toute installation.
    sync_api.expect(page.get_by_text("Demande un abonnement Claude Pro, Max, Team ou Enterprise.")).to_be_visible()
    sync_api.expect(page.get_by_text("Demande un abonnement ChatGPT Plus ou supérieur.")).to_be_visible()
    sync_api.expect(page.get_by_text("Déjà prêt sur cet ordinateur")).to_have_count(0)
    capturer(page, "0-premier-lancement")
    page.get_by_role("radio", name=re.compile("^Claude")).check()
    page.get_by_role("button", name="Continuer").click()

    # Installation simulée.
    sync_api.expect(page.get_by_role("heading", name="Installer Claude")).to_be_visible()
    assert not poste.exe["claude"].exists()
    page.get_by_role("button", name="Installer Claude").click()
    sync_api.expect(page.get_by_text(re.compile("Installation de Claude en cours"))).to_be_visible()
    capturer(page, "0-installation")

    # Connexion simulée : le lien officiel est affiché, pas celui d'un autre site.
    sync_api.expect(page.get_by_role("heading", name="Se connecter à Claude")).to_be_visible(timeout=30000)
    assert poste.exe["claude"].exists()
    page.get_by_role("button", name="Ouvrir la page de connexion").click()
    lien = page.get_by_role("link", name="page de connexion de Claude")
    sync_api.expect(lien).to_be_visible(timeout=20000)
    assert lien.get_attribute("href").startswith("https://claude.com/cai/oauth/authorize")
    assert lien.get_attribute("rel") == "noopener noreferrer"
    assert "evil.example" not in page.content()
    capturer(page, "0-connexion")

    # Le code collé est transmis au programme, qui termine la connexion.
    page.get_by_label("Si la page affiche un code, collez-le ici").fill("CODE-collé-42")
    page.get_by_role("button", name="Envoyer le code").click()
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible(timeout=30000)
    assert poste.code_recu() == "CODE-collé-42"
    assert moteur_enregistre(appli) == "claude"
    assert page.get_by_role("radio", name=re.compile("^Claude")).is_checked()
    assert "exemple.invalid" not in page.content() and "Creche Fictive" not in page.content()
    assert page.erreurs == []


def test_premier_lancement_chatgpt_code_a_usage_unique(page, appli, poste, monkeypatch):
    poste.installer("codex")
    monkeypatch.setenv("FAUX_LOGIN_DELAI", "4")
    ouvrir_premier_lancement(page, appli)
    page.get_by_role("radio", name=re.compile("^ChatGPT")).check()
    page.get_by_role("button", name="Continuer").click()
    sync_api.expect(page.get_by_role("heading", name="Se connecter à ChatGPT")).to_be_visible()
    sync_api.expect(page.get_by_text("réglages de sécurité de votre compte ChatGPT")).to_be_visible()
    page.get_by_role("button", name="Autre méthode : code à usage unique").click()
    sync_api.expect(page.locator(".code-appareil")).to_have_text("PVRM-K4VLO", timeout=15000)
    lien = page.get_by_role("link", name="page de connexion de ChatGPT")
    assert lien.get_attribute("href") == "https://auth.openai.com/codex/device"
    capturer(page, "0-code-appareil")
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible(timeout=30000)
    assert moteur_enregistre(appli) == "codex"


def test_assistant_deja_pret_est_preselectionne(page, appli, poste):
    poste.installer("claude")
    poste.connecter("claude")
    ouvrir_premier_lancement(page, appli)
    sync_api.expect(page.get_by_text("Déjà prêt sur cet ordinateur")).to_have_count(1)
    assert page.get_by_role("radio", name=re.compile("^Claude")).is_checked()
    page.get_by_role("button", name="Continuer").click()
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    assert moteur_enregistre(appli) == "claude"


def test_compte_claude_gratuit_refuse(page, appli, poste):
    poste.installer("claude")
    poste.connecter("claude", "free")
    ouvrir_premier_lancement(page, appli)
    sync_api.expect(page.get_by_text("Déjà prêt sur cet ordinateur")).to_have_count(0)
    page.get_by_role("radio", name=re.compile("^Claude")).check()
    page.get_by_role("button", name="Continuer").click()
    sync_api.expect(page.get_by_role("alert").filter(has_text="Ce compte Claude est gratuit")).to_be_visible()
    assert moteur_enregistre(appli) is None


def test_premier_lancement_a_la_main_puis_changer_d_assistant(page, appli, poste):
    ouvrir_premier_lancement(page, appli)
    page.get_by_role("button", name="Continuer").click()
    sync_api.expect(page.get_by_role("alert").filter(has_text="Choisissez une réponse")).to_be_visible()
    page.get_by_role("radio", name=re.compile("^Rien de tout ça")).check()
    page.get_by_role("button", name="Continuer").click()
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    assert moteur_enregistre(appli) == "manuel"
    # Depuis l'étape 1, on peut revenir à la question, puis garder son choix.
    page.get_by_role("button", name="Changer d'assistant").click()
    sync_api.expect(page.get_by_role("group", name=QUESTION)).to_be_visible()
    page.get_by_role("button", name="Garder mon choix actuel").click()
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    assert page.erreurs == []


def test_premier_lancement_cle_deepseek(page, appli, poste):
    ouvrir_premier_lancement(page, appli)
    page.get_by_role("radio", name=re.compile("^Une clé DeepSeek")).check()
    page.get_by_role("button", name="Continuer").click()
    assert page.get_by_role("button", name="Continuer").is_disabled()
    page.get_by_label("Clé DeepSeek").fill("sk-e2e-premier-lancement")
    page.get_by_role("button", name="Enregistrer la clé").click()
    sync_api.expect(page.get_by_text("Une clé DeepSeek est enregistrée")).to_be_visible()
    page.get_by_role("button", name="Continuer").click()
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    assert moteur_enregistre(appli) == "deepseek"


def test_fermer_l_outil(page, appli, poste):
    appli.post("/api/config", {"moteur": "manuel"})
    page.goto(appli.url + "/")
    page.get_by_role("button", name="Fermer l'outil").click()
    sync_api.expect(page.get_by_role("heading", name="L'outil est fermé")).to_be_visible()
    sync_api.expect(page.get_by_text("icône « Planning des perms » sur le bureau")).to_be_visible()
    assert page.get_by_role("button", name="Fermer l'outil").is_hidden()
    capturer(page, "0-outil-ferme")
    fin = time.monotonic() + 10
    while time.monotonic() < fin:
        try:
            urllib.request.urlopen(appli.url + "/api/etat", timeout=1)
        except (urllib.error.URLError, OSError):
            break
        time.sleep(0.2)
    else:
        pytest.fail("le serveur répond encore après « Fermer l'outil »")


def test_presence_chaque_minute_et_bandeau_si_l_outil_s_arrete(page, appli, poste):
    appli.post("/api/config", {"moteur": "manuel"})
    pings = []
    page.on("request", lambda r: pings.append(r) if r.url.endswith("/api/presence") else None)
    page.clock.install()
    page.goto(appli.url + "/")
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    assert pings == []
    page.clock.run_for(61_000)
    page.wait_for_timeout(500)
    assert len(pings) == 1 and pings[0].method == "POST"
    sync_api.expect(page.locator("#banniere-arret")).to_be_hidden()
    appli.post("/api/arreter", {})
    assert appli.serveur.arrete.wait(5)
    time.sleep(0.5)
    appli.serveur.server_close()  # comme main() : sans cela le port accepte encore les connexions
    page.clock.run_for(61_000)
    sync_api.expect(page.get_by_text(re.compile("^L'outil s'est arrêté\\. Relancez-le comme d'habitude"))).to_be_visible()
