"""Assistants d'IA installés sur le poste : détection, installation, connexion (spec V3, V3-7 à V3-12).

Claude (Claude Code) et ChatGPT (Codex) sont deux programmes en ligne de commande. Ce module les
trouve, les installe et ouvre la connexion au compte, en tâche de fond : la page lit l'état par
interrogations régulières. Un seul travail à la fois par assistant. Aucun courriel, aucune
organisation, aucun jeton ne sort d'ici : le navigateur ne reçoit que des états et des liens filtrés.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import moteurs

ASSISTANTS = ("claude", "codex")
NOMS = {"claude": "Claude", "codex": "ChatGPT"}
EXECUTABLES = {"claude": "claude", "codex": "codex"}
VARIABLES_EXE = {"claude": "PLANNING_PERMS_CLAUDE", "codex": "PLANNING_PERMS_CODEX"}
VARIABLES_INSTALLEUR = {"claude": "PLANNING_PERMS_INSTALLEUR_CLAUDE", "codex": "PLANNING_PERMS_INSTALLEUR_CODEX"}
SCRIPTS_INSTALLATION = {"claude": "irm https://claude.ai/install.ps1 | iex",
                        "codex": "irm https://chatgpt.com/codex/install.ps1 | iex"}
# Abonnements Claude qui incluent Claude Code (V3-11). « free » est refusé ; une valeur inconnue passe.
ABONNEMENTS_CLAUDE_REFUSES = {"free"}
DELAI_ETAT_S = 30
DELAI_INSTALLATION_S = 900
DELAI_CONNEXION_S = 900
# Domaines dont les liens peuvent être affichés (V3-12), sous-domaines compris.
DOMAINES_LIENS = ("claude.com", "claude.ai", "anthropic.com", "openai.com", "chatgpt.com")
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AUTORITE = re.compile(r"[A-Za-z0-9.-]+(?::443)?")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
LIEN = re.compile(r"https?://[^\s<>\"']+")
CODE_APPAREIL = re.compile(r"^[A-Z0-9]{4,}-[A-Z0-9]{4,}$")
MAX_LIGNE = 4000
MAX_CODE = 2000


class ErreurAssistant(Exception):
    """Demande impossible (assistant inconnu, absent, travail déjà en cours). Message lisible."""

    def __init__(self, message: str, conflit: bool = False):
        super().__init__(message)
        self.conflit = conflit


# ---------------------------------------------------------------- détection (V3-7)

def chemins_connus(assistant: str) -> list[Path]:
    """Emplacements des installeurs officiels. Le PATH du processus n'est pas rafraîchi après une
    installation : on les vérifie en plus du PATH. Variables lues à chaque appel (tests)."""
    profil = Path(os.environ.get("USERPROFILE") or Path.home())
    if assistant == "claude":
        return [profil / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude")]
    local = os.environ.get("LOCALAPPDATA")
    if assistant == "codex" and local:
        dossier = Path(local) / "Programs" / "OpenAI" / "Codex" / "bin"
        return [dossier / "codex.exe"]
    return []


def commande(assistant: str) -> str | None:
    """Chemin de l'exécutable : variable d'environnement, puis PATH, puis emplacements connus.
    Une variable renseignée est seule prise en compte (elle sert à imposer un faux exécutable)."""
    imposee = os.environ.get(VARIABLES_EXE[assistant])
    if imposee:
        return imposee if Path(imposee).is_file() else None
    trouve = shutil.which(EXECUTABLES[assistant])
    if trouve:
        return trouve
    for chemin in chemins_connus(assistant):
        if chemin.is_file():
            return str(chemin)
    return None


def lancer_court(args: list[str], delai: float = DELAI_ETAT_S) -> subprocess.CompletedProcess | None:
    """Commande courte et muette. None si elle ne démarre pas ou dépasse le délai."""
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=delai,
                              creationflags=SANS_FENETRE)
    except (OSError, subprocess.TimeoutExpired):
        return None


def etat_connexion(assistant: str) -> dict:
    """{connecte, abonnement}. `abonnement` : texte du CLI Claude, None pour ChatGPT. Ni courriel
    ni organisation : seuls ces deux champs sont lus."""
    exe = commande(assistant)
    if not exe:
        return {"connecte": False, "abonnement": None}
    if assistant == "claude":
        r = lancer_court([exe, "auth", "status", "--json"])
        if r is None:
            return {"connecte": False, "abonnement": None}
        try:
            donnees = json.loads(r.stdout.decode("utf-8", "replace"))
        except ValueError:
            return {"connecte": False, "abonnement": None}
        if not isinstance(donnees, dict) or donnees.get("loggedIn") is not True or r.returncode != 0:
            return {"connecte": False, "abonnement": None}
        abonnement = donnees.get("subscriptionType")
        return {"connecte": True, "abonnement": abonnement.lower() if isinstance(abonnement, str) else None}
    r = lancer_court([exe, "login", "status"])
    return {"connecte": bool(r is not None and r.returncode == 0), "abonnement": None}


def abonnement_ok(assistant: str, abonnement: str | None) -> bool:
    """Faux seulement pour un abonnement Claude gratuit (V3-11)."""
    return not (assistant == "claude" and abonnement in ABONNEMENTS_CLAUDE_REFUSES)


def message_gratuit(assistant: str) -> str:
    if assistant == "claude":
        return ("Ce compte Claude est gratuit : il ne permet pas d'utiliser l'assistant ici. "
                "Il faut un abonnement Pro, Max, Team ou Enterprise.")
    return "Ce compte ne permet pas d'utiliser l'assistant ici. Il faut un abonnement ChatGPT Plus ou supérieur."


# ---------------------------------------------------------------- texte de sortie (V3-12)

def nettoyer(texte: str) -> str:
    """Sortie d'un programme : codes de couleur retirés, caractères de contrôle retirés."""
    texte = ANSI.sub("", texte)
    return "".join(c for c in texte if c in "\t" or c >= " ").strip()[:MAX_LIGNE]


def lien_autorise(lien: str) -> bool:
    """Seuls les liens https vers les domaines des deux éditeurs sont rendus cliquables."""
    if len(lien) > 4096 or any(c.isspace() or ord(c) < 32 for c in lien):
        return False
    # Un navigateur lit « \\ » comme « / » et décode « %2F » : un hôte n'a rien à faire de ces signes.
    if "\\" in lien:
        return False
    try:
        u = urlparse(lien)
    except ValueError:
        return False
    hote = (u.hostname or "").lower()
    if u.scheme != "https" or not hote or not AUTORITE.fullmatch(u.netloc):
        return False
    return any(hote == d or hote.endswith("." + d) for d in DOMAINES_LIENS)


def liens_autorises(ligne: str) -> list[str]:
    return [m.rstrip(".,;)") for m in LIEN.findall(ligne) if lien_autorise(m.rstrip(".,;)"))]


# ---------------------------------------------------------------- travaux de fond

class Travail:
    """Installation ou connexion en cours (ou terminée) pour un assistant."""

    def __init__(self, assistant: str, type_: str, methode: str | None = None):
        self.assistant, self.type, self.methode = assistant, type_, methode
        self.statut = "en_cours"          # en_cours, termine, echec, annule
        self.message = ""
        self.lien: str | None = None
        self.code: str | None = None      # code à usage unique de ChatGPT (méthode « code »)
        self.processus: subprocess.Popen | None = None
        self.annule = False
        self.debut = time.monotonic()
        self.verrou = threading.Lock()

    def public(self) -> dict:
        return {"type": self.type, "methode": self.methode, "statut": self.statut, "message": self.message,
                "lien": self.lien, "code": self.code, "secondes": int(time.monotonic() - self.debut)}


TRAVAUX: dict[str, Travail | None] = {a: None for a in ASSISTANTS}
VERROU_TRAVAUX = threading.Lock()


def verifier(assistant: str) -> str:
    if assistant not in ASSISTANTS:
        raise ErreurAssistant("Assistant inconnu.")
    return assistant


def travail_en_cours(assistant: str | None = None) -> bool:
    with VERROU_TRAVAUX:
        return any(t is not None and t.statut == "en_cours"
                   for a, t in TRAVAUX.items() if assistant in (None, a))


def etat_travail(assistant: str) -> dict | None:
    with VERROU_TRAVAUX:
        t = TRAVAUX[assistant]
    return t.public() if t else None


def _demarrer(assistant: str, type_: str, methode: str | None, args: list[str], env: dict,
              delai: float, avec_entree: bool, fin) -> Travail:
    """Lance `args` caché, suit sa sortie dans un fil, puis appelle `fin(travail, code_retour)`."""
    with VERROU_TRAVAUX:
        actuel = TRAVAUX[assistant]
        if actuel is not None and actuel.statut == "en_cours":
            raise ErreurAssistant("Une opération est déjà en cours pour cet assistant.", conflit=True)
        travail = Travail(assistant, type_, methode)
        try:
            travail.processus = subprocess.Popen(
                args, stdin=subprocess.PIPE if avec_entree else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, creationflags=SANS_FENETRE)
        except OSError:
            raise ErreurAssistant("Le programme n'a pas pu démarrer sur cet ordinateur.") from None
        TRAVAUX[assistant] = travail
    threading.Thread(target=_suivre, args=(travail, delai, fin), daemon=True).start()
    return travail


def _lire_sortie(travail: Travail) -> None:
    """Lit la sortie ligne à ligne : retient le premier lien autorisé et le code à usage unique."""
    try:
        for brut in iter(travail.processus.stdout.readline, b""):
            ligne = nettoyer(brut.decode("utf-8", "replace"))
            if not ligne:
                continue
            with travail.verrou:
                if travail.lien is None:
                    liens = liens_autorises(ligne)
                    travail.lien = liens[0] if liens else None
                if travail.code is None and CODE_APPAREIL.match(ligne):
                    travail.code = ligne
    except (OSError, ValueError):
        pass  # tube fermé par l'annulation


def _suivre(travail: Travail, delai: float, fin) -> None:
    lecteur = threading.Thread(target=_lire_sortie, args=(travail,), daemon=True)
    lecteur.start()
    try:
        code = travail.processus.wait(timeout=delai)
    except subprocess.TimeoutExpired:
        _tuer(travail)
        _conclure(travail, "echec", "Le délai est dépassé. Réessayez.")
        return
    lecteur.join(timeout=5)
    if travail.annule:
        _conclure(travail, "annule", "Annulé.")
        return
    try:
        fin(travail, code)
    except Exception:  # noqa: BLE001 (le travail ne doit jamais rester « en cours » par erreur)
        _conclure(travail, "echec", "Une erreur est survenue. Réessayez.")


def _conclure(travail: Travail, statut: str, message: str) -> None:
    with travail.verrou:
        if travail.statut == "en_cours":
            travail.statut, travail.message = statut, message


def _tuer(travail: Travail) -> None:
    try:
        moteurs.tuer_arbre(travail.processus)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- installation (V3-8)

def commande_installation(assistant: str) -> list[str]:
    """Script officiel lancé caché, sans droits administrateur. Remplaçable pour les tests."""
    imposee = os.environ.get(VARIABLES_INSTALLEUR[assistant])
    if imposee:
        try:
            args = json.loads(imposee)
        except ValueError:
            args = None
        if not (isinstance(args, list) and args and all(isinstance(a, str) for a in args)):
            raise ErreurAssistant("La commande d'installation imposée est illisible.")
        return args
    if sys.platform != "win32":
        raise ErreurAssistant("L'installation automatique n'est prévue que sous Windows.")
    return [os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "WindowsPowerShell", "v1.0",
                         "powershell.exe"), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command", SCRIPTS_INSTALLATION[assistant]]


def installer(assistant: str) -> dict:
    verifier(assistant)
    if commande(assistant):
        raise ErreurAssistant(f"{NOMS[assistant]} est déjà installé sur cet ordinateur.", conflit=True)
    env = dict(os.environ)
    if assistant == "codex":
        env["CODEX_NON_INTERACTIVE"] = "1"
    if sys.platform == "win32":
        # Le script Codex appelle `tar` : celui de Windows (System32) d'abord, car un `tar` de
        # Git Bash placé avant dans le PATH ne comprend pas les chemins « C:\… » (constaté le 2026-10-30).
        systeme = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"
        env["PATH"] = f"{systeme}{os.pathsep}{env.get('PATH', '')}"

    def fin(travail, code):
        if code == 0 and commande(assistant):
            _conclure(travail, "termine", "Installation terminée.")
        else:
            _conclure(travail, "echec", "L'installation n'a pas abouti. Vérifiez la connexion internet, "
                                        "puis réessayez.")
    return _demarrer(assistant, "installation", None, commande_installation(assistant), env,
                     DELAI_INSTALLATION_S, False, fin).public()


# ---------------------------------------------------------------- connexion (V3-9, V3-10, V3-11)

def commande_connexion(assistant: str, methode: str) -> list[str]:
    exe = commande(assistant)
    if not exe:
        raise ErreurAssistant(f"{NOMS[assistant]} n'est pas installé sur cet ordinateur.", conflit=True)
    if assistant == "claude":
        return [exe, "auth", "login", "--claudeai"]
    return [exe, "login", "--device-auth"] if methode == "code" else [exe, "login"]


def connecter(assistant: str, methode: str = "navigateur") -> dict:
    verifier(assistant)
    if methode not in ("navigateur", "code"):
        raise ErreurAssistant("Méthode de connexion inconnue.")
    args = commande_connexion(assistant, methode)

    def fin(travail, code):
        etat = etat_connexion(assistant) if code == 0 else {"connecte": False, "abonnement": None}
        if not etat["connecte"]:
            _conclure(travail, "echec", "La connexion n'a pas abouti. Réessayez.")
        elif not abonnement_ok(assistant, etat["abonnement"]):
            _conclure(travail, "echec", message_gratuit(assistant))
        else:
            _conclure(travail, "termine", "Connexion réussie.")
    return _demarrer(assistant, "connexion", methode, args, dict(os.environ), DELAI_CONNEXION_S, True, fin).public()


def envoyer_code(assistant: str, code: str) -> None:
    """Code collé par l'utilisatrice, transmis tel quel sur l'entrée du programme de connexion."""
    verifier(assistant)
    code = code.strip() if isinstance(code, str) else ""
    if not code or len(code) > MAX_CODE or any(c.isspace() or ord(c) < 32 for c in code):
        raise ErreurAssistant("Le code est vide ou illisible. Copiez-le de nouveau depuis la page de connexion.")
    with VERROU_TRAVAUX:
        travail = TRAVAUX[assistant]
    if travail is None or travail.type != "connexion" or travail.statut != "en_cours":
        raise ErreurAssistant("Aucune connexion n'est en cours. Cliquez d'abord sur « Ouvrir la page de connexion ».",
                              conflit=True)
    try:
        travail.processus.stdin.write((code + "\n").encode("utf-8"))
        travail.processus.stdin.flush()
    except (OSError, ValueError):
        raise ErreurAssistant("Le code n'a pas pu être transmis. Relancez la connexion.", conflit=True) from None


# ---------------------------------------------------------------- annulation

def annuler(assistant: str) -> dict | None:
    verifier(assistant)
    with VERROU_TRAVAUX:
        travail = TRAVAUX[assistant]
    if travail is not None and travail.statut == "en_cours":
        travail.annule = True
        _tuer(travail)
        _conclure(travail, "annule", "Annulé.")
    return etat_travail(assistant)


def tout_annuler() -> None:
    for assistant in ASSISTANTS:
        annuler(assistant)


# ---------------------------------------------------------------- état public

def etat_assistants(rapide: bool = False) -> dict:
    """Ce que la page peut voir. `rapide` : sans interroger la connexion (suivi d'un travail)."""
    sortie = {}
    for assistant in ASSISTANTS:
        installe = commande(assistant) is not None
        connecte = ok = None
        if installe and not rapide:
            etat = etat_connexion(assistant)
            connecte = etat["connecte"]
            ok = abonnement_ok(assistant, etat["abonnement"]) if connecte else None
        sortie[assistant] = {"nom": NOMS[assistant], "installe": installe, "connecte": connecte,
                             "abonnement_ok": ok, "travail": etat_travail(assistant)}
    return sortie
