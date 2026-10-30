"""Dossiers de données et de configuration, clé DeepSeek (spec V2, décisions V2-6 à V2-8)."""
import json
import os
import sys
from pathlib import Path

MOTEURS = ("claude", "codex", "deepseek", "manuel")


def dossier_donnees() -> Path:
    """Racine des dossiers du mois : ~/balustrade-planning, comme la V1."""
    return Path(os.environ.get("PLANNING_PERMS_DONNEES") or Path.home() / "balustrade-planning")


def fichier_config() -> Path:
    """config.json hors du repo et hors des données."""
    if os.environ.get("PLANNING_PERMS_CONFIG"):
        return Path(os.environ["PLANNING_PERMS_CONFIG"])
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "balustrade-planning" / "config.json"


def lire_config() -> dict:
    """Config enregistrée ; un fichier absent ou abîmé vaut une config vide."""
    try:
        brut = json.loads(fichier_config().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return brut if isinstance(brut, dict) else {}


def ecrire_config(config: dict) -> None:
    chemin = fichier_config()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(".tmp")
    temporaire.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporaire, chemin)


def cle_deepseek() -> str:
    """Clé enregistrée, sinon variable DEEPSEEK_API_KEY, sinon chaîne vide."""
    return str(lire_config().get("deepseek_cle") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def enregistrer(moteur: str | None = None, deepseek_cle: str | None = None) -> None:
    """Met à jour le moteur choisi et/ou la clé. Une clé vide efface la clé enregistrée."""
    config = lire_config()
    if moteur is not None:
        if moteur not in MOTEURS:
            raise ValueError(f"Moteur inconnu : {moteur}")
        config["moteur"] = moteur
    if deepseek_cle is not None:
        cle = deepseek_cle.strip()
        if cle:
            config["deepseek_cle"] = cle
        else:
            config.pop("deepseek_cle", None)
    ecrire_config(config)


def etat_public() -> dict:
    """Ce que le navigateur peut voir de la config : jamais la clé elle-même."""
    config = lire_config()
    moteur = config.get("moteur")
    return {"moteur": moteur if moteur in MOTEURS else None, "deepseek_cle": bool(cle_deepseek())}
