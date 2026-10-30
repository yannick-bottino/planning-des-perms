"""Moteurs d'IA : traduire les commentaires du sondage en règles (spec V2, V2-9 à V2-13).

L'IA ne fait que proposer. Sa réponse est validée par `solve.lire_contraintes` (V1).
"""
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import parcours
from solve import lire_contraintes

REFERENCES = parcours.SKILL / "references"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODELE = "deepseek-chat"
DELAI_CLAUDE_S = 180
DELAI_CODEX_S = 300
MAX_JETONS = 8000
DELAI_DEEPSEEK_S = 120
NOMS = {"claude": "Claude", "codex": "ChatGPT", "deepseek": "DeepSeek"}


class ErreurMoteur(Exception):
    """Le moteur n'a pas pu répondre (absent, injoignable, clé refusée). Message lisible."""


# ---------------------------------------------------------------- consigne

def section(markdown: str, titre: str) -> str:
    """Texte d'une section de niveau 2 (« ## titre »), jusqu'à la section suivante de même niveau."""
    m = re.search(rf"^## {re.escape(titre)}\s*$(.*?)(?=^## |\Z)", markdown, re.M | re.S)
    if not m:
        raise ValueError(f"Section « {titre} » introuvable dans les références")
    return m.group(1).strip()


def consigne_systeme() -> str:
    """Règles de traduction lues dans les références V1 (aucune copie dans le code)."""
    regles = (REFERENCES / "regles-affectation.md").read_text(encoding="utf-8")
    formats = (REFERENCES / "format-planning.md").read_text(encoding="utf-8")
    return "\n\n".join([
        "Tu aides la famille planning d'une crèche parentale. Tu traduis les commentaires "
        "d'un sondage de disponibilités en règles pour un programme de calcul de planning. "
        "Tu ne places jamais une famille toi-même.",
        "# Format attendu (le fichier contraintes.yaml, que tu écris en JSON)",
        section(formats, "contraintes.yaml"),
        "# Comment traduire un commentaire",
        section(regles, "Traduire un commentaire en règle"),
        "# Consignes de réponse",
        "- Réponds uniquement par un objet JSON, sans texte autour, avec les clés "
        "`familles` (objet) et `commentaires_non_traduits` (liste de textes).\n"
        "- N'ajoute une famille que si un commentaire la concerne. Les noms de famille sont "
        "ceux de la liste fournie, en majuscules.\n"
        "- Chaque famille porte une clé `source` : « <auteur>, <jj/mm> : <texte du commentaire> ».\n"
        "- Les semaines d'absence sont des lundis de la liste fournie (format AAAA-MM-JJ).\n"
        "- Un commentaire sans demande (remerciement, information) ne produit rien.\n"
        "- En cas de doute, copie le commentaire (auteur compris) dans `commentaires_non_traduits`.",
    ])


def donnees_sondage(sondage: dict) -> str:
    """Partie variable de la consigne : semaines, familles, créneaux, commentaires."""
    lundis = parcours.semaines(sondage)
    sans_dispo = {}
    for f in sondage["familles"]:
        for s in lundis:
            ids = [c["id"] for c in sondage["creneaux"] if c["semaine"] == s]
            if not any(f["dispos"].get(i) in ("oui", "si_besoin") for i in ids):
                sans_dispo.setdefault(f["nom"], []).append(s)
    return json.dumps({
        "titre": sondage["titre"],
        "semaines_lundis": lundis,
        "nombre_de_semaines": len(lundis),
        "familles": sorted(f["nom"] for f in sondage["familles"]),
        "creneaux": sorted(c["id"] for c in sondage["creneaux"]),
        "familles_sans_aucune_dispo_ces_semaines": sans_dispo,
        "commentaires": [{"auteur": c["auteur"], "date": c["date"], "texte": c["texte"]}
                         for c in sondage.get("commentaires", [])],
    }, ensure_ascii=False, indent=1)


def extraire_json(texte: str) -> dict:
    """Premier objet JSON d'une réponse, blocs ``` compris. ValueError sinon."""
    texte = texte.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", texte, re.S)
    if m:
        texte = m.group(1).strip()
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin < debut:
        raise ValueError("la réponse ne contient aucun objet JSON")
    try:
        objet = json.loads(texte[debut:fin + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalide : {e}") from None
    if not isinstance(objet, dict):
        raise ValueError("la racine du JSON doit être un objet")
    return objet


def ecarter_reglages(brut: dict) -> dict:
    """Les réglages généraux ne viennent jamais de l'IA : un commentaire de famille ne doit pas
    changer une règle qui vaut pour tout le monde. Une valeur proposée devient une demande à traiter."""
    propres = {k: v for k, v in brut.items() if k not in parcours.CLES_REGLAGES}
    ecartes = [f"Réglage général proposé par l'IA, non appliqué : {k} = {brut[k]}"
               for k in parcours.CLES_REGLAGES if k in brut]
    if ecartes:
        textes = propres.get("commentaires_non_traduits")
        propres["commentaires_non_traduits"] = (list(textes) if isinstance(textes, list) else []) + ecartes
    return propres


def verifier(reponse: str, sondage: dict) -> dict:
    """Réponse brute de l'IA -> dict brut validé par la V1 et convertible en lignes du tableau."""
    brut = ecarter_reglages(extraire_json(reponse))
    if not isinstance(brut.get("commentaires_non_traduits", []), list):
        raise ValueError("commentaires_non_traduits doit être une liste de textes")
    if not isinstance(brut.get("familles") or {}, dict):
        raise ValueError("familles doit être un objet (nom de famille -> règles)")
    lire_contraintes(brut, sondage)
    # Le tableau doit pouvoir afficher puis réécrire ces règles.
    parcours.contraintes_depuis_regles(parcours.regles_depuis_contraintes(brut), sondage)
    return brut


# ---------------------------------------------------------------- moteurs

def tuer_arbre(processus: subprocess.Popen, attendre: bool = True) -> None:
    """Arrête le processus et ses enfants (claude.cmd lance node, que kill() seul laisserait).
    `attendre` faux : un autre fil attend déjà ce processus (communicate), on ne le double pas."""
    if sys.platform == "win32":
        taskkill = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "taskkill.exe")
        subprocess.run([taskkill, "/T", "/F", "/PID", str(processus.pid)], capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    processus.kill()
    if attendre:
        try:
            processus.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass


# Processus d'IA en cours : l'arrêt de l'outil doit les tuer (sinon Claude ou Codex tourne encore, caché).
EN_COURS: set = set()
VERROU_EN_COURS = threading.Lock()


def suivre_processus(processus: subprocess.Popen) -> subprocess.Popen:
    with VERROU_EN_COURS:
        EN_COURS.add(processus)
    return processus


def oublier_processus(processus: subprocess.Popen) -> None:
    with VERROU_EN_COURS:
        EN_COURS.discard(processus)


def tuer_moteurs() -> None:
    """Arrête tous les processus d'IA lancés par cette application."""
    with VERROU_EN_COURS:
        restants = list(EN_COURS)
    for processus in restants:
        if processus.poll() is None:
            try:
                tuer_arbre(processus, attendre=False)
            except OSError:
                pass


def commande_claude() -> str | None:
    """Exécutable de Claude Code (détection : assistants.py, V3-7). Nom gardé : les tests le remplacent."""
    import assistants  # import tardif : assistants.py utilise tuer_arbre de ce module
    return assistants.commande("claude")


def commande_codex() -> str | None:
    import assistants
    return assistants.commande("codex")


def texte_conversation(messages: list[dict]) -> str:
    """Pas de session à reprendre : la conversation est rejouée en un seul texte."""
    return "\n\n".join(
        m["content"] if m["role"] != "assistant" else f"Ta réponse précédente :\n{m['content']}"
        for m in messages)


class MoteurClaude:
    """Claude Code en mode non interactif, sans outils ni réglages du poste (V2-9)."""
    nom = "claude"

    def __init__(self, dossier: Path):
        self.dossier = dossier

    def appeler(self, messages: list[dict]) -> str:
        commande = commande_claude()
        if not commande:
            raise ErreurMoteur("Claude n'est pas installé sur cet ordinateur.")
        texte = texte_conversation(messages)
        args = [commande, "-p", "--output-format", "json", "--model", "sonnet", "--tools", "",
                "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
        try:
            processus = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.dossier, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise ErreurMoteur(f"Claude n'a pas pu démarrer ({e.strerror}).") from None
        suivre_processus(processus)
        try:
            stdout, _ = processus.communicate(texte.encode("utf-8"), timeout=DELAI_CLAUDE_S)
        except subprocess.TimeoutExpired:
            tuer_arbre(processus)
            raise ErreurMoteur("Claude n'a pas répondu à temps.") from None
        finally:
            oublier_processus(processus)
        sortie = stdout.decode("utf-8", "replace")
        try:
            resultat = json.loads(sortie)
        except json.JSONDecodeError:
            raise ErreurMoteur("Claude a répondu dans un format inattendu. "
                               "Vérifiez qu'il est connecté (lancez « claude » une fois).") from None
        if processus.returncode != 0 or resultat.get("is_error") or not isinstance(resultat.get("result"), str):
            raise ErreurMoteur("Claude a renvoyé une erreur. Vérifiez qu'il est connecté "
                               "(lancez « claude » une fois dans un terminal).")
        return resultat["result"]


class MoteurCodex:
    """Codex (abonnement ChatGPT) en mode non interactif : lecture seule, sans session gardée, sans
    réglages du poste (V3-13). Le dernier message est lu dans le fichier donné à `-o`."""
    nom = "codex"

    def __init__(self, dossier: Path):
        self.dossier = dossier

    def appeler(self, messages: list[dict]) -> str:
        commande = commande_codex()
        if not commande:
            raise ErreurMoteur("ChatGPT n'est pas installé sur cet ordinateur.")
        texte = texte_conversation(messages)
        # Dossier de travail vide et jetable : l'IA n'a aucun fichier du mois à portée (V3-13). Aucun réglage
        # de `codex features list` ne coupe son outil de commande (vérifié sur Codex 0.166.0) : le bac à sable
        # en lecture seule reste la seule barrière, d'où ce dossier vide.
        with tempfile.TemporaryDirectory(prefix="planning-perms-", ignore_cleanup_errors=True) as temp:
            sortie = Path(temp) / "reponse.txt"
            travail = Path(temp) / "travail"
            travail.mkdir()
            args = [commande, "exec", "-", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                    "--ignore-user-config", "--color", "never", "-C", str(travail), "-o", str(sortie)]
            try:
                processus = subprocess.Popen(
                    args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=travail, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as e:
                raise ErreurMoteur(f"ChatGPT n'a pas pu démarrer ({e.strerror}).") from None
            suivre_processus(processus)
            try:
                processus.communicate(texte.encode("utf-8"), timeout=DELAI_CODEX_S)
            except subprocess.TimeoutExpired:
                tuer_arbre(processus)
                raise ErreurMoteur("ChatGPT n'a pas répondu à temps.") from None
            finally:
                oublier_processus(processus)
            try:
                reponse = sortie.read_text(encoding="utf-8")
            except OSError:
                reponse = ""
        if processus.returncode != 0 or not reponse.strip():
            raise ErreurMoteur("ChatGPT a renvoyé une erreur. Vérifiez qu'il est connecté "
                               "(Changer d'assistant, puis ChatGPT).")
        return reponse


class MoteurDeepSeek:
    """API DeepSeek compatible OpenAI (V2-10). La clé ne sort jamais de cette classe."""
    nom = "deepseek"

    def __init__(self, cle: str):
        self._cle = cle

    def appeler(self, messages: list[dict]) -> str:
        if not self._cle:
            raise ErreurMoteur("Aucune clé DeepSeek n'est enregistrée.")
        corps = json.dumps({
            "model": os.environ.get("PLANNING_PERMS_DEEPSEEK_MODELE") or DEEPSEEK_MODELE,
            "messages": messages, "temperature": 0, "max_tokens": MAX_JETONS,
            "response_format": {"type": "json_object"}}).encode("utf-8")
        req = urllib.request.Request(
            os.environ.get("PLANNING_PERMS_DEEPSEEK_URL") or DEEPSEEK_URL, data=corps,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._cle}"})
        try:
            with urllib.request.urlopen(req, timeout=DELAI_DEEPSEEK_S) as rep:
                resultat = json.loads(rep.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            messages_http = {401: "La clé DeepSeek est refusée. Vérifiez-la dans les réglages.",
                             402: "Le crédit DeepSeek est épuisé.",
                             429: "DeepSeek est saturé. Réessayez dans une minute."}
            raise ErreurMoteur(messages_http.get(e.code, f"DeepSeek a renvoyé l'erreur {e.code}.")) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise ErreurMoteur("DeepSeek est injoignable. Vérifiez la connexion internet.") from None
        except ValueError:
            raise ErreurMoteur("DeepSeek a répondu dans un format inattendu.") from None
        try:
            choix = resultat["choices"][0]
            contenu = choix["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ErreurMoteur("DeepSeek a répondu dans un format inattendu.") from None
        if choix.get("finish_reason") == "length":
            # Réponse coupée : le JSON sera invalide, le nouvel essai le signalera.
            return contenu + "\n[réponse tronquée : trop longue]"
        return contenu


def proposer(moteur, sondage: dict, essais_max: int = 2) -> dict:
    """Demande les règles au moteur. Renvoie {brut, moteur, essais, manuel, message}.

    Réponse invalide : nouvel essai avec le message d'erreur. Au-delà, ou si le moteur ne répond
    pas : mode manuel (brut vide) et un message qui dit pourquoi.
    """
    nom = NOMS.get(moteur.nom, moteur.nom)
    messages = [{"role": "system", "content": consigne_systeme()},
                {"role": "user", "content": "Voici le sondage. Propose les règles.\n\n"
                                            + donnees_sondage(sondage)}]
    erreur, reponse = "", ""
    for essai in range(1, essais_max + 1):
        try:
            reponse = moteur.appeler(messages)
        except ErreurMoteur as e:
            return {"brut": {}, "moteur": moteur.nom, "essais": essai, "manuel": True,
                    "message": f"{e} Saisissez les règles à la main."}
        try:
            brut = verifier(reponse, sondage)
        except ValueError as e:
            erreur = str(e)
            messages += [{"role": "assistant", "content": reponse},
                         {"role": "user", "content": "Ta réponse est refusée par le programme : "
                                                     f"{erreur}\nCorrige-la et renvoie tout le JSON."}]
            continue
        return {"brut": brut, "moteur": moteur.nom, "essais": essai, "manuel": False,
                "message": f"Règles proposées par {nom}. Relisez-les avant de calculer."}
    partiel = sauver_partiel(reponse, sondage)
    if partiel is not None and (partiel.get("familles") or partiel.get("commentaires_non_traduits")):
        return {"brut": partiel, "moteur": moteur.nom, "essais": essais_max, "manuel": False,
                "message": f"{nom} a proposé des règles en partie invalides. Les règles valables sont "
                           "dans le tableau ; les autres sont dans « À traiter pendant l'arbitrage ». "
                           "Relisez tout avant de calculer."}
    return {"brut": {}, "moteur": moteur.nom, "essais": essais_max, "manuel": True,
            "message": f"{nom} n'a pas proposé de règles valables ({erreur}). "
                       "Saisissez les règles à la main."}


def sauver_partiel(reponse: str, sondage: dict) -> dict | None:
    """Garde les familles valables d'une réponse refusée ; les autres deviennent des demandes
    à traiter à la main. None si la réponse n'est même pas du JSON."""
    try:
        objet = extraire_json(reponse)
    except ValueError:
        return None
    brut: dict = {}
    objet = ecarter_reglages(objet)
    textes = objet.get("commentaires_non_traduits")
    non_traduits = [str(t) for t in textes if isinstance(t, (str, int, float))] \
        if isinstance(textes, list) else []
    familles = objet.get("familles") if isinstance(objet.get("familles"), dict) else {}
    gardees = {}
    for nom, regles in familles.items():
        essai = {"familles": {nom: regles}}
        try:
            verifier(json.dumps(essai, ensure_ascii=False, default=str), sondage)
            gardees[nom] = regles
        except ValueError as e:
            source = regles.get("source") if isinstance(regles, dict) else None
            non_traduits.append(f"{nom} : {source or json.dumps(regles, ensure_ascii=False, default=str)} "
                                f"(règle non reconnue : {e})")
    if gardees:
        brut["familles"] = gardees
    if non_traduits:
        brut["commentaires_non_traduits"] = non_traduits
    return brut
