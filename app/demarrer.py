"""Lanceur léger du raccourci du bureau (spec V3) : `pythonw.exe app\\demarrer.py`.

Bibliothèque standard seulement, et aucun import de serveur, moteurs ou parcours en tête de module :
le premier démarrage à froid prend 15 à 20 secondes (ortools charge pandas), et l'utilisatrice ne doit
ni rester devant un écran vide, ni lancer l'outil deux fois. Ordre :
1. l'outil répond déjà : on ouvre le navigateur dessus ;
2. un autre lanceur démarre l'outil (verrou unique) : on ouvre la page d'attente sur son port ;
3. sinon : port choisi, journal ouvert, page d'attente ouverte tout de suite, puis chargement du serveur.
"""
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser
import socket
from pathlib import Path

PORT_DEFAUT = 8765
APPLICATION = "planning-perms"
JOURNAL_MAX = 1_000_000
NOM_VERROU = "Local\\planning-perms-balustrade"
ERREUR_DEJA_EXISTANT = 183
ATTENTE = Path(__file__).resolve().parent / "static" / "demarrage.html"
ETAT_CONSOLE = {"sans": False}   # vrai quand la sortie a été redirigée vers le journal
_verrou = []                     # garde le verrou ouvert jusqu'à la fin du processus


# ---------------------------------------------------------------- journal (V3-2)

def chemin_journal() -> Path:
    """Journal du mode sans console : %LOCALAPPDATA%\\balustrade-planning\\journal.txt."""
    if os.environ.get("PLANNING_PERMS_JOURNAL"):
        return Path(os.environ["PLANNING_PERMS_JOURNAL"])
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
    return base / "balustrade-planning" / "journal.txt"


def rediriger_sans_console() -> None:
    """Sous pythonw, `sys.stdout` et `sys.stderr` valent None : tout va dans le journal, remis à zéro
    au-delà de 1 Mo. Le journal ne reçoit que des lignes de requête et des erreurs, jamais un corps.
    Sans effet si la sortie existe déjà (console, ou redirection déjà faite)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    chemin = chemin_journal()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        trop_gros = chemin.exists() and chemin.stat().st_size > JOURNAL_MAX
        flux = open(chemin, "w" if trop_gros else "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        flux = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stdout or flux
    sys.stderr = sys.stderr or flux
    ETAT_CONSOLE["sans"] = True
    flux.write(f"--- démarrage {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")


# ---------------------------------------------------------------- navigateur (V3-3)

def chemins_chrome() -> list[Path]:
    """Emplacements standard de Chrome. Variables lues à chaque appel (tests)."""
    relatif = Path("Google") / "Chrome" / "Application" / "chrome.exe"
    return [Path(base) / relatif for base in (os.environ.get("ProgramFiles"),
                                              os.environ.get("ProgramFiles(x86)"),
                                              os.environ.get("LOCALAPPDATA")) if base]


def trouver_chrome() -> str | None:
    return next((str(c) for c in chemins_chrome() if c.is_file()), None)


def ouvrir_navigateur(adresse: str) -> None:
    """Chrome s'il est installé, sinon le navigateur par défaut. Pour les tests, PLANNING_PERMS_NAVIGATEUR
    (liste JSON) remplace le navigateur : la commande reçoit l'adresse en dernier argument."""
    imposee = os.environ.get("PLANNING_PERMS_NAVIGATEUR")
    if imposee:
        subprocess.Popen([*json.loads(imposee), adresse], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return
    chrome = trouver_chrome() if sys.platform == "win32" else None
    if chrome:
        try:
            subprocess.Popen([chrome, adresse], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(adresse)


def navigateur_autorise() -> bool:
    return not os.environ.get("PLANNING_PERMS_SANS_NAVIGATEUR") or bool(os.environ.get("PLANNING_PERMS_NAVIGATEUR"))


def adresse_attente(port: int) -> str:
    """Page locale d'attente (file://) : elle interroge le port puis ouvre l'outil."""
    return f"{ATTENTE.as_uri()}#{port}"


# ---------------------------------------------------------------- instance unique et port

def application_repond(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=1) as rep:
            return json.loads(rep.read().decode("utf-8")).get("application") == APPLICATION
    except (OSError, ValueError):
        return False


def prendre_verrou() -> bool:
    """Vrai si ce lanceur est le premier. Windows : mutex nommé (libéré à la fin du processus)."""
    nom = os.environ.get("PLANNING_PERMS_VERROU") or NOM_VERROU
    if sys.platform == "win32":
        import ctypes
        noyau = ctypes.WinDLL("kernel32", use_last_error=True)
        noyau.CreateMutexW.restype = ctypes.c_void_p
        poignee = noyau.CreateMutexW(None, False, nom)
        deja = ctypes.get_last_error() == ERREUR_DEJA_EXISTANT
        _verrou.append(poignee)
        return not deja
    try:
        import fcntl
        fichier = open(chemin_journal().with_name("verrou.lock"), "w")
        fcntl.flock(fichier, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _verrou.append(fichier)
        return True
    except ImportError:
        return True
    except OSError:
        return False


def fichier_port() -> Path:
    return chemin_journal().with_name("port.txt")


def port_de_l_autre_lanceur(defaut: int, delai_s: float = 5.0) -> int:
    """Port écrit par le lanceur qui démarre l'outil (il l'écrit juste après avoir pris le verrou)."""
    fin = time.monotonic() + delai_s
    while time.monotonic() < fin:
        try:
            return int(fichier_port().read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            time.sleep(0.1)
    return defaut


def port_libre(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choisir_port(demande: int) -> int:
    """Le port demandé s'il est libre, sinon un port libre : la page d'attente doit connaître le bon."""
    if port_libre(demande):
        return demande
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- démarrage

def main() -> int:
    sys.modules["demarrer"] = sys.modules[__name__]  # lancé en script : serveur doit voir ce même module
    demande = int(os.environ.get("PLANNING_PERMS_PORT") or PORT_DEFAUT)
    if application_repond(demande):
        if navigateur_autorise():
            ouvrir_navigateur(f"http://127.0.0.1:{demande}/")
        return 0
    if not prendre_verrou():
        if navigateur_autorise():
            ouvrir_navigateur(adresse_attente(port_de_l_autre_lanceur(demande)))
        return 0
    fichier_port().unlink(missing_ok=True)  # l'ancien port ne doit pas tromper un second lanceur
    port = choisir_port(demande)
    os.environ["PLANNING_PERMS_PORT"] = str(port)
    try:
        fichier_port().parent.mkdir(parents=True, exist_ok=True)
        fichier_port().write_text(str(port), encoding="utf-8")
    except OSError:
        pass
    rediriger_sans_console()
    if navigateur_autorise():
        ouvrir_navigateur(adresse_attente(port))
    os.environ["PLANNING_PERMS_SANS_NAVIGATEUR"] = "1"  # la page d'attente ouvre l'outil : pas d'autre onglet
    try:
        time.sleep(float(os.environ.get("PLANNING_PERMS_DEMARRAGE_LENT_S") or 0))  # essais : démarrage lent
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import serveur  # import lourd, après l'ouverture du journal et de la page d'attente
        return serveur.main()
    except Exception:  # noqa: BLE001 (la trace va au journal : personne ne verrait la console)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
