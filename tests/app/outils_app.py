"""Outils partagés des tests V2 : faux Framadate, faux DeepSeek, client HTTP.

Nom unique (pas `conftest`) : `tests/e2e/conftest.py` existe aussi et masquerait l'import."""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
FIXTURES = SKILL / "tests" / "fixtures"
sys.path.insert(0, str(SKILL / "app"))
sys.path.insert(0, str(SKILL / "scripts"))

# Réponse d'IA valable pour fixtures/poll.* (prénoms fictifs).
REPONSE_IA = {
    "familles": {
        "LEA": {"au_moins": {"n": 1, "parmi": [{"jour": "lundi", "demi": "M"}]},
                "source": "Léa, 11/10 : si possible un lundi matin"},
        "ZOE": {"absences": ["2026-11-09"], "quota_mois": 2,
                "source": "zoé, 15/10 : congés la semaine du 9 novembre, 2 perms ensuite"},
    },
    "commentaires_non_traduits": ["INCONNU : absents du mercredi 11 au vendredi 13"],
}


def _demarrer(gestionnaire) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gestionnaire)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class FauxFramadate:
    """Sert /polls/<id>.csv et /polls/<id>. Sondages : id -> (csv, html)."""

    def __init__(self):
        self.sondages = {"Test1": ((FIXTURES / "poll.csv").read_text(encoding="utf-8"),
                                   (FIXTURES / "poll.html").read_text(encoding="utf-8"))}
        faux = self

        class G(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                chemin = self.path.split("?")[0]
                pid = chemin.removeprefix("/polls/").removesuffix(".csv")
                if not chemin.startswith("/polls/") or pid not in faux.sondages:
                    self.send_response(404)
                    self.end_headers()
                    return
                corps = faux.sondages[pid][1 if not chemin.endswith(".csv") else 0].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

        self.srv, self.url = _demarrer(G)

    def lien(self, pid: str = "Test1") -> str:
        return f"{self.url}/polls/{pid}"


class FauxDeepSeek:
    """API compatible OpenAI. `reponses` : contenus renvoyés dans l'ordre (le dernier se répète).
    Un entier renvoie ce code d'erreur HTTP, avec un corps qui cite la clé (test de fuite)."""

    def __init__(self):
        self.reponses: list = [json.dumps(REPONSE_IA)]
        self.requetes: list[dict] = []
        faux = self

        class G(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                faux.requetes.append({"auth": self.headers.get("Authorization"), "corps": corps})
                rep = faux.reponses[min(len(faux.requetes), len(faux.reponses)) - 1]
                if isinstance(rep, int):
                    donnees = json.dumps({"error": {"message": f"invalid key {self.headers.get('Authorization')}"}})
                    statut = rep
                else:
                    donnees = json.dumps({"choices": [{"message": {"content": rep}, "finish_reason": "stop"}]})
                    statut = 200
                b = donnees.encode("utf-8")
                self.send_response(statut)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.srv, self.url = _demarrer(G)


class Client:
    """Petit client HTTP qui imite le navigateur (Origin, JSON)."""

    def __init__(self, url: str):
        self.url = url

    def requete(self, methode: str, chemin: str, corps=None, entetes=None):
        donnees = None if corps is None else json.dumps(corps).encode("utf-8")
        h = {"Origin": self.url}
        if corps is not None:
            h["Content-Type"] = "application/json"
        h.update(entetes or {})
        req = urllib.request.Request(self.url + chemin, data=donnees, method=methode, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as rep:
                return rep.status, rep.read(), dict(rep.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def post(self, chemin: str, corps: dict, **kw):
        statut, brut, _ = self.requete("POST", chemin, corps, **kw)
        return statut, json.loads(brut or b"{}")

    def get_json(self, chemin: str):
        statut, brut, _ = self.requete("GET", chemin)
        return statut, json.loads(brut or b"{}")
