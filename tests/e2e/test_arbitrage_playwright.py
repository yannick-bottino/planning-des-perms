"""Tests bout en bout de la page d'arbitrage (Chromium headless, file://)."""
import json
import os
import re
import subprocess
import sys

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

from e2e_outils import (  # noqa: E402
    SCRIPTS, alertes, bouton_annuler, case, detail, entete, ouvrir, rx, toutes_les_cases,
)

pytestmark = pytest.mark.e2e


def exporter(page) -> dict:
    with page.expect_download() as dl:
        page.get_by_role("button", name="Exporter mes choix").click()
    assert dl.value.suggested_filename == "arbitrages.json"
    with open(dl.value.path(), encoding="utf-8") as f:
        return json.load(f)


def retirer(page, jeu, creneau, famille):
    case(page, jeu, creneau).click()
    detail(page).get_by_role("button", name=f"Retirer {famille} de {jeu.libelle(creneau)}").click()


def alerte_vide(page, lib):
    return alertes(page).get_by_role("button", name=rx("Créneau sans parent : " + lib))


# 1 -------------------------------------------------------------------------
def test_chargement(page, jeu, erreurs):
    ouvrir(page, jeu)
    expect(page.get_by_role("heading", level=1)).to_have_text("Planning fictif")
    assert page.title() == "Arbitrage : Planning fictif"
    assert toutes_les_cases(page).count() == len(jeu.sondage["creneaux"]) == 24
    assert page.locator('[data-testid^="ferme-"]').count() == 6  # mercredi, 3 semaines, matin et après-midi
    expect(page.get_by_text("Matin : fermé").first).to_be_visible()
    assert erreurs == []


# 2 -------------------------------------------------------------------------
def test_case_vide_signalee(page, jeu):
    vides = jeu.creneaux_vides()
    assert vides, "le jeu fictif doit contenir au moins un créneau vide"
    c, lib = vides[0], jeu.libelle(vides[0])
    ouvrir(page, jeu)
    bouton = case(page, jeu, c)
    # Texte (pas seulement la couleur) : badge visible et nom accessible.
    expect(bouton.get_by_text("Vide")).to_be_visible()
    expect(bouton).to_have_accessible_name(re.compile("créneau vide"))
    # Couleur distincte d'une case neutre.
    neutre = jeu.creneau_a_un_parent()
    assert (bouton.evaluate("e => getComputedStyle(e).backgroundColor") !=
            case(page, jeu, neutre).evaluate("e => getComputedStyle(e).backgroundColor"))
    # Panneau d'alertes, puis clic qui mène à la case.
    alerte_vide(page, lib).click()
    expect(case(page, jeu, c)).to_have_attribute("aria-pressed", "true")
    expect(case(page, jeu, c)).to_be_focused()
    expect(detail(page).get_by_role("heading", name=lib)).to_be_visible()


# 3 -------------------------------------------------------------------------
def test_detail_familles_et_compteurs(page, jeu):
    c = jeu.creneau_a_un_parent()
    affectee = jeu.parents(c)[0]
    libre = jeu.famille_disponible_hors_creneau(c)
    sem = jeu.semaine_de(c)
    ouvrir(page, jeu)
    case(page, jeu, c).click()
    d = detail(page)
    expect(d.get_by_role("heading", name="Familles affectées")).to_be_visible()
    expect(d.get_by_role("heading", name="Familles qui peuvent venir")).to_be_visible()
    quota = jeu.donnees["quota_mois"]
    for f, verbe, prep in ((affectee, "Retirer", "de"), (libre, "Ajouter", "sur")):
        attendu = (f"Cette semaine {jeu.par_semaine(f, sem)}/{jeu.donnees['plafond_hebdo']}"
                   f" · Mois {jeu.total(f)}/{quota[f]}")
        expect(d.get_by_test_id("compteurs-" + f)).to_have_text(attendu)
    expect(d.get_by_role("button", name=f"Retirer {affectee} de {jeu.libelle(c)}")).to_be_visible()
    expect(d.get_by_role("button", name=f"Ajouter {libre} sur {jeu.libelle(c)}")).to_be_visible()


# 4 -------------------------------------------------------------------------
def test_retrait_met_a_jour_et_alerte_a1(page, jeu):
    c = jeu.creneau_a_un_parent()
    f = jeu.parents(c)[0]
    lib = jeu.libelle(c)
    avant = jeu.total(f)
    quota = jeu.donnees["quota_mois"][f]
    ouvrir(page, jeu)
    expect(alerte_vide(page, lib)).to_have_count(0)
    retirer(page, jeu, c, f)
    expect(case(page, jeu, c)).to_have_accessible_name(re.compile("aucune famille, 0 parent, créneau vide"))
    expect(alerte_vide(page, lib)).to_be_visible()
    ligne = page.get_by_role("region", name="Familles").get_by_role("row", name=re.compile("^" + f))
    expect(ligne).to_contain_text(f"{avant - 1} / {quota} (manque {quota - avant + 1})")
    expect(page.get_by_text(f"{f} retirée de {lib}.")).to_be_visible()
    # Dans le détail, la famille retirée repasse dans les candidates avec le compteur à jour.
    attendu = (f"Cette semaine {jeu.par_semaine(f, jeu.semaine_de(c)) - 1}/{jeu.donnees['plafond_hebdo']}"
               f" · Mois {avant - 1}/{quota}")
    expect(detail(page).get_by_test_id("compteurs-" + f)).to_have_text(attendu)


# 5 -------------------------------------------------------------------------
def test_ajout_famille_non_disponible(page, jeu):
    c, f = "2026-11-02_M", "CLEO"
    lib = jeu.libelle(c)
    assert f not in jeu.parents(c)
    ouvrir(page, jeu)
    case(page, jeu, c).click()
    d = detail(page)
    expect(d.get_by_role("button", name=f"Ajouter {f} sur {lib}")).to_have_count(0)
    d.get_by_role("checkbox", name=re.compile("afficher aussi les familles non disponibles")).check()
    d.get_by_role("button", name=f"Ajouter {f} sur {lib}").click()
    statut = page.get_by_role("status")
    expect(statut).to_contain_text(f"Attention : {f} n'est pas disponible sur {lib}")
    expect(statut).to_contain_text("règle dure")
    expect(alertes(page).get_by_role(
        "button", name=re.compile(f"La famille {f} est affectée sur .*pas disponible"))).to_be_visible()
    expect(case(page, jeu, c).get_by_text("Règle")).to_be_visible()
    expect(d.get_by_text("Hors disponibilité : règle non respectée.")).to_be_visible()
    assert re.search(r"règles? non respectée", entete(page).inner_text())


# 6 -------------------------------------------------------------------------
def test_annuler_dernier_changement(page, jeu):
    c = jeu.creneau_a_un_parent()
    f = jeu.parents(c)[0]
    ouvrir(page, jeu)
    expect(bouton_annuler(page)).to_be_disabled()
    nom_initial = case(page, jeu, c).get_attribute("aria-label")
    retirer(page, jeu, c, f)
    assert case(page, jeu, c).get_attribute("aria-label") != nom_initial
    expect(bouton_annuler(page)).to_be_enabled()
    bouton_annuler(page).click()
    assert case(page, jeu, c).get_attribute("aria-label") == nom_initial
    expect(bouton_annuler(page)).to_be_disabled()
    expect(page.get_by_text("Dernier changement annulé")).to_be_visible()
    assert exporter(page)["changements"] == []


# 7 -------------------------------------------------------------------------
def test_export_format_et_changements_nets(page, jeu):
    c = jeu.creneau_a_un_parent()
    f = jeu.parents(c)[0]
    g = jeu.famille_disponible_hors_creneau(c)
    ouvrir(page, jeu)
    # Ajout puis retrait de la même famille : aucun changement net.
    case(page, jeu, c).click()
    detail(page).get_by_role("button", name=f"Ajouter {g} sur {jeu.libelle(c)}").click()
    detail(page).get_by_role("button", name=f"Retirer {g} de {jeu.libelle(c)}").click()
    o = exporter(page)
    assert set(o) == {"empreinte", "exporte_le", "changements"}
    assert o["empreinte"] == jeu.planning["empreinte"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", o["exporte_le"])
    assert o["changements"] == []
    expect(page.get_by_role("status")).to_contain_text("sans aucun changement")
    # Un retrait réel.
    detail(page).get_by_role("button", name=f"Retirer {f} de {jeu.libelle(c)}").click()
    o = exporter(page)
    assert o["changements"] == [{"action": "retirer", "famille": f, "creneau": c}]
    # Texte par défaut du skill (l'application V2 passe le sien via apres_export).
    expect(page.get_by_role("status")).to_contain_text("Revenez dans le chat pour la suite.")


def test_commentaires_non_traduits_titre_neutre(page, jeu):
    ouvrir(page, jeu)
    expect(page.get_by_role("heading", name="Commentaires à traiter à la main")).to_be_visible()
    expect(page.get_by_text("Claude n'a pas pu")).to_have_count(0)


# 8 -------------------------------------------------------------------------
def _compter(chemin, nom: str) -> int:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(chemin)
    return sum(1 for ws in wb for ligne in ws.iter_rows(values_only=True)
               for v in ligne if isinstance(v, str) and v.strip().upper() == nom)


def _export_cli(jeu, sortie, arbitrages=None):
    cmd = [sys.executable, str(SCRIPTS / "export_xlsx.py"), "--planning", str(jeu.chemin_planning),
           "--out", str(sortie)]
    if arbitrages:
        cmd += ["--arbitrages", str(arbitrages), "--sondage", str(jeu.chemin_sondage),
                "--contraintes", str(jeu.chemin_contraintes)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def test_aller_retour_export_xlsx(page, jeu, tmp_path):
    c = jeu.creneau_a_un_parent()
    g = jeu.famille_disponible_hors_creneau(c)
    ouvrir(page, jeu)
    case(page, jeu, c).click()
    detail(page).get_by_role("button", name=f"Ajouter {g} sur {jeu.libelle(c)}").click()
    with page.expect_download() as dl:
        page.get_by_role("button", name="Exporter mes choix").click()
    arb = tmp_path / "arbitrages.json"
    dl.value.save_as(arb)
    base = _export_cli(jeu, tmp_path / "base.xlsx")
    assert base.returncode == 0, base.stderr
    r = _export_cli(jeu, tmp_path / "final.xlsx", arb)
    assert r.returncode == 0, r.stderr
    assert _compter(tmp_path / "final.xlsx", g) == _compter(tmp_path / "base.xlsx", g) + 1


# 9 -------------------------------------------------------------------------
def test_persistance_et_reinitialisation(page, jeu):
    c = jeu.creneau_a_un_parent()
    f = jeu.parents(c)[0]
    ouvrir(page, jeu)
    initial = case(page, jeu, c).get_attribute("aria-label")
    retirer(page, jeu, c, f)
    modifie = case(page, jeu, c).get_attribute("aria-label")
    assert modifie != initial
    stockage_ok = page.evaluate(
        "() => { try { localStorage.setItem('t','1'); localStorage.removeItem('t'); return true; }"
        " catch (e) { return false; } }")
    page.reload()
    page.get_by_role("heading", level=1).wait_for()
    if stockage_ok:
        assert case(page, jeu, c).get_attribute("aria-label") == modifie
        expect(page.get_by_role("region", name="Historique des changements")).to_contain_text("(1)")
    else:  # localStorage bloqué en file:// : la page reste utilisable
        assert toutes_les_cases(page).count() == 24
        retirer(page, jeu, c, f)
        assert case(page, jeu, c).get_attribute("aria-label") == modifie
    page.once("dialog", lambda d: d.accept())
    entete(page).get_by_role("button", name="Repartir du planning calculé").click()
    assert case(page, jeu, c).get_attribute("aria-label") == initial
    page.reload()
    page.get_by_role("heading", level=1).wait_for()
    assert case(page, jeu, c).get_attribute("aria-label") == initial
    expect(page.get_by_role("region", name="Historique des changements")).to_contain_text("(0)")


# 10 ------------------------------------------------------------------------
def test_modes_clair_et_sombre(navigateur, jeu, tmp_path):
    styles = {}
    for mode in ("light", "dark"):
        ctx = navigateur.new_context(viewport={"width": 1280, "height": 900}, color_scheme=mode)
        p = ctx.new_page()
        ouvrir(p, jeu)
        p.screenshot(path=str(tmp_path / f"{mode}.png"), full_page=True)
        styles[mode] = p.evaluate(
            "() => ({fond: getComputedStyle(document.body).backgroundColor,"
            " texte: getComputedStyle(document.body).color})")
        assert (tmp_path / f"{mode}.png").stat().st_size > 5000
        ctx.close()
    assert styles["light"]["fond"] != styles["dark"]["fond"]
    assert styles["light"]["texte"] != styles["dark"]["texte"]
    assert styles["light"]["fond"] != styles["light"]["texte"]
    assert styles["dark"]["fond"] != styles["dark"]["texte"]


# 11 ------------------------------------------------------------------------
def test_clavier(page, jeu):
    ouvrir(page, jeu)
    atteint = False
    for _ in range(12):
        page.keyboard.press("Tab")
        if page.evaluate("() => (document.activeElement.id || '').startsWith('case-')"):
            atteint = True
            break
    assert atteint, "aucune case atteinte au clavier en 12 Tab"
    id_case = page.evaluate("() => document.activeElement.id")
    page.keyboard.press("Enter")
    lib = jeu.donnees["libelles"][id_case.removeprefix("case-")]
    expect(detail(page).get_by_role("heading", name=lib)).to_be_visible()
    assert page.evaluate("() => document.activeElement.id") == id_case  # le focus reste sur la case
    # Le panneau de détail est atteignable ensuite au clavier.
    atteint = False
    for _ in range(300):
        page.keyboard.press("Tab")
        if page.evaluate("() => !!document.activeElement.closest('#detail')"):
            atteint = True
            break
    assert atteint, "le panneau de détail n'est pas atteignable au clavier"


# 12 ------------------------------------------------------------------------
def test_pas_de_defilement_horizontal(page, jeu):
    ouvrir(page, jeu)
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 1280
    case(page, jeu, jeu.creneau_a_un_parent()).click()
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 1280
