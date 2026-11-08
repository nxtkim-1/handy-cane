"""Family alerts via a Discord webhook. Runs in a thread so the cane never waits on the network."""
import threading, requests
from config import DISCORD_WEBHOOK

def _post(text):
    if not DISCORD_WEBHOOK:
        print("[alert - no webhook set]", text)
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": text}, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print("alert failed:", e)

def notify(text):
    threading.Thread(target=_post, args=(text,), daemon=True).start()
