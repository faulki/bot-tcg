# ---------------------------------------------------------------------------
# Configuration du bot — modifie les valeurs ici
# ---------------------------------------------------------------------------

# Nom exact (ou partiel) de l'événement à surveiller sur la page d'accueil
EVENT_TITLE = "[November 2026] OP Store Tournament Event"

# Boutique à laquelle s'inscrire
SHOP_NAME = "One Piece Official Shop Paris"

# Région à sélectionner dans le filtre
REGION = "Paris"

# Intervalle entre deux vérifications (en secondes). Un peu d'aléatoire est ajouté.
CHECK_INTERVAL = 120

# Détection « en coulisses » (surveille.py) : l'API permet de lire un événement par son
# numéro avant qu'il soit affiché sur l'accueil. Les numéros se suivent.
SCAN_INTERVAL = 600         # vérifie les nouveaux numéros toutes les 10 min
SCAN_START_ID = 8600        # point de départ au 1er lancement (octobre = 8034)
SCAN_FORWARD_MISSES = 30    # s'arrête après 30 numéros vides d'affilée
SCAN_RECHECK_WINDOW = 150   # revérifie les trous parmi les 150 derniers numéros

# Notifications push sur ton téléphone via https://ntfy.sh (gratuit, sans compte).
# 1. Installe l'app "ntfy" sur ton téléphone
# 2. Abonne-toi à un topic au nom unique et difficile à deviner, ex: "op-chatelet-k8x2q9"
# 3. Mets ce même nom dans config_local.py (fichier gardé sur ton PC, jamais publié sur GitHub).
#    Sur GitHub, il est dans le secret NTFY_TOPIC du dépôt.
try:
    from config_local import NTFY_TOPIC
except ImportError:
    NTFY_TOPIC = ""

# « Signe de vie » (surveille.py) : notification discrète sur le téléphone, même si rien
# n'est détecté, avec la liste des événements en ligne. En secondes ; 0 pour désactiver.
# 7200 = toutes les 2 h, 1800 = toutes les 30 min.
HEARTBEAT_INTERVAL = 7200

# Textes des boutons tels qu'affichés sur le site (en français).
# Les apostrophes ' et ’ sont traitées comme équivalentes.
TEXT_EVENT_DETAILS = "Détails de l'événement"
TEXT_CONFIRM_SERIES = "Confirmer série de tournoi"
TEXT_APPLY = "Poser sa candidature"
TEXT_VERIFY_REGISTER = "Vérifier le contenu et s'inscrire"

# Si une dernière fenêtre de confirmation apparaît après "Vérifier le contenu et s'inscrire",
# le bot essaiera de cliquer sur l'un de ces boutons (texte exact).
FINAL_CONFIRM_TEXTS = ["S'inscrire", "Confirmer", "Confirmer l'inscription", "OK"]

# Libellés possibles du filtre de région
REGION_FILTER_LABELS = ["Région du tournoi", "Région", "Region", "Zone"]

# Textes possibles du bouton « page suivante » de la pagination
NEXT_PAGE_TEXTS = ["Suivant", "Page suivante", "Next", ">", "›", "»", "→"]

# Boutons éventuels pour appliquer le filtre
FILTER_APPLY_TEXTS = ["Rechercher", "Appliquer", "Valider", "Recherche"]

HOME_URL = "https://www.bandai-tcg-plus.com/home"
