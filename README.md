# Planning des perms

L'outil de la Crèche Balustrade qui prépare le planning mensuel des perms parents. Vous collez le lien du sondage Framadate, vous relisez les règles, vous tranchez les cas difficiles, et vous téléchargez l'Excel à importer dans le Google Sheet de la crèche.

## Installer (Windows)

[![Télécharger pour Windows](https://img.shields.io/badge/T%C3%A9l%C3%A9charger-pour%20Windows-2f6f4f?style=for-the-badge)](https://github.com/yannick-bottino/planning-des-perms/releases/latest/download/Installer-Planning-des-perms.exe)

1. Cliquez sur le bouton ci-dessus. Le fichier `Installer-Planning-des-perms.exe` se télécharge.
2. Ouvrez-le. Windows affiche « Windows a protégé votre ordinateur » : cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même**.
3. Suivez les écrans. Aucun mot de passe administrateur n'est demandé.
4. Une icône **Planning des perms** apparaît sur le bureau. Un clic dessus ouvre l'outil dans sa propre fenêtre (Chrome, ou Edge si Chrome n'est pas installé).

Le guide pas à pas, avec les écrans : [GUIDE.md](GUIDE.md).

## Premier lancement

L'outil vous demande : « Vous avez un abonnement Claude, ChatGPT, ou une clé DeepSeek ? »

- **Claude** : il faut un abonnement payant (Pro, Max, Team ou Enterprise). L'outil installe Claude, puis vous connectez votre compte dans le navigateur.
- **ChatGPT** : il faut un abonnement payant (Plus ou supérieur). L'outil installe l'assistant de ChatGPT, puis vous connectez votre compte.
- **Clé DeepSeek** : vous collez la clé, l'outil la garde sur cet ordinateur.
- **Rien de tout ça** : vous saisissez les règles à la main, l'outil fonctionne quand même.

L'assistant ne fait que lire les commentaires du sondage et proposer des règles. Vous les relisez toujours avant le calcul.

## Fermer l'outil

Bouton **Fermer l'outil** en haut de la page. Si vous oubliez, l'outil s'arrête seul après quelques minutes sans page ouverte.

## Désinstaller

Paramètres Windows, Applications, **Planning des perms**, Désinstaller. Vos plannings (dossier `balustrade-planning` de votre dossier personnel) restent sur l'ordinateur.

## Vos données

Tout reste sur votre ordinateur : les plannings dans `balustrade-planning`, la clé DeepSeek dans les réglages de l'outil. Seuls les commentaires du sondage partent vers l'assistant choisi (Claude, ChatGPT ou DeepSeek).

---

Pour les personnes qui maintiennent l'outil : construction de l'installeur dans [installeur/README-installeur.md](installeur/README-installeur.md), spécifications dans [docs/specs/](docs/specs/). Ce dépôt est généré depuis un dépôt privé par un export à sens unique : les modifications se font là-bas.

Licence MIT (fichier [LICENSE](LICENSE)) : réutilisation libre, sans garantie.
