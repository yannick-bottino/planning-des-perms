# Formats : contraintes.yaml, planning.json, arbitrages.json, onglet SEMAINE

Source de vérité : `scripts/solve.py` (`lire_contraintes`, `evaluer`), `scripts/export_xlsx.py`, `templates/arbitrage.html`.

## contraintes.yaml

Proposé par Claude, validé par la famille planning avant tout calcul. Fichier vide accepté (tout par défaut). La racine doit être un dictionnaire.

### Clés racine

| Clé | Défaut | Validation |
|---|---|---|
| `cible_hebdo` | 1 | entier >= 0 (souple) |
| `plafond_hebdo` | 2 | entier >= 0 (dur) |
| `max_parents_par_creneau` | 2 | entier >= 1 (souple) |
| `familles` | aucune | dictionnaire nom -> règles |
| `commentaires_non_traduits` | liste vide | liste de textes (chacun devient une alerte A4) |

Les booléens et les non-entiers sont refusés. Toute autre clé racine : erreur `Clé inconnue dans contraintes.yaml`.

### Clés par famille

Le nom est normalisé (casse et accents ignorés). Une famille absente du yaml reçoit les défauts. Une valeur vide est acceptée.

| Clé | Défaut | Format et validation |
|---|---|---|
| `quota_mois` | nombre de semaines du sondage moins le nombre d'absences | entier >= 0 |
| `absences` | liste vide | lundis ISO des semaines sans perm (`"2026-11-09"`). Une semaine absente du sondage : erreur |
| `au_moins` | aucun | `{n: <entier >= 1, défaut 1>, parmi: [filtre, ...]}`. `parmi` obligatoire et non vide |
| `preferences` | liste vide | liste de `{creneau: "<id>", poids: n}` ou `{jour: ..., demi: ..., poids: n}`. `poids` entier >= 0, défaut 1 |
| `source` | chaîne vide | texte libre (commentaire d'origine). Ignoré par le solveur |

Un filtre est `{jour: lundi|mardi|mercredi|jeudi|vendredi, demi: M|A}`. `demi` est facultatif (absent : les deux demi-journées). Aucune autre clé n'est admise dans un filtre. Erreurs : jour inconnu, `demi` invalide, aucun créneau du sondage correspondant. Dans une préférence, un `creneau` inconnu est une erreur ; avec `creneau`, les autres clés (hors `poids`) sont ignorées.

Erreurs communes : famille du yaml absente du sondage, famille déclarée deux fois après normalisation, clé inconnue dans une famille, YAML invalide.

Attention : l'empreinte du planning couvre les contraintes normalisées, `source` et `commentaires_non_traduits` compris. Modifier le yaml après `solve.py` impose de relancer `solve.py` (sinon `render_arbitrage.py` et `export_xlsx.py` refusent le fichier).

### Exemple complet (prénoms fictifs)

```yaml
cible_hebdo: 1
plafond_hebdo: 2
max_parents_par_creneau: 2
familles:
  ALMA:
    quota_mois: 5
    absences: ["2026-11-09"]
    source: "Alma, 15/10 : congés semaine du 9/11, peut prendre 2 perms ensuite"
  BRUNO:
    quota_mois: 4
    source: "Bruno, 12/10 : une perm déjà faite début octobre"
  CLEO:
    au_moins:
      n: 1
      parmi:
        - {jour: lundi, demi: M}
        - {jour: mercredi}
    preferences:
      - {creneau: "2026-11-06_A", poids: 5}
      - {jour: mardi, demi: A, poids: 2}
    source: "Cléo, 11/10 : lundi matin ou mercredi, seuls jours possibles pour un des parents"
commentaires_non_traduits:
  - "BRUNO : 1 ou 3 absences à confirmer la semaine du 16"
```

## planning.json (sortie de solve.py)

```json
{
  "poll_id": "abc123",
  "titre": "Planning Novembre",
  "empreinte": "<sha256 de {sondage, contraintes normalisées}>",
  "solveur": {"statut": "OPTIMAL", "score": 40, "duree_s": 0.12, "ortools": "9.15.6755"},
  "creneaux": [
    {"id": "2026-11-02_M", "date": "2026-11-02", "demi": "M", "semaine": "2026-11-02",
     "semaine_iso": 45, "familles": ["ALMA", "BRUNO"]}
  ],
  "affectations": [
    {"famille": "ALMA", "creneau": "2026-11-02_M", "dispo": "oui", "origine": "solveur"}
  ],
  "bilan": {
    "ALMA": {"quota_mois": 4, "total": 4, "par_semaine": {"2026-11-02": 1, "2026-11-09": 0}}
  },
  "alertes": [
    {"code": "A1", "gravite": "rouge", "creneau": "2026-11-05_A", "famille": null,
     "message": "Créneau sans parent : jeudi 5/11 après-midi"}
  ]
}
```

- `solveur.statut` : `OPTIMAL` ou `FEASIBLE`. Autre statut : erreur, pas de fichier. `score` : somme des pénalités.
- `affectations[].origine` : `solveur` ou `arbitrage` (ajout par la famille planning). `dispo` : dispo du sondage ; un ajout hors dispo porte `non` ou `vide`.
- `bilan.<famille>.par_semaine` : clés = lundis ISO.
- `alertes[]` : `code`, `gravite`, `creneau` (id ou null), `famille` (nom ou null), `message`, et `regle` (D1 à D4) pour le code `D` uniquement. Triées par code, créneau, famille, message.
- Résolution déterministe : 1 worker, graine 0, limite 10 s par défaut (`--temps-max`).

## arbitrages.json (exporté par la page arbitrage.html)

```json
{
  "empreinte": "<celle de planning.json>",
  "exporte_le": "2026-10-30T14:05:12",
  "changements": [
    {"action": "retirer", "famille": "ALMA", "creneau": "2026-11-02_M"},
    {"action": "ajouter", "famille": "CLEO", "creneau": "2026-11-02_A"}
  ]
}
```

Changements nets par rapport au planning calculé (ajouts triés, puis retraits). `export_xlsx.py --arbitrages` les applique dans l'ordre et recalcule bilan et alertes. Erreurs : empreinte différente de `planning.json` (planning recalculé depuis l'arbitrage : refaire l'arbitrage), action autre que `ajouter` ou `retirer`, famille ou créneau inconnu, ajout d'une famille déjà affectée, retrait d'une famille non affectée. Exige `--sondage` et `--contraintes` ; `--planning-final` écrit le planning.json final.

## Onglet SEMAINE n de l'xlsx

Un onglet par semaine, nommé `SEMAINE <numéro ISO>`, dans l'ordre chronologique. Aucun autre onglet. Colonnes 1-based : A, D, F, K.

- `A1` : `SEMAINE n`. Ligne 2 vide. Premier bloc jour à la ligne 3.
- Seuls les jours présents dans le sondage ont un bloc. Un jour fermé n'a aucun bloc.
- Bloc jour commençant à la ligne `r`, avec `nm = max(4, nombre de matin)` et `na = max(4, nombre d'après-midi)` :

| Cellule | Contenu |
|---|---|
| `A r` | nom du jour en majuscules (`LUNDI`), gras |
| `D r` | `MATIN`, gras |
| `K r` à `AE r` | heures `8h30` à `18h30` par pas de 30 min (21 colonnes) |
| `AF r`, `AG r` | `Nb h`, `Nb h réelles` |
| `A r+1` | date, vraie valeur `datetime`, format `dd/mm` |
| `D r+1` ... | prénoms du matin, un par ligne |
| `A r+4`, `A r+5` | `Nb prév`, `enfants` (libellés seuls, non remplis) |
| `D r+1+nm` | `A-MIDI`, gras |
| `D r+2+nm` ... | prénoms de l'après-midi |

- Bloc suivant à la ligne `r + 2 + nm + na + 1` (soit `r + 11` pour un bloc standard : lundi ligne 3, mardi ligne 14).
- Pied de page, `p` = première ligne libre après le dernier bloc : `F p+2` = `Heures/enfants`, `F p+3` = `Heures/contrat`.
- Colonnes F à J (horaires du personnel) : vides. Largeurs : A 12, D 16, F 16, heures 6.
- Prénoms en majuscules ASCII sans accent (`NOE`).

## Compatibilité avec le skill perm-creche-balustrade

Ce skill teste `isinstance(val, pd.Timestamp)` sur la colonne A. Pandas renvoie un `datetime.datetime` quand la colonne mélange texte et dates : le skill ne trouve alors aucune perm. Défaut connu, antérieur à ce plugin, présent aussi avec l'export Google. Correctif côté `perm-creche-balustrade` (hors de ce repo) : `isinstance(val, (pd.Timestamp, datetime.datetime))`. Le test `test_compatibilite_skill_perm_creche` applique ce correctif seul. Sans lui, prévenir la famille planning que le skill ne trouvera aucune perm dans le fichier produit.
