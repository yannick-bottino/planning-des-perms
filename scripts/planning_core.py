"""Modèle de données partagé : normalisation des noms, semaines, créneaux, libellés."""
import unicodedata
from datetime import date, timedelta


def normaliser_nom(brut: str) -> str:
    """Retire les espaces et les accents, passe en majuscules ASCII."""
    sans_accent = unicodedata.normalize("NFKD", brut.strip())
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return sans_accent.upper()


def lundi_de(d: date) -> date:
    """Renvoie le lundi de la semaine de `d`."""
    return d - timedelta(days=d.weekday())


def id_creneau(d: date, demi: str) -> str:
    """Identifiant de créneau, ex. '2026-11-02_M'."""
    if demi not in ("M", "A"):
        raise ValueError(f"Demi-journée invalide : {demi!r} (attendu 'M' ou 'A')")
    return f"{d.isoformat()}_{demi}"


# Clés en minuscules : la recherche ignore casse et espaces de bord.
# Les libellés « si besoin » ne sont pas vérifiés sur un vrai export Framadate.
DISPOS = {
    "yes": "oui",
    "no": "non",
    "": "vide",
    "if needed": "si_besoin",
    "if need be": "si_besoin",
    "ifneedbe": "si_besoin",
    "si nécessaire": "si_besoin",
    "si besoin": "si_besoin",
}

DEMIS = {"matin": "M", "apres-midi": "A", "après-midi": "A"}


def convertir_dispo(brut: str, famille: str, creneau: str) -> str:
    """Valeur brute du CSV -> oui / non / vide / si_besoin, sinon ValueError."""
    try:
        return DISPOS[brut.strip().lower()]
    except KeyError:
        raise ValueError(
            f"Valeur de dispo inconnue {brut!r} (famille {famille}, créneau {creneau})"
        ) from None


def convertir_demi(libelle: str) -> str:
    """Libellé de demi-journée -> 'M' ou 'A', sinon ValueError."""
    try:
        return DEMIS[libelle.strip().lower()]
    except KeyError:
        raise ValueError(f"Libellé de demi-journée inconnu : {libelle!r}") from None
