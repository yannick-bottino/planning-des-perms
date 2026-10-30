"""Lancement réel par lancer.bat (critères 1 et 2), depuis le zip remis à la famille planning.

Lent (premier `uv run` : téléchargement d'ortools). Ignoré hors Windows ou sans uv.
L'installation de uv elle-même (critère 2) demande le réseau : PLANNING_PERMS_TEST_INSTALL_UV=1.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

from outils_app import SKILL

sys.path.insert(0, str(SKILL / "app"))
import emballer  # noqa: E402

pytestmark = [pytest.mark.lancement,
              pytest.mark.skipif(sys.platform != "win32", reason="lancer.bat : Windows seulement")]


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def extraire(tmp_path: Path) -> Path:
    archive = tmp_path / "planning.zip"
    emballer.emballer(archive)
    cible = tmp_path / "Dossier avec espaces é"
    with zipfile.ZipFile(archive) as z:
        noms = z.namelist()
        assert not any("/tests/" in n or "__pycache__" in n for n in noms)
        z.extractall(cible)
    dossier = cible / emballer.RACINE
    assert (dossier / "lancer.bat").read_bytes().count(b"\r\n") > 10
    assert b"\r\n" not in (dossier / "lancer.sh").read_bytes()
    return dossier


def lancer(dossier: Path, env: dict, delai: float) -> dict:
    """Lance lancer.bat, attend /api/etat, arrête l'arbre de processus. Renvoie l'état et la sortie."""
    port = int(env["PLANNING_PERMS_PORT"])
    p = subprocess.Popen(["cmd", "/c", str(dossier / "lancer.bat")], cwd=str(dossier), env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    etat, fin = None, time.monotonic() + delai
    try:
        while time.monotonic() < fin and p.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=2) as r:
                    etat = json.loads(r.read())
                    break
            except OSError:
                time.sleep(1)
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        sortie = p.communicate(timeout=30)[0].decode("utf-8", "replace")
    return {"etat": etat, "sortie": sortie}


def environnement_lancement(tmp_path: Path) -> dict:
    env = dict(os.environ)
    env.update(PLANNING_PERMS_SANS_NAVIGATEUR="1", PLANNING_PERMS_PORT=str(port_libre()),
               PLANNING_PERMS_DONNEES=str(tmp_path / "donnees"),
               PLANNING_PERMS_CONFIG=str(tmp_path / "config.json"))
    return env


@pytest.mark.skipif(not shutil.which("uv"), reason="uv absent")
def test_lancer_bat_depuis_le_zip(tmp_path):
    dossier = extraire(tmp_path)
    r = lancer(dossier, environnement_lancement(tmp_path), delai=300)
    assert r["etat"] and r["etat"]["application"] == "planning-perms", r["sortie"]
    assert "Adresse : http://127.0.0.1:" in r["sortie"]


@pytest.mark.skipif(os.environ.get("PLANNING_PERMS_TEST_INSTALL_UV") != "1",
                    reason="installe uv depuis internet : PLANNING_PERMS_TEST_INSTALL_UV=1")
def test_lancer_bat_installe_uv(tmp_path):
    dossier = extraire(tmp_path)
    env = environnement_lancement(tmp_path)
    profil = tmp_path / "profil"
    profil.mkdir()
    # Un poste sans uv : retiré du PATH, profil vide, installation dans un dossier jetable.
    env["PATH"] = os.pathsep.join(d for d in env["PATH"].split(os.pathsep)
                                  if d and not (Path(d) / "uv.exe").exists())
    # only-managed : uv ignore le Python du poste et télécharge le sien, comme chez une famille sans Python.
    env.update(USERPROFILE=str(profil), UV_INSTALL_DIR=str(tmp_path / "uv-bin"), UV_NO_MODIFY_PATH="1",
               UV_PYTHON_PREFERENCE="only-managed", UV_PYTHON_INSTALL_DIR=str(tmp_path / "uv-python"))
    r = lancer(dossier, env, delai=600)
    assert (tmp_path / "uv-bin" / "uv.exe").is_file(), r["sortie"]
    assert "Premiere utilisation" in r["sortie"]
    assert any((tmp_path / "uv-python").glob("cpython-*")), "aucun Python géré par uv"
    assert r["etat"] and r["etat"]["application"] == "planning-perms", r["sortie"]


def test_zip_non_extrait(tmp_path):
    """lancer.bat seul (zip ouvert sans extraction) : message clair, pas de plantage."""
    shutil.copy(SKILL / "lancer.bat", tmp_path / "lancer.bat")
    p = subprocess.run(["cmd", "/c", str(tmp_path / "lancer.bat")], cwd=str(tmp_path),
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert p.returncode == 1
    assert b"Extraire tout" in p.stdout


# ---------------------------------------------------------------- pythonw sans console (spec V3, V3-2, V3-4, V3-5)

PYTHONW = Path(sys.executable).with_name("pythonw.exe")


def test_lancer_bat_dit_de_ne_pas_fermer_la_fenetre():
    texte = (SKILL / "lancer.bat").read_text(encoding="utf-8")
    assert "echo Cette fenetre fait tourner l'outil : allez dans Chrome, et ne fermez pas cette fenetre." in texte
    assert all(ord(c) < 128 for c in texte), "lancer.bat ne doit pas contenir d'accents"


def lancer_pythonw(tmp_path: Path, **supplement) -> tuple[subprocess.Popen, int, Path]:
    port = port_libre()
    journal = tmp_path / "local" / "journal.txt"
    env = environnement_lancement(tmp_path)
    env.update(PLANNING_PERMS_PORT=str(port), PLANNING_PERMS_JOURNAL=str(journal), PYTHONUTF8="1", **supplement)
    return demarrer_sans_console(env, tmp_path), port, journal


def demarrer_sans_console(env: dict, cwd: Path) -> subprocess.Popen:
    """Comme un raccourci du bureau : processus détaché, aucune entrée ni sortie standard (sys.stdout vaut None)."""
    return subprocess.Popen([str(PYTHONW), str(SKILL / "app" / "serveur.py")], env=env, cwd=str(cwd),
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def attendre_etat(p: subprocess.Popen, port: int, delai: float = 60) -> dict:
    fin = time.monotonic() + delai
    while time.monotonic() < fin and p.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=2) as r:
                return json.loads(r.read())
        except OSError:
            time.sleep(0.3)
    pytest.fail(f"le serveur sous pythonw ne répond pas (code {p.poll()})")


def poster(port: int, chemin: str, corps: dict) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{chemin}", data=json.dumps(corps).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json",
                                                         "Origin": f"http://127.0.0.1:{port}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


@pytest.mark.skipif(not PYTHONW.exists(), reason="pythonw.exe absent")
def test_pythonw_journal_et_arret_par_l_api(tmp_path):
    p, port, journal = lancer_pythonw(tmp_path)
    try:
        etat = attendre_etat(p, port)
        assert etat["application"] == "planning-perms"
        assert poster(port, "/api/config", {"deepseek_cle": "sk-journal-secret", "moteur": "deepseek"}) == 200
        texte = journal.read_text(encoding="utf-8")
        assert "--- démarrage" in texte and "GET /api/etat 200" in texte and "POST /api/config 200" in texte
        assert "sk-journal-secret" not in texte
        # L'arrêt par la page : réponse, puis le processus se termine proprement (code 0).
        assert poster(port, "/api/arreter", {}) == 200
        assert p.wait(timeout=20) == 0
        with pytest.raises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=2)
    finally:
        if p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)


@pytest.mark.skipif(not PYTHONW.exists(), reason="pythonw.exe absent")
def test_pythonw_s_arrete_seul_apres_inactivite(tmp_path):
    p, port, journal = lancer_pythonw(tmp_path, PLANNING_PERMS_INACTIVITE_S="3")
    try:
        attendre_etat(p, port)
        assert p.wait(timeout=30) == 0
        assert "Arrêt : aucune activité." in journal.read_text(encoding="utf-8")
    finally:
        if p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)


@pytest.mark.skipif(not PYTHONW.exists(), reason="pythonw.exe absent")
def test_pythonw_ne_reste_pas_en_double(tmp_path):
    """Un second lancement (double-clic répété) trouve l'outil déjà lancé et ne démarre rien."""
    p, port, _ = lancer_pythonw(tmp_path)
    try:
        attendre_etat(p, port)
        journal = tmp_path / "local" / "journal.txt"
        avant = journal.read_bytes()
        env = environnement_lancement(tmp_path)
        env.update(PLANNING_PERMS_PORT=str(port), PLANNING_PERMS_JOURNAL=str(journal))
        second = demarrer_sans_console(env, tmp_path)
        assert second.wait(timeout=60) == 0
        # Le second lancement ne touche pas au journal de la première instance.
        assert journal.read_bytes().startswith(avant)
        assert p.poll() is None
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
