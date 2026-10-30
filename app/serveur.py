# /// script
# requires-python = ">=3.11,<3.15"
# dependencies = [
#   "ortools==9.15.6755",
#   "pyyaml>=6",
#   "openpyxl>=3.1",
# ]
# ///
"""Application locale du planning des permanences (spec V2). Lancement : `uv run app/serveur.py`.

Serveur de la bibliothèque standard, lié à 127.0.0.1 uniquement.
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser  # noqa: F401 (les tests le remplacent : voir demarrer.ouvrir_navigateur)
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assistants  # noqa: E402
import demarrer  # noqa: E402
import moteurs  # noqa: E402
import parcours  # noqa: E402
import reglages  # noqa: E402

# Journal et navigateur vivent dans demarrer.py (sans dépendance lourde) ; noms gardés ici pour les tests.
from demarrer import (JOURNAL_MAX, chemin_journal, chemins_chrome, ouvrir_navigateur,  # noqa: E402,F401
                      rediriger_sans_console, trouver_chrome)

STATIQUE = Path(__file__).resolve().parent / "static"
PORT_DEFAUT = 8765
APPLICATION = "planning-perms"
CSP_APP = "default-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
# La page d'arbitrage V1 contient ses scripts en ligne : seule la protection anti-cadre s'applique.
CSP_ARBITRAGE = "frame-ancestors 'self'; object-src 'none'; base-uri 'none'"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
TAILLE_MAX = 2_000_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
INACTIVITE_DEFAUT_S = 600
# Requêtes qui n'attendent pas l'action en cours (une IA peut tenir le verrou plusieurs minutes).
SANS_VERROU = frozenset({"/api/assistants/installer", "/api/assistants/connecter", "/api/assistants/code",
                         "/api/assistants/annuler", "/api/presence", "/api/arreter"})
# Trop fréquentes pour le journal (une par minute, une par seconde pendant une installation).
SANS_JOURNAL = frozenset({"/api/presence", "/api/assistants"})


class Etat:
    """Travail en cours (un seul mois à la fois). Les fichiers du mois sont la trace durable."""

    def __init__(self):
        self.verrou = threading.Lock()
        self.vider()

    def vider(self):
        self.sondage = self.mois = self.dossier = None
        self.contraintes = self.planning = self.final = None
        self.proposition = None

    def exiger(self, *attributs):
        for a in attributs:
            if getattr(self, a) is None:
                raise ErreurRequete("Cette étape n'est pas encore disponible. Reprenez à l'étape précédente.",
                                    HTTPStatus.CONFLICT)


class ErreurRequete(Exception):
    def __init__(self, message: str, statut=HTTPStatus.BAD_REQUEST, **extra):
        super().__init__(message)
        self.statut, self.extra = statut, extra


ETAT = Etat()
ACTIVITE = {"derniere": time.monotonic()}


def noter_activite():
    ACTIVITE["derniere"] = time.monotonic()


# ---------------------------------------------------------------- actions

def action_etat(_corps):
    return {"application": APPLICATION, **reglages.etat_public(),
            "deepseek_cle_environnement": not reglages.lire_config().get("deepseek_cle")
            and bool(os.environ.get("DEEPSEEK_API_KEY")), "claude": bool(moteurs.commande_claude()),
            "codex": bool(moteurs.commande_codex()), "dossier_donnees": str(reglages.dossier_donnees())}


def action_config(corps):
    try:
        reglages.enregistrer(corps.get("moteur"), corps.get("deepseek_cle"))
    except ValueError as e:
        raise ErreurRequete(str(e)) from None
    return action_etat(corps)


def action_sondage(corps):
    try:
        sondage = parcours.charger_sondage(str(corps.get("lien") or ""))
        mois = parcours.mois_du_sondage(sondage)
        if not sondage["familles"]:
            raise ValueError("aucune famille n'a encore répondu")
    except ValueError as e:
        raise ErreurRequete(f"Le sondage n'a pas pu être lu : {e}") from None
    except OSError as e:
        raise ErreurRequete("Le sondage n'a pas pu être téléchargé. Vérifiez le lien et la connexion "
                            f"internet ({getattr(e, 'reason', e)}).") from None
    dossier = reglages.dossier_donnees() / mois
    dossier.mkdir(parents=True, exist_ok=True)
    parcours.ecrire_json(dossier / "sondage.json", sondage)
    ETAT.vider()
    ETAT.sondage, ETAT.mois, ETAT.dossier = sondage, mois, dossier
    return {"mois": mois, "dossier": str(dossier), "resume": parcours.resumer(sondage),
            "options": parcours.options(sondage)}


def action_proposer(corps):
    ETAT.exiger("sondage")
    choix = corps.get("moteur") or reglages.etat_public()["moteur"] or "manuel"
    if choix == "claude":
        moteur = moteurs.MoteurClaude(ETAT.dossier)
    elif choix == "codex":
        moteur = moteurs.MoteurCodex(ETAT.dossier)
    elif choix == "deepseek":
        moteur = moteurs.MoteurDeepSeek(reglages.cle_deepseek())
    elif choix == "manuel":
        moteur = None
    else:
        raise ErreurRequete(f"Moteur inconnu : {choix}")
    if moteur is None:
        resultat = {"brut": {}, "moteur": "manuel", "essais": 0, "manuel": True,
                    "message": "Saisissez les règles à la main à partir des commentaires."}
    elif not ETAT.sondage.get("commentaires"):
        resultat = {"brut": {}, "moteur": choix, "essais": 0, "manuel": False,
                    "message": "Le sondage ne contient aucun commentaire : aucune règle à proposer."}
    else:
        resultat = moteurs.proposer(moteur, ETAT.sondage)
    ETAT.proposition = resultat
    lignes = parcours.regles_depuis_contraintes(resultat["brut"])
    lignes["regles"] += parcours.regles_sans_reponse(ETAT.sondage, lignes["regles"])
    return {**{k: v for k, v in resultat.items() if k != "brut"}, **lignes}


def action_calculer(corps):
    ETAT.exiger("sondage")
    try:
        brut, contraintes = parcours.valider_regles(corps, ETAT.sondage)
    except parcours.ErreurRegle as e:
        raise ErreurRequete(str(e), index=e.index) from None
    # Un nouveau calcul invalide l'ancien, qu'il réussisse ou non : aucune étape suivante
    # ne doit servir un planning calculé avec d'autres règles.
    ETAT.contraintes = ETAT.planning = ETAT.final = None
    try:
        planning = parcours.calculer(ETAT.sondage, contraintes)
        page = parcours.page_arbitrage(planning, ETAT.sondage, contraintes)
    except ValueError as e:
        raise ErreurRequete(f"Le calcul a échoué : {e}") from None
    # Fichiers écrits seulement après un calcul réussi, pour rester cohérents avec la V1.
    for perime in ("arbitrages.json", "planning-final.json"):
        (ETAT.dossier / perime).unlink(missing_ok=True)
    parcours.ecrire_contraintes(ETAT.dossier / "contraintes.yaml", brut)
    parcours.ecrire_json(ETAT.dossier / "planning.json", planning)
    (ETAT.dossier / "arbitrage.html").write_text(page, encoding="utf-8")
    ETAT.contraintes, ETAT.planning = contraintes, planning
    return parcours.resumer_calcul(planning)


def action_arbitrages(corps):
    ETAT.exiger("planning")
    arbitrages = corps.get("arbitrages")
    if arbitrages is not None and not isinstance(arbitrages, dict):
        raise ErreurRequete("Fichier de choix illisible.")
    try:
        final = parcours.finaliser(ETAT.planning, arbitrages, ETAT.sondage, ETAT.contraintes)
    except ValueError as e:
        raise ErreurRequete(f"Les choix de l'arbitrage n'ont pas pu être appliqués : {e}") from None
    ETAT.final = None
    excel = ETAT.dossier / parcours.nom_excel(ETAT.mois)
    temporaire = excel.with_name(excel.stem + ".tmp.xlsx")
    try:
        parcours.ecrire_excel(final, temporaire)
        os.replace(temporaire, excel)
    except PermissionError:
        temporaire.unlink(missing_ok=True)
        raise ErreurRequete(f"Le fichier {excel.name} est ouvert dans Excel ou un autre logiciel. "
                            "Fermez-le, puis cliquez de nouveau.", HTTPStatus.CONFLICT) from None
    if arbitrages is not None:
        parcours.ecrire_json(ETAT.dossier / "arbitrages.json", arbitrages)
    else:
        (ETAT.dossier / "arbitrages.json").unlink(missing_ok=True)
    parcours.ecrire_json(ETAT.dossier / "planning-final.json", final)
    ETAT.final = final
    return {**parcours.bilan(final, ETAT.sondage), "fichier": parcours.nom_excel(ETAT.mois),
            "dossier": str(ETAT.dossier),
            "changements": len((arbitrages or {}).get("changements") or [])}


def action_ouvrir_dossier(_corps):
    ETAT.exiger("dossier")
    chemin = str(ETAT.dossier)
    if sys.platform == "win32":
        os.startfile(chemin)  # noqa: S606 (dossier local de l'utilisatrice)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", chemin])
    return {"ok": True}


def assistant_demande(corps) -> str:
    nom = corps.get("assistant")
    if nom not in assistants.ASSISTANTS:
        raise ErreurRequete("Assistant inconnu.")
    return nom


def appel_assistant(fonction, *args):
    try:
        return fonction(*args)
    except assistants.ErreurAssistant as e:
        raise ErreurRequete(str(e), HTTPStatus.CONFLICT if e.conflit else HTTPStatus.BAD_REQUEST) from None


def action_installer(corps):
    return {"travail": appel_assistant(assistants.installer, assistant_demande(corps))}


def action_connecter(corps):
    methode = corps.get("methode") or "navigateur"
    return {"travail": appel_assistant(assistants.connecter, assistant_demande(corps), methode)}


def action_code(corps):
    appel_assistant(assistants.envoyer_code, assistant_demande(corps), corps.get("code"))
    return {"ok": True}


def action_annuler(corps):
    return {"travail": assistants.annuler(assistant_demande(corps))}


def action_presence(_corps):
    return {"ok": True}


def action_arreter(_corps):
    moteurs.tuer_moteurs()  # une IA en cours ne doit pas survivre à l'outil
    return {"ok": True}  # l'arrêt lui-même a lieu après l'envoi de la réponse (do_POST)


ACTIONS = {
    "/api/config": action_config,
    "/api/assistants/installer": action_installer,
    "/api/assistants/connecter": action_connecter,
    "/api/assistants/code": action_code,
    "/api/assistants/annuler": action_annuler,
    "/api/presence": action_presence,
    "/api/arreter": action_arreter,
    "/api/sondage": action_sondage,
    "/api/regles/proposer": action_proposer,
    "/api/calculer": action_calculer,
    "/api/arbitrages": action_arbitrages,
    "/api/ouvrir-dossier": action_ouvrir_dossier,
}


# ---------------------------------------------------------------- HTTP

class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "planning-perms"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 (signature imposée)
        # Ligne de requête seulement : les corps (clé DeepSeek comprise) ne sont jamais journalisés.
        if not self.server.silencieux and self.path.split("?")[0] not in SANS_JOURNAL:
            sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def _hote_valide(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _envoyer(self, statut, corps: bytes, type_: str, entetes: dict | None = None):
        self.send_response(statut)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        if "Content-Security-Policy" not in (entetes or {}):
            self.send_header("Content-Security-Policy", CSP_APP)
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, statut, donnees: dict):
        self._envoyer(statut, json.dumps(donnees, ensure_ascii=False).encode("utf-8"),
                      "application/json; charset=utf-8")

    def _refuser(self):
        self._json(HTTPStatus.FORBIDDEN, {"erreur": "Requête refusée."})

    def do_GET(self):  # noqa: N802
        if not self._hote_valide():
            return self._refuser()
        noter_activite()
        chemin, _, requete = self.path.partition("?")
        if chemin == "/api/etat":
            return self._json(HTTPStatus.OK, action_etat({}))
        if chemin == "/api/assistants":
            return self._json(HTTPStatus.OK, assistants.etat_assistants("rapide=1" in requete.split("&")))
        if chemin == "/arbitrage":
            if ETAT.planning is None:
                return self._json(HTTPStatus.CONFLICT, {"erreur": "Aucun planning calculé."})
            page = (ETAT.dossier / "arbitrage.html").read_bytes()
            return self._envoyer(HTTPStatus.OK, page, TYPES[".html"],
                                 {"Content-Security-Policy": CSP_ARBITRAGE})
        if chemin == "/api/excel":
            if ETAT.final is None:
                return self._json(HTTPStatus.CONFLICT, {"erreur": "Aucun Excel produit."})
            nom = parcours.nom_excel(ETAT.mois)
            return self._envoyer(HTTPStatus.OK, (ETAT.dossier / nom).read_bytes(), XLSX,
                                 {"Content-Disposition": f'attachment; filename="{nom}"'})
        fichier = "index.html" if chemin == "/" else chemin.removeprefix("/static/")
        cible = (STATIQUE / fichier).resolve()
        if (chemin == "/" or chemin.startswith("/static/")) and cible.is_file() \
                and cible.parent == STATIQUE.resolve() and cible.suffix in TYPES:
            return self._envoyer(HTTPStatus.OK, cible.read_bytes(), TYPES[cible.suffix])
        self._json(HTTPStatus.NOT_FOUND, {"erreur": "Page introuvable."})

    def do_POST(self):  # noqa: N802
        # Les navigateurs envoient toujours Origin sur un POST : son absence trahit un appel étranger.
        origine = self.headers.get("Origin")
        port = self.server.server_address[1]
        if (not self._hote_valide()
                or origine not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
                or not self.headers.get("Content-Type", "").startswith("application/json")):
            # Corps lu avant le refus : fermer sur des octets non lus fait réinitialiser la connexion
            # (Windows), et le navigateur ne verrait pas la réponse.
            try:
                self.rfile.read(min(int(self.headers.get("Content-Length") or 0), TAILLE_MAX))
            except (ValueError, OSError):
                pass
            return self._refuser()
        noter_activite()
        chemin = self.path.split("?")[0]
        action = ACTIONS.get(chemin)
        if action is None:
            return self._json(HTTPStatus.NOT_FOUND, {"erreur": "Action inconnue."})
        try:
            try:
                taille = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ErreurRequete("Requête illisible.") from None
            if taille > TAILLE_MAX:
                raise ErreurRequete("Requête trop volumineuse.")
            try:
                corps = json.loads(self.rfile.read(taille) or b"{}")
            except ValueError:  # UnicodeDecodeError et JSONDecodeError en héritent
                raise ErreurRequete("Requête illisible.") from None
            if not isinstance(corps, dict):
                raise ErreurRequete("Requête illisible.")
            if chemin in SANS_VERROU:
                reponse = action(corps)
            else:
                with ETAT.verrou:
                    reponse = action(corps)
        except ErreurRequete as e:
            return self._json(e.statut, {"erreur": str(e), **e.extra})
        except Exception as e:  # noqa: BLE001 (message lisible plutôt qu'une connexion coupée)
            sys.stderr.write(f"Erreur interne : {type(e).__name__}\n")
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                              {"erreur": "Erreur inattendue de l'application. Relancez-la, "
                                         "puis recommencez l'étape."})
        self._json(HTTPStatus.OK, reponse)
        if chemin == "/api/arreter":
            self.server.demander_arret()


class ServeurLocal(ThreadingHTTPServer):
    # Sous Windows, SO_REUSEADDR laisse deux serveurs partager le même port sans erreur :
    # on le désactive pour que le repli sur un port libre fonctionne.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.arrete = threading.Event()

    def demander_arret(self):
        """`shutdown` attend la fin de la boucle : appelé depuis un fil de requête, il part dans un fil à part."""
        if not self.arrete.is_set():
            self.arrete.set()
            threading.Thread(target=self.shutdown, daemon=True).start()


def creer_serveur(port: int = PORT_DEFAUT, silencieux: bool = False) -> ServeurLocal:
    """Serveur lié à 127.0.0.1. Port demandé, ou un port libre s'il est pris (V2-3)."""
    try:
        serveur = ServeurLocal(("127.0.0.1", port), Gestionnaire)
    except OSError:
        serveur = ServeurLocal(("127.0.0.1", 0), Gestionnaire)
    serveur.silencieux = silencieux
    return serveur


def instance_existante(port: int) -> bool:
    """Vrai si l'application tourne déjà sur ce port (double-clic répété sur lancer.bat)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=1) as rep:
            return json.loads(rep.read().decode("utf-8")).get("application") == APPLICATION
    except (OSError, ValueError):
        return False


def delai_inactivite() -> float:
    try:
        delai = float(os.environ.get("PLANNING_PERMS_INACTIVITE_S") or INACTIVITE_DEFAUT_S)
    except ValueError:
        return INACTIVITE_DEFAUT_S
    return delai if delai > 0 else INACTIVITE_DEFAUT_S


def surveiller(serveur: ServeurLocal, delai_s: float) -> threading.Thread:
    """Arrêt seul (V3-4) : aucune requête depuis `delai_s` secondes et aucun travail en cours
    (action de l'application, IA comprise, installation ou connexion). Un travail en cours compte
    comme une activité : le délai repart de zéro à sa fin."""
    pas = max(0.1, min(5.0, delai_s / 4))

    def boucle():
        while not serveur.arrete.wait(pas):
            if ETAT.verrou.locked() or assistants.travail_en_cours():
                noter_activite()
            elif time.monotonic() - ACTIVITE["derniere"] > delai_s:
                sys.stderr.write("Arrêt : aucune activité.\n")
                serveur.demander_arret()
    fil = threading.Thread(target=boucle, daemon=True)
    fil.start()
    return fil


def main() -> int:
    port = int(os.environ.get("PLANNING_PERMS_PORT") or PORT_DEFAUT)
    # Journal après le contrôle de l'instance : un second lancement ne doit pas toucher au journal de la première.
    deja = instance_existante(port)
    if not deja:
        rediriger_sans_console()
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if deja:
        print("L'application est déjà lancée : elle s'ouvre dans votre navigateur.")
        if not os.environ.get("PLANNING_PERMS_SANS_NAVIGATEUR"):
            ouvrir_navigateur(f"http://127.0.0.1:{port}/")
        return 0
    serveur = creer_serveur(port)
    adresse = f"http://127.0.0.1:{serveur.server_address[1]}/"
    print("Planning des permanences : l'application est ouverte dans votre navigateur.")
    print(f"Adresse : {adresse}")
    # Sans console (raccourci du bureau), il n'y a pas de fenêtre à fermer.
    fenetre = "" if demarrer.ETAT_CONSOLE["sans"] else ", ou fermez cette fenêtre"
    print(f"Pour arrêter l'application, cliquez sur « Fermer l'outil » dans la page{fenetre}.", flush=True)
    if not os.environ.get("PLANNING_PERMS_SANS_NAVIGATEUR"):
        threading.Timer(0.5, ouvrir_navigateur, args=(adresse,)).start()
    surveiller(serveur, delai_inactivite())
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 (la trace va au journal : sans console, personne ne la verrait)
        traceback.print_exc()
        return 1
    finally:
        serveur.arrete.set()
        assistants.tout_annuler()
        moteurs.tuer_moteurs()
        serveur.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
