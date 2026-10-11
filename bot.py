"""Bot Bandai TCG+ : surveille l'ouverture des tournois One Piece et s'inscrit
automatiquement à ceux de la boutique officielle de Paris (Châtelet).

Usage :
    python bot.py --login                 # 1re fois : se connecter à son compte
    python bot.py --dry-run --once        # test : fait tout sauf l'inscription finale
    python bot.py                         # surveillance en boucle + inscription
Voir README.md pour les détails.
"""
import argparse
import hashlib
import json
import random
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import config

ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / "profil_navigateur"
CAPTURES_DIR = ROOT / "captures"
STATE_FILE = ROOT / "inscriptions.json"

sys.stdout.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def rx(text, exact=False):
    """Regex insensible à la casse, qui accepte ' et ’ indifféremment."""
    pattern = re.sub(r"['’]", "['’]", re.escape(text))
    if exact:
        pattern = rf"^\s*{pattern}\s*$"
    return re.compile(pattern, re.IGNORECASE)


def notify(title, message):
    log(f"🔔 {title} — {message}")
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
    if not config.NTFY_TOPIC:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{config.NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title.encode("ascii", "ignore").decode(), "Priority": "high"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"Échec notification ntfy : {e}")


def screenshot(page, name):
    CAPTURES_DIR.mkdir(exist_ok=True)
    path = CAPTURES_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log(f"Capture : {path.name}")
    except Exception:
        pass


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"done": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def settle(page, ms=1500):
    """Laisse le temps à la page (site en JS) de se charger."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    page.wait_for_timeout(ms)


def clickable(scope, text, exact=False):
    """Retourne le premier bouton/lien visible portant ce texte (ou None)."""
    pattern = rx(text, exact)
    candidates = [
        scope.get_by_role("button", name=pattern),
        scope.get_by_role("link", name=pattern),
        scope.get_by_text(pattern),
    ]
    for loc in candidates:
        try:
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    return el
        except Exception:
            continue
    return None


def click(page, text, timeout=15, exact=False, scope=None):
    """Attend qu'un bouton avec ce texte apparaisse puis clique dessus."""
    scope = scope or page
    deadline = time.time() + timeout
    while time.time() < deadline:
        el = clickable(scope, text, exact)
        if el:
            el.scroll_into_view_if_needed()
            el.click()
            log(f"Clic : « {text} »")
            settle(page)
            return True
        page.wait_for_timeout(500)
    return False


def load_everything(page):
    """Scrolle jusqu'en bas et clique sur « Voir plus » pour charger toute la liste."""
    for _ in range(30):
        more = clickable(page, "Voir plus") or clickable(page, "Afficher plus") or clickable(page, "Charger plus")
        if more:
            more.click()
            settle(page, 800)
            continue
        before = page.evaluate("document.body.scrollHeight")
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(800)
        if page.evaluate("document.body.scrollHeight") == before:
            break
    page.evaluate("window.scrollTo(0, 0)")


# ---------------------------------------------------------------------------
# Étapes du parcours
# ---------------------------------------------------------------------------

def is_logged_out(page):
    return clickable(page, "Se connecter") is not None or clickable(page, "Log in", exact=True) is not None


def open_event(page, event_title):
    """Page d'accueil → cherche l'événement → clique sur « Détails de l'événement »."""
    page.goto(config.HOME_URL)
    settle(page, 3000)
    load_everything(page)

    titles = page.get_by_text(rx(event_title))
    if titles.count() == 0:
        return False

    # Remonte depuis le titre jusqu'à la « carte » qui contient le bouton Détails
    node = titles.first
    for _ in range(12):
        node = node.locator("xpath=..")
        btn = clickable(node, config.TEXT_EVENT_DETAILS)
        if btn:
            btn.scroll_into_view_if_needed()
            btn.click()
            log(f"Clic : « {config.TEXT_EVENT_DETAILS} »")
            settle(page)
            return True
    # Pas de bouton Détails trouvé : on clique directement sur le titre
    titles.first.click()
    settle(page)
    return True


def apply_region_filter(page):
    """Essaie de filtrer sur la région Paris. Si ça échoue, ce n'est pas bloquant :
    le bot repère de toute façon la boutique par son nom."""
    region = config.REGION
    # 1) liste déroulante native <select>
    for sel in page.locator("select").all():
        try:
            options = [o.strip() for o in sel.locator("option").all_inner_texts()]
            match = next((o for o in options if o.lower() == region.lower()), None)
            if match:
                sel.select_option(label=match)
                log(f"Filtre région : {match}")
                break
        except Exception:
            continue
    else:
        # 2) liste déroulante « maison » : clic sur le libellé puis sur « Paris »
        done = False
        for label in config.REGION_FILTER_LABELS:
            ctl = clickable(page, label)
            if not ctl:
                continue
            ctl.click()
            page.wait_for_timeout(800)
            opt = clickable(page, region, exact=True)
            if opt:
                opt.click()
                log(f"Filtre région : {region}")
                done = True
                break
            page.keyboard.press("Escape")
        if not done:
            log("⚠ Filtre région introuvable, on continue sans (la boutique est repérée par son nom).")
            return

    settle(page, 800)
    for txt in config.FILTER_APPLY_TEXTS:
        if click(page, txt, timeout=1, exact=True):
            break


def find_shop_cards(page):
    """Retourne la liste (carte, bouton) des tournois de la boutique qui ont
    encore un bouton « Poser sa candidature »."""
    apply_rx = rx(config.TEXT_APPLY)
    shop_rx = rx(config.SHOP_NAME)
    results = []
    buttons = [b for b in (page.get_by_role("button", name=apply_rx).all()
                           or page.get_by_text(apply_rx).all()) if b.is_visible()]
    for btn in buttons:
        # Remonte depuis le bouton jusqu'au plus petit bloc qui contient un nom de boutique.
        # Si on tombe d'abord sur un bloc contenant plusieurs boutons, c'est que ce bouton
        # n'appartient pas à une carte de notre boutique → on l'ignore.
        node = btn
        for _ in range(12):
            node = node.locator("xpath=..")
            if node.get_by_text(apply_rx).count() > 1:
                break
            text = node.inner_text()
            if shop_rx.search(text):
                results.append((node, btn, text))
                break
    return results


def card_key(text):
    return hashlib.sha1(" ".join(text.split()).encode()).hexdigest()[:16]


def register_one(page, state, dry_run):
    """Inscrit à UN tournoi de la boutique non encore traité. Renvoie True si fait."""
    for card, btn, text in find_shop_cards(page):
        key = card_key(text)
        if key in state["done"]:
            continue
        summary = " | ".join(line.strip() for line in text.splitlines() if line.strip())[:200]
        log(f"Tournoi trouvé : {summary}")

        btn.scroll_into_view_if_needed()
        btn.click()
        log(f"Clic : « {config.TEXT_APPLY} »")
        settle(page)

        if dry_run:
            screenshot(page, "dry_run_avant_inscription")
            log("[DRY-RUN] Arrêt avant « Vérifier le contenu et s'inscrire ».")
            state["done"][key] = {"date": datetime.now().isoformat(), "resume": summary, "dry_run": True}
            return True

        if not click(page, config.TEXT_VERIFY_REGISTER, timeout=20):
            screenshot(page, "erreur_verifier_inscrire")
            notify("Bot OP : action requise", f"Bouton « {config.TEXT_VERIFY_REGISTER} » introuvable pour : {summary}")
            state["done"][key] = {"date": datetime.now().isoformat(), "resume": summary, "erreur": True}
            return True

        # Éventuelle fenêtre de confirmation finale
        for txt in config.FINAL_CONFIRM_TEXTS:
            if click(page, txt, timeout=2, exact=True):
                break

        screenshot(page, "inscription")
        state["done"][key] = {"date": datetime.now().isoformat(), "resume": summary}
        notify("Bot OP : inscription faite !", summary)
        return True
    return False


def run_cycle(page, state, args, alerted):
    if not open_event(page, args.event):
        if is_logged_out(page):
            if not alerted.get("logout"):
                notify("Bot OP : déconnecté", "Relance « python bot.py --login » pour te reconnecter.")
                alerted["logout"] = True
        else:
            log("Événement pas encore en ligne.")
        return

    alerted["logout"] = False
    if not alerted.get("event"):
        notify("Bot OP : événement détecté !", args.event)
        alerted["event"] = True

    # Parcourt toutes les pages de résultats. Après chaque inscription, on refait le
    # parcours complet depuis l'accueil (plus robuste) et on revient à la même page.
    page_index = 0
    registered = 0
    need_reload = False  # l'événement vient d'être ouvert par open_event ci-dessus
    for _ in range(300):
        if need_reload:
            if not open_event(page, args.event):
                break
        if need_reload or page_index == 0:
            if not open_series_list(page, page_index):
                return
            need_reload = False

        if register_one(page, state, args.dry_run):
            registered += 1
            save_state(state)
            need_reload = True  # il peut en rester d'autres sur cette même page
            continue

        if not next_page(page):
            break
        page_index += 1
        log(f"Page {page_index + 1} des résultats.")
        load_everything(page)

    if registered == 0:
        log(f"Aucun nouveau tournoi « {config.SHOP_NAME} » ouvert ({page_index + 1} page(s) parcourue(s)).")
    else:
        log(f"{registered} tournoi(s) traité(s) sur {page_index + 1} page(s).")


def open_series_list(page, page_index):
    """Depuis la page de l'événement : confirme la série, filtre Paris, va à la page demandée."""
    if not click(page, config.TEXT_CONFIRM_SERIES, timeout=20):
        screenshot(page, "erreur_confirmer_serie")
        log(f"⚠ Bouton « {config.TEXT_CONFIRM_SERIES} » introuvable.")
        return False
    apply_region_filter(page)
    load_everything(page)
    for _ in range(page_index):
        if not next_page(page):
            break
        load_everything(page)
    return True


def list_fingerprint(page):
    try:
        return hashlib.sha1(page.inner_text("body").encode()).hexdigest()
    except Exception:
        return None


def is_disabled(el):
    try:
        if not el.is_enabled():
            return True
        attrs = " ".join(filter(None, [el.get_attribute("aria-disabled"), el.get_attribute("class"),
                                       el.evaluate("e => e.parentElement ? e.parentElement.className : ''")]))
        return "true" in attrs or "disabled" in attrs.lower()
    except Exception:
        return False


def next_page_button(page):
    """Cherche le bouton « page suivante » de la pagination."""
    lower_label = "translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
    candidates = [
        page.locator(f"xpath=//*[contains({lower_label},'next') or contains({lower_label},'suivant')]"),
        page.locator("button[class*='next' i], a[class*='next' i], li[class*='next' i] > *"),
    ]
    for text in config.NEXT_PAGE_TEXTS:
        candidates.append(page.get_by_role("button", name=rx(text, exact=True)))
        candidates.append(page.get_by_role("link", name=rx(text, exact=True)))
        candidates.append(page.get_by_text(rx(text, exact=True)))
    for loc in candidates:
        try:
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible() and not is_disabled(el):
                    return el
        except Exception:
            continue
    return None


def next_page(page):
    """Passe à la page suivante. Renvoie False s'il n'y en a pas (dernière page)."""
    before = list_fingerprint(page)
    btn = next_page_button(page)
    if not btn:
        # Repli : bouton avec le numéro de la page suivante
        current = page.locator("[aria-current='page'], [aria-current='true'], [class*='active' i]")
        try:
            num = int(current.filter(has_text=re.compile(r"^\s*\d+\s*$")).first.inner_text().strip())
            btn = clickable(page, str(num + 1), exact=True)
        except Exception:
            btn = None
    if not btn:
        return False
    btn.scroll_into_view_if_needed()
    btn.click()
    settle(page)
    # Si le contenu n'a pas changé, on était déjà sur la dernière page
    return list_fingerprint(page) != before


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Bot d'inscription aux tournois One Piece — Bandai TCG+")
    ap.add_argument("--login", action="store_true", help="ouvre le navigateur pour te connecter")
    ap.add_argument("--dry-run", action="store_true", help="fait tout sauf l'inscription finale")
    ap.add_argument("--once", action="store_true", help="un seul passage puis quitte")
    ap.add_argument("--headless", action="store_true", help="navigateur invisible")
    ap.add_argument("--event", default=config.EVENT_TITLE, help="nom de l'événement (pour tester sur un autre)")
    args = ap.parse_args()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=args.headless and not args.login,
            locale="fr-FR",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if args.login:
            page.goto(config.HOME_URL)
            print("\nConnecte-toi à ton compte Bandai TCG+ dans la fenêtre qui s'est ouverte.")
            print("Choisis la langue Français et le jeu « ONE PIECE CARD GAME (Français) ».")
            input("Une fois que tu vois les événements sur l'accueil, appuie sur Entrée ici… ")
            ctx.close()
            print("Session enregistrée. Lance maintenant : python bot.py --dry-run --once")
            return

        # En dry-run on n'enregistre rien, pour ne pas bloquer les vraies inscriptions ensuite
        state = {"done": {}} if args.dry_run else load_state()
        if args.dry_run:
            globals()["save_state"] = lambda _state: None
        alerted = {}
        log(f"Surveillance de « {args.event} » pour « {config.SHOP_NAME} »"
            + (" [DRY-RUN]" if args.dry_run else ""))
        while True:
            try:
                run_cycle(page, state, args, alerted)
                save_state(state)
            except Exception as e:
                log(f"Erreur : {e!r}")
                screenshot(page, "erreur")
            if args.once:
                break
            wait = config.CHECK_INTERVAL + random.randint(0, 30)
            log(f"Prochaine vérification dans {wait}s.")
            time.sleep(wait)
        ctx.close()


if __name__ == "__main__":
    main()
