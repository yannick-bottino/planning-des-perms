# Règles d'affectation

Source de vérité : `scripts/solve.py` (modèle CP-SAT dans `resoudre`, alertes dans `evaluer`). Claude propose les règles, la famille planning valide. Aucun calcul avant sa validation.

## Contraintes dures

Une affectation `famille x créneau` n'existe que si la dispo vaut `oui` ou `si_besoin` et si la semaine n'est pas une absence.

| Règle | Contenu |
|---|---|
| D1 | Au plus 1 perm par famille et par jour (matin et après-midi inclus) |
| D2 | Au plus `plafond_hebdo` perms par famille et par semaine (défaut 2) |
| D3 | Aucune affectation hors dispo (`non`, `vide`) |
| D4 | Aucune affectation une semaine d'absence déclarée |

## Contraintes souples (pénalités minimisées)

| Réf | Cas | Poids |
|---|---|---|
| S0 | Écart au `quota_mois` (manque ou excès) | 5000 par perm d'écart |
| S1 | Créneau sans parent | 1000 par créneau |
| S2 | Parents au-delà de `max_parents_par_creneau` | 100 par parent en trop, et 100 de plus pour le 2e parent en trop : deux créneaux à 3 valent mieux qu'un créneau à 4 |
| S3 | `au_moins` non atteint | 50 par perm manquante |
| S4 | Écart à `cible_hebdo`, par famille et par semaine (hors semaines d'absence) | 20 par perm d'écart |
| S5 | Dispo `si_besoin` utilisée | 10 par affectation |
| S6 | Préférence non satisfaite | `poids` déclaré (défaut 1), une fois par préférence |

Conséquences de l'ordre des poids :
- Le quota prime sur le remplissage : le solveur préfère un créneau vide à un quota non tenu (5000 contre 1000).
- Le solveur rend toujours un planning, même si les dispos ne suffisent pas (alerte A3 ou A1).
- Une préférence de poids 20 ou plus peut l'emporter sur l'étalement hebdomadaire (S4). Un poids de 10 ou plus peut l'emporter sur le coût d'un `si_besoin` (S5). Un poids de 1 à 5 départage seulement les cas à égalité.
- Il n'y a aucune récompense pour un créneau à 2 parents plutôt qu'à 1.

## Codes d'alerte

Les alertes sont recalculées sur le planning final (après arbitrage) par `evaluer`.

| Code | Gravité | Sens pour la famille planning | Action conseillée |
|---|---|---|---|
| A1 | rouge | Créneau sans aucun parent | Ajouter une famille disponible (la page liste les dispos, `oui` avant `si_besoin`). Sinon l'accepter et le dire au personnel |
| A2 | orange | Créneau avec plus de parents que le maximum prévu | Retirer une famille qui a d'autres options, ou accepter si le mois est saturé |
| A3 | orange | Une famille a un nombre de perms du mois différent de son quota | Vérifier si le quota est juste. Sinon ajouter ou retirer une perm, ou corriger `quota_mois` et relancer `solve.py` |
| A4 | jaune | Commentaire que Claude n'a pas su traduire en règle (`commentaires_non_traduits`) | Lire le commentaire, décider avec la famille planning, traiter à la main dans l'arbitrage |
| A5 | sans objet | Prévu par la spec (famille de la liste de référence absente du sondage). Le code ne l'émet pas | Ne pas annoncer cette alerte. Comparer à la main avec le planning du mois précédent si la famille planning le demande |
| A6 | gris | Famille placée sur un créneau où elle avait répondu « si besoin » | Prévenir la famille concernée et obtenir son accord, ou la remplacer |
| A7 | jaune | Règle `au_moins` ou préférence non respectée (une alerte par famille, toutes les règles manquées dans le message) | Arbitrer si la règle est importante, sinon accepter |
| D | rouge | Règle dure violée. Le solveur n'en produit jamais : elles viennent d'un ajout manuel. Le champ `regle` précise la sous-règle | Annuler le changement, sauf accord explicite de la famille concernée (voir ci-dessous) |

Sous-règles du code D :
- D1 : même famille deux fois sur le même créneau, ou deux perms le même jour. Annuler l'un des deux.
- D2 : plus de `plafond_hebdo` perms dans la semaine (alerte sans créneau). Annuler, ou relever `plafond_hebdo` dans le yaml si la famille planning l'accepte, puis relancer `solve.py`.
- D3 : famille hors dispo, famille inconnue du sondage, créneau inconnu. Demander à la famille concernée si elle peut en fait venir ; sinon annuler.
- D4 : affectation pendant une semaine d'absence déclarée. Vérifier le yaml ; si l'absence est levée, la retirer du yaml et relancer `solve.py`.

Note : la page d'arbitrage recalcule en direct D1 à D4, A1, A2, A3 et A6, et recopie A4. Elle ne recalcule pas A7. Le bilan final (A7 compris) vient de `export_xlsx.py`.

## Traduire un commentaire en règle

Claude propose la règle et note la `source` (auteur, date, texte). La famille planning valide. En cas de doute, ne rien inventer : copier le commentaire (auteur inclus) dans `commentaires_non_traduits`.

| Formulation typique | Règle yaml à proposer |
|---|---|
| « Absents la semaine du 9 novembre » (semaine entière) | `absences: ["<lundi>"]`. Le quota par défaut baisse d'une perm par absence |
| « En congés semaine du 9, on peut en prendre 2 ensuite » (rattrapage) | `absences: ["<lundi>"]` et `quota_mois` égal au nombre de semaines du sondage. Le plafond de 2 par semaine autorise le rattrapage |
| « Absents du mercredi 11 au vendredi 13 » (congés partiels) | Aucune règle de jour n'existe. Vérifier dans `sondage.json` que la famille a répondu `non` ces jours-là : alors rien à faire. Sinon `commentaires_non_traduits` |
| « Déjà fait une perm début octobre », « déjà compensé » | `quota_mois` réduit du nombre de perms déjà faites (ex. 4 au lieu de 5) |
| « Une seule perm ce mois-ci » | `quota_mois: 1` |
| « Pas de perm ce mois-ci » | `quota_mois: 0` |
| « Plutôt le mardi après-midi », « si possible le 6/11 » (préférence) | `preferences: [{jour: mardi, demi: A, poids: 2}]` ou `[{creneau: "2026-11-06_A", poids: 2}]`. Poids 1 à 5 pour un confort |
| « Le lundi matin est le seul jour possible pour un des parents » | `au_moins: {n: 1, parmi: [{jour: lundi, demi: M}]}` (pénalité 50, souple). Si la famille veut dire « uniquement ces jours », aucune règle exclusive n'existe : vérifier les dispos du sondage, sinon `commentaires_non_traduits` |
| « 1 ou 3 absences à confirmer », « on vous dit plus tard » (flou) | `commentaires_non_traduits`. Ne pas deviner |
| Toute demande sans clé correspondante (maximum par famille, pas deux semaines de suite, couplage avec une autre famille) | `commentaires_non_traduits` |

Points de contrôle avant de présenter le yaml :
- Les semaines d'absence sont des lundis présents dans `sondage.json`.
- Le total des quotas reste réaliste : environ 10 créneaux par semaine (8 avec un jour férié), 1 perm par famille et par semaine en cible.
- Une semaine sans aucune dispo pour une famille se rattrape dans le mois ; ne pas la déclarer en absence sans commentaire qui le dit.
