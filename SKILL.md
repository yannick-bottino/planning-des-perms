---
name: planning-perms
description: >-
  Construire le planning mensuel des permanences parents de la Crèche Balustrade
  à partir des réponses au sondage Framadate : lecture des dispos et des
  commentaires, calcul du planning, page d'arbitrage des cas difficiles, export
  Excel au format du Google Sheet de la crèche. Déclenché par
  /balustrade:planning-perms, ou par « traite les résultats du planning <lien> »,
  « fais le planning des perms », « sondage Framadate des perms ».
---

# Planning mensuel des permanences

Tu aides la famille planning. Elle n'est pas technique : parle simplement, montre des tableaux courts, ne cite pas de noms de fichiers JSON sans dire à quoi ils servent.

Principe : **les scripts calculent, toi tu interprètes les commentaires et tu dialogues.** Tu ne places jamais une famille toi-même dans le planning. Tu ne modifies jamais un fichier produit par un script.

Références à charger au besoin :
- `references/format-sondage.md` : structure du sondage et de `sondage.json`.
- `references/format-planning.md` : `contraintes.yaml`, `planning.json`, `arbitrages.json`, structure de l'Excel.
- `references/regles-affectation.md` : règles du solveur, codes d'alerte, traduction des commentaires en règles.

## Variables

```bash
SKILL="${CLAUDE_PLUGIN_ROOT}/skills/planning-perms"
TRAVAIL="$HOME/balustrade-planning/<AAAA-MM>"   # mois du planning, d'après les dates du sondage
```

Toutes les données du mois vivent dans `$TRAVAIL`. Ne copie jamais ces fichiers dans le repo du plugin : ils contiennent les prénoms des enfants et les commentaires des familles.

## Étape 0 : prérequis

```bash
python -c "import ortools, yaml, openpyxl" 2>/dev/null || python -m pip install --user -r "$SKILL/requirements.txt"
```

L'installation se fait sans droits admin. Si elle échoue, arrête-toi et montre l'erreur.

## Étape 1 : lire le sondage

```bash
mkdir -p "$TRAVAIL"
python "$SKILL/scripts/fetch_framadate.py" "<URL du sondage>" --out "$TRAVAIL/sondage.json"
```

Montre un résumé : titre, nombre de familles, nombre de créneaux, semaines couvertes, jours fermés (jours ouvrés absents du sondage). Signale :
- chaque avertissement du script, expliqué en une phrase ;
- les familles avec moins de 2 dispos « oui » dans une semaine (règle du sondage) ;
- les familles sans aucune dispo une semaine : le solveur rattrapera la perm une autre semaine du mois, sauf si la famille planning en décide autrement.

Si le sondage n'est pas encore clos, dis-le : des familles peuvent encore répondre.

## Étape 2 : traduire les commentaires en règles

Lis chaque commentaire de `sondage.json`. Propose un `contraintes.yaml` en suivant `references/regles-affectation.md`, section « Traduire un commentaire en règle ».

Présente-le d'abord sous forme de tableau dans le chat :

| Famille | Règle proposée | Commentaire d'origine |
|---|---|---|

Ajoute aussi :
- les quotas du mois différents du défaut (une perm par semaine ouverte), avec la raison ;
- les commentaires que tu ne sais pas traduire, qui iront dans `commentaires_non_traduits`.

**Attends la validation de la famille planning avant de lancer le calcul.** En cas de doute sur un commentaire, pose la question au lieu de deviner. Écris ensuite `$TRAVAIL/contraintes.yaml`, avec une clé `source` qui cite le commentaire pour chaque règle.

## Étape 3 : calculer le planning

```bash
python "$SKILL/scripts/solve.py" --sondage "$TRAVAIL/sondage.json" --contraintes "$TRAVAIL/contraintes.yaml" --out "$TRAVAIL/planning.json"
```

Si le script sort en erreur (faute de frappe dans le yaml, famille inconnue), corrige le yaml, montre la correction et relance.

Résume le résultat :
- nombre de créneaux à 2 parents, à 1 parent, vides, à 3 parents ou plus ;
- familles dont le total diffère du quota ;
- alertes regroupées par code, en langage simple.

## Étape 4 : arbitrer

S'il reste une alerte A1, A2, A3, A4, A7 ou D, ou si la famille planning veut ajuster le planning :

```bash
python "$SKILL/scripts/render_arbitrage.py" --planning "$TRAVAIL/planning.json" --sondage "$TRAVAIL/sondage.json" --contraintes "$TRAVAIL/contraintes.yaml" --out "$TRAVAIL/arbitrage.html"
```

Explique à la famille planning :
1. ouvrir `arbitrage.html` dans le navigateur (double-clic) ;
2. cliquer sur une case rouge ou orange, puis ajouter ou retirer une famille ;
3. cliquer sur « Exporter mes choix » et noter où le fichier `arbitrages.json` est téléchargé ;
4. revenir ici et donner le chemin du fichier.

Les choix sont liés à ce calcul précis. Si tu modifies `contraintes.yaml` et relances `solve.py` après l'arbitrage, préviens la famille : ses choix ne seront plus acceptés et elle devra refaire l'arbitrage sur la nouvelle page.

S'il n'y a aucune alerte à trancher, propose de passer directement à l'étape 5.

## Étape 5 : produire l'Excel

Sans arbitrage :

```bash
python "$SKILL/scripts/export_xlsx.py" --planning "$TRAVAIL/planning.json" --out "$TRAVAIL/planning-<AAAA-MM>.xlsx"
```

Avec arbitrage :

```bash
python "$SKILL/scripts/export_xlsx.py" --planning "$TRAVAIL/planning.json" --arbitrages "<chemin de arbitrages.json>" --sondage "$TRAVAIL/sondage.json" --contraintes "$TRAVAIL/contraintes.yaml" --planning-final "$TRAVAIL/planning-final.json" --out "$TRAVAIL/planning-<AAAA-MM>.xlsx"
```

Le script affiche les alertes restantes. Pour une alerte D (règle dure violée par un choix manuel), demande une confirmation explicite à la famille planning avant de considérer le planning comme final.

## Étape 6 : bilan

Donne :
- le chemin de l'Excel ;
- un tableau « famille, nombre de perms, quota » ;
- les créneaux à 1 parent ;
- les alertes restantes et ce que la famille planning a décidé pour chacune.

Pour publier : dans le Google Sheet de la crèche, Fichier > Importer > Importer > « Insérer de nouvelles feuilles », puis sélectionner l'Excel. Les colonnes du personnel restent à remplir par la crèche.

## Sans Claude Code : l'application locale

Une famille planning sans Claude Code peut faire le même parcours seule : double-clic sur `lancer.bat` (Windows) ou `sh lancer.sh` (macOS), dans le dossier du skill décompressé. L'application ouvre le navigateur, lit les commentaires avec Claude Code s'il est installé, avec une clé DeepSeek ou sans IA, et écrit les mêmes fichiers dans le même dossier du mois. Un mois commencé dans l'application peut être repris ici, et l'inverse. Zip à lui remettre : `python app/emballer.py --out <zip>`. Spec : `docs/specs/planning-perms-v2.md`.

## Interdits

- Placer ou retirer une famille sans passer par le solveur ou par l'arbitrage de la famille planning.
- Inventer une dispo ou interpréter un commentaire flou sans demander.
- Envoyer le planning aux familles : hors du rôle de ce skill.
- Copier des données réelles (sondage, planning, commentaires) dans le repo du plugin.

## Nomenclature

Dans ce skill, une famille est désignée par le prénom de l'enfant tel qu'il apparaît dans le sondage, en majuscules sans accent (`NOE`). C'est le format de l'Excel. La règle « prénom de l'enfant (parent1/parent2) » du plugin ne s'applique pas ici, car le sondage ne donne pas les prénoms des parents.
