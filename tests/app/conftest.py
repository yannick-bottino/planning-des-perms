"""Fixtures des tests V2. Les outils sont dans outils_app.py."""
import threading

import pytest

from faux_assistants import Poste
from outils_app import Client, FauxDeepSeek, FauxFramadate

import assistants
import serveur


def pytest_configure(config):
    config.addinivalue_line("markers", "reel: appelle un vrai moteur d'IA (Claude Code, DeepSeek)")
    config.addinivalue_line("markers", "e2e: parcours complet dans un vrai navigateur (Playwright)")
    config.addinivalue_line("markers", "lancement: lance lancer.bat ou lancer.sh pour de vrai")


@pytest.fixture
def framadate():
    f = FauxFramadate()
    yield f
    f.srv.shutdown()


@pytest.fixture
def deepseek(monkeypatch):
    f = FauxDeepSeek()
    monkeypatch.setenv("PLANNING_PERMS_DEEPSEEK_URL", f.url + "/chat/completions")
    yield f
    f.srv.shutdown()


@pytest.fixture
def environnement(tmp_path, monkeypatch):
    """Données et configuration dans un dossier temporaire ; aucun Claude Code ni Codex réel."""
    monkeypatch.setenv("PLANNING_PERMS_DONNEES", str(tmp_path / "donnees"))
    monkeypatch.setenv("PLANNING_PERMS_CONFIG", str(tmp_path / "config" / "config.json"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # Aucun assistant réel du poste de développement : un chemin imposé qui n'existe pas.
    monkeypatch.setenv("PLANNING_PERMS_CLAUDE", str(tmp_path / "absent" / "claude"))
    monkeypatch.setenv("PLANNING_PERMS_CODEX", str(tmp_path / "absent" / "codex"))
    serveur.ETAT.vider()
    yield tmp_path
    # Un travail oublié (installation, connexion) ne doit pas déborder sur le test suivant.
    assistants.tout_annuler()
    assistants.TRAVAUX.update({a: None for a in assistants.ASSISTANTS})


@pytest.fixture
def poste(environnement, monkeypatch):
    """Faux claude et faux codex, absents au départ ; installeurs et connexions simulés (jamais le réseau)."""
    return Poste(environnement, monkeypatch)


@pytest.fixture
def appli(environnement):
    """Serveur de l'application sur un port libre. Renvoie un Client."""
    srv = serveur.creer_serveur(0, silencieux=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client = Client(f"http://127.0.0.1:{srv.server_address[1]}")
    client.serveur = srv
    yield client
    srv.shutdown()
    srv.server_close()
