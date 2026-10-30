"""Parcours complet dans Chromium (Playwright), sondage et DeepSeek simulés en local (critères 7, 8, 11).

Captures d'écran : PLANNING_PERMS_CAPTURES=<dossier> python -m pytest tests/app/test_app_e2e.py
"""
import json
import os
import re
from pathlib import Path

import pytest
from openpyxl import load_workbook

pytestmark = pytest.mark.e2e
sync_api = pytest.importorskip("playwright.sync_api")

CLE = "sk-e2e-0000"
PIEGE = '<img src=x onerror="window.__piege=1">Absents le 11'


@pytest.fixture(scope="module")
def chromium():
    with sync_api.sync_playwright() as p:
        try:
            navigateur = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium indisponible : {e}")
        yield navigateur
        navigateur.close()


@pytest.fixture(params=[(1280, 900)], ids=["portable"])
def page(chromium, request):
    contexte = chromium.new_context(viewport={"width": request.param[0], "height": request.param[1]},
                                    accept_downloads=True, locale="fr-FR")
    p = contexte.new_page()
    erreurs = []
    p.on("pageerror", lambda e: erreurs.append(str(e)))
    p.erreurs = erreurs
    yield p
    contexte.close()


def capturer(page, nom):
    dossier = os.environ.get("PLANNING_PERMS_CAPTURES")
    if dossier:
        Path(dossier).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(dossier) / f"{nom}.png"), full_page=True)


def etape_sondage(page, appli, lien, moteur_libelle):
    # Un moteur déjà enregistré : sans lui, l'écran de premier lancement (V3) précède l'étape 1.
    appli.post("/api/config", {"moteur": "manuel"})
    page.goto(appli.url + "/")
    sync_api.expect(page.get_by_role("heading", name="Préparer le planning du mois")).to_be_visible()
    page.get_by_label("Lien du sondage Framadate").fill(lien)
    page.get_by_role("radio", name=re.compile(moteur_libelle)).check()


def test_parcours_complet_deepseek(page, appli, framadate, deepseek, environnement):
    etape_sondage(page, appli, framadate.lien(), "DeepSeek")
    page.get_by_label("Clé DeepSeek").fill(CLE)
    page.get_by_role("button", name="Enregistrer la clé").click()
    sync_api.expect(page.get_by_text("Une clé DeepSeek est enregistrée")).to_be_visible()
    assert CLE not in page.content()
    capturer(page, "1-sondage")
    page.get_by_role("button", name="Lire le sondage").click()

    # Étape 2 : résumé
    sync_api.expect(page.get_by_role("heading", name="Planning Test")).to_be_visible()
    sync_api.expect(page.get_by_text("jeudi 5/11, vendredi 6/11.")).to_be_visible()
    capturer(page, "2-resume")
    page.get_by_role("button", name="Lire les commentaires avec DeepSeek").click()

    # Étape 3 : règles proposées, une règle modifiée
    sync_api.expect(page.get_by_role("heading", name="Relire les règles")).to_be_visible()
    lignes = page.locator("table.regles tbody tr")
    sync_api.expect(lignes).to_have_count(3)
    sync_api.expect(page.get_by_text("Règles proposées par DeepSeek")).to_be_visible()
    sync_api.expect(page.locator("table.regles").get_by_text("Nous serons en congés la semaine du 9 novembre").first).to_be_visible()
    assert "YAML" not in page.content() and "quota_mois" not in page.inner_text("main")
    quota = page.get_by_label(re.compile(r"^Nombre de perms du mois"))
    assert quota.input_value() == "2"
    quota.fill("1")
    capturer(page, "3-regles")
    page.get_by_role("button", name="Calculer le planning").click()

    # Étape 4 : arbitrage dans le cadre, un ajout
    sync_api.expect(page.get_by_role("heading", name="Arbitrer les cas difficiles")).to_be_visible()
    cadre = page.frame_locator("iframe.cadre")
    sync_api.expect(cadre.locator("button[id^='case-']").first).to_be_visible()
    ajout = None
    for case in cadre.locator("button[id^='case-']").all():
        case.click()
        bouton = cadre.get_by_role("button", name=re.compile(r"^Ajouter \S+ sur "))
        if bouton.count():
            nom = bouton.first.get_attribute("aria-label")
            ajout = (re.match(r"Ajouter (\S+) sur", nom).group(1), case.get_attribute("id").removeprefix("case-"))
            bouton.first.click()
            break
    assert ajout, "aucune case ne permet d'ajouter une famille disponible"
    capturer(page, "4-arbitrage")
    page.get_by_role("button", name="Valider l'arbitrage").click()

    # Étape 5 : Excel
    sync_api.expect(page.get_by_role("heading", name="Le planning est prêt")).to_be_visible()
    sync_api.expect(page.get_by_text("Le planning tient compte de votre changement d'arbitrage.")).to_be_visible()
    capturer(page, "5-excel")
    with page.expect_download() as tele:
        page.get_by_role("link", name=re.compile("Télécharger planning-2026-11.xlsx")).click()
    chemin = environnement / "telecharge.xlsx"
    tele.value.save_as(chemin)
    wb = load_workbook(chemin)
    assert [ws.title for ws in wb] == ["SEMAINE 45", "SEMAINE 46"]
    final = json.loads((environnement / "donnees" / "2026-11" / "planning-final.json").read_text(encoding="utf-8"))
    assert {"famille": ajout[0], "creneau": ajout[1]} in [
        {k: a[k] for k in ("famille", "creneau")} for a in final["affectations"] if a["origine"] == "arbitrage"]
    valeurs = {c.value for ws in wb for ligne in ws.iter_rows() for c in ligne}
    assert ajout[0] in valeurs
    # La règle modifiée (quota de ZOE à 1) est bien celle du calcul.
    assert final["bilan"]["ZOE"]["quota_mois"] == 1
    assert page.erreurs == []


def test_parcours_manuel_sans_arbitrage_et_commentaire_piege(page, appli, framadate, environnement):
    csv, html = framadate.sondages["Test1"]
    framadate.sondages["Piege1"] = (csv, html.replace("Nous sommes absents du mercredi 11 au vendredi 13.",
                                                      PIEGE.replace("<", "&lt;").replace(">", "&gt;")))
    etape_sondage(page, appli, framadate.lien("Piege1"), "Personne")
    page.get_by_role("button", name="Lire le sondage").click()
    sync_api.expect(page.get_by_text(PIEGE)).to_be_visible()
    page.get_by_role("button", name="Saisir les règles").click()

    sync_api.expect(page.get_by_role("heading", name="Relire les règles")).to_be_visible()
    sync_api.expect(page.locator("table.regles tbody tr")).to_have_count(1)  # ligne vide « Aucune règle »
    page.get_by_role("button", name="Ajouter une règle").click()
    page.get_by_label("Famille (règle 1)").select_option("ZOE")
    page.get_by_label("Type de règle (règle 1)").select_option("absence")
    page.get_by_label("Semaine d'absence (règle 1)").select_option("2026-11-09")
    page.get_by_role("button", name="Ajouter une demande à traiter").click()
    page.get_by_role("textbox", name="Commentaire à traiter 1").fill("INCONNU : absents du 11 au 13 " + PIEGE)
    page.get_by_role("button", name="Calculer le planning").click()

    sync_api.expect(page.get_by_role("heading", name="Arbitrer les cas difficiles")).to_be_visible()
    cadre = page.frame_locator("iframe.cadre")
    sync_api.expect(cadre.get_by_text("INCONNU : absents du 11 au 13").first).to_be_visible()
    page.get_by_role("button", name="Garder le planning calculé").click()
    sync_api.expect(page.get_by_role("heading", name="Le planning est prêt")).to_be_visible()
    sync_api.expect(page.get_by_text("sans changement")).to_be_visible()
    assert page.evaluate("window.__piege") is None
    assert all(f.evaluate("window.__piege") is None for f in page.frames)
    assert (environnement / "donnees" / "2026-11" / "planning-2026-11.xlsx").is_file()
    assert "absences:" in (environnement / "donnees" / "2026-11" / "contraintes.yaml").read_text(encoding="utf-8")
    assert page.erreurs == []


def test_erreur_de_regle_signalee_sur_la_ligne(page, appli, framadate):
    etape_sondage(page, appli, framadate.lien(), "Personne")
    page.get_by_role("button", name="Lire le sondage").click()
    page.get_by_role("button", name="Saisir les règles").click()
    page.get_by_role("button", name="Ajouter une règle").click()
    page.get_by_role("button", name="Calculer le planning").click()
    sync_api.expect(page.get_by_role("alert")).to_contain_text("Choisissez une famille")
    sync_api.expect(page.locator("tr.fautive")).to_have_count(1)


def test_lien_errone(page, appli, framadate):
    etape_sondage(page, appli, framadate.lien("Inexistant9"), "Personne")
    page.get_by_role("button", name="Lire le sondage").click()
    sync_api.expect(page.get_by_role("alert")).to_contain_text("n'a pas pu être téléchargé")


def test_petit_ecran_sans_defilement_horizontal(chromium, appli, framadate, deepseek):
    contexte = chromium.new_context(viewport={"width": 390, "height": 844})
    page = contexte.new_page()
    try:
        etape_sondage(page, appli, framadate.lien(), "Personne")
        page.get_by_role("button", name="Lire le sondage").click()
        sync_api.expect(page.get_by_role("heading", name="Planning Test")).to_be_visible()
        page.get_by_role("button", name="Saisir les règles").click()
        page.get_by_role("button", name="Ajouter une règle").click()
        page.get_by_label("Type de règle (règle 1)").select_option("au_moins")
        capturer(page, "3-regles-mobile")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    finally:
        contexte.close()
