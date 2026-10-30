"""Page d'attente du raccourci (demarrage.html, ouverte en file://) dans un vrai navigateur."""
import socket
import threading
import time

import pytest

from test_app_e2e import capturer, chromium, page  # noqa: F401 (fixtures du module voisin)

import demarrer
import serveur

pytestmark = pytest.mark.e2e
sync_api = pytest.importorskip("playwright.sync_api")


def port_reserve() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_page_d_attente_ouvre_l_outil_des_qu_il_repond(page, environnement):
    port = port_reserve()
    page.goto(demarrer.adresse_attente(port))
    sync_api.expect(page.get_by_text("L'outil démarre. La première fois, cela peut prendre jusqu'à une minute.")).to_be_visible()
    sync_api.expect(page.get_by_role("alert")).to_be_hidden()
    capturer(page, "0-attente")
    demarre = {}

    def lancer_plus_tard():
        time.sleep(1.5)
        demarre["srv"] = serveur.creer_serveur(port, silencieux=True)
        demarre["srv"].serve_forever()
    threading.Thread(target=lancer_plus_tard, daemon=True).start()
    try:
        page.wait_for_url(f"http://127.0.0.1:{port}/**", timeout=20000)
        sync_api.expect(page.get_by_role("group", name="Vous avez un abonnement Claude, ChatGPT, ou une clé DeepSeek ?")).to_be_visible()
    finally:
        if "srv" in demarre:
            demarre["srv"].shutdown()
            demarre["srv"].server_close()
    assert page.erreurs == []


def test_page_d_attente_annonce_l_echec(page):
    page.goto(demarrer.adresse_attente(port_reserve()) + "&delai=2")
    echec = page.get_by_role("alert")
    sync_api.expect(echec).to_be_visible(timeout=15000)
    sync_api.expect(echec).to_contain_text("L'outil n'a pas démarré. Relancez-le depuis l'icône du bureau.")
    sync_api.expect(echec).to_contain_text("journal.txt (dossier %LOCALAPPDATA%\\balustrade-planning)")
    sync_api.expect(page.get_by_text("L'outil démarre.")).to_be_hidden()


def test_page_d_attente_sans_port_valable(page):
    page.goto(demarrer.adresse_attente(0).replace("#0", "#abc"))
    sync_api.expect(page.get_by_role("alert")).to_be_visible(timeout=10000)
