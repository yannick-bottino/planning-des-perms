"""Test local de l'installeur : installation silencieuse, raccourcis, lancement, désinstallation.

Usage : python tester_installeur.py [--exe CHEMIN] [--reel]
  (défaut) installation dans un dossier temporaire (/DIR). Les raccourcis atterrissent quand même
           sur le vrai Bureau et le vrai menu Démarrer : le test les supprime via le désinstalleur.
  --reel   installation à l'emplacement par défaut (%LOCALAPPDATA%\\Programs\\Planning des perms).
Les données utilisateur (~\\balustrade-planning) ne sont jamais touchées par le désinstalleur.
Le test s'arrête avant toute action si un raccourci Planning des perms existe déjà.
"""
import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
NOM_RACCOURCI = "Planning des perms.lnk"
resultats: list[tuple[bool, str]] = []


def verifie(ok: bool, texte: str) -> bool:
    resultats.append((ok, texte))
    print(("[OK]    " if ok else "[ECHEC] ") + texte, flush=True)
    return ok


def dossier_connu(csidl: int) -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def lire_raccourci(lnk: Path) -> dict:
    chemin = str(lnk).replace("'", "''")
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
          f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{chemin}');"
          "@{cible=$s.TargetPath;args=$s.Arguments;dossier=$s.WorkingDirectory;icone=$s.IconLocation}"
          "|ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                       text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise SystemExit(f"Lecture du raccourci impossible : {r.stderr.strip() or r.stdout.strip()}")


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def noms_enfants(pid: int) -> list[str]:
    ps = (f"Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' | "
          "ForEach-Object { $_.Name.ToLower() }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return [n for n in r.stdout.split() if n]


def attendre(condition, delai: float, pas: float = 0.5) -> bool:
    fin = time.time() + delai
    while time.time() < fin:
        if condition():
            return True
        time.sleep(pas)
    return condition()


def main() -> int:
    ap = argparse.ArgumentParser(description="Test local de l'installeur")
    ap.add_argument("--exe", help="installeur (défaut : build/Installer-Planning-des-perms.exe)")
    ap.add_argument("--reel", action="store_true", help="installer à l'emplacement par défaut")
    args = ap.parse_args()
    exe = Path(args.exe) if args.exe else ICI / "build" / "Installer-Planning-des-perms.exe"
    if not exe.is_file():
        print(f"Installeur introuvable : {exe} (lancer construire.py)")
        return 2

    bureau = dossier_connu(0x10) / NOM_RACCOURCI
    demarrer = dossier_connu(0x02) / NOM_RACCOURCI
    if bureau.exists() or demarrer.exists():
        print("Un raccourci Planning des perms existe déjà : test annulé pour ne pas toucher à l'installation réelle.")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="pp-test-"))
    if args.reel:
        cible = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Planning des perms"
        extra = []
    else:
        cible = tmp / "Planning des perms"
        extra = [f"/DIR={cible}"]
    print(f"Installeur : {exe.name} ({exe.stat().st_size / 1e6:.1f} Mo)")
    print(f"Mode : {'réel' if args.reel else 'dossier temporaire'}, cible : {cible}\n")

    pid = None
    p = None
    try:
        t0 = time.time()
        r = subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                            f"/LOG={tmp / 'install.log'}", *extra])
        verifie(r.returncode == 0, f"installation silencieuse : code {r.returncode} en {time.time() - t0:.0f} s")
        python = cible / "python" / "pythonw.exe"
        verifie(python.is_file(), "pythonw.exe installé")
        verifie((cible / "planning-perms" / "app" / "demarrer.py").is_file(), "demarrer.py installé")
        verifie((cible / "unins000.exe").is_file(), "désinstalleur présent")
        verifie(bureau.is_file(), f"raccourci Bureau : {bureau}")
        verifie(demarrer.is_file(), f"raccourci menu Démarrer : {demarrer}")

        if bureau.is_file():
            lnk = lire_raccourci(bureau)
            verifie(Path(lnk["cible"]).resolve() == python.resolve(), f"cible du raccourci : {lnk['cible']}")
            attendu = str(cible / "planning-perms" / "app" / "demarrer.py")
            verifie(attendu.lower() in lnk["args"].lower(), "paramètre du raccourci : demarrer.py (entre guillemets)")
            verifie(Path(lnk["dossier"]).resolve() == (cible / "planning-perms").resolve(), "dossier de travail du raccourci")

            # Lancement : commande exacte du raccourci, sans console, sans navigateur, port libre.
            port = port_libre()
            env = {**os.environ, "PLANNING_PERMS_SANS_NAVIGATEUR": "1", "PLANNING_PERMS_PORT": str(port)}
            cmd = f'"{lnk["cible"]}" {lnk["args"]}'
            t_lancement = time.time()
            p = subprocess.Popen(cmd, cwd=lnk["dossier"], env=env)  # comme un double-clic : aucun indicateur de console
            pid = p.pid

            def repond() -> bool:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=1) as rep:
                        return rep.status == 200
                except OSError:
                    return False

            ok = attendre(repond, 90, 0.1)
            verifie(ok, f"le serveur répond sur /api/etat (port {port}), démarrage à froid : {time.time() - t_lancement:.1f} s")
            verifie(p.poll() is None, "le processus pythonw tourne")
            enfants = noms_enfants(pid)
            verifie("conhost.exe" not in enfants and "cmd.exe" not in enfants and "python.exe" not in enfants,
                    f"aucune console ni processus enfant visible (enfants de pythonw : {enfants or 'aucun'})")
            print("        Désinstallation pendant que l'application tourne...")
    finally:
        unins = cible / "unins000.exe"
        if unins.is_file():
            subprocess.run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
            # Le désinstalleur Inno se relance depuis un dossier temporaire : attendre la suppression.
            attendre(lambda: not cible.exists(), 90)
        verifie(not cible.exists(), "dossier d'installation entièrement supprimé après désinstallation (application en marche)")
        if pid:
            verifie(attendre(lambda: p.poll() is not None, 10), "le processus de l'application a été arrêté par le désinstalleur")
            if p.poll() is None:
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
        verifie(not bureau.exists(), "raccourci Bureau supprimé")
        verifie(not demarrer.exists(), "raccourci menu Démarrer supprimé")
        shutil.rmtree(tmp, ignore_errors=True)

    echecs = [t for ok, t in resultats if not ok]
    print(f"\nBilan : {len(resultats) - len(echecs)} contrôles réussis sur {len(resultats)}.")
    if echecs:
        print("Échecs :")
        for t in echecs:
            print(f"  - {t}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
