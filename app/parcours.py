"""Logique des étapes de l'application, sans HTTP (spec V2, section 4).

Importe les scripts V1 : rien du calcul n'est recopié ici.
"""
import json
import re
import sys
import urllib.parse
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import fetch_framadate  # noqa: E402
from export_xlsx import LIBELLE_CODE, appliquer_arbitrages, ecrire_xlsx  # noqa: E402
from planning_core import normaliser_nom  # noqa: E402
from render_arbitrage import generer_page, titre_semaine  # noqa: E402
from solve import (  # noqa: E402
    DEMI_LIBELLE, JOURS, construire_planning, libelle_creneau, libelle_jour, lire_contraintes,
)

TYPES_REGLE = ("absence", "quota", "au_moins", "preference")
CLES_REGLAGES = ("cible_hebdo", "plafond_hebdo", "max_parents_par_creneau")
REGLAGES_DEFAUT = {"cible_hebdo": 1, "plafond_hebdo": 2, "max_parents_par_creneau": 2}
HOTES_LOCAUX = ("127.0.0.1", "localhost")
RE_CRENEAU = re.compile(r"^\d{4}-\d{2}-\d{2}_[MA]$")


class ErreurRegle(ValueError):
    """Règle invalide. `index` désigne la ligne du tableau quand elle est connue."""

    def __init__(self, message: str, index: int | None = None):
        super().__init__(message)
        self.index = index


# ---------------------------------------------------------------- étape 1 : sondage

def adresses_sondage(lien: str) -> tuple[str, str, str]:
    """Lien collé -> (poll_id, URL du CSV, URL de la page). ValueError si le lien ne convient pas."""
    lien = lien.strip()
    if not lien:
        raise ValueError("Collez le lien du sondage Framadate.")
    if "://" not in lien:
        lien = "https://" + lien
    url = urllib.parse.urlsplit(lien)
    m = re.search(r"/polls/([A-Za-z0-9]+)", url.path)
    if not m or not url.hostname:
        raise ValueError("Ce lien ne ressemble pas à un sondage Framadate "
                         "(il doit contenir « /polls/ » suivi du code du sondage).")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in HOTES_LOCAUX):
        raise ValueError("Le lien du sondage doit commencer par https://")
    poll_id = m.group(1)
    base = f"{url.scheme}://{url.netloc}{url.path[:m.start()]}/polls/{poll_id}"
    return poll_id, base + ".csv", base


def charger_sondage(lien: str, telecharger=fetch_framadate.telecharger) -> dict:
    """Télécharge CSV et page, assemble le sondage.json de la V1."""
    poll_id, url_csv, url_page = adresses_sondage(lien)
    return fetch_framadate.construire(poll_id, telecharger(url_csv), telecharger(url_page))


def mois_du_sondage(sondage: dict) -> str:
    """'AAAA-MM' du mois qui compte le plus de créneaux (V2-6)."""
    compte = Counter(c["date"][:7] for c in sondage["creneaux"])
    if not compte:
        raise ValueError("Le sondage ne contient aucun créneau.")
    return sorted(compte.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def semaines(sondage: dict) -> list[str]:
    return sorted({c["semaine"] for c in sondage["creneaux"]})


def resumer(sondage: dict) -> dict:
    """Résumé de l'étape 2 : chiffres, jours fermés, familles à signaler."""
    creneaux = sondage["creneaux"]
    dates = sorted({c["date"] for c in creneaux})
    fermes = []
    if dates:
        d, fin = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        while d <= fin:
            if d.weekday() < 5 and d.isoformat() not in dates:
                fermes.append(libelle_jour(d.isoformat()))
            d += timedelta(days=1)
    par_semaine = {s: [c["id"] for c in creneaux if c["semaine"] == s] for s in semaines(sondage)}
    peu, sans = [], []
    for f in sorted(sondage["familles"], key=lambda f: f["nom"]):
        for s, ids in par_semaine.items():
            oui = sum(f["dispos"].get(i) == "oui" for i in ids)
            possibles = sum(f["dispos"].get(i) in ("oui", "si_besoin") for i in ids)
            if possibles == 0:
                sans.append({"famille": f["nom"], "semaine": titre_semaine(s)})
            elif oui < 2:
                peu.append({"famille": f["nom"], "semaine": titre_semaine(s), "oui": oui})
    return {
        "titre": sondage["titre"],
        "familles": sorted(f["nom"] for f in sondage["familles"]),
        "nb_creneaux": len(creneaux),
        "semaines": [{"lundi": s, "titre": titre_semaine(s), "creneaux": len(ids)}
                     for s, ids in par_semaine.items()],
        "jours_fermes": fermes,
        "avertissements": list(sondage.get("avertissements", [])),
        "peu_de_dispos": peu,
        "sans_dispo": sans,
        "commentaires": sondage.get("commentaires", []),
    }


# ---------------------------------------------------------------- étape 3 : règles

def options(sondage: dict) -> dict:
    """Listes de choix du tableau : familles, semaines, jours, créneaux."""
    jours_presents = {date.fromisoformat(c["date"]).weekday() for c in sondage["creneaux"]}
    filtres = []
    for j in sorted(jours_presents):
        filtres.append({"valeur": JOURS[j], "libelle": f"le {JOURS[j]}"})
        for demi in ("M", "A"):
            filtres.append({"valeur": f"{JOURS[j]}:{demi}",
                            "libelle": f"le {JOURS[j]} {DEMI_LIBELLE[demi]}"})
    return {
        "familles": sorted(f["nom"] for f in sondage["familles"]),
        "semaines": [{"valeur": s, "libelle": titre_semaine(s)} for s in semaines(sondage)],
        "filtres": filtres,
        "creneaux": [{"valeur": c["id"], "libelle": libelle_creneau(c)}
                     for c in sorted(sondage["creneaux"], key=lambda c: (c["date"], c["demi"] != "M"))],
        "nb_semaines": len(semaines(sondage)),
    }


def _cible_vers_filtre(cible: str) -> dict:
    jour, _, demi = cible.partition(":")
    return {"jour": jour, "demi": demi} if demi else {"jour": jour}


def _filtre_vers_cible(filtre: dict) -> str:
    jour = str(filtre.get("jour", "")).strip().lower()
    return f"{jour}:{filtre['demi']}" if filtre.get("demi") else jour


def _date_iso(valeur) -> str:
    return valeur.isoformat() if isinstance(valeur, date) else str(valeur)


def regles_depuis_contraintes(brut: dict | None) -> dict:
    """Dict brut de contraintes.yaml (déjà validé) -> lignes du tableau."""
    brut = brut or {}
    regles = []
    for cle, v in (brut.get("familles") or {}).items():
        nom, v = normaliser_nom(str(cle)), v or {}
        source = str(v.get("source") or "")
        for a in sorted({_date_iso(a) for a in v.get("absences") or []}):
            regles.append({"famille": nom, "type": "absence", "semaine": _date_iso(a), "source": source})
        if v.get("quota_mois") is not None:
            regles.append({"famille": nom, "type": "quota", "quota": v["quota_mois"], "source": source})
        if v.get("au_moins") is not None:
            am = v["au_moins"]
            regles.append({"famille": nom, "type": "au_moins", "n": am.get("n", 1),
                           "parmi": [_filtre_vers_cible(f) for f in am.get("parmi") or []],
                           "source": source})
        for p in v.get("preferences") or []:
            cible = p["creneau"] if "creneau" in p else _filtre_vers_cible(p)
            regles.append({"famille": nom, "type": "preference", "cible": cible,
                           "poids": p.get("poids", 1), "source": source})
    reglages = {k: brut[k] if k in brut else REGLAGES_DEFAUT[k] for k in CLES_REGLAGES}
    return {"regles": regles, "reglages": reglages,
            "non_traduits": [str(t) for t in brut.get("commentaires_non_traduits") or []]}


def regles_sans_reponse(sondage: dict, regles: list[dict]) -> list[dict]:
    """Règle « 0 perm » proposée pour une famille sans aucune dispo sur tout le sondage.

    Sans elle, le quota par défaut produit une alerte certaine. La ligne reste visible et
    supprimable : la famille planning décide.
    """
    deja = {r["famille"] for r in regles if r.get("type") == "quota"}
    return [{"famille": f["nom"], "type": "quota", "quota": 0,
             "source": "Aucune disponibilité cochée dans le sondage (à vérifier avec la famille)"}
            for f in sorted(sondage["familles"], key=lambda f: f["nom"])
            if f["nom"] not in deja
            and not any(v in ("oui", "si_besoin") for v in f["dispos"].values())]


def _entier(valeur, message: str, index: int | None, minimum: int = 0) -> int:
    if isinstance(valeur, str) and valeur.strip().lstrip("-").isdigit():
        valeur = int(valeur.strip())
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < minimum:
        raise ErreurRegle(message, index)
    return valeur


def contraintes_depuis_regles(donnees: dict, sondage: dict) -> dict:
    """Lignes du tableau -> dict brut de contraintes.yaml. ErreurRegle si une ligne est incomplète."""
    noms = {f["nom"] for f in sondage["familles"]}
    lundis = set(semaines(sondage))
    familles: dict[str, dict] = {}
    sources: dict[str, list[str]] = {}
    for i, r in enumerate(donnees.get("regles") or []):
        if not isinstance(r, dict):
            raise ErreurRegle("Ligne illisible.", i)
        nom = normaliser_nom(str(r.get("famille") or ""))
        if not nom:
            raise ErreurRegle("Choisissez une famille.", i)
        if nom not in noms:
            raise ErreurRegle(f"La famille {nom} n'est pas dans le sondage.", i)
        f = familles.setdefault(nom, {})
        type_ = r.get("type")
        if type_ == "absence":
            semaine = str(r.get("semaine") or "")
            if semaine not in lundis:
                raise ErreurRegle("Choisissez la semaine d'absence.", i)
            if semaine in f.get("absences", []):
                raise ErreurRegle(f"Cette semaine d'absence est déjà indiquée pour {nom}.", i)
            f.setdefault("absences", []).append(semaine)
        elif type_ == "quota":
            if "quota_mois" in f:
                raise ErreurRegle(f"{nom} a déjà une ligne « Nombre de perms du mois ».", i)
            f["quota_mois"] = _entier(r.get("quota"), "Indiquez un nombre de perms (0 ou plus).", i)
        elif type_ == "au_moins":
            if "au_moins" in f:
                raise ErreurRegle(f"{nom} a déjà une ligne « Au moins ». Regroupez les jours sur une seule ligne.", i)
            parmi = r.get("parmi") or []
            if not isinstance(parmi, list) or not parmi:
                raise ErreurRegle("Cochez au moins un jour.", i)
            f["au_moins"] = {"n": _entier(r.get("n", 1), "Indiquez un nombre de perms (1 ou plus).", i, 1),
                             "parmi": [_cible_vers_filtre(str(c)) for c in parmi]}
        elif type_ == "preference":
            cible = str(r.get("cible") or "")
            if not cible:
                raise ErreurRegle("Choisissez le jour ou le créneau préféré.", i)
            pref = {"creneau": cible} if RE_CRENEAU.match(cible) else _cible_vers_filtre(cible)
            pref["poids"] = _entier(r.get("poids", 1), "Choisissez l'importance de la préférence.", i)
            f.setdefault("preferences", []).append(pref)
        else:
            raise ErreurRegle("Choisissez le type de règle.", i)
        source = str(r.get("source") or "").strip()
        if source and source not in sources.setdefault(nom, []):
            sources[nom].append(source)
    for nom, liste in sources.items():
        familles[nom]["source"] = " | ".join(liste)
    brut: dict = {}
    reglages = donnees.get("reglages") or {}
    for k in CLES_REGLAGES:
        if k in reglages and reglages[k] not in (None, ""):
            brut[k] = _entier(reglages[k], f"Réglage avancé invalide : {k}.", None,
                              1 if k == "max_parents_par_creneau" else 0)
    if familles:
        brut["familles"] = familles
    non_traduits = donnees.get("non_traduits") or []
    if not isinstance(non_traduits, list):
        raise ErreurRegle("La liste des commentaires à traiter est illisible.")
    non_traduits = [str(t).strip() for t in non_traduits if str(t).strip()]
    if non_traduits:
        brut["commentaires_non_traduits"] = non_traduits
    return brut


def valider_regles(donnees: dict, sondage: dict) -> tuple[dict, dict]:
    """Lignes -> (dict brut, contraintes normalisées par la V1). ErreurRegle sinon."""
    brut = contraintes_depuis_regles(donnees, sondage)
    try:
        return brut, lire_contraintes(brut, sondage)
    except ValueError as e:
        raise ErreurRegle(str(e)) from None


# ---------------------------------------------------------------- étape 3 bis : calcul

def ecrire_json(chemin: Path, donnees: dict) -> None:
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def ecrire_contraintes(chemin: Path, brut: dict) -> None:
    """contraintes.yaml lisible par la V1 (le skill Claude Code peut reprendre le mois)."""
    chemin.write_text(yaml.safe_dump(brut, allow_unicode=True, sort_keys=False), encoding="utf-8")


def calculer(sondage: dict, contraintes: dict) -> dict:
    return construire_planning(sondage, contraintes)


def resumer_calcul(planning: dict) -> dict:
    """Chiffres de l'étape 4."""
    n = Counter(min(len(c["familles"]), 3) for c in planning["creneaux"])
    hors_quota = [{"famille": f, "total": b["total"], "quota": b["quota_mois"]}
                  for f, b in sorted(planning["bilan"].items()) if b["total"] != b["quota_mois"]]
    return {"a_deux": n[2], "a_un": n[1], "vides": n[0], "a_trois_ou_plus": n[3],
            "hors_quota": hors_quota, "alertes": _alertes_groupees(planning["alertes"])}


def _alertes_groupees(alertes: list[dict]) -> list[dict]:
    groupes = []
    for code in sorted({a["code"] for a in alertes}, key=lambda c: (c != "D", c)):
        liste = [a for a in alertes if a["code"] == code]
        groupes.append({"code": code, "titre": LIBELLE_CODE.get(code, code),
                        "gravite": liste[0]["gravite"], "messages": [a["message"] for a in liste]})
    return groupes


# ---------------------------------------------------------------- étape 4 : arbitrage

# Insérée juste après <head> : intercepte le téléchargement de arbitrages.json par la page V1
# (lien « download » sur une URL blob:) et l'envoie au serveur (décision V2-18).
PASSERELLE = """<script>
(function () {
  "use strict";
  var blobs = {};
  var creer = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (objet) {
    var url = creer(objet);
    if (objet instanceof Blob) blobs[url] = objet;
    return url;
  };
  function prevenir(ok, reponse) {
    parent.postMessage({ type: "arbitrage", ok: ok, reponse: reponse }, location.origin);
  }
  function envoyer(texte) {
    var corps;
    try { corps = JSON.stringify({ arbitrages: JSON.parse(texte) }); }
    catch (e) { prevenir(false, { erreur: "Fichier de choix illisible." }); return; }
    fetch("/api/arbitrages", { method: "POST", headers: { "Content-Type": "application/json" }, body: corps })
      .then(function (r) { return r.json().then(function (j) { prevenir(r.ok, j); }); })
      .catch(function () { prevenir(false, { erreur: "L'application ne répond plus. Relancez-la." }); });
  }
  function intercepter(lien) {
    var nom = lien.getAttribute("download") || "";
    var blob = blobs[lien.href];
    if (!/\\.json$/i.test(nom) || !blob) return false;
    parent.postMessage({ type: "arbitrage-recu" }, location.origin);
    blob.text().then(envoyer);
    return true;
  }
  var cliquer = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (!intercepter(this)) return cliquer.call(this);
  };
  window.addEventListener("click", function (e) {
    var lien = e.target && e.target.closest ? e.target.closest("a[download]") : null;
    if (lien && intercepter(lien)) { e.preventDefault(); e.stopPropagation(); }
  }, true);
})();
</script>"""


def page_arbitrage(planning: dict, sondage: dict, contraintes: dict) -> str:
    """Page d'arbitrage V1, passerelle comprise."""
    page = generer_page(planning, sondage, contraintes,
                        apres_export="L'application prépare maintenant le fichier Excel.")
    m = re.search(r"<head[^>]*>", page, re.I)
    if not m:
        raise ValueError("Gabarit d'arbitrage sans balise <head>.")
    return page[:m.end()] + PASSERELLE + page[m.end():]


# ---------------------------------------------------------------- étape 5 : Excel

def finaliser(planning: dict, arbitrages: dict | None, sondage: dict, contraintes: dict) -> dict:
    """Planning final : celui du calcul, ou celui de l'arbitrage revérifié par la V1."""
    if arbitrages is None:
        return planning
    return appliquer_arbitrages(planning, arbitrages, sondage, contraintes)


def nom_excel(mois: str) -> str:
    return f"planning-{mois}.xlsx"


def ecrire_excel(planning: dict, chemin: Path) -> None:
    ecrire_xlsx(planning, chemin)


def bilan(planning: dict, sondage: dict) -> dict:
    """Bilan de l'étape 5 : perms par famille, créneaux à 1 parent, alertes restantes."""
    cr = {c["id"]: c for c in sondage["creneaux"]}
    return {
        "familles": [{"famille": f, "total": b["total"], "quota": b["quota_mois"]}
                     for f, b in sorted(planning["bilan"].items())],
        "a_un_parent": [libelle_creneau(cr[c["id"]])
                        for c in sorted(planning["creneaux"], key=lambda c: (c["date"], c["demi"] != "M"))
                        if len(c["familles"]) == 1 and c["id"] in cr],
        "alertes": _alertes_groupees(planning["alertes"]),
        "regle_dure_violee": any(a["code"] == "D" for a in planning["alertes"]),
    }
