# Spec V2 : application locale du planning des permanences

Statut : implémentée sur la branche `feat/planning-perms-v2`. Date : 2026-10-30. Relue avant le code par un sous-agent vérificateur : 15 constats, tous intégrés ci-dessous (V2-3, V2-4, V2-4b, V2-9, V2-10, V2-13, V2-15, V2-15b, V2-17, V2-18, V2-20, V2-20b, V2-21, V2-24, V2-25, critères 3 à 7). Le code fait foi une fois la V2 fusionnée.

Les familles citées ici portent des noms fictifs. Aucune donnée réelle de famille n'entre dans le repo.

## 1. Objectif

La V1 (`docs/specs/planning-perms-v1.md`) exige Claude Code et un dialogue dans le chat. La V2 permet à une famille planning non technique de produire seule l'Excel du mois :

1. elle double-clique sur `lancer.bat` (Windows) ou lance `lancer.sh` (macOS) ;
2. son navigateur s'ouvre sur une application locale ;
3. elle colle le lien Framadate et suit cinq étapes jusqu'au téléchargement de l'Excel.

Aucun droit administrateur. Aucun Python préinstallé. Claude Code est utilisé s'il est installé, sinon une clé DeepSeek, sinon une saisie manuelle.

Hors périmètre V2 : écriture directe dans le Google Sheet, registre des soldes entre mois, envoi du planning aux familles, liste de référence des familles (alerte A5). Ces points restent ceux de la V1 (questions Q2, Q3, Q5).

## 2. Architecture

Principe inchangé : l'IA traduit les commentaires, le code déterministe de la V1 calcule. La V2 ajoute une interface et des moteurs d'IA. Elle **importe** les scripts V1, elle ne les recopie pas.

```
skills/planning-perms/
  lancer.bat                 Windows : installe uv si besoin, lance l'application
  lancer.sh                  macOS / Linux : idem
  LISEZMOI-APPLICATION.txt   mode d'emploi pour la famille planning
  app/
    serveur.py               point d'entrée (métadonnées PEP 723 pour `uv run`), serveur HTTP
    parcours.py              logique des étapes, sans HTTP : sondage, règles, calcul, arbitrage, Excel
    moteurs.py               moteurs d'IA (Claude Code, DeepSeek), consigne, validation et nouvel essai
    reglages.py              dossiers de données et de configuration, clé DeepSeek
    emballer.py              construit le zip remis à la famille planning
    static/                  index.html, app.css, app.js (sans dépendance externe, sans étape de build)
  scripts/                   V1, importés par app/ (sys.path, comme les scripts V1 entre eux)
  templates/arbitrage.html   V1, servi tel quel dans l'étape 4
  tests/app/                 tests unitaires, serveur, Playwright de bout en bout, lancement réel
```

Dépendances : celles de la V1 (`ortools` épinglé, `pyyaml`, `openpyxl`), déclarées en tête de `serveur.py` au format PEP 723. Le serveur utilise la bibliothèque standard (`http.server`, `urllib`, `subprocess`). Aucun framework web.

## 3. Décisions tranchées

| N° | Sujet | Décision | Raison |
|---|---|---|---|
| V2-1 | Lancement | `lancer.bat` cherche `uv` (PATH, `%UV_INSTALL_DIR%`, puis `%USERPROFILE%\.local\bin\uv.exe`). S'il manque, il l'installe avec le script officiel d'Astral (`powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 \| iex"`), en mode utilisateur. Puis `uv run --script app\serveur.py`. | `uv` s'installe sans admin, télécharge un Python géré si aucun n'existe et installe `ortools` dans un environnement en cache. Aucun `pip install` visible. |
| V2-2 | Version de Python | `requires-python = ">=3.11,<3.15"` dans l'en-tête PEP 723. | Bornes couvertes par les roues `ortools` 9.15. |
| V2-3 | Serveur | `ThreadingHTTPServer` de la bibliothèque standard, lié à `127.0.0.1` uniquement. Port 8765, ou un port libre si 8765 est pris. `allow_reuse_address` est coupé sous Windows (sinon deux serveurs partagent le port sans erreur). Si l'application répond déjà sur 8765, un second lancement ouvre le navigateur sur elle et s'arrête. Le navigateur s'ouvre toujours sur `127.0.0.1`. | Un port stable garde la même origine d'un lancement à l'autre : la sauvegarde locale de la page d'arbitrage (`localStorage`) survit à un redémarrage. |
| V2-4 | Sécurité locale | Requêtes refusées (403) si l'en-tête `Host` n'est pas `127.0.0.1:<port>` ou `localhost:<port>` (DNS rebinding). Tout effet de bord passe par `POST`, refusé sans `Content-Type: application/json` ou sans `Origin` égal à l'application (les navigateurs envoient toujours `Origin` sur un `POST`). Les `GET` sont en lecture seule. En-têtes `X-Frame-Options: SAMEORIGIN` et CSP `frame-ancestors 'self'` partout ; CSP `default-src 'self'` sur l'application (aucun script en ligne). | Une page web tierce ne peut ni lire, ni piloter, ni encadrer l'application. |
| V2-4b | Texte venu du sondage | Commentaires et noms viennent de personnes extérieures. L'interface ne les insère que par `textContent`, jamais par `innerHTML`. La CSP bloque tout script en ligne. Test avec un commentaire `<img onerror>`. | Un script injecté par un commentaire pourrait sinon piloter l'application et consommer la clé DeepSeek. |
| V2-5 | Distribution | La famille reçoit un zip du dossier `skills/planning-perms/`, limité à une liste fermée (`app/`, `scripts/`, `references/`, `templates/`, `lancer.*`, `LISEZMOI-APPLICATION.txt`, `SKILL.md`, `requirements.txt`) : `python app/emballer.py --out <zip>`. Elle le décompresse où elle veut. | Le dossier contient déjà le code V1 importé. Le repo GitHub est privé : le zip est le seul canal. |
| V2-6 | Données du mois | `~/balustrade-planning/<AAAA-MM>/`, comme en V1. Le mois est celui qui compte le plus de créneaux dans le sondage (le premier en cas d'égalité). Fichiers : `sondage.json`, `contraintes.yaml`, `planning.json`, `arbitrage.html`, `arbitrages.json`, `planning-final.json`, `planning-<AAAA-MM>.xlsx`. Variable `PLANNING_PERMS_DONNEES` pour les tests. | Même dossier et mêmes formats que la V1 : le skill Claude Code peut reprendre un mois commencé dans l'application, et l'inverse. |
| V2-7 | Configuration | `config.json` dans `%APPDATA%\balustrade-planning\` (Windows) ou `~/.config/balustrade-planning/` (autres). Contient le moteur choisi et la clé DeepSeek. Variable `PLANNING_PERMS_CONFIG` pour les tests. | Hors du repo et hors du dossier des données, qu'on peut être amené à partager. |
| V2-8 | Clé DeepSeek | Saisie dans l'interface, écrite dans `config.json`. L'API ne renvoie jamais la clé, seulement `deepseek_cle: true/false`. Elle n'apparaît dans aucun journal ni message d'erreur. Le journal HTTP ne contient que la méthode, le chemin et le statut (la clé voyage dans le corps). La variable `DEEPSEEK_API_KEY` sert de repli. | Exigence de confidentialité. |
| V2-9 | Moteur Claude Code | Disponible si `shutil.which("claude")` le trouve (`claude.exe` ou `claude.cmd`). Appel : `claude -p --output-format json --model sonnet --tools "" --no-session-persistence --setting-sources "" --strict-mcp-config`, consigne envoyée en UTF-8 sur l'entrée standard, dossier courant = dossier du mois, délai maximal 180 s. Au délai dépassé, l'arbre de processus est tué (`taskkill /T /F` sous Windows, car `claude.cmd` lance `node`). Le champ `result` de la sortie JSON est lu ; `is_error` ou un code de retour non nul donnent une erreur lisible. Variable `PLANNING_PERMS_CLAUDE` pour pointer un faux exécutable en test. | Sans outils, sans MCP et sans réglages du poste : Claude ne fait que répondre. Ligne de commande vérifiée contre Claude Code 2.1.312. `--bare` est écarté car il exige une clé `ANTHROPIC_API_KEY` et ignore la connexion par abonnement. Sonnet suffit pour cette traduction et répond plus vite. |
| V2-10 | Moteur DeepSeek | `POST https://api.deepseek.com/chat/completions`, modèle `deepseek-chat` (variable `PLANNING_PERMS_DEEPSEEK_MODELE`), `temperature: 0`, `max_tokens: 8000`, `response_format: {"type": "json_object"}`, délai 120 s, via `urllib`. Une réponse coupée (`finish_reason: length`) compte comme invalide. Les erreurs HTTP sont traduites en phrases (401 clé refusée, 402 crédit épuisé, 429 saturé) ; le corps de l'erreur n'est jamais relayé. URL remplaçable par `PLANNING_PERMS_DEEPSEEK_URL` pour les tests. | API compatible OpenAI, pas de bibliothèque à installer. Le corps d'une erreur peut citer la clé. |
| V2-11 | Mode manuel | Toujours proposé. Il ouvre l'étape 3 avec un tableau vide et tous les commentaires listés. | La famille peut finir sans IA. |
| V2-12 | Format demandé à l'IA | Du JSON qui suit le schéma de `contraintes.yaml` (clés `familles`, `commentaires_non_traduits`). La consigne inclut, lus à l'exécution, la section « Traduire un commentaire en règle » de `references/regles-affectation.md` et la section « contraintes.yaml » de `references/format-planning.md`. Elle liste aussi les familles, les lundis ISO, les identifiants de créneaux, les familles sans dispo par semaine et les commentaires. | Une seule source de vérité métier : la référence V1. JSON plutôt que YAML : plus fiable à produire et à analyser. Les dates sans année (« le 15/02 ») se résolvent avec les lundis fournis. |
| V2-13 | Validation et nouvel essai | Réponse analysée en JSON, puis passée à `solve.lire_contraintes` et à la conversion en lignes du tableau. En cas d'échec : un second essai avec le message d'erreur. Après le second échec, sauvetage famille par famille : les familles valables sont gardées, les autres deviennent des demandes « à traiter » avec la raison, et un bandeau le dit. Si la réponse n'est même pas du JSON, ou si le moteur est injoignable : mode manuel, avec un message qui dit pourquoi. Sans aucun commentaire dans le sondage, l'IA n'est pas appelée. | Exigence 2. Une seule famille fautive ne doit pas faire perdre les règles justes. |
| V2-14 | Tableau des règles | Une ligne par règle : famille, type de règle, détail, commentaire d'origine, bouton supprimer. Types : « Absente la semaine du », « Nombre de perms du mois », « Au moins N perms parmi », « Préférence ». Les commentaires non traduits forment une liste à part (« À traiter pendant l'arbitrage »), modifiable. Trois réglages généraux (cible par semaine, maximum par semaine, maximum de parents par créneau) sont repliés sous « Réglages avancés ». Aucun YAML visible. Sur petit écran, chaque ligne devient une carte. | Exigence 3. |
| V2-15 | Commentaire d'origine | Colonne affichant les commentaires du sondage dont l'auteur est la famille de la ligne. À défaut (auteur qui n'est pas une famille, règle sans commentaire), la `source` proposée par l'IA. Sous le tableau, la liste complète des commentaires du sondage reste consultable (« Tous les commentaires du sondage »). | Rien ne relie de façon sûre une règle à un commentaire précis : afficher tous les commentaires évite une liste « sans règle » fausse. |
| V2-15b | Famille sans aucune dispo | Une famille sans aucun « oui » ni « si besoin » sur tout le sondage reçoit une ligne proposée « Nombre de perms du mois : 0 », source « Aucune disponibilité cochée dans le sondage (à vérifier avec la famille) ». La ligne reste supprimable. | Sans elle, le quota par défaut produit une alerte A3 certaine. La famille planning garde la décision. |
| V2-16 | Aller-retour règles et contraintes | `parcours.regles_depuis_contraintes` (dict brut validé vers lignes) et `parcours.contraintes_depuis_regles` (lignes vers dict brut), puis `lire_contraintes`. Une famille ne peut avoir qu'une ligne « Nombre de perms » et une ligne « Au moins » (limite V1). Les `source` des lignes d'une famille sont dédoublonnées puis jointes par « \| ». Les noms de famille sont normalisés et les trois réglages toujours écrits : l'égalité vaut donc sur la forme normalisée (critère 6). | Le dict brut est écrit tel quel dans `contraintes.yaml`, lisible par la V1. |
| V2-17 | Poids des préférences | Deux niveaux proposés : « léger » (poids 2) et « important » (poids 20). Un autre poids venu de l'IA reste sélectionné et s'affiche dans son palier : « léger (N) » de 0 à 5, « moyen (N) » de 6 à 9, « important (N) » à partir de 10. | Un poids de 20 peut l'emporter sur l'étalement hebdomadaire (référence V1) ; un poids de 1 à 5 départage seulement. |
| V2-18 | Arbitrage | Le serveur génère la page avec `render_arbitrage.generer_page` (gabarit V1 non modifié), y insère un petit script passerelle après la balise `<head …>` (erreur si elle manque), et la sert dans un cadre (`iframe`) de l'application. La passerelle garde les `Blob` créés par `URL.createObjectURL` et intercepte le téléchargement d'un fichier `.json` : par `HTMLAnchorElement.click` et par un écouteur `click` en phase de capture. Elle envoie le JSON au serveur et prévient l'application (`postMessage`, même origine), qui passe à l'étape 5. Le bouton « Valider l'arbitrage » de l'application clique le bouton d'export de la page (`#btn-export`, sinon le bouton dont le texte contient « Export ») ; le bouton de la page fonctionne aussi. Repli : sans réponse de la passerelle au bout de 5 s, l'application propose de choisir le fichier `arbitrages.json` téléchargé. Le bouton « Garder le planning calculé » saute l'arbitrage. | Le gabarit est retravaillé en parallèle sur une autre branche : la passerelle ne dépend que du contrat V1 (l'export télécharge `arbitrages.json`), et le repli couvre une rupture de ce contrat. Le contrat est testé dans `tests/app`. |
| V2-19 | Confirmation des alertes D | Si l'arbitrage laisse une alerte D (règle dure violée), l'Excel est produit mais son téléchargement exige de cocher « Je confirme ces choix ». | Reprend la confirmation explicite exigée par le SKILL V1. |
| V2-20 | Reprise | Pas de reprise d'un mois après redémarrage en V2 : l'application repart de l'étape 1. Les fichiers du mois restent sur le disque. Un nouveau calcul supprime `arbitrages.json` et `planning-final.json` périmés ; « Garder le planning calculé » écrit `planning-final.json` (copie du calcul) et supprime un `arbitrages.json` ancien. | Simplicité. Les fichiers restent cohérents pour une reprise par le skill V1. |
| V2-20b | Concurrence | Un verrou sérialise toutes les requêtes `POST`. L'interface désactive ses boutons pendant un travail. Un arbitrage d'un autre calcul est refusé dès `POST /api/arbitrages` (empreinte V1). | Double clic ou second onglet. |
| V2-21 | Adresse du sondage | Le lien collé doit contenir `/polls/<id>`. L'hôte du lien est conservé (`https://<hôte>/polls/<id>.csv`), en HTTPS ; HTTP n'est accepté que pour `127.0.0.1` et `localhost` (tests). Un sondage sans créneau ou sans aucune famille est refusé avec un message. | Supporte une autre instance Framadate. Les tests servent des fixtures en local sans modifier la V1. |
| V2-22 | Bouton « Ouvrir le dossier » | À l'étape 5, ouvre le dossier du mois dans l'explorateur (`os.startfile` sous Windows, `open` sous macOS, `xdg-open` ailleurs). Requête `POST`. | La famille retrouve l'Excel sans chercher un chemin. |
| V2-23 | Arrêt | La fenêtre noire de `lancer.bat` reste ouverte et affiche l'adresse. La fermer arrête l'application. Le pied de page le rappelle. | Pas de processus caché à tuer. |
| V2-24 | Robustesse de `lancer.bat` | `cd /d "%~dp0"`, chemins entre guillemets, `chcp 65001`, `PYTHONUTF8=1`. Si `app\serveur.py` manque (zip ouvert sans extraction), message « Extraire tout ». Message d'attente avant le premier lancement. Messages de la console sans accents (analyse UTF-8 des `.bat` peu fiable). `.gitattributes` force CRLF pour `.bat` et LF pour `.sh` ; `app/emballer.py` fait de même dans le zip et rend `lancer.sh` exécutable. Le LISEZMOI explique « Débloquer » (SmartScreen) et l'installation manuelle de `uv`. | Pièges relevés à la relecture : zip non extrait, espaces dans le chemin, encodage console, PATH non rafraîchi après installation, marque d'origine Internet. |
| V2-25 | Outils de test | Tests de bout en bout avec l'API synchrone de `playwright` (sans le greffon `pytest-playwright`), dans `tests/app/`. Ignorés si Chromium n'est pas installé. Test réel Claude Code marqué `reel` ; test réel DeepSeek ignoré sans `DEEPSEEK_API_KEY`. | Pas de collision avec l'outillage de la branche d'interface (`tests/e2e/`, `pytest.ini`). |

## 4. Parcours

| Étape | Écran | Action serveur |
|---|---|---|
| 1. Sondage | Champ « Lien du sondage Framadate ». Choix de qui lit les commentaires : Claude Code (grisé s'il est absent), DeepSeek (champ clé si aucune clé enregistrée), personne. | `POST /api/config`, puis `POST /api/sondage` : télécharge CSV et page, `fetch_framadate.construire`, écrit `sondage.json`. |
| 2. Résumé | Titre, familles, créneaux, semaines, jours fermés, avertissements du script, familles avec moins de 2 « oui » dans une semaine, familles sans dispo une semaine, commentaires. Bouton « Lire les commentaires avec … » ou « Saisir les règles ». | Calcul du résumé dans `parcours.resumer`. |
| 3. Règles | Bandeau qui dit quel moteur a proposé les règles, ou pourquoi on est en mode manuel. Tableau éditable (V2-14), liste « à traiter », tous les commentaires, réglages avancés, bouton « Calculer le planning ». | `POST /api/regles/proposer` puis `POST /api/calculer` : lignes vers dict, `lire_contraintes`, écrit `contraintes.yaml`, `solve.construire_planning`, écrit `planning.json` et `arbitrage.html`. Erreurs affichées au-dessus du tableau, avec la ligne fautive surlignée quand elle est connue. |
| 4. Arbitrage | Résumé du calcul (demi-journées à 2, à 1, sans parent, à 3 et plus ; familles hors quota ; alertes groupées), puis la page d'arbitrage V1 dans un cadre. Boutons « Valider l'arbitrage », « Garder le planning calculé », « Revenir aux règles ». | `GET /arbitrage`, puis `POST /api/arbitrages`. |
| 5. Excel | Bouton de téléchargement, bouton « Ouvrir le dossier », mode d'import dans le Google Sheet, tableau « famille, perms, quota », demi-journées à 1 parent, alertes restantes. | `export_xlsx.appliquer_arbitrages`, `export_xlsx.ecrire_xlsx`, écrit `planning-final.json` et l'Excel. `GET /api/excel`. |

Chaque étape validée reste consultable. Revenir à l'étape 3 et recalculer invalide l'arbitrage en cours (empreinte V1).

## 5. Interface

- Français simple, phrases courtes, aucun terme technique (pas de « JSON », « YAML », « solveur » ; « calcul » à la place).
- Une seule colonne de contenu, indicateur d'étapes en haut (`<ol>` avec `aria-current="step"`). L'étape 4 s'élargit pour la page d'arbitrage.
- Accessible : contrastes AA, focus visible, libellés liés aux champs, messages d'état dans une zone `aria-live`, navigation au clavier complète, cibles d'au moins 44 px, pas d'information portée par la couleur seule.
- Palette cohérente avec `templates/arbitrage.html` (mêmes variables de couleur, thème sombre automatique).
- Aucune ressource externe : polices système, aucune bibliothèque, aucun CDN. L'application fonctionne hors ligne sauf pour le sondage et l'IA.
- Texte venu du sondage inséré par `textContent` uniquement (V2-4b).
- Passe de design : skills `impeccable:impeccable` puis `taste-skill:design-taste-frontend`.

## 6. Critères d'acceptation

1. Sur ce poste Windows, `lancer.bat` démarre le serveur via `uv` et `GET /api/etat` répond. Test automatisé `tests/app/test_app_lancement.py`, plus un essai manuel noté dans la PR.
2. Avec `uv` absent du PATH et une destination d'installation temporaire, `lancer.bat` installe `uv` puis démarre. Essai manuel noté dans la PR.
3. Le serveur n'écoute que sur `127.0.0.1` ; une requête avec un `Host` étranger reçoit 403 ; un `POST` sans JSON, sans `Origin` ou d'une autre origine reçoit 403 ; les réponses portent `X-Frame-Options` et une CSP. Un port pris donne un autre port.
4. La clé DeepSeek enregistrée n'apparaît dans aucune réponse HTTP, ni dans le journal du serveur, ni dans le dossier des données, même quand DeepSeek renvoie une erreur dont le corps cite la clé (test qui capture stderr).
5. Une réponse d'IA invalide déclenche un second essai qui contient le message d'erreur ; deux échecs gardent les familles valables et versent les autres dans « à traiter » ; une réponse illisible ou un moteur injoignable donnent le mode manuel avec un message (tests sur faux moteurs).
6. Pour les contraintes des fixtures V1 et une fixture qui couvre les quatre types de règle (préférence par jour et par créneau, `parmi` à plusieurs filtres, poids omis) : `lire_contraintes(contraintes_depuis_regles(regles_depuis_contraintes(c))) == lire_contraintes(c)`, `source` comprise.
7. Parcours Playwright de bout en bout, sondage servi en local, faux DeepSeek : lien collé, résumé, règles proposées affichées, une règle modifiée, calcul, un ajout dans l'arbitrage, validation, Excel téléchargé et relu (onglets `SEMAINE`, perm ajoutée présente). Un commentaire contenant `<img src=x onerror=...>` ne s'exécute pas.
8. Même parcours en mode manuel, sans arbitrage.
9. Moteur Claude Code testé avec un faux exécutable, et un test réel avec `claude` s'il est présent (marqueur `reel`). Test réel DeepSeek ignoré sans `DEEPSEEK_API_KEY`.
10. Les tests V1 passent toujours. Le gabarit `templates/arbitrage.html` ne change que pour la Q11 (deux textes), avec l'accord de la session qui le possédait, et avec ses tests (`tests/test_render_arbitrage.py`, `tests/e2e/`).
11. Après synchronisation avec `main` (nouveau gabarit d'arbitrage), le test de bout en bout passe toujours.

## 7. Questions ouvertes

- **Q8. Antivirus et proxy d'entreprise.** Le script d'installation de `uv` peut être bloqué. Repli documenté dans `LISEZMOI-APPLICATION.txt` : installer `uv` à la main depuis le site d'Astral.
- **Q9. macOS.** `lancer.sh` est écrit mais pas testé sur un Mac (aucun Mac disponible). Un `.sh` ne s'ouvre pas d'un double-clic dans le Finder : le LISEZMOI passe par le Terminal.
- **Q10. Coût DeepSeek.** Un mois de commentaires représente quelques milliers de jetons. Non mesuré sur un vrai mois.
- **Q11. Textes de la page d'arbitrage (réglée).** Le titre des commentaires non traduits devient « Commentaires à traiter à la main » (il nommait Claude, même quand DeepSeek ou personne avait lu les commentaires). La phrase affichée après « Exporter mes choix » vient des données injectées (`apres_export` de `render_arbitrage.generer_page`) : le skill garde « Revenez dans le chat pour la suite », l'application passe « L'application prépare maintenant le fichier Excel ».

## 8. Relecture du code (2026-10-30)

Un sous-agent vérificateur a relu le code avant la PR : 12 constats, aucun bloquant, tous traités.

| Constat | Correction |
|---|---|
| Un calcul en échec laissait l'ancien planning et l'ancien Excel accessibles, avec un `contraintes.yaml` neuf | Le calcul invalide l'état avant de commencer ; les fichiers ne sont écrits qu'après un calcul réussi ; l'interface referme les étapes 4 et 5 |
| Un Excel ouvert dans Excel (verrou Windows) donnait « erreur inattendue » | Écriture dans un fichier temporaire puis `os.replace`, avant `planning-final.json` ; message « Fermez-le, puis cliquez de nouveau » |
| L'IA pouvait changer un réglage général (par exemple 3 parents par créneau) sans que la famille le voie | Les trois réglages généraux ne sont jamais pris de la réponse de l'IA ; une valeur proposée devient une demande « à traiter » |
| Gabarit modifié sur cette branche | Accord explicite de la session propriétaire ; Q11 réglée, critère 10 mis à jour |
| Une semaine d'absence citée deux fois faisait rejeter la famille | Absences dédoublonnées, comme en V1 |
| Le zip emportait tout fichier présent sur le disque | `emballer.py` suit une liste fermée de dossiers et d'extensions |
| Le test XSS ne regardait pas le cadre d'arbitrage | Piège ajouté dans une demande « à traiter », vérifié dans tous les cadres |
| Toute `ValueError` interne devenait « Requête illisible » | Ce message est réservé à l'analyse du corps ; le reste donne une erreur 500 |
| Connexion DeepSeek coupée en cours de lecture | `http.client.HTTPException` attrapée : mode manuel |
| Repli par fichier déclenché à tort si l'enregistrement dure plus de 5 s | La passerelle envoie un accusé de réception dès l'interception, qui arrête le minuteur |
| Durée d'attente de l'IA sous-estimée | « souvent moins d'une minute, parfois jusqu'à six » |
| Boutons de la clé DeepSeek sans gestion d'erreur ; clé de l'environnement impossible à effacer | Erreurs annoncées ; une clé venue de `DEEPSEEK_API_KEY` est signalée comme telle |
