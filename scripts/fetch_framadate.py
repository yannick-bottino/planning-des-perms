"""Télécharge un sondage Framadate (CSV + page HTML) et écrit sondage.json."""
import argparse
import csv
import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planning_core import (  # noqa: E402
    convertir_demi, convertir_dispo, id_creneau, lundi_de, normaliser_nom,
)

BASE = "https://framadate.org/polls/"


def extraire_poll_id(entree: str) -> str:
    """Accepte une URL (.../polls/<id> ou .../polls/<id>.csv) ou l'id seul."""
    entree = entree.strip()
    m = re.search(r"/polls/([A-Za-z0-9]+)", entree)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]+", entree):
        return entree
    raise ValueError(f"Impossible d'extraire l'id du sondage depuis : {entree!r}")


def telecharger(url: str) -> str:
    """Télécharge une URL et décode en UTF-8."""
    req = urllib.request.Request(
        url, headers={"Accept-Language": "en-GB", "User-Agent": "planning-perms/1"}
    )
    with urllib.request.urlopen(req, timeout=30) as rep:
        return rep.read().decode("utf-8")


def parser_csv(texte: str, avertissements: list[str]) -> tuple[list[dict], list[dict]]:
    """CSV Framadate -> (créneaux, familles)."""
    lignes = list(csv.reader(io.StringIO(texte.lstrip("﻿"), newline="")))
    if len(lignes) < 2:
        raise ValueError("CSV vide ou sans les deux lignes d'en-tête")
    dates, demis = lignes[0][1:], lignes[1][1:]
    if not dates:
        raise ValueError("CSV sans aucune colonne de créneau")
    creneaux = []
    for i, brut in enumerate(dates):
        d = date.fromisoformat(brut.strip())
        demi = convertir_demi(demis[i] if i < len(demis) else "")
        creneaux.append({
            "id": id_creneau(d, demi), "date": d.isoformat(), "demi": demi,
            "semaine": lundi_de(d).isoformat(), "semaine_iso": d.isocalendar().week,
        })
    familles = []
    for ligne in lignes[2:]:
        if not any(c.strip() for c in ligne):
            continue
        brut = ligne[0].strip()
        if not brut:
            avertissements.append("Ligne sans nom de famille ignorée")
            continue
        nom = normaliser_nom(brut)
        dispos = {}
        for i, cr in enumerate(creneaux):
            cellule = ligne[i + 1] if i + 1 < len(ligne) else ""
            dispos[cr["id"]] = convertir_dispo(cellule, nom, cr["id"])
        familles.append({"nom": nom, "nom_brut": brut, "dispos": dispos})
    return creneaux, _fusionner_doublons(familles, avertissements)


# Ordre de fusion : la meilleure réponse d'une des lignes l'emporte.
_RANG_DISPO = {"vide": 0, "non": 1, "si_besoin": 2, "oui": 3}


def _fusionner_doublons(familles: list[dict], avertissements: list[str]) -> list[dict]:
    """Une entrée par nom normalisé. Plusieurs lignes (ex. un vote par parent) sont
    fusionnées créneau par créneau en gardant la meilleure réponse."""
    par_nom: dict[str, dict] = {}
    for f in familles:
        deja = par_nom.get(f["nom"])
        if deja is None:
            par_nom[f["nom"]] = f
            continue
        deja.setdefault("noms_bruts", [deja["nom_brut"]]).append(f["nom_brut"])
        for c, v in f["dispos"].items():
            if _RANG_DISPO[v] > _RANG_DISPO[deja["dispos"][c]]:
                deja["dispos"][c] = v
    for f in par_nom.values():
        if "noms_bruts" in f:
            avertissements.append(
                f"Plusieurs lignes de famille se normalisent en {f['nom']} "
                f"({' / '.join(f['noms_bruts'])}) : dispos fusionnées, à vérifier")
    return list(par_nom.values())


class _ParseurPage(HTMLParser):
    """Extrait le titre et les <article id="comment-..."> de la page Framadate."""

    def __init__(self):
        super().__init__()
        self.titre = ""
        self.commentaires: list[dict] = []
        self._dans_titre = False
        self._article = None   # dict du commentaire en cours
        self._zone = None      # 'auteur' | 'date' | None
        self._header = False
        self._div_prof = 0
        self._para: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._dans_titre = True
        elif tag == "article" and (a.get("id") or "").startswith("comment-"):
            self._article = {"auteur": "", "date_iso": None, "date_txt": "", "paras": []}
        elif self._article is None:
            return
        elif tag == "header":
            self._header = True
        elif tag == "span" and self._header and self._zone is None and not self._article["auteur"]:
            self._zone = "auteur"
        elif tag == "time" and self._header:
            self._article["date_iso"] = a.get("datetime")
            self._zone = "date"
        elif tag == "div" and not self._header:
            self._div_prof += 1
        elif tag == "p" and self._div_prof:
            self._para = []
        elif tag == "br" and self._para is not None:
            self._para.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._dans_titre = False
        elif self._article is None:
            return
        elif tag == "header":
            self._header = False
        elif tag in ("span", "time") and self._zone in ("auteur", "date"):
            self._zone = None
        elif tag == "div" and self._div_prof:
            self._div_prof -= 1
        elif tag == "p" and self._para is not None:
            self._article["paras"].append("".join(self._para).strip())
            self._para = None
        elif tag == "article":
            a = self._article
            self.commentaires.append({
                "auteur": a["auteur"].strip(), "date_iso": a["date_iso"],
                "date_txt": a["date_txt"].strip(), "texte": "\n".join(a["paras"]).strip(),
            })
            self._article = None
            self._header = False
            self._zone = None
            self._div_prof = 0
            self._para = None

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data
        elif self._article is None:
            return
        elif self._zone == "auteur":
            self._article["auteur"] += data
        elif self._zone == "date":
            self._article["date_txt"] += data
        elif self._para is not None:
            # Les sauts de ligne du source suivent un <br />: on les garde tels quels.
            self._para.append(data)


def _date_commentaire(c: dict, avertissements: list[str]) -> str:
    """Date ISO à la minute : attribut datetime, sinon texte '11 Oct 2026, 10:43'."""
    if c["date_iso"]:
        try:
            return datetime.fromisoformat(c["date_iso"]).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    try:
        return datetime.strptime(c["date_txt"], "%d %b %Y, %H:%M").strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        avertissements.append(f"Date de commentaire illisible, gardée brute : {c['date_txt']!r}")
        return c["date_txt"]


def parser_html(texte: str, avertissements: list[str]) -> tuple[str, list[dict]]:
    """Page HTML -> (titre, commentaires)."""
    p = _ParseurPage()
    p.feed(texte)
    titre = re.sub(r"\s*[–—-]\s*Framadate\s*$", "", p.titre.strip())
    commentaires = [
        {
            "auteur": normaliser_nom(c["auteur"]), "auteur_brut": c["auteur"],
            "date": _date_commentaire(c, avertissements), "texte": c["texte"],
        }
        for c in p.commentaires
    ]
    if not commentaires:
        # Un changement de gabarit Framadate donnerait 0 commentaire sans erreur.
        avertissements.append("Aucun commentaire lu : vérifier les commentaires sur la page du sondage")
    return titre, commentaires


def construire(poll_id: str, csv_txt: str, html_txt: str) -> dict:
    """Assemble le sondage.json (spec section 5)."""
    avertissements: list[str] = []
    creneaux, familles = parser_csv(csv_txt, avertissements)
    titre, commentaires = parser_html(html_txt, avertissements)
    noms = {f["nom"] for f in familles}
    for auteur in sorted({c["auteur"] for c in commentaires} - noms):
        avertissements.append(f"Auteur de commentaire absent des familles : {auteur}")
    return {
        "poll_id": poll_id, "titre": titre, "creneaux": creneaux, "familles": familles,
        "commentaires": commentaires, "avertissements": avertissements,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sondage Framadate -> sondage.json")
    ap.add_argument("poll", nargs="?", help="URL ou id du sondage")
    ap.add_argument("--out", required=True, help="fichier JSON de sortie")
    ap.add_argument("--csv", help="CSV local (mode hors ligne)")
    ap.add_argument("--html", help="page HTML locale (mode hors ligne)")
    args = ap.parse_args(argv)
    try:
        if args.csv or args.html:
            if not (args.csv and args.html):
                raise ValueError("Le mode hors ligne demande --csv et --html ensemble")
            csv_txt = Path(args.csv).read_bytes().decode("utf-8")
            html_txt = Path(args.html).read_bytes().decode("utf-8")
            poll_id = extraire_poll_id(args.poll) if args.poll else Path(args.csv).stem
        else:
            if not args.poll:
                raise ValueError("Indiquer une URL ou un id de sondage (ou --csv et --html)")
            poll_id = extraire_poll_id(args.poll)
            csv_txt = telecharger(f"{BASE}{poll_id}.csv")
            html_txt = telecharger(f"{BASE}{poll_id}")
        data = construire(poll_id, csv_txt, html_txt)
        Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except (ValueError, OSError, urllib.error.URLError, csv.Error, UnicodeDecodeError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    for w in data["avertissements"]:
        print(f"Avertissement : {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
