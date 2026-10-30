"""sondage.json + contraintes.yaml -> planning.json (solveur CP-SAT, spec section 6)."""
import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

import yaml
from ortools import __version__ as ORTOOLS_VERSION
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planning_core import normaliser_nom  # noqa: E402

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"]
DEMI_LIBELLE = {"M": "matin", "A": "après-midi"}
DISPOS_UTILISABLES = ("oui", "si_besoin")
GRAVITE = {"A1": "rouge", "A2": "orange", "A3": "orange", "A4": "jaune",
           "A6": "gris", "A7": "jaune", "D": "rouge"}

# Poids des pénalités (spec section 6).
P_QUOTA, P_VIDE, P_TROP, P_AU_MOINS, P_CIBLE, P_SI_BESOIN = 5000, 1000, 100, 50, 20, 10


# ---------------------------------------------------------------- libellés

def libelle_creneau(cr: dict) -> str:
    """Ex. 'lundi 2/11 matin'."""
    d = date.fromisoformat(cr["date"])
    return f"{JOURS[d.weekday()]} {d.day}/{d.month} {DEMI_LIBELLE[cr['demi']]}"


def libelle_jour(iso: str) -> str:
    """Ex. 'lundi 2/11'."""
    d = date.fromisoformat(iso)
    return f"{JOURS[d.weekday()]} {d.day}/{d.month}"


def libelle_semaine(lundi: str) -> str:
    """Ex. 'semaine du 9/11'."""
    d = date.fromisoformat(lundi)
    return f"semaine du {d.day}/{d.month}"


# ---------------------------------------------------------------- contraintes

def _entier(valeur, nom: str, minimum: int = 0) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < minimum:
        raise ValueError(f"{nom} doit être un entier >= {minimum} (reçu {valeur!r})")
    return valeur


def _filtre(brut, sondage: dict, contexte: str) -> tuple[list[str], str]:
    """Filtre {jour, demi?} -> (ids de créneaux du sondage, libellé)."""
    if not isinstance(brut, dict) or set(brut) - {"jour", "demi"}:
        raise ValueError(f"{contexte} : filtre invalide {brut!r} (attendu jour et demi optionnel)")
    jour = str(brut.get("jour", "")).strip().lower()
    if jour not in JOURS:
        raise ValueError(f"{contexte} : jour inconnu {brut.get('jour')!r} (lundi à vendredi)")
    demi = brut.get("demi")
    if demi is not None and demi not in DEMI_LIBELLE:
        raise ValueError(f"{contexte} : demi invalide {demi!r} (attendu M ou A)")
    ids = sorted(
        c["id"] for c in sondage["creneaux"]
        if date.fromisoformat(c["date"]).weekday() == JOURS.index(jour)
        and demi in (None, c["demi"])
    )
    libelle = jour if demi is None else f"{jour} {DEMI_LIBELLE[demi]}"
    if not ids:
        raise ValueError(f"{contexte} : aucun créneau du sondage ne correspond à « {libelle} »")
    return ids, libelle


def _union_filtres(filtres, sondage: dict, contexte: str) -> tuple[list[str], str]:
    ids, libelles = set(), []
    for brut in filtres:
        sous_ids, libelle = _filtre(brut, sondage, contexte)
        ids.update(sous_ids)
        libelles.append(libelle)
    return sorted(ids), " ou ".join(libelles)


def _preference(brut, sondage: dict, contexte: str) -> dict:
    if not isinstance(brut, dict):
        raise ValueError(f"{contexte} : préférence invalide {brut!r}")
    poids = _entier(brut.get("poids", 1), f"{contexte} : poids")
    if "creneau" in brut:
        cr = {c["id"]: c for c in sondage["creneaux"]}.get(brut["creneau"])
        if cr is None:
            raise ValueError(f"{contexte} : créneau inconnu {brut['creneau']!r}")
        return {"creneaux": [cr["id"]], "poids": poids, "libelle": libelle_creneau(cr)}
    filtre = {k: v for k, v in brut.items() if k != "poids"}
    ids, libelle = _filtre(filtre, sondage, contexte)
    return {"creneaux": ids, "poids": poids, "libelle": libelle}


def lire_contraintes(brut: dict | None, sondage: dict) -> dict:
    """Dict YAML -> contraintes normalisées, défauts remplis pour toutes les familles du sondage."""
    brut = brut or {}
    inconnues = set(brut) - {"cible_hebdo", "plafond_hebdo", "max_parents_par_creneau",
                             "familles", "commentaires_non_traduits"}
    if inconnues:
        raise ValueError(f"Clé inconnue dans contraintes.yaml : {sorted(inconnues)}")
    semaines = sorted({c["semaine"] for c in sondage["creneaux"]})
    noms = sorted(f["nom"] for f in sondage["familles"])
    doublons = sorted({n for n in noms if noms.count(n) > 1})
    if doublons:
        raise ValueError(f"Famille en double dans sondage.json : {doublons} "
                         f"(relancer fetch_framadate.py, qui fusionne les doublons)")
    yaml_familles = {}
    for cle, val in (brut.get("familles") or {}).items():
        nom = normaliser_nom(str(cle))
        if nom not in noms:
            raise ValueError(f"Famille {cle!r} du yaml absente du sondage")
        if nom in yaml_familles:
            raise ValueError(f"Famille {nom} déclarée deux fois dans le yaml")
        yaml_familles[nom] = val or {}
    familles = {}
    for nom in noms:
        v = yaml_familles.get(nom, {})
        ctx = f"Famille {nom}"
        inc = set(v) - {"quota_mois", "absences", "au_moins", "preferences", "source"}
        if inc:
            raise ValueError(f"{ctx} : clé inconnue {sorted(inc)}")
        absences = sorted({
            a.isoformat() if isinstance(a, date) else str(a) for a in v.get("absences") or []
        })
        for a in absences:
            if a not in semaines:
                raise ValueError(
                    f"{ctx} : semaine d'absence inconnue {a!r} (lundis du sondage : {semaines})")
        quota = v.get("quota_mois")
        quota = len(semaines) - len(absences) if quota is None else _entier(quota, f"{ctx} : quota_mois")
        au_moins = None
        if v.get("au_moins") is not None:
            brut_am = v["au_moins"]
            if not isinstance(brut_am, dict) or not brut_am.get("parmi"):
                raise ValueError(f"{ctx} : au_moins attend n et parmi (liste de filtres)")
            ids, libelle = _union_filtres(brut_am["parmi"], sondage, f"{ctx} : au_moins")
            au_moins = {"n": _entier(brut_am.get("n", 1), f"{ctx} : au_moins.n", 1),
                        "creneaux": ids, "libelle": libelle}
        familles[nom] = {
            "quota_mois": quota, "absences": absences, "au_moins": au_moins,
            "preferences": [_preference(p, sondage, f"{ctx} : preference")
                            for p in v.get("preferences") or []],
            "source": v.get("source", ""),
        }
    return {
        "cible_hebdo": _entier(brut.get("cible_hebdo", 1), "cible_hebdo"),
        "plafond_hebdo": _entier(brut.get("plafond_hebdo", 2), "plafond_hebdo"),
        "max_parents_par_creneau": _entier(brut.get("max_parents_par_creneau", 2),
                                           "max_parents_par_creneau", 1),
        "familles": familles,
        "commentaires_non_traduits": [str(t) for t in brut.get("commentaires_non_traduits") or []],
    }


def charger_contraintes(chemin: Path, sondage: dict) -> dict:
    """Lit contraintes.yaml. ValueError avec un message clair si le fichier est invalide."""
    try:
        brut = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"contraintes.yaml invalide : {e}") from None
    if brut is not None and not isinstance(brut, dict):
        raise ValueError("contraintes.yaml invalide : la racine doit être un dictionnaire")
    return lire_contraintes(brut, sondage)


# ---------------------------------------------------------------- évaluation

def _alerte(code, message, creneau=None, famille=None, regle=None) -> dict:
    a = {"code": code, "gravite": GRAVITE[code], "creneau": creneau,
         "famille": famille, "message": message}
    if regle:
        a["regle"] = regle
    return a


def creneaux_avec_familles(sondage: dict, affectations: list[dict]) -> list[dict]:
    """Liste des créneaux du sondage, chacun avec les familles affectées (triées)."""
    par_creneau: dict[str, set] = {}
    for a in affectations:
        par_creneau.setdefault(a["creneau"], set()).add(a["famille"])
    return [
        {"id": c["id"], "date": c["date"], "demi": c["demi"], "semaine": c["semaine"],
         "semaine_iso": c.get("semaine_iso") or date.fromisoformat(c["date"]).isocalendar().week,
         "familles": sorted(par_creneau.get(c["id"], []))}
        for c in sorted(sondage["creneaux"], key=lambda c: c["id"])
    ]


def _violations_dures(contraintes, affectations, cr_par_id, dispos) -> list[dict]:
    """Alertes D : règles dures D1 à D4, et références inconnues."""
    alertes = []
    valides = set()
    for a in affectations:
        f, c = a["famille"], a["creneau"]
        if f not in contraintes["familles"]:
            alertes.append(_alerte("D", f"Famille inconnue du sondage : {f}", c, f, "D3"))
        elif c not in cr_par_id:
            alertes.append(_alerte("D", f"Créneau inconnu du sondage : {c} (famille {f})", c, f, "D3"))
        elif (f, c) in valides:
            alertes.append(_alerte(
                "D", f"La famille {f} est affectée deux fois sur {libelle_creneau(cr_par_id[c])}",
                c, f, "D1"))
        else:
            valides.add((f, c))
    par_jour: dict[tuple, list] = {}
    par_semaine: dict[tuple, list] = {}
    for f, c in sorted(valides):
        cr = cr_par_id[c]
        lib = libelle_creneau(cr)
        if dispos[f].get(c) not in DISPOS_UTILISABLES:
            alertes.append(_alerte(
                "D", f"La famille {f} est affectée sur {lib} alors qu'elle n'est pas disponible",
                c, f, "D3"))
        if cr["semaine"] in contraintes["familles"][f]["absences"]:
            alertes.append(_alerte(
                "D", f"La famille {f} est affectée sur {lib}, pendant sa semaine d'absence",
                c, f, "D4"))
        par_jour.setdefault((f, cr["date"]), []).append(c)
        par_semaine.setdefault((f, cr["semaine"]), []).append(c)
    for (f, jour), ids in sorted(par_jour.items()):
        if len(ids) > 1:
            alertes.append(_alerte(
                "D", f"La famille {f} a {len(ids)} perms le même jour ({libelle_jour(jour)})",
                ids[0], f, "D1"))
    for (f, sem), ids in sorted(par_semaine.items()):
        if len(ids) > contraintes["plafond_hebdo"]:
            alertes.append(_alerte(
                "D", f"La famille {f} a {len(ids)} perms la {libelle_semaine(sem)} "
                     f"(maximum {contraintes['plafond_hebdo']})", None, f, "D2"))
    return alertes


def evaluer(sondage: dict, contraintes: dict, affectations: list[dict]) -> dict:
    """Bilan par famille et alertes pour une liste d'affectations quelconque.

    `contraintes` est le dict normalisé de `lire_contraintes`. Indépendant du solveur.
    """
    cr_par_id = {c["id"]: c for c in sondage["creneaux"]}
    dispos = {f["nom"]: f["dispos"] for f in sondage["familles"]}
    semaines = sorted({c["semaine"] for c in sondage["creneaux"]})
    alertes = _violations_dures(contraintes, affectations, cr_par_id, dispos)
    valides = sorted({(a["famille"], a["creneau"]) for a in affectations
                      if a["famille"] in contraintes["familles"] and a["creneau"] in cr_par_id})

    bilan = {}
    for f in sorted(contraintes["familles"]):
        par_semaine = {s: 0 for s in semaines}
        for fam, c in valides:
            if fam == f:
                par_semaine[cr_par_id[c]["semaine"]] += 1
        bilan[f] = {"quota_mois": contraintes["familles"][f]["quota_mois"],
                    "total": sum(par_semaine.values()), "par_semaine": par_semaine}

    parents = {c: [] for c in cr_par_id}
    for f, c in valides:
        parents[c].append(f)
    for c in sorted(parents):
        lib = libelle_creneau(cr_par_id[c])
        n = len(parents[c])
        if n == 0:
            alertes.append(_alerte("A1", f"Créneau sans parent : {lib}", c))
        elif n > contraintes["max_parents_par_creneau"]:
            alertes.append(_alerte(
                "A2", f"{n} parents sur {lib} ({', '.join(sorted(parents[c]))}) : "
                      f"le maximum prévu est {contraintes['max_parents_par_creneau']}", c))
    for f, b in bilan.items():
        if b["total"] != b["quota_mois"]:
            alertes.append(_alerte(
                "A3", f"La famille {f} a {b['total']} perm(s) sur le mois, "
                      f"son quota est de {b['quota_mois']}", None, f))
    for texte in contraintes["commentaires_non_traduits"]:
        alertes.append(_alerte("A4", f"Commentaire à traiter à la main : {texte}"))
    for f, c in valides:
        if dispos[f].get(c) == "si_besoin":
            alertes.append(_alerte(
                "A6", f"La famille {f} est placée sur {libelle_creneau(cr_par_id[c])} "
                      f"alors qu'elle avait répondu « si besoin »", c, f))
    alertes.extend(_regles_non_respectees(contraintes, valides))
    alertes.sort(key=lambda a: (a["code"], a["creneau"] or "", a["famille"] or "", a["message"]))
    return {"bilan": bilan, "alertes": alertes}


def _regles_non_respectees(contraintes: dict, valides: list[tuple]) -> list[dict]:
    """Alertes A7 : au_moins et préférences non satisfaits, une alerte par famille."""
    alertes = []
    for f, cf in sorted(contraintes["familles"].items()):
        pris = {c for fam, c in valides if fam == f}
        manques = []
        am = cf["au_moins"]
        if am and len(pris & set(am["creneaux"])) < am["n"]:
            manques.append(f"au moins {am['n']} perm(s) parmi : {am['libelle']}")
        for p in cf["preferences"]:
            if not pris & set(p["creneaux"]):
                manques.append(f"préférence pour : {p['libelle']}")
        if manques:
            alertes.append(_alerte(
                "A7", f"La famille {f} : règle non respectée ({' ; '.join(manques)})", None, f))
    return alertes


# ---------------------------------------------------------------- résolution

def resoudre(sondage: dict, contraintes: dict, temps_max: float = 10.0) -> tuple[list[dict], dict]:
    """Modèle CP-SAT. Renvoie (affectations, infos solveur sans la durée)."""
    m = cp_model.CpModel()
    creneaux = sorted(sondage["creneaux"], key=lambda c: c["id"])
    familles = sorted(contraintes["familles"])
    dispos = {f["nom"]: f["dispos"] for f in sondage["familles"]}
    semaines = sorted({c["semaine"] for c in creneaux})
    x = {}
    for f in familles:
        absences = contraintes["familles"][f]["absences"]
        for c in creneaux:
            if dispos[f].get(c["id"]) in DISPOS_UTILISABLES and c["semaine"] not in absences:
                x[f, c["id"]] = m.NewBoolVar(f"x_{f}_{c['id']}")

    def somme(famille, ids):
        """Somme des x de `famille` (ou de toutes si None) sur les créneaux `ids`."""
        return sum(x[k] for k in sorted(x) if k[1] in ids and famille in (None, k[0]))

    ids_jour: dict[str, set] = {}
    ids_semaine: dict[str, set] = {}
    for c in creneaux:
        ids_jour.setdefault(c["date"], set()).add(c["id"])
        ids_semaine.setdefault(c["semaine"], set()).add(c["id"])
    tous = {c["id"] for c in creneaux}
    penalites = []

    for f in familles:
        cf = contraintes["familles"][f]
        for ids in ids_jour.values():                                    # D1
            m.Add(somme(f, ids) <= 1)
        for ids in ids_semaine.values():                                 # D2
            m.Add(somme(f, ids) <= contraintes["plafond_hebdo"])
        manque, exces = m.NewIntVar(0, 100, f"manque_{f}"), m.NewIntVar(0, 100, f"exces_{f}")
        m.Add(somme(f, tous) - cf["quota_mois"] == exces - manque)
        penalites.append(P_QUOTA * (manque + exces))                     # S0
        for sem in semaines:                                             # S4
            if sem in cf["absences"]:
                continue
            ecart = m.NewIntVar(0, 100, f"ecart_{f}_{sem}")
            total = somme(f, ids_semaine[sem])
            m.Add(ecart >= total - contraintes["cible_hebdo"])
            m.Add(ecart >= contraintes["cible_hebdo"] - total)
            penalites.append(P_CIBLE * ecart)
        if cf["au_moins"]:                                               # S3
            am = cf["au_moins"]
            reste = m.NewIntVar(0, am["n"], f"reste_{f}")
            m.Add(reste >= am["n"] - somme(f, set(am["creneaux"])))
            penalites.append(P_AU_MOINS * reste)
        for i, p in enumerate(cf["preferences"]):                        # S6
            non_satisfaite = m.NewBoolVar(f"pref_{f}_{i}")
            m.Add(somme(f, set(p["creneaux"])) + non_satisfaite >= 1)
            penalites.append(p["poids"] * non_satisfaite)
    for c in creneaux:
        n = somme(None, {c["id"]})
        vide = m.NewBoolVar(f"vide_{c['id']}")                           # S1
        m.Add(n + vide >= 1)
        penalites.append(P_VIDE * vide)
        en_trop = m.NewIntVar(0, len(familles), f"trop_{c['id']}")       # S2
        m.Add(en_trop >= n - contraintes["max_parents_par_creneau"])
        penalites.append(P_TROP * en_trop)
        # Un 2e parent en trop sur le même créneau coûte double : deux triplets
        # valent mieux qu'un créneau à 4 parents.
        en_trop_2 = m.NewIntVar(0, len(familles), f"trop2_{c['id']}")
        m.Add(en_trop_2 >= n - contraintes["max_parents_par_creneau"] - 1)
        penalites.append(P_TROP * en_trop_2)
    for (f, c), var in sorted(x.items()):                                # S5
        if dispos[f][c] == "si_besoin":
            penalites.append(P_SI_BESOIN * var)

    m.Minimize(sum(penalites))
    solveur = cp_model.CpSolver()
    solveur.parameters.num_search_workers = 1
    solveur.parameters.random_seed = 0
    # Relaxation linéaire plus forte : sans elle, la preuve d'optimalité dépasse 10 s
    # dès qu'une semaine manque de créneaux (férié, vacances).
    solveur.parameters.linearization_level = 2
    solveur.parameters.max_time_in_seconds = temps_max
    statut = solveur.StatusName(solveur.Solve(m))
    if statut not in ("OPTIMAL", "FEASIBLE"):
        raise ValueError(f"Le solveur n'a trouvé aucun planning (statut {statut})")
    affectations = [
        {"famille": f, "creneau": c, "dispo": dispos[f][c], "origine": "solveur"}
        for (f, c), var in sorted(x.items()) if solveur.Value(var)
    ]
    return affectations, {"statut": statut, "score": int(round(solveur.ObjectiveValue())),
                          "ortools": ORTOOLS_VERSION}


def empreinte(sondage: dict, contraintes: dict) -> str:
    """SHA-256 du JSON canonique de {sondage, contraintes}."""
    canon = json.dumps({"sondage": sondage, "contraintes": contraintes},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def construire_planning(sondage: dict, contraintes: dict, temps_max: float = 10.0) -> dict:
    """Résout puis assemble le planning.json."""
    debut = time.monotonic()
    affectations, infos = resoudre(sondage, contraintes, temps_max)
    infos["duree_s"] = round(time.monotonic() - debut, 2)
    resultat = evaluer(sondage, contraintes, affectations)
    return {
        "poll_id": sondage["poll_id"], "titre": sondage["titre"],
        "empreinte": empreinte(sondage, contraintes),
        "solveur": {k: infos[k] for k in ("statut", "score", "duree_s", "ortools")},
        "creneaux": creneaux_avec_familles(sondage, affectations),
        "affectations": affectations,
        "bilan": resultat["bilan"], "alertes": resultat["alertes"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="sondage.json + contraintes.yaml -> planning.json")
    ap.add_argument("--sondage", required=True)
    ap.add_argument("--contraintes", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--temps-max", type=float, default=10.0, help="durée maximale du solveur (s)")
    args = ap.parse_args(argv)
    try:
        sondage = json.loads(Path(args.sondage).read_text(encoding="utf-8"))
        contraintes = charger_contraintes(Path(args.contraintes), sondage)
        planning = construire_planning(sondage, contraintes, args.temps_max)
        Path(args.out).write_text(
            json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
    except (ValueError, OSError, KeyError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
