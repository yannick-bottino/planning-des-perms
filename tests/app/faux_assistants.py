"""Faux `claude` et faux `codex` pour les tests (connexion, état, exécution) et faux installeur.

Deux usages :
- importé : `creer_faux(chemin, "claude" | "codex")` écrit un lanceur (`.cmd` sous Windows, script sh ailleurs)
  qui rappelle ce fichier ;
- lancé : `faux_assistants.py claude|codex <arguments du vrai programme>` ou
  `faux_assistants.py installer <claude|codex> <chemin du lanceur à créer>`.

État partagé dans le dossier FAUX_ASSISTANTS_ETAT : `claude_connecte` (abonnement, texte), `codex_connecte`,
`code_recu` (code lu sur l'entrée du faux `claude auth login`). Réglages par variables d'environnement :
FAUX_LOGIN_DELAI (secondes avant réussite seule ; absent : attend un code sur l'entrée), FAUX_LOGIN_ECHEC=1,
FAUX_ABONNEMENT (défaut « team »), FAUX_INSTALL_DELAI, FAUX_INSTALL_ECHEC=1. Pour `codex exec` :
FAUX_CODEX_JOURNAL, FAUX_CODEX_REPONSES (liste JSON ; « ERREUR » et « LENT » comme faux_claude.py).
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

ICI = Path(__file__).resolve()


def creer_faux(chemin: Path, nom: str) -> Path:
    """Écrit le lanceur du faux programme `nom` à `chemin` (le dossier est créé si besoin)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        chemin.write_text(f'@"{sys.executable}" "{ICI}" {nom} %*\r\n', encoding="utf-8")
    else:
        chemin.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{ICI}" {nom} "$@"\n')
        chemin.chmod(0o755)
    return chemin


def etat_dir() -> Path:
    return Path(os.environ["FAUX_ASSISTANTS_ETAT"])


def ecrire(texte: str, fin: str = "\n") -> None:
    sys.stdout.buffer.write((texte + fin).encode("utf-8"))
    sys.stdout.buffer.flush()


def attendre_connexion(nom: str, abonnement: str) -> None:
    """Réussit après FAUX_LOGIN_DELAI secondes, ou dès qu'une ligne arrive sur l'entrée."""
    recu = threading.Event()

    def lire():
        ligne = sys.stdin.buffer.readline().decode("utf-8").strip()
        if ligne:
            (etat_dir() / "code_recu").write_text(ligne, encoding="utf-8")
            recu.set()
    threading.Thread(target=lire, daemon=True).start()
    delai = os.environ.get("FAUX_LOGIN_DELAI")
    recu.wait(float(delai) if delai else None)
    if os.environ.get("FAUX_LOGIN_ECHEC") == "1":
        sys.exit(1)
    (etat_dir() / f"{nom}_connecte").write_text(abonnement, encoding="utf-8")


def claude(args: list[str]) -> int:
    abonnement = os.environ.get("FAUX_ABONNEMENT", "team")
    if args[:2] == ["auth", "status"]:
        fichier = etat_dir() / "claude_connecte"
        if not fichier.exists():
            ecrire(json.dumps({"loggedIn": False, "authMethod": "none"}))
            return 1
        # Courriel et organisation : l'outil ne doit jamais les renvoyer au navigateur.
        ecrire(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
                           "email": "prenom.nom@exemple.invalid", "orgName": "Creche Fictive",
                           "subscriptionType": fichier.read_text(encoding="utf-8")}))
        return 0
    if args[:2] == ["auth", "login"]:
        ecrire("Opening browser to sign in…")
        ecrire("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&state=abc")
        ecrire("Autre lien non fiable : https://evil.example/hameçon et http://claude.com/clair")
        ecrire("Paste code here if prompted > ", fin="")
        attendre_connexion("claude", abonnement)
        ecrire("\nLogin successful.")
        return 0
    return 2


def codex(args: list[str]) -> int:
    if args[:2] == ["login", "status"]:
        if (etat_dir() / "codex_connecte").exists():
            ecrire("Logged in using ChatGPT")
            return 0
        ecrire("Not logged in")
        return 1
    if args[:1] == ["login"] and "--device-auth" in args:
        ecrire("\x1b[1mWelcome to Codex\x1b[0m")
        ecrire("1. Open this link in your browser and sign in: \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m")
        ecrire("2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m")
        ecrire("   \x1b[94mPVRM-K4VLO\x1b[0m")
        attendre_connexion("codex", "")
        return 0
    if args[:1] == ["login"]:
        ecrire("Starting local login server on http://localhost:1455.")
        ecrire("If your browser did not open, navigate to this URL to authenticate:")
        ecrire("")
        ecrire("https://auth.openai.com/oauth/authorize?client_id=x&state=y")
        attendre_connexion("codex", "")
        ecrire("Successfully logged in")
        return 0
    if args[:1] == ["exec"]:
        consigne = sys.stdin.buffer.read().decode("utf-8")
        journal = Path(os.environ["FAUX_CODEX_JOURNAL"])
        with journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"args": args, "consigne": consigne, "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
        n = len(journal.read_text(encoding="utf-8").splitlines())
        reponses = json.loads(Path(os.environ["FAUX_CODEX_REPONSES"]).read_text(encoding="utf-8"))
        reponse = reponses[min(n, len(reponses)) - 1]
        if reponse == "LENT":
            time.sleep(60)
        if reponse == "ERREUR":
            sys.stderr.write("ERROR: not logged in\n")
            return 1
        sortie = args[args.index("-o") + 1]
        Path(sortie).write_text(reponse, encoding="utf-8")
        ecrire("bruit de progression qui n'est pas la réponse")
        return 0
    return 2


def installeur(nom: str, cible: str) -> int:
    time.sleep(float(os.environ.get("FAUX_INSTALL_DELAI", "0")))
    if os.environ.get("FAUX_INSTALL_ECHEC") == "1":
        sys.stderr.write("Download failed\n")
        return 1
    ecrire(f"Installing {nom}...")
    creer_faux(Path(cible), nom)
    return 0


if __name__ == "__main__":
    mode, reste = sys.argv[1], sys.argv[2:]
    try:
        code = installeur(reste[0], reste[1]) if mode == "installer" else {"claude": claude, "codex": codex}[mode](reste)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    sys.stdout.flush()
    # Sortie directe : un fil resté bloqué sur l'entrée standard fait planter l'arrêt normal de Python sous Windows.
    os._exit(code)


class Poste:
    """Un ordinateur fictif : faux claude et faux codex absents au départ, installables et connectables."""

    def __init__(self, racine: Path, monkeypatch):
        extension = ".cmd" if sys.platform == "win32" else ""
        self.bin, self.etat = racine / "bin-faux", racine / "etat-faux"
        self.etat.mkdir(parents=True, exist_ok=True)
        self.exe = {"claude": self.bin / f"claude{extension}", "codex": self.bin / f"codex{extension}"}
        monkeypatch.setenv("FAUX_ASSISTANTS_ETAT", str(self.etat))
        for nom, exe in self.exe.items():
            monkeypatch.setenv(f"PLANNING_PERMS_{nom.upper()}", str(exe))
            monkeypatch.setenv(f"PLANNING_PERMS_INSTALLEUR_{nom.upper()}",
                               json.dumps([sys.executable, str(ICI), "installer", nom, str(exe)]))

    def installer(self, nom: str) -> None:
        creer_faux(self.exe[nom], nom)

    def connecter(self, nom: str, abonnement: str = "team") -> None:
        (self.etat / f"{nom}_connecte").write_text(abonnement, encoding="utf-8")

    def code_recu(self) -> str | None:
        fichier = self.etat / "code_recu"
        return fichier.read_text(encoding="utf-8") if fichier.exists() else None
