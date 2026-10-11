"""Surveille Bandai TCG+ et prévient (PC + téléphone) dès que l'événement configuré
(par défaut « [November 2026] OP Store Tournament Event ») est mis en ligne.

Pas besoin de navigateur ni de compte : le script interroge directement l'API
publique utilisée par le site.

Usage :
    python surveille.py              # boucle : vérifie toutes les ~2 min, notifie puis s'arrête
    python surveille.py --once       # une seule vérification (pour un serveur / une tâche planifiée)
    python surveille.py --test       # envoie une notification de test
    python surveille.py --liste      # affiche les événements actuellement en ligne
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import config

API_URL = "https://api.bandai-tcg-plus.com/api/user/eventseries"
EVENT_LIST_URL = "https://api.bandai-tcg-plus.com/api/user/event/list"
WEB_URL = "https://www.bandai-tcg-plus.com"
HOME_URL = f"{WEB_URL}/home"
GAME_TITLE_ID = 13  # ONE PIECE CARD GAME (Français)
COUNTRY = "FR"
# Sans en-têtes « navigateur », l'API répond 403
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Origin": "https://www.bandai-tcg-plus.com",
    "Referer": "https://www.bandai-tcg-plus.com/",
    "Accept": "application/json",
}
STATE_FILE = Path(__file__).parent / "etat_surveillance.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or config.NTFY_TOPIC

sys.stdout.reconfigure(encoding="utf-8")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch_events():
    """Renvoie la liste de tous les événements en ligne (toutes les pages de l'API)."""
    events, offset, limit = [], 0, 50
    while True:
        url = f"{API_URL}?game_title_id={GAME_TITLE_ID}&country_code={COUNTRY}&limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            batch = json.load(r)["success"]["event_series_list"]
        events += batch
        if len(batch) < limit:
            return events
        offset += limit


def find_event(events, title):
    wanted = title.lower().strip()
    return next((e for e in events if wanted in e["title"].lower()), None)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:TOAST_TITLE)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:TOAST_MSG)) > $null
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def notify_pc(title, message):
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
    try:
        env = dict(os.environ, TOAST_TITLE=title, TOAST_MSG=message)
        subprocess.run(["powershell", "-NoProfile", "-Command", TOAST_PS], env=env,
                       capture_output=True, timeout=30)
    except Exception as e:
        log(f"Échec notification PC : {e}")


def notify_phone(title, message, priority=5, tags=("rotating_light",), click=HOME_URL):
    """Push ntfy. Le lien https://www.bandai-tcg-plus.com/... ouvre directement l'appli
    TCG+ si elle est installée (Android et iPhone), sinon le navigateur."""
    if not NTFY_TOPIC:
        return
    try:
        payload = {"topic": NTFY_TOPIC, "title": title, "message": message,
                   "priority": priority, "tags": list(tags), "click": click}
        req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"Échec notification téléphone : {e}")


def notify(title, message, click=HOME_URL):
    log(f"🔔 {title} — {message}")
    notify_pc(title, message)
    notify_phone(title, message, click=click)


def format_events(events):
    if not events:
        return "Aucun événement en ligne."
    return "\n".join(f"- {e['title']} ({e['apply_start_date']} → {e['apply_end_date']})" for e in events)


def events_body(intro, events=None, error=None):
    if error:
        return f"{intro}\n\n⚠️ Impossible de lire les événements : {error}"
    return f"{intro}\n\nÉvénements en ligne :\n{format_events(events)}"


def heartbeat(title, body, state):
    """Notification régulière sur le téléphone pour montrer que le bot tourne toujours."""
    log(f"Signe de vie envoyé sur le téléphone : {title}")
    notify_phone(title, body, priority=3, tags=("white_check_mark",))
    state["dernier_signe_de_vie"] = time.time()


def notify_startup(title, state):
    try:
        body = events_body(f"Je surveille « {title} ».", fetch_events())
    except Exception as e:
        body = events_body(f"Je surveille « {title} ».", error=repr(e))
    log("Notification de lancement envoyée sur le téléphone.")
    notify_phone("Bot One Piece lancé", body, priority=3, tags=("rocket",))
    state["dernier_signe_de_vie"] = time.time()


def heartbeat_due(state):
    return (config.HEARTBEAT_INTERVAL > 0
            and time.time() - state.get("dernier_signe_de_vie", 0) >= config.HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"notifie": [], "ids_connus": [], "max_id": config.SCAN_START_ID}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def fetch_series(series_id):
    """Détail d'un événement par son numéro, ou None s'il n'existe pas (ou est caché)."""
    req = urllib.request.Request(f"{API_URL}/{series_id}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)["success"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch_shop_tournaments(series_id):
    """Tournois de la boutique (config.SHOP_NAME) dans un événement, par date."""
    tournaments, offset, limit = [], 0, 50
    while True:
        query = urllib.parse.urlencode({
            "game_title_id": GAME_TITLE_ID, "event_series_id": series_id,
            "organizer_name": config.SHOP_NAME, "favorite": 0, "application_open_flg": 0,
            "order": 1, "limit": limit, "offset": offset,
        })
        req = urllib.request.Request(f"{EVENT_LIST_URL}?{query}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            batch = json.load(r)["success"]["event_list"]
        # Le filtre de l'API est approximatif : on garde seulement la bonne boutique
        tournaments += [t for t in batch if config.SHOP_NAME.lower() in (t.get("organizer_name") or "").lower()]
        if len(batch) < limit:
            return sorted(tournaments, key=lambda t: t["start_datetime"])
        offset += limit


def tournament_status(t):
    if t.get("is_canceled"):
        return "annulé"
    if t.get("is_over_max_join_count"):
        return "complet"
    if str(t.get("applicationOpen")) == "1":
        return "inscriptions ouvertes"
    try:
        opens = datetime.fromisoformat(t["apply_start_datetime"]).astimezone()
        return f"inscriptions à partir du {opens:%d/%m à %H:%M}"
    except (KeyError, TypeError, ValueError):
        return "inscriptions pas encore ouvertes"


def format_tournaments(tournaments):
    return "\n".join(f"- {datetime.fromisoformat(t['start_datetime']):%d/%m à %H:%M} : {tournament_status(t)}"
                     for t in tournaments)


def check_list(title, state, events):
    """Page d'accueil. Quand l'événement est en ligne, cherche les tournois de la boutique.
    Renvoie (événement ou None, True si au moins un tournoi de la boutique a été trouvé)."""
    event = find_event(events, title)
    if not event:
        log(f"Accueil vérifié ({len(events)} événements en ligne) : « {title} » pas encore là.")
        return None, False

    sid = event["event_series_id"]
    tournaments = fetch_shop_tournaments(sid)
    found = bool(tournaments)
    if found:
        shop_txt = f"{len(tournaments)} tournoi(s) « {config.SHOP_NAME} » :\n{format_tournaments(tournaments)}"
        click = f"{WEB_URL}/event/{tournaments[0]['id']}"
    else:
        shop_txt = (f"Pas encore de tournoi « {config.SHOP_NAME} ». Je continue de vérifier "
                    f"et je te préviens dès qu'il y en a un.")
        click = HOME_URL
    log(f"Événement en ligne. {shop_txt}")

    if f"liste:{sid}" not in state["notifie"]:
        notify(f"NOUVEL EVENT DETECTE : {event['title']}",
               events_body(shop_txt, events), click=click)
        state["notifie"].append(f"liste:{sid}")
        if found:
            state["notifie"].append(f"boutique:{sid}")
    elif found and f"boutique:{sid}" not in state["notifie"]:
        notify(f"TOURNOI DISPO : {config.SHOP_NAME}", f"{event['title']}\n\n{shop_txt}", click=click)
        state["notifie"].append(f"boutique:{sid}")
    return event, found


def check_hidden(title, state):
    """Parcourt les numéros d'événements récents pour repérer l'événement dès sa
    création, avant même qu'il apparaisse sur la page d'accueil."""
    known = set(state["ids_connus"])
    max_id = state["max_id"]
    wanted = title.lower().strip()

    # Trous récents (événements d'autres régions ou brouillons qui peuvent être publiés plus tard)
    # + nouveaux numéros au-delà du plus grand connu
    to_check = [i for i in range(max_id - config.SCAN_RECHECK_WINDOW, max_id + 1) if i not in known]
    log(f"Coulisses : scan des numéros d'événements en cours (environ {len(to_check) + config.SCAN_FORWARD_MISSES} "
        f"numéros, 1 à 2 min)…")
    misses, i = 0, max_id + 1
    checked = 0
    queue = list(to_check)
    while queue or misses < config.SCAN_FORWARD_MISSES:
        if queue:
            sid = queue.pop(0)
            forward = False
        else:
            sid, i = i, i + 1
            forward = True
        data = fetch_series(sid)
        checked += 1
        time.sleep(0.15)
        if not data or not data.get("event_series_title"):
            misses += forward
            continue
        if forward:
            misses = 0
        known.add(sid)
        max_id = max(max_id, sid)
        if wanted in data["event_series_title"].lower():
            key = f"coulisses:{sid}"
            if key not in state["notifie"]:
                terms = data.get("terms") or [{}]
                debut = (terms[0].get("apply_start_date") or "?")[:10]
                notify(f"NOUVEL EVENT DETECTE (en coulisses) : {data['event_series_title']}",
                       f"Bandai vient de le créer (n° {sid}, tournois à partir du {debut}). Il n'est peut-être "
                       f"pas encore visible dans l'appli : je te préviens dès qu'il est en ligne.")
                state["notifie"].append(key)

    # On ne garde en mémoire que les numéros récents
    state["ids_connus"] = sorted(k for k in known if k >= max_id - config.SCAN_RECHECK_WINDOW)
    state["max_id"] = max_id
    log(f"Coulisses : {checked} numéros vérifiés, dernier événement existant n° {max_id}.")


def main():
    ap = argparse.ArgumentParser(description="Alerte quand un événement One Piece sort sur Bandai TCG+")
    ap.add_argument("--event", default=config.EVENT_TITLE, help="nom de l'événement à surveiller")
    ap.add_argument("--once", action="store_true", help="une seule vérification")
    ap.add_argument("--test", action="store_true", help="envoie une notification de test")
    ap.add_argument("--liste", action="store_true", help="affiche les événements en ligne")
    args = ap.parse_args()

    if args.test:
        notify("Test bot One Piece", "Si tu vois ce message, les notifications marchent !")
        return
    if args.liste:
        print(format_events(fetch_events()))
        return

    state = load_state()
    no_event = "Vérification régulière, pas de nouvel event détecté"
    no_shop = f"Vérification régulière, pas encore de tournoi {config.SHOP_NAME}"
    if args.once:
        # Une seule vérification (GitHub Actions / tâche planifiée) : l'état est gardé entre les lancements
        try:
            events = fetch_events()
            event, found = check_list(args.event, state, events)
            if not found and heartbeat_due(state):
                heartbeat(no_shop if event else no_event, events_body(f"Je surveille « {args.event} ».", events), state)
            if not event:
                check_hidden(args.event, state)
        except Exception as e:
            log(f"Erreur : {e!r}")
            if heartbeat_due(state):
                heartbeat(no_event, events_body(f"Je surveille « {args.event} ».", error=repr(e)), state)
        save_state(state)
        return

    log(f"Surveillance de « {args.event} » (Ctrl+C pour arrêter)")
    notify_startup(args.event, state)
    last_scan = 0
    event = None
    while True:
        try:
            # Accueil d'abord (rapide), puis le scan en coulisses (plus long)
            events = fetch_events()
            event, found = check_list(args.event, state, events)
            if found:
                save_state(state)
                log("Tournoi de la boutique trouvé, terminé. Bonne inscription !")
                return
            if heartbeat_due(state):
                heartbeat(no_shop if event else no_event, events_body(f"Je surveille « {args.event} ».", events), state)
            save_state(state)
            # Inutile de scanner les coulisses une fois l'événement en ligne
            if not event and time.time() - last_scan >= config.SCAN_INTERVAL:
                check_hidden(args.event, state)
                last_scan = time.time()
                save_state(state)
        except Exception as e:
            log(f"Erreur (on réessaie) : {e!r}")
            if heartbeat_due(state):
                heartbeat(no_shop if event else no_event,
                          events_body(f"Je surveille « {args.event} ».", error=repr(e)), state)
        pause = config.CHECK_INTERVAL + random.randint(0, 30)
        log(f"Prochaine vérification à {datetime.fromtimestamp(time.time() + pause):%H:%M:%S}.")
        time.sleep(pause)


if __name__ == "__main__":
    main()
