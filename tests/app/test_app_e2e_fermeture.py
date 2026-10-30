"""Fermeture de la fenêtre dans un vrai navigateur : la page prévient l'outil (`pagehide`), une page rechargée l'annule."""
import time

import pytest

from test_app_e2e import chromium, page  # noqa: F401 (fixtures du module voisin)

import serveur

pytestmark = pytest.mark.e2e
sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(autouse=True)
def fenetre_ouverte():
    serveur.ACTIVITE["fenetre_fermee"] = False
    yield
    serveur.ACTIVITE["fenetre_fermee"] = False


def attendre(condition, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def ouvrir(page, appli):
    appli.post("/api/config", {"moteur": "manuel"})
    page.goto(appli.url + "/")
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    # Les requêtes de chargement ont déjà annulé toute fermeture précédente.
    assert serveur.ACTIVITE["fenetre_fermee"] is False


def test_fermer_la_page_previent_l_outil(page, appli, poste):
    ouvrir(page, appli)
    page.close(run_before_unload=False)
    assert attendre(lambda: serveur.ACTIVITE["fenetre_fermee"]), "le signal de fermeture n'est pas arrivé"


def test_recharger_la_page_annule_la_fermeture(page, appli, poste):
    ouvrir(page, appli)
    page.reload()
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    # Le pagehide du rechargement a pu passer par le serveur ; la page neuve doit l'avoir annulé.
    assert attendre(lambda: serveur.ACTIVITE["fenetre_fermee"] is False)
    time.sleep(0.5)
    assert serveur.ACTIVITE["fenetre_fermee"] is False


def test_fermer_l_outil_puis_la_page_ne_plante_pas(page, appli, poste):
    ouvrir(page, appli)
    page.get_by_role("button", name="Fermer l'outil").click()
    sync_api.expect(page.get_by_role("heading", name="L'outil est fermé")).to_be_visible()
    assert appli.serveur.arrete.wait(5)
    page.close(run_before_unload=False)
    assert page.erreurs == []
