import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from e2e_outils import Jeu  # noqa: E402


@pytest.fixture(scope="session")
def navigateur():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:  # Chromium absent ou inutilisable
            pytest.skip(f"Chromium indisponible : {e}")
        yield b
        b.close()


@pytest.fixture
def jeu(tmp_path):
    return Jeu(tmp_path)


@pytest.fixture
def erreurs():
    return []


@pytest.fixture
def contexte(navigateur, tmp_path):
    """Contexte neuf par test (localStorage vierge), clair par défaut, téléchargements acceptés."""
    c = navigateur.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True,
                               color_scheme="light")
    yield c
    c.close()


@pytest.fixture
def page(contexte, erreurs):
    p = contexte.new_page()
    p.on("console", lambda m: erreurs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    p.on("pageerror", lambda e: erreurs.append(f"pageerror: {e}"))
    p.set_default_timeout(5000)
    yield p
