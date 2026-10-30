import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from planning_core import (  # noqa: E402
    convertir_demi, convertir_dispo, id_creneau, lundi_de, normaliser_nom,
)


@pytest.mark.parametrize("brut,attendu", [
    ("Noé", "NOE"), ("arujan", "ARUJAN"), (" éloïse ", "ELOISE"), ("BASILE", "BASILE"),
])
def test_normaliser_nom(brut, attendu):
    assert normaliser_nom(brut) == attendu


@pytest.mark.parametrize("d,lundi", [
    (date(2026, 11, 2), date(2026, 11, 2)),
    (date(2026, 11, 8), date(2026, 11, 2)),   # dimanche
    (date(2026, 12, 31), date(2026, 12, 28)),
    (date(2027, 1, 1), date(2026, 12, 28)),
])
def test_lundi_de(d, lundi):
    assert lundi_de(d) == lundi


def test_id_creneau():
    assert id_creneau(date(2026, 11, 2), "M") == "2026-11-02_M"
    assert id_creneau(date(2026, 11, 2), "A") == "2026-11-02_A"
    with pytest.raises(ValueError):
        id_creneau(date(2026, 11, 2), "X")


@pytest.mark.parametrize("brut,attendu", [
    ("Yes", "oui"), ("No", "non"), ("", "vide"), ("If needed", "si_besoin"),
    ("Ifneedbe", "si_besoin"), ("Si nécessaire", "si_besoin"),
])
def test_convertir_dispo(brut, attendu):
    assert convertir_dispo(brut, "NOE", "2026-11-02_M") == attendu


def test_dispo_inconnue():
    with pytest.raises(ValueError) as e:
        convertir_dispo("Peut-etre", "NOE", "2026-11-02_M")
    msg = str(e.value)
    assert "Peut-etre" in msg and "NOE" in msg and "2026-11-02_M" in msg


def test_demis():
    assert convertir_demi("Matin") == "M"
    assert convertir_demi("Apres-midi") == "A"
    assert convertir_demi("Après-midi") == "A"
    with pytest.raises(ValueError):
        convertir_demi("Soir")
