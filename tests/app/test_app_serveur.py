"""Serveur HTTP : parcours complet par l'API, sécurité locale, clé DeepSeek (critères 3 à 5)."""
import io
import json
import sys
import threading
import time
import urllib.request

import pytest
from openpyxl import load_workbook

from outils_app import REPONSE_IA, Client

import assistants
import serveur

CLE = "sk-test-secret-0123456789"


def parcours_jusquau_calcul(appli, framadate, moteur="deepseek"):
    statut, rep = appli.post("/api/sondage", {"lien": framadate.lien()})
    assert statut == 200, rep
    statut, regles = appli.post("/api/regles/proposer", {"moteur": moteur})
    assert statut == 200, regles
    return rep, regles


def test_etat_initial(appli):
    statut, etat = appli.get_json("/api/etat")
    assert statut == 200
    assert etat["application"] == "planning-perms"
    assert etat == {**etat, "moteur": None, "deepseek_cle": False, "claude": False}


def test_parcours_complet_api(appli, framadate, deepseek, environnement):
    appli.post("/api/config", {"deepseek_cle": CLE, "moteur": "deepseek"})
    sondage, regles = parcours_jusquau_calcul(appli, framadate)
    assert sondage["mois"] == "2026-11"
    assert sondage["resume"]["titre"] == "Planning Test"
    assert not regles["manuel"] and regles["essais"] == 1
    types = sorted((r["famille"], r["type"]) for r in regles["regles"])
    assert types == [("LEA", "au_moins"), ("ZOE", "absence"), ("ZOE", "quota")]
    assert regles["non_traduits"] == REPONSE_IA["commentaires_non_traduits"]
    # La clé part bien vers DeepSeek, en en-tête.
    assert deepseek.requetes[0]["auth"] == f"Bearer {CLE}"

    statut, calcul = appli.post("/api/calculer", {k: regles[k] for k in ("regles", "non_traduits", "reglages")})
    assert statut == 200, calcul
    assert calcul["a_deux"] + calcul["a_un"] + calcul["vides"] + calcul["a_trois_ou_plus"] == 10
    dossier = environnement / "donnees" / "2026-11"
    for nom in ("sondage.json", "contraintes.yaml", "planning.json", "arbitrage.html"):
        assert (dossier / nom).is_file(), nom

    statut, page, entetes = appli.requete("GET", "/arbitrage")
    assert statut == 200 and b"/api/arbitrages" in page
    assert entetes["X-Frame-Options"] == "SAMEORIGIN"

    planning = json.loads((dossier / "planning.json").read_text(encoding="utf-8"))
    libre = next(c for c in planning["creneaux"] if "BASILE" not in c["familles"]
                 and json.loads((dossier / "sondage.json").read_text(encoding="utf-8"))
                 ["familles"][2]["dispos"].get(c["id"]) == "oui")
    arbitrages = {"empreinte": planning["empreinte"],
                  "changements": [{"action": "ajouter", "famille": "BASILE", "creneau": libre["id"]}]}
    statut, bilan = appli.post("/api/arbitrages", {"arbitrages": arbitrages})
    assert statut == 200, bilan
    assert bilan["changements"] == 1 and bilan["fichier"] == "planning-2026-11.xlsx"
    statut, xlsx, entetes = appli.requete("GET", "/api/excel")
    assert statut == 200 and "attachment" in entetes["Content-Disposition"]
    wb = load_workbook(io.BytesIO(xlsx))
    assert [ws.title for ws in wb] == ["SEMAINE 45", "SEMAINE 46"]
    assert (dossier / "arbitrages.json").is_file() and (dossier / "planning-final.json").is_file()


def test_garder_le_planning_sans_arbitrage(appli, framadate, environnement):
    _, regles = parcours_jusquau_calcul(appli, framadate, moteur="manuel")
    assert regles["manuel"] and regles["regles"] == []
    appli.post("/api/calculer", {"regles": [], "non_traduits": [], "reglages": regles["reglages"]})
    statut, bilan = appli.post("/api/arbitrages", {"arbitrages": None})
    assert statut == 200 and bilan["changements"] == 0
    assert not (environnement / "donnees" / "2026-11" / "arbitrages.json").exists()


def test_regle_invalide_indique_la_ligne(appli, framadate):
    parcours_jusquau_calcul(appli, framadate, moteur="manuel")
    regles = [{"famille": "LEA", "type": "quota", "quota": 2},
              {"famille": "ZOE", "type": "absence", "semaine": ""}]
    statut, rep = appli.post("/api/calculer", {"regles": regles, "non_traduits": [], "reglages": {}})
    assert statut == 400 and rep["index"] == 1
    assert "semaine" in rep["erreur"]


def test_arbitrage_d_un_autre_calcul_refuse(appli, framadate):
    parcours_jusquau_calcul(appli, framadate, moteur="manuel")
    appli.post("/api/calculer", {"regles": [], "non_traduits": [], "reglages": {}})
    statut, rep = appli.post("/api/arbitrages", {"arbitrages": {"empreinte": "autre", "changements": []}})
    assert statut == 400 and "empreinte" in rep["erreur"]


def test_etape_non_disponible(appli):
    statut, rep = appli.post("/api/calculer", {"regles": []})
    assert statut == 409
    assert appli.requete("GET", "/arbitrage")[0] == 409
    assert appli.requete("GET", "/api/excel")[0] == 409


def test_lien_invalide(appli):
    statut, rep = appli.post("/api/sondage", {"lien": "https://exemple.org/pas-un-sondage"})
    assert statut == 400 and "/polls/" in rep["erreur"]
    statut, rep = appli.post("/api/sondage", {"lien": "http://framadate.org/polls/Abc"})
    assert statut == 400 and "https" in rep["erreur"]


# ---------------------------------------------------------------- sécurité locale (critère 3)

def test_host_etranger_refuse(appli):
    assert appli.requete("GET", "/api/etat", entetes={"Host": "evil.example:80"})[0] == 403
    assert appli.requete("GET", "/", entetes={"Host": "evil.example"})[0] == 403


def test_post_sans_json_ou_autre_origine_refuse(appli):
    assert appli.requete("POST", "/api/config", {"moteur": "manuel"},
                         entetes={"Origin": "https://evil.example"})[0] == 403
    assert appli.requete("POST", "/api/config", {"moteur": "manuel"},
                         entetes={"Content-Type": "text/plain"})[0] == 403
    # Sans en-tête Origin : refusé aussi (un navigateur l'envoie toujours).
    import urllib.request
    req = urllib.request.Request(appli.url + "/api/config", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 403


def test_serveur_lie_a_127_0_0_1(environnement):
    srv = serveur.creer_serveur(0, silencieux=True)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_port_pris_donne_un_autre_port(environnement):
    premier = serveur.creer_serveur(0, silencieux=True)
    try:
        second = serveur.creer_serveur(premier.server_address[1], silencieux=True)
        assert second.server_address[1] != premier.server_address[1]
        second.server_close()
    finally:
        premier.server_close()


def test_csp_et_fichiers_statiques(appli):
    statut, page, entetes = appli.requete("GET", "/")
    assert statut == 200 and b"app.js" in page
    assert "script-src" not in entetes["Content-Security-Policy"]  # default-src 'self' s'applique
    assert "default-src 'self'" in entetes["Content-Security-Policy"]
    assert appli.requete("GET", "/static/../serveur.py")[0] == 404
    assert appli.requete("GET", "/static/app.css")[0] == 200


# ---------------------------------------------------------------- clé DeepSeek (critère 4)

def test_cle_jamais_renvoyee_ni_journalisee(appli, framadate, deepseek, environnement, capsys):
    srv_journal = serveur.creer_serveur(0)  # serveur bavard : on capture son journal
    import threading
    threading.Thread(target=srv_journal.serve_forever, daemon=True).start()
    from outils_app import Client
    bavard = Client(f"http://127.0.0.1:{srv_journal.server_address[1]}")
    try:
        reponses = [bavard.post("/api/config", {"deepseek_cle": CLE})[1],
                    bavard.get_json("/api/etat")[1]]
        deepseek.reponses = [401]
        bavard.post("/api/sondage", {"lien": framadate.lien()})
        reponses.append(bavard.post("/api/regles/proposer", {"moteur": "deepseek"})[1])
    finally:
        srv_journal.shutdown()
        srv_journal.server_close()
    texte = json.dumps(reponses, ensure_ascii=False) + capsys.readouterr().err
    assert reponses[1]["deepseek_cle"] is True
    assert CLE not in texte and "sk-test" not in texte
    assert "refusée" in reponses[2]["message"] and reponses[2]["manuel"]
    # La clé est bien sur le disque, dans la config, hors des données.
    assert CLE in (environnement / "config" / "config.json").read_text(encoding="utf-8")
    assert not any(CLE in p.read_text(encoding="utf-8", errors="ignore")
                   for p in (environnement / "donnees").rglob("*") if p.is_file())


def test_effacer_la_cle(appli):
    appli.post("/api/config", {"deepseek_cle": CLE})
    statut, etat = appli.post("/api/config", {"deepseek_cle": ""})
    assert statut == 200 and etat["deepseek_cle"] is False


def test_moteur_inconnu(appli):
    statut, rep = appli.post("/api/config", {"moteur": "gpt"})
    assert statut == 400


def test_famille_sans_aucune_dispo_recoit_quota_zero(appli, framadate):
    csv, html = framadate.sondages["Test1"]
    framadate.sondages["Vide1"] = (csv.replace("BASILE,Yes,Yes,Yes,No,Yes,No,No,Yes,Yes,Yes",
                                               "BASILE,No,No,No,No,No,No,No,No,No,No"), html)
    appli.post("/api/sondage", {"lien": framadate.lien("Vide1")})
    statut, regles = appli.post("/api/regles/proposer", {"moteur": "manuel"})
    assert {"famille": "BASILE", "type": "quota", "quota": 0} in [
        {k: r[k] for k in ("famille", "type", "quota")} for r in regles["regles"] if r["type"] == "quota"]


def test_sondage_sans_commentaire_n_appelle_pas_l_ia(appli, framadate, deepseek):
    csv, _ = framadate.sondages["Test1"]
    framadate.sondages["Sans1"] = (csv, "<html><head><title>Planning X - Framadate</title></head></html>")
    appli.post("/api/config", {"deepseek_cle": CLE})
    appli.post("/api/sondage", {"lien": framadate.lien("Sans1")})
    statut, regles = appli.post("/api/regles/proposer", {"moteur": "deepseek"})
    assert statut == 200 and deepseek.requetes == [] and "aucun commentaire" in regles["message"]


@pytest.mark.skipif(sys.platform != "win32", reason="journal Windows")
def test_ouvrir_dossier_exige_un_mois(appli):
    assert appli.post("/api/ouvrir-dossier", {})[0] == 409


# ---------------------------------------------------------------- relecture du code

def jusqu_a_l_excel(appli, framadate):
    parcours_jusquau_calcul(appli, framadate, moteur="manuel")
    assert appli.post("/api/calculer", {"regles": [], "non_traduits": [], "reglages": {}})[0] == 200
    assert appli.post("/api/arbitrages", {"arbitrages": None})[0] == 200


def test_calcul_en_echec_invalide_l_ancien(appli, framadate, environnement, monkeypatch):
    jusqu_a_l_excel(appli, framadate)
    dossier = environnement / "donnees" / "2026-11"
    avant = (dossier / "contraintes.yaml").read_text(encoding="utf-8")

    def echec(*a):
        raise ValueError("aucun planning")
    monkeypatch.setattr(serveur.parcours, "calculer", echec)
    regles = [{"famille": "LEA", "type": "quota", "quota": 1}]
    statut, rep = appli.post("/api/calculer", {"regles": regles, "non_traduits": [], "reglages": {}})
    assert statut == 400 and "aucun planning" in rep["erreur"]
    # Aucune étape suivante ne sert l'ancien calcul, et les fichiers restent cohérents.
    assert appli.requete("GET", "/api/excel")[0] == 409
    assert appli.requete("GET", "/arbitrage")[0] == 409
    assert (dossier / "contraintes.yaml").read_text(encoding="utf-8") == avant
    assert (dossier / "planning-final.json").exists()


def test_excel_ouvert_message_clair(appli, framadate, environnement, monkeypatch):
    jusqu_a_l_excel(appli, framadate)
    dossier = environnement / "donnees" / "2026-11"
    final_avant = (dossier / "planning-final.json").read_bytes()

    def verrouille(*a):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(serveur.parcours, "ecrire_excel", verrouille)
    statut, rep = appli.post("/api/arbitrages", {"arbitrages": None})
    assert statut == 409 and "Fermez-le" in rep["erreur"]
    assert (dossier / "planning-final.json").read_bytes() == final_avant
    assert not list(dossier.glob("*.tmp.xlsx"))
    assert appli.requete("GET", "/api/excel")[0] == 409


def test_erreur_interne_n_est_pas_une_requete_illisible(appli, framadate, monkeypatch):
    parcours_jusquau_calcul(appli, framadate, moteur="manuel")

    def casse(*a):
        raise ValueError("bogue")
    monkeypatch.setattr(serveur.parcours, "resumer_calcul", casse)
    statut, rep = appli.post("/api/calculer", {"regles": [], "non_traduits": [], "reglages": {}})
    assert statut == 500 and "illisible" not in rep["erreur"]


def test_corps_illisible(appli):
    statut, brut, _ = appli.requete("POST", "/api/config", entetes={"Content-Type": "application/json"})
    import urllib.request
    req = urllib.request.Request(appli.url + "/api/config", data=b"{pas du json", method="POST",
                                 headers={"Content-Type": "application/json", "Origin": appli.url})
    try:
        urllib.request.urlopen(req, timeout=10)
        code = 200
    except urllib.error.HTTPError as e:
        code, corps = e.code, json.loads(e.read())
    assert code == 400 and corps["erreur"] == "Requête illisible."


def test_cle_fournie_par_l_environnement(appli, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    etat = appli.get_json("/api/etat")[1]
    assert etat["deepseek_cle"] is True and etat["deepseek_cle_environnement"] is True
    assert "sk-env" not in json.dumps(etat)


# ---------------------------------------------------------------- assistants, arrêt, présence (spec V3)

ENDPOINTS_V3 = ["/api/assistants/installer", "/api/assistants/connecter", "/api/assistants/code",
                "/api/assistants/annuler", "/api/presence", "/api/arreter"]


def attendre_travail(appli, assistant, statut, delai=30):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        _, etat = appli.get_json("/api/assistants?rapide=1")
        travail = etat[assistant]["travail"]
        if travail and travail["statut"] == statut:
            return travail
        time.sleep(0.1)
    pytest.fail(f"{assistant} : statut {statut!r} non atteint")


def test_etat_annonce_codex(appli, poste):
    assert appli.get_json("/api/etat")[1]["codex"] is False
    poste.installer("codex")
    assert appli.get_json("/api/etat")[1]["codex"] is True


def test_etat_des_assistants(appli, poste):
    statut, etat = appli.get_json("/api/assistants")
    assert statut == 200
    assert etat["claude"] == {"nom": "Claude", "installe": False, "connecte": None, "abonnement_ok": None, "travail": None}
    poste.installer("claude")
    poste.connecter("claude", "free")
    _, etat = appli.get_json("/api/assistants")
    assert etat["claude"]["installe"] and etat["claude"]["connecte"] is True and etat["claude"]["abonnement_ok"] is False


@pytest.mark.parametrize("chemin", ENDPOINTS_V3)
def test_endpoints_v3_refuses_hors_regles(appli, chemin):
    assert appli.requete("POST", chemin, {}, entetes={"Origin": "https://evil.example"})[0] == 403
    assert appli.requete("POST", chemin, {}, entetes={"Content-Type": "text/plain"})[0] == 403
    assert appli.requete("POST", chemin, {}, entetes={"Host": "evil.example"})[0] == 403


def test_lecture_des_assistants_refusee_hors_hote(appli):
    assert appli.requete("GET", "/api/assistants", entetes={"Host": "evil.example"})[0] == 403


def test_installation_par_l_api(appli, poste, monkeypatch):
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "1")
    statut, rep = appli.post("/api/assistants/installer", {"assistant": "claude"})
    assert statut == 200 and rep["travail"]["statut"] == "en_cours" and rep["travail"]["type"] == "installation"
    assert appli.post("/api/assistants/installer", {"assistant": "claude"})[0] == 409
    attendre_travail(appli, "claude", "termine")
    _, etat = appli.get_json("/api/assistants")
    assert etat["claude"]["installe"] and etat["claude"]["connecte"] is False
    assert appli.post("/api/assistants/installer", {"assistant": "claude"})[0] == 409  # déjà installé


def test_connexion_par_l_api_et_aucune_fuite(appli, poste):
    poste.installer("claude")
    statut, rep = appli.post("/api/assistants/connecter", {"assistant": "claude", "methode": "navigateur"})
    assert statut == 200 and rep["travail"]["methode"] == "navigateur"
    fin = time.monotonic() + 20
    while time.monotonic() < fin and not appli.get_json("/api/assistants?rapide=1")[1]["claude"]["travail"]["lien"]:
        time.sleep(0.1)
    brut = appli.requete("GET", "/api/assistants?rapide=1")[1].decode("utf-8")
    assert "https://claude.com/cai/oauth/authorize" in brut and "evil.example" not in brut
    assert appli.post("/api/assistants/code", {"assistant": "claude", "code": "mon code"})[0] == 400
    assert appli.post("/api/assistants/code", {"assistant": "claude", "code": "abc123"})[0] == 200
    attendre_travail(appli, "claude", "termine")
    for chemin in ("/api/assistants", "/api/etat"):
        brut = appli.requete("GET", chemin)[1].decode("utf-8")
        assert "exemple.invalid" not in brut and "Creche Fictive" not in brut
    assert poste.code_recu() == "abc123"
    _, etat = appli.get_json("/api/assistants")
    assert etat["claude"]["connecte"] and etat["claude"]["abonnement_ok"]


def test_connexion_et_annulation_ne_bloquent_pas_l_application(appli, poste):
    poste.installer("claude")
    appli.post("/api/assistants/connecter", {"assistant": "claude"})
    # Pendant que la connexion attend, le verrou global reste libre et les autres requêtes répondent.
    assert not serveur.ETAT.verrou.locked()
    debut = time.monotonic()
    assert appli.post("/api/config", {"moteur": "manuel"})[0] == 200
    assert time.monotonic() - debut < 5
    statut, rep = appli.post("/api/assistants/annuler", {"assistant": "claude"})
    assert statut == 200 and rep["travail"]["statut"] == "annule"


def test_presence_et_arret_repondent_pendant_une_action_longue(appli):
    with serveur.ETAT.verrou:  # une action de l'application (IA, calcul) tient le verrou
        assert appli.post("/api/presence", {}) == (200, {"ok": True})
        assert appli.post("/api/assistants/annuler", {"assistant": "codex"})[0] == 200


def test_requetes_d_assistant_invalides(appli, poste):
    assert appli.post("/api/assistants/installer", {"assistant": "gemini"})[0] == 400
    assert appli.post("/api/assistants/installer", {})[0] == 400
    assert appli.post("/api/assistants/connecter", {"assistant": "claude"})[0] == 409  # pas installé
    poste.installer("claude")
    assert appli.post("/api/assistants/connecter", {"assistant": "claude", "methode": "x"})[0] == 400
    assert appli.post("/api/assistants/code", {"assistant": "claude", "code": "abc"})[0] == 409  # aucune connexion
    assert appli.post("/api/assistants/annuler", {"assistant": "claude"}) == (200, {"travail": None})


def test_config_accepte_codex(appli):
    statut, etat = appli.post("/api/config", {"moteur": "codex"})
    assert statut == 200 and etat["moteur"] == "codex"


def test_proposition_par_codex(appli, framadate, poste, tmp_path, monkeypatch):
    poste.installer("codex")
    monkeypatch.setenv("FAUX_CODEX_JOURNAL", str(tmp_path / "journal-codex.jsonl"))
    monkeypatch.setenv("FAUX_CODEX_REPONSES", str(tmp_path / "reponses-codex.json"))
    (tmp_path / "reponses-codex.json").write_text(json.dumps([json.dumps(REPONSE_IA)]), encoding="utf-8")
    _, regles = parcours_jusquau_calcul(appli, framadate, moteur="codex")
    assert not regles["manuel"] and regles["moteur"] == "codex"
    assert regles["message"].startswith("Règles proposées par ChatGPT.")
    assert sorted((r["famille"], r["type"]) for r in regles["regles"]) == [
        ("LEA", "au_moins"), ("ZOE", "absence"), ("ZOE", "quota")]


def test_arreter_repond_puis_ferme_le_serveur(appli):
    assert appli.post("/api/arreter", {}) == (200, {"ok": True})
    fin = time.monotonic() + 10
    while time.monotonic() < fin:
        try:
            urllib.request.urlopen(appli.url + "/api/etat", timeout=1)
        except OSError:
            return
        time.sleep(0.1)
    pytest.fail("le serveur répond encore après /api/arreter")


def lancer_serveur():
    srv = serveur.creer_serveur(0, silencieux=True)
    srv.fil = threading.Thread(target=srv.serve_forever, daemon=True)
    srv.fil.start()
    return srv


def fermer_serveur(srv):
    srv.fil.join(timeout=10)  # la boucle doit être finie avant de fermer la socket
    srv.server_close()


def test_arret_seul_apres_inactivite(environnement):
    srv = lancer_serveur()
    serveur.noter_activite()
    serveur.surveiller(srv, 1.0)
    assert srv.arrete.wait(10), "le serveur ne s'est pas arrêté seul"
    fermer_serveur(srv)


def test_une_requete_repousse_l_arret_seul(environnement):
    srv = lancer_serveur()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/etat"
    serveur.noter_activite()
    serveur.surveiller(srv, 1.5)
    for _ in range(6):
        urllib.request.urlopen(url, timeout=2)
        time.sleep(0.5)
    assert not srv.arrete.is_set()
    assert srv.arrete.wait(10)
    fermer_serveur(srv)


def test_pas_d_arret_seul_pendant_un_travail(environnement, poste, monkeypatch):
    """IA en cours (verrou pris) ou installation en cours : l'outil reste, puis le délai repart de zéro."""
    srv = lancer_serveur()
    serveur.noter_activite()
    serveur.surveiller(srv, 1.0)
    with serveur.ETAT.verrou:
        time.sleep(2.5)
        assert not srv.arrete.is_set()
    monkeypatch.setenv("FAUX_INSTALL_DELAI", "2.5")
    assistants.installer("claude")
    time.sleep(2.0)
    assert not srv.arrete.is_set()
    assert srv.arrete.wait(15)
    fermer_serveur(srv)


def test_delai_d_inactivite_par_variable(monkeypatch):
    assert serveur.delai_inactivite() == 600
    monkeypatch.setenv("PLANNING_PERMS_INACTIVITE_S", "42.5")
    assert serveur.delai_inactivite() == 42.5
    for invalide in ("zéro", "0", "-3"):
        monkeypatch.setenv("PLANNING_PERMS_INACTIVITE_S", invalide)
        assert serveur.delai_inactivite() == 600


# ---------------------------------------------------------------- journal sans console (V3-2)

def test_sans_console_tout_va_au_journal(tmp_path, monkeypatch):
    journal = tmp_path / "dossier neuf" / "journal.txt"
    monkeypatch.setenv("PLANNING_PERMS_JOURNAL", str(journal))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        serveur.rediriger_sans_console()
        assert sys.stdout is not None and sys.stdout is sys.stderr
        print("ligne sortie standard")
        sys.stderr.write("GET /api/etat 200\n")
    finally:
        flux = sys.stdout
        monkeypatch.undo()
        if flux is not None:
            flux.close()
    texte = journal.read_text(encoding="utf-8")
    assert "démarrage" in texte and "ligne sortie standard" in texte and "GET /api/etat 200" in texte


def test_journal_remis_a_zero_au_dela_d_un_mo(tmp_path, monkeypatch):
    journal = tmp_path / "journal.txt"
    journal.write_bytes(b"x" * (serveur.JOURNAL_MAX + 10))
    monkeypatch.setenv("PLANNING_PERMS_JOURNAL", str(journal))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        serveur.rediriger_sans_console()
    finally:
        flux = sys.stdout
        monkeypatch.undo()
        flux.close()
    assert 0 < journal.stat().st_size < 1000 and journal.read_text(encoding="utf-8").startswith("--- démarrage")


def test_avec_console_rien_ne_change(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PLANNING_PERMS_JOURNAL", str(tmp_path / "journal.txt"))
    avant = (sys.stdout, sys.stderr)
    serveur.rediriger_sans_console()
    assert (sys.stdout, sys.stderr) == avant and not (tmp_path / "journal.txt").exists()


def test_chemin_du_journal_par_defaut(monkeypatch, tmp_path):
    monkeypatch.delenv("PLANNING_PERMS_JOURNAL", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert serveur.chemin_journal() == tmp_path / "balustrade-planning" / "journal.txt"


def test_le_journal_ne_garde_ni_corps_ni_presence(tmp_path, monkeypatch, capsys, environnement):
    srv = serveur.creer_serveur(0, silencieux=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client = Client(f"http://127.0.0.1:{srv.server_address[1]}")
    client.post("/api/config", {"deepseek_cle": CLE})
    client.post("/api/presence", {})
    client.get_json("/api/assistants?rapide=1")
    client.get_json("/api/etat")
    srv.shutdown()
    srv.server_close()
    sortie = capsys.readouterr().err
    assert "POST /api/config 200" in sortie and "GET /api/etat 200" in sortie
    assert CLE not in sortie and "presence" not in sortie and "/api/assistants" not in sortie


# ---------------------------------------------------------------- navigateur (V3-3)

@pytest.fixture
def dossiers_programmes(tmp_path, monkeypatch):
    for nom in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(nom, str(tmp_path / nom))
    return tmp_path


def poser_chrome(tmp_path, variable):
    chemin = tmp_path / variable / "Google" / "Chrome" / "Application" / "chrome.exe"
    chemin.parent.mkdir(parents=True)
    chemin.write_bytes(b"")
    return str(chemin)


def test_chrome_absent(dossiers_programmes):
    assert serveur.trouver_chrome() is None


@pytest.mark.parametrize("variable", ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"])
def test_chrome_trouve_dans_chaque_dossier_standard(dossiers_programmes, variable):
    attendu = poser_chrome(dossiers_programmes, variable)
    assert serveur.trouver_chrome() == attendu


def test_chrome_ordre_des_dossiers(dossiers_programmes):
    poser_chrome(dossiers_programmes, "LOCALAPPDATA")
    prioritaire = poser_chrome(dossiers_programmes, "ProgramFiles")
    assert serveur.trouver_chrome() == prioritaire


@pytest.mark.skipif(sys.platform != "win32", reason="chemins de Chrome sous Windows")
def test_ouvrir_navigateur_prefere_chrome(dossiers_programmes, monkeypatch):
    chrome = poser_chrome(dossiers_programmes, "ProgramFiles(x86)")
    lances = []
    monkeypatch.setattr(serveur.subprocess, "Popen", lambda args, **kw: lances.append(args))
    monkeypatch.setattr(serveur.webbrowser, "open", lambda url: lances.append(("defaut", url)))
    serveur.ouvrir_navigateur("http://127.0.0.1:8765/")
    assert lances == [[chrome, "http://127.0.0.1:8765/"]]


def test_ouvrir_navigateur_repli_sur_le_navigateur_par_defaut(dossiers_programmes, monkeypatch):
    ouverts = []
    monkeypatch.setattr(serveur.webbrowser, "open", lambda url: ouverts.append(url))
    serveur.ouvrir_navigateur("http://127.0.0.1:8765/")
    assert ouverts == ["http://127.0.0.1:8765/"]


@pytest.mark.skipif(sys.platform != "win32", reason="chemins de Chrome sous Windows")
def test_ouvrir_navigateur_repli_si_chrome_ne_demarre_pas(dossiers_programmes, monkeypatch):
    poser_chrome(dossiers_programmes, "ProgramFiles")
    ouverts = []

    def echec(*a, **kw):
        raise OSError("refusé")
    monkeypatch.setattr(serveur.subprocess, "Popen", echec)
    monkeypatch.setattr(serveur.webbrowser, "open", lambda url: ouverts.append(url))
    serveur.ouvrir_navigateur("http://127.0.0.1:8765/")
    assert ouverts == ["http://127.0.0.1:8765/"]


def test_arreter_tue_les_moteurs_d_ia(appli, monkeypatch):
    tues = []
    monkeypatch.setattr(serveur.moteurs, "tuer_moteurs", lambda: tues.append(1))
    assert appli.post("/api/arreter", {})[0] == 200
    assert tues == [1]
