# Spec V3 : installeur Windows et premier lancement guidé

Statut : en cours sur la branche `claude/planning-perms-installeur-d91c33`. Date : 2026-10-30. Prolonge la V2 (`planning-perms-v2.md`), qui reste valable sauf mention contraire ici.

Les familles citées ici portent des noms fictifs. Aucune donnée réelle de famille n'entre dans le repo.

## 1. Objectif

L'outil passe aux mains de parents bénévoles non techniques, sous Windows. Parcours visé :

1. sur la page GitHub publique, un bouton « Télécharger » ;
2. un fichier `.exe` non signé : deux clics pour passer SmartScreen (« Informations complémentaires », puis « Exécuter quand même ») ;
3. une icône « Planning des perms » sur le bureau et dans le menu Démarrer ;
4. un clic sur l'icône ouvre l'outil dans sa propre fenêtre, sans fenêtre noire ;
5. au premier lancement, la page aide à installer Claude ou ChatGPT et à se connecter au compte, ou à saisir une clé DeepSeek.

Hors périmètre V3 : macOS, signature du `.exe`, mise à jour automatique.

## 2. Décisions

| N° | Sujet | Décision | Raison |
|---|---|---|---|
| V3-1 | Contenu de l'installeur | L'installeur embarque un Python autonome (python-build-standalone, via `uv python install`) avec `ortools`, `pyyaml` et `openpyxl` déjà installés, plus le dossier de l'outil (liste fermée de `app/emballer.py`). Rien n'est téléchargé au premier lancement. | Aucun téléchargement de `uv`, de Python ou d'`ortools` sur le poste : pas d'attente muette d'une à deux minutes, pas de blocage par un proxy au premier clic. |
| V3-2 | Démarrage | Le raccourci lance `python\pythonw.exe planning-perms\app\serveur.py`. `pythonw` n'a pas de console. Sans console (`sys.stdout` vaut `None`), le serveur écrit son journal dans `%LOCALAPPDATA%\balustrade-planning\journal.txt` (méthode, chemin, statut, erreurs ; jamais un corps de requête ; remis à zéro au-delà de 1 Mo). | Pas de fenêtre noire. Un journal reste disponible en cas de souci. |
| V3-3 | Navigateur | L'outil s'ouvre dans sa propre fenêtre (mode application : `--app=<adresse>`, sans onglets ni barre d'adresse, une entrée à part dans la barre des tâches). Chrome s'il est installé (`%ProgramFiles%`, `%ProgramFiles(x86)%`, `%LOCALAPPDATA%`), sinon Edge (`%ProgramFiles(x86)%`, `%ProgramFiles%`, `%LOCALAPPDATA%`), sinon un onglet du navigateur par défaut. La fenêtre s'ouvre sur la page d'attente `file://`, qui passe à `http://127.0.0.1:<port>/` dans la même fenêtre. Un second lancement ouvre une autre fenêtre sur l'outil. Les liens externes (pages de connexion Claude et ChatGPT, `target=_blank`) s'ouvrent dans une fenêtre normale du même navigateur. (Amendé en v0.3.1 : fenêtre d'application et repli sur Edge.) | Choix de l'utilisateur : une vraie fenêtre d'outil plutôt qu'un onglet. Chrome reste premier : c'est le navigateur de l'utilisateur, où ses comptes Claude et ChatGPT sont ouverts, et celui des tests de bout en bout. Edge est présent sur tout Windows 10 et 11 et connaît le même mode. Vérifié le 2026-10-30 dans Chrome et Edge réels : redirection dans la même fenêtre, lien externe dans une autre fenêtre, téléchargement de l'Excel, page d'arbitrage, `localStorage`. |
| V3-4 | Arrêt | Bouton « Fermer l'outil » dans le bandeau : `POST /api/arreter`, puis la page dit que l'outil est fermé et comment le relancer. Arrêt seul : sans aucune requête pendant 10 minutes (`PLANNING_PERMS_INACTIVITE_S`), hors travail en cours (IA, installation, connexion). La page envoie `POST /api/presence` chaque minute, et cesse après 2 heures sans clic ni frappe. Si l'outil ne répond plus, la page l'annonce.  Fenêtre fermée : sur `pagehide`, la page envoie `POST /api/fermeture` (`fetch` avec `keepalive`, mêmes en-têtes JSON et `Origin` que les autres requêtes ; `sendBeacon` ne permet pas l'en-tête JSON). Le délai d'arrêt seul passe alors à 90 secondes (`PLANNING_PERMS_FERMETURE_S`), au-delà de la présence d'une autre fenêtre restée ouverte. Toute requête suivante l'annule (rechargement, autre fenêtre). Jamais pendant un travail en cours : le délai court part de sa fin. (Amendé en v0.3.1.) | Pas de processus oublié. Une fenêtre fermée arrête l'outil après 90 secondes. Un rechargement envoie aussi le signal : d'où un délai plutôt qu'un arrêt immédiat. Si le navigateur se ferme avec la fenêtre et perd le signal (1 essai sur 6 le 2026-10-30), l'arrêt après 10 minutes reste le filet. |
| V3-5 | Fenêtre de `lancer.bat` | Le zip V2 reste possible. Sa fenêtre dit en une phrase : « Cette fenêtre fait tourner l'outil : allez dans Chrome, et ne fermez pas cette fenêtre. » | Seul cas où une fenêtre apparaît encore. |
| V3-6 | Moteurs | Quatre choix : Claude (abonnement Claude, CLI Claude Code), ChatGPT (abonnement ChatGPT, CLI Codex), DeepSeek (clé API), à la main. Codex est au même niveau que Claude Code. | Décision de l'utilisateur. |
| V3-7 | Détection | Claude : `PLANNING_PERMS_CLAUDE`, PATH, puis `%USERPROFILE%\.local\bin\claude.exe`. Codex : `PLANNING_PERMS_CODEX`, PATH, puis le dossier de l'installeur officiel. Chemins connus vérifiés en plus du PATH, car le PATH du processus n'est pas rafraîchi après une installation. Connexion : `claude auth status --json` (`loggedIn`, `subscriptionType`), `codex login status` (code de sortie 0 si connecté). | Documentation officielle (voir section 4). |
| V3-8 | Installation d'un CLI | Script officiel, lancé caché (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command …`, `CREATE_NO_WINDOW`), sans droits admin : `irm https://claude.ai/install.ps1 \| iex` ; `irm https://chatgpt.com/codex/install.ps1 \| iex` avec `CODEX_NON_INTERACTIVE=1`. Tâche de fond suivie par la page. Commandes remplaçables par variables d'environnement pour les tests. | Méthodes documentées, sans Node.js ni Git. |
| V3-9 | Connexion Claude | `claude auth login --claudeai`, caché. Le CLI ouvre lui-même le navigateur et attend le retour de la page de connexion. La page de l'outil affiche aussi le lien (au cas où l'onglet ne s'ouvre pas) et un champ « Si la page affiche un code, collez-le ici », transmis sur l'entrée standard. Fin : `claude auth status`. | Preuve de faisabilité réelle du 2026-10-30 : connexion d'un compte Team réussie en processus caché, sans code à coller, puis `claude -p` répond. |
| V3-10 | Connexion ChatGPT | `codex login`, caché (le CLI ouvre le navigateur, retour sur `localhost:1455`). Repli : `codex login --device-auth`, qui affiche un lien et un code à usage unique ; il faut d'abord autoriser cette méthode dans les réglages de sécurité ChatGPT, et la page le dit. Fin : `codex login status`. | Les deux sorties ont été lues en processus caché le 2026-10-30. Connexion réelle non testée (pas de compte ChatGPT disponible). |
| V3-11 | Abonnement payant | La page le dit avant toute installation : Claude exige Pro, Max, Team ou Enterprise ; ChatGPT, un abonnement Plus ou supérieur. Après connexion, `subscriptionType` égal à `free` donne un message clair et le moteur n'est pas retenu. | Le plan Claude gratuit n'inclut pas Claude Code. Le cas ChatGPT gratuit n'est pas tranché par la documentation. |
| V3-12 | Liens affichés | Seuls les liens `https` vers `claude.com`, `claude.ai`, `anthropic.com`, `openai.com`, `chatgpt.com` (et leurs sous-domaines), lus dans la sortie du CLI, sont rendus cliquables. Codes ANSI retirés. Texte inséré par `textContent`. | La sortie d'un processus n'est pas une source de confiance. |
| V3-13 | Moteur Codex | `codex exec - --skip-git-repo-check --ephemeral --sandbox read-only --ignore-user-config --color never -o <fichier>`, consigne sur l'entrée standard, dossier courant = dossier du mois, délai 300 s, arbre de processus tué au délai. Le dernier message est lu dans le fichier `-o`. | Équivalent le plus proche de `claude -p --tools ""` : lecture seule, sans session gardée, sans réglages du poste. |
| V3-14 | Installeur | Inno Setup 6, `PrivilegesRequired=lowest`, dossier `%LOCALAPPDATA%\Programs\Planning des perms`, en français. Raccourcis bureau et menu Démarrer. Désinstallation par « Ajouter ou supprimer des programmes ». Les données du mois (`~/balustrade-planning`) et la configuration restent sur le poste après désinstallation. | Standard Windows sans droits admin. |
| V3-15 | Construction | GitHub Actions, runner `windows-latest`, dans le dépôt public : tests, construction, installation silencieuse de contrôle, publication dans les Releases sur une étiquette `v*`. | Le `.exe` vient d'une source vérifiable. |
| V3-16 | Dépôt public | Généré depuis le dépôt privé par un script d'export à liste fermée, qui vérifie l'absence de données réelles. Pas d'historique repris. Le dépôt privé reste la source. | Voir la section 3. |

## 3. Synchronisation dépôt privé vers dépôt public

Stratégie retenue : **export à sens unique**. Le dépôt privé reste la seule source. Le script `skills/planning-perms/public/exporter.py` copie une liste fermée de fichiers vers un dossier, qui est le clone du dépôt public. On relit le diff, puis on committe et on pousse ce dossier à la main.

Alternatives écartées :

- `git subtree split` ou `git filter-repo` : ils reprennent l'historique de `skills/planning-perms/`. Un ancien commit peut contenir une donnée réelle de famille ou une trace des autres outils du dépôt privé. Le risque ne se corrige plus une fois publié.
- Sous-module, ou dépôt public comme source : il faudrait sortir l'outil du dépôt privé et changer le skill Claude Code, qui l'importe. Coût élevé pour un seul mainteneur.

Prix de l'export : deux commits pour un changement (privé, puis public). C'est acceptable à ce rythme de changements.

## 4. Sources (vérifiées le 2026-10-30)

- Claude Code : https://code.claude.com/docs/en/setup (installation Windows sans admin, Git for Windows facultatif), https://code.claude.com/docs/en/authentication, https://code.claude.com/docs/en/cli-reference (`claude auth status`). Testé sur ce poste : Claude Code 2.1.312.
- Codex : https://developers.openai.com/codex/cli (script `install.ps1`), https://developers.openai.com/codex/auth (`codex login`, `--device-auth`, `codex login status`), https://developers.openai.com/codex/cli/reference (`codex exec`). Aides lues sur Codex 0.166.0.

## 5. Critères d'acceptation

1. Les 215 tests existants restent verts.
2. Tests de détection et de choix du moteur (Claude, Codex, DeepSeek, à la main), avec des CLI simulés.
3. Parcours de premier lancement en Playwright : question, installation simulée, connexion simulée (lien affiché, code transmis), moteur retenu, puis étape 1.
4. Moteur Codex testé avec un faux exécutable (consigne lue sur l'entrée standard, réponse lue dans `-o`, erreur et délai).
5. Lanceur : `pythonw` démarre le serveur sans console, écrit le journal, s'arrête sur `POST /api/arreter` et après inactivité (délai court en test).
6. Installeur construit et installé pour de vrai sur ce poste : raccourcis présents, outil lancé depuis le raccourci, aucune fenêtre console, désinstallation propre.
7. Dépôt public exporté : aucune donnée réelle, README avec bouton « Télécharger », guide illustré.
