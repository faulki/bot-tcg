# Bot tournois One Piece — Bandai TCG+

## Alerte simple (recommandé) : `surveille.py`

Pas de navigateur, pas de compte : interroge directement l'API publique de Bandai TCG+
et notifie (PC + téléphone via ntfy) dès que l'événement de `config.py` sort.

```
python surveille.py --test     # notification de test
python surveille.py --liste    # événements actuellement en ligne
python surveille.py            # surveille toutes les ~2 min, notifie puis s'arrête
```

Téléphone : installe l'app **ntfy** et abonne-toi au topic indiqué dans `NTFY_TOPIC` (`config.py`).

Deux alertes possibles :
1. **« créé (en coulisses) »** : toutes les 10 min, le script parcourt les nouveaux numéros
   d'événements dans l'API. Bandai crée l'événement avant de l'afficher, donc tu peux être
   prévenu en avance (mais les inscriptions ne sont peut-être pas encore ouvertes).
2. **« NOUVEL EVENT DETECTE : … »** : l'événement est visible sur la page d'accueil. Le script
   cherche alors les tournois de `SHOP_NAME` (`config.py`) dans cet événement et les liste dans
   la notif. S'il n'y en a pas encore, il continue de vérifier et envoie **« TOURNOI DISPO »**
   dès qu'il en trouve un, puis s'arrête.

Cliquer sur la notif ouvre l'appli Bandai TCG+ (si elle est installée), directement sur le
tournoi de la boutique quand il y en a un.

En plus, sur le téléphone :
- une notif **« Bot One Piece lancé »** à chaque lancement ;
- une notif **« Vérification régulière, pas de nouvel event détecté »** toutes les 2 h
  (`HEARTBEAT_INTERVAL` dans `config.py`), avec la liste des événements en ligne.

L'état (numéros déjà vus, alertes déjà envoyées) est gardé dans `etat_surveillance.json`.

### Faire tourner sans PC (gratuit) : GitHub Actions

Le fichier `.github/workflows/surveille.yml` fait tourner `python3 surveille.py --once` sur les
serveurs de GitHub toutes les 10 min, et sauvegarde `etat_surveillance.json` dans le dépôt.

1. Crée un compte sur https://github.com, puis un dépôt **public** (illimité ; privé = 2000 min/mois, trop peu).
2. Dans le dépôt : Settings → Secrets and variables → Actions → New repository secret :
   nom `NTFY_TOPIC`, valeur = ton topic ntfy.
3. Sur le PC, dans ce dossier :
   ```
   git init -b main
   git add .
   git commit -m "Bot One Piece"
   git remote add origin https://github.com/<ton-pseudo>/<ton-depot>.git
   git push -u origin main
   ```
   (`.gitignore` empêche de publier `profil_navigateur/` et `config_local.py`.)
4. Onglet **Actions** → « Surveillance Bandai TCG+ » → **Run workflow** pour un premier test.

Avant de modifier le code sur le PC, fais `git pull` (le bot y enregistre son état).

---

## Inscription automatique (ancien bot) : `bot.py`

Surveille la page d'accueil de Bandai TCG+. Dès que l'événement configuré apparaît
(par défaut `[November 2026] OP Store Tournament Event`), il :

1. clique sur **Détails de l'événement**
2. clique sur **Confirmer série de tournoi**
3. filtre la région sur **Paris**
4. pour chaque tournoi **One Piece Official Shop Paris** : **Poser sa candidature** → **Vérifier le contenu et s'inscrire**
5. t'envoie une notification (son sur le PC + push sur ton téléphone si ntfy est configuré)

## Installation (déjà faite sur ce PC)

```
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## 1. Se connecter (une seule fois)

```
python bot.py --login
```

Une fenêtre Chrome s'ouvre : connecte-toi à ton compte Bandai TCG+, choisis Français
et le jeu « ONE PIECE CARD GAME (Français) », puis appuie sur Entrée dans le terminal.
La session est gardée dans le dossier `profil_navigateur/` (ne le partage pas : il contient ta connexion).

## 2. Tester sans s'inscrire

Teste le parcours sur un événement **déjà en ligne** (mets son nom exact) :

```
python bot.py --dry-run --once --event "[October 2026] OP Store Tournament Event"
```

Le bot va jusqu'à « Poser sa candidature » puis s'arrête et prend une capture dans `captures/`.
Si un bouton n'est pas trouvé, une capture `erreur_*.png` y est aussi enregistrée.

## 3. Lancer la surveillance

```
python bot.py
```

Laisse le terminal ouvert (le PC ne doit pas se mettre en veille). Vérification toutes les
~2 minutes. Ajoute `--headless` pour cacher la fenêtre du navigateur.

Les tournois déjà traités sont notés dans `inscriptions.json` pour ne pas recommencer.

## Notifications sur téléphone

1. Installe l'app **ntfy** (Android / iOS)
2. Abonne-toi à un topic au nom unique, ex. `op-chatelet-k8x2q9`
3. Mets ce nom dans `NTFY_TOPIC` dans `config.py`

## Si le site change

Tous les textes des boutons, le nom de l'événement, la boutique et la région sont
dans `config.py`.
