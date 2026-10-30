# Format du sondage Framadate et de sondage.json

Source de vérité : `scripts/fetch_framadate.py` et `scripts/planning_core.py`.

## URL

- Page publique : `https://framadate.org/polls/<id>`
- Export CSV : `https://framadate.org/polls/<id>.csv`
- Le script accepte l'URL complète, l'URL du CSV ou l'id seul (lettres et chiffres). L'id est la partie après `/polls/`.
- Les deux fichiers sont téléchargés puis décodés en UTF-8 (erreur si le décodage échoue). En-têtes envoyés : `Accept-Language: en-GB`, `User-Agent: planning-perms/1`.
- Mode hors ligne : `--csv` et `--html` ensemble (jamais l'un sans l'autre).

Commande : `python fetch_framadate.py <URL ou id> --out sondage.json`. Code de sortie 1 et message `Erreur : ...` sur stderr en cas d'échec. Les avertissements vont sur stderr (`Avertissement : ...`) et dans le JSON.

## Structure du CSV

| Ligne | Contenu |
|---|---|
| 1 | Cellule A vide, puis une date ISO par colonne (`2026-11-02`), répétée pour matin et après-midi |
| 2 | Cellule A vide, puis `Matin` ou `Apres-midi` (casse libre, `Après-midi` accepté) |
| 3 et suivantes | Une ligne par famille : nom saisi dans le sondage, puis une valeur par créneau |

- Un BOM en tête de fichier est retiré.
- Moins de 2 lignes, ou aucune colonne de créneau : erreur.
- Ligne de famille vide : ignorée sans avertissement. Ligne avec des valeurs mais sans nom : ignorée avec avertissement.
- Ligne plus courte que l'en-tête : les cellules manquantes valent `vide`.
- Les jours fériés et fermetures n'apparaissent pas : le calendrier vient du sondage.

Valeurs de cellule (clés lues sans casse, espaces de bord ignorés) :

| Cellule | Valeur dans sondage.json | Statut |
|---|---|---|
| `Yes` | `oui` | vérifié sur le sondage de novembre |
| `No` | `non` | vérifié |
| vide | `vide` (traité comme `non` par le solveur) | vérifié |
| `if needed`, `if need be`, `ifneedbe`, `si nécessaire`, `si besoin` | `si_besoin` | NON VÉRIFIÉ : libellés supposés, jamais vus dans un vrai export |

Toute autre valeur fait échouer le script : `Valeur de dispo inconnue '...' (famille X, créneau Y)`. Toute demi-journée inconnue aussi : `Libellé de demi-journée inconnu`. Si le message cite une valeur proche de « si besoin », ajouter son libellé à `DISPOS` dans `planning_core.py` après accord de la famille planning, puis le noter ici comme vérifié.

Seules les valeurs `oui` et `si_besoin` rendent une famille affectable.

## Commentaires dans le HTML

Ils ne sont pas dans le CSV. Balises lues par le parseur :

- Titre du sondage : balise `<title>`, suffixe final `– Framadate` retiré (tiret court, long ou trait d'union).
- Un commentaire = un `<article id="comment-...">` (l'id doit commencer par `comment-`).
- Dans l'article, `<header>` contient :
  - le premier `<span>` : nom de l'auteur ;
  - `<time datetime="...">` : date. Si l'attribut manque ou est illisible, repli sur le texte `11 Oct 2026, 10:43` (format `%d %b %Y, %H:%M`, mois en anglais).
- Le texte : les `<p>` situés dans un `<div>` hors `<header>`. Un `<br>` devient un saut de ligne, les paragraphes sont joints par un saut de ligne.
- Date écrite à la minute sans fuseau : `2026-10-15T16:20`.
- L'auteur est normalisé comme les noms de famille (majuscules ASCII sans accent, `Noé` devient `NOE`).

Un changement de gabarit Framadate donne 0 commentaire sans erreur : d'où l'avertissement « Aucun commentaire lu ».

## Format de sondage.json

```json
{
  "poll_id": "abc123",
  "titre": "Planning Novembre",
  "creneaux": [
    {"id": "2026-11-02_M", "date": "2026-11-02", "demi": "M",
     "semaine": "2026-11-02", "semaine_iso": 45}
  ],
  "familles": [
    {"nom": "NOE", "nom_brut": "Noé",
     "dispos": {"2026-11-02_M": "oui", "2026-11-02_A": "non"}}
  ],
  "commentaires": [
    {"auteur": "NOE", "auteur_brut": "Noé", "date": "2026-10-15T16:20",
     "texte": "Nous serons en congés la semaine du 9 novembre."}
  ],
  "avertissements": []
}
```

- `creneaux[].id` : `<date ISO>_<M|A>`. `demi` vaut `M` (matin) ou `A` (après-midi).
- `semaine` : date ISO du lundi de la semaine. C'est la clé de semaine partout (yaml, planning, bilan). `semaine_iso` : numéro ISO, utilisé seulement pour le nom d'onglet `SEMAINE n`.
- `familles[].dispos` : une entrée par créneau, valeurs `oui`, `si_besoin`, `non`, `vide`.
- `familles[].nom` : clé utilisée partout (yaml, affectations). `nom_brut` : saisie d'origine.
- `commentaires[].date` : repli sur le texte brut si illisible (avec avertissement).

## Avertissements

| Message | Sens | Action |
|---|---|---|
| `Ligne sans nom de famille ignorée` | Une ligne du CSV a des valeurs mais pas de nom | Vérifier le sondage ; la ligne est perdue |
| `Plusieurs lignes de famille se normalisent en X (A / B) : dispos fusionnées, à vérifier` | Deux saisies donnent le même nom (casse, accents, doublon de vote). Le script fusionne les lignes créneau par créneau et garde la meilleure réponse (oui, puis si besoin, puis non) | Montrer la fusion à la famille planning et lui faire confirmer qu'il s'agit bien de la même famille |
| `Date de commentaire illisible, gardée brute : '...'` | Ni `datetime` ni le format texte attendu | Non bloquant ; l'ordre chronologique peut être faux |
| `Aucun commentaire lu : vérifier les commentaires sur la page du sondage` | Aucun `<article id="comment-...">` trouvé | Ouvrir la page : soit il n'y a pas de commentaire, soit le gabarit Framadate a changé |
| `Auteur de commentaire absent des familles : X` | Le nom de l'auteur ne correspond à aucune famille du CSV (autre graphie, ou « Inconnu ») | Rapprocher à la main de la bonne famille avant de traduire le commentaire en règle |

Aucun contrôle de présence d'une famille attendue : le code n'a pas de liste de référence.
