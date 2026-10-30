"""Lanceur léger du raccourci (demarrer.py) : page d'attente tout de suite, une seule instance, port choisi."""
import json
import socket
import subprocess
import sys
import time
import uuid

import pytest

from outils_app import SKILL
from test_app_lancement import PYTHONW, attendre_etat, environnement_lancement, port_libre, poster

import demarrer

pytestmark = [pytest.mark.lancement, pytest.mark.skipif(sys.platform != "win32", reason="pythonw : Windows seulement"),
              pytest.mark.skipif(not PYTHONW.exists(), reason="pythonw.exe absent")]

ENREGISTREUR = "import sys;open(sys.argv[1],'a',encoding='utf-8').write(sys.argv[2]+'\\n')"


class Lanceur:
    """Un poste fictif : navigateur remplacé par un enregistreur d'adresses, verrou et journal à part."""

    def __init__(self, tmp_path, **env):
        self.tmp, self.urls = tmp_path, tmp_path / "urls.txt"
        self.env = environnement_lancement(tmp_path)
        self.env.update(PLANNING_PERMS_JOURNAL=str(tmp_path / "local" / "journal.txt"), PYTHONUTF8="1",
                        PLANNING_PERMS_VERROU="Local\\pp-test-" + uuid.uuid4().hex,
                        PLANNING_PERMS_NAVIGATEUR=json.dumps([sys.executable, "-c", ENREGISTREUR, str(self.urls)]),
                        **env)
        self.processus = []

    def demarrer(self):
        p = subprocess.Popen([str(PYTHONW), str(SKILL / "app" / "demarrer.py")], env=self.env, cwd=str(self.tmp),
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        self.processus.append(p)
        return p

    def adresses(self) -> list[str]:
        return self.urls.read_text(encoding="utf-8").split() if self.urls.exists() else []

    def attendre_adresses(self, n: int, delai: float = 30) -> list[str]:
        fin = time.monotonic() + delai
        while time.monotonic() < fin and len(self.adresses()) < n:
            time.sleep(0.1)
        assert len(self.adresses()) >= n, self.adresses()
        return self.adresses()

    def port(self) -> int:
        return int(self.env["PLANNING_PERMS_PORT"])

    def fermer(self):
        for p in self.processus:
            if p.poll() is None:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)


@pytest.fixture
def lanceur(tmp_path):
    cree = []

    def fabrique(**env):
        lan = Lanceur(tmp_path, **env)
        cree.append(lan)
        return lan
    yield fabrique
    for lan in cree:
        lan.fermer()


def port_de(adresse: str) -> int:
    assert adresse.startswith("file:///") and "/static/demarrage.html#" in adresse, adresse
    return int(adresse.rsplit("#", 1)[1])


def test_ouvre_la_page_d_attente_puis_sert_l_outil(lanceur):
    lan = lanceur()
    p = lan.demarrer()
    adresse = lan.attendre_adresses(1)[0]
    assert port_de(adresse) == lan.port()
    assert attendre_etat(p, lan.port())["application"] == "planning-perms"
    assert lan.adresses() == [adresse]  # un seul onglet : l'outil n'en ouvre pas un second
    journal = (lan.tmp / "local" / "journal.txt").read_text(encoding="utf-8")
    assert "--- démarrage" in journal and "fermez cette fenêtre" not in journal
    assert poster(lan.port(), "/api/arreter", {}) == 200
    assert p.wait(timeout=20) == 0


def test_second_lancement_pendant_le_demarrage(lanceur):
    lan = lanceur(PLANNING_PERMS_DEMARRAGE_LENT_S="4")
    premier = lan.demarrer()
    lan.attendre_adresses(1)
    second = lan.demarrer()
    assert second.wait(timeout=30) == 0
    adresses = lan.attendre_adresses(2)
    assert len(adresses) == 2 and port_de(adresses[0]) == port_de(adresses[1]) == lan.port()
    # Une seule instance : le port annoncé répond, le premier lanceur tourne toujours.
    assert attendre_etat(premier, lan.port(), delai=60)["application"] == "planning-perms"
    assert premier.poll() is None
    poster(lan.port(), "/api/arreter", {})


def test_lancement_quand_l_outil_repond_deja(lanceur):
    lan = lanceur()
    premier = lan.demarrer()
    attendre_etat(premier, lan.port())
    second = lan.demarrer()
    assert second.wait(timeout=30) == 0
    assert lan.attendre_adresses(2)[-1] == f"http://127.0.0.1:{lan.port()}/"
    poster(lan.port(), "/api/arreter", {})


def test_port_occupe_par_un_autre_programme(lanceur):
    etranger = socket.socket()
    etranger.bind(("127.0.0.1", 0))
    etranger.listen()
    occupe = etranger.getsockname()[1]
    try:
        lan = lanceur(PLANNING_PERMS_PORT=str(occupe))
        p = lan.demarrer()
        choisi = port_de(lan.attendre_adresses(1)[0])
        assert choisi != occupe
        assert attendre_etat(p, choisi)["application"] == "planning-perms"
        poster(choisi, "/api/arreter", {})
        assert p.wait(timeout=20) == 0
    finally:
        etranger.close()


def test_erreur_de_chargement_dans_le_journal(lanceur, tmp_path):
    """Un import qui échoue laisse sa trace dans le journal (la page d'attente annoncera l'échec)."""
    piege = tmp_path / "piege"
    piege.mkdir()
    (piege / "ortools.py").write_text("raise ImportError('ortools volontairement absent')\n", encoding="utf-8")
    lan = lanceur(PYTHONPATH=str(piege))
    p = lan.demarrer()
    assert p.wait(timeout=60) == 1
    assert "ortools volontairement absent" in (tmp_path / "local" / "journal.txt").read_text(encoding="utf-8")


def test_lanceur_en_processus_quand_l_outil_repond(appli, monkeypatch):
    ouverts = []
    monkeypatch.setattr(demarrer, "ouvrir_navigateur", lambda adresse: ouverts.append(adresse))
    monkeypatch.delenv("PLANNING_PERMS_SANS_NAVIGATEUR", raising=False)
    monkeypatch.setenv("PLANNING_PERMS_PORT", appli.url.rsplit(":", 1)[1])
    assert demarrer.main() == 0
    assert ouverts == [appli.url + "/"]


def test_navigateur_autorise(monkeypatch):
    monkeypatch.setenv("PLANNING_PERMS_SANS_NAVIGATEUR", "1")
    monkeypatch.delenv("PLANNING_PERMS_NAVIGATEUR", raising=False)
    assert not demarrer.navigateur_autorise()
    monkeypatch.setenv("PLANNING_PERMS_NAVIGATEUR", "[]")
    assert demarrer.navigateur_autorise()


def test_demarrer_n_importe_rien_de_lourd():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import demarrer; "
            "print([m for m in ('serveur','moteurs','parcours','ortools','pandas') if m in sys.modules])")
    r = subprocess.run([sys.executable, "-c", code, str(SKILL / "app")], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "[]", r.stdout + r.stderr


def test_choix_du_port():
    libre = port_libre()
    assert demarrer.choisir_port(libre) == libre
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        occupe = s.getsockname()[1]
        autre = demarrer.choisir_port(occupe)
        assert autre != occupe and demarrer.port_libre(autre)
