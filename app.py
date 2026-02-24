import os
from fastapi import FastAPI, Query, HTTPException
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

app = FastAPI()

DEFAULT_URL = "https://tryhackme.com/room/defensivesecurityintro"

@app.get("/")
def root():
    return {
        "ok": True,
        "usage": "/extract?url=https://tryhackme.com/room/defensivesecurityintro"
    }

@app.get("/extract")
def extract(
    url: str = Query(DEFAULT_URL, description="URL de la page TryHackMe (ou autre)"),
    wait_ms: int = Query(1500, ge=0, le=20000, description="Attente (ms) après chargement"),
    timeout_ms: int = Query(45000, ge=5000, le=120000, description="Timeout global (ms)")
):
    # Petite sécurité basique: évite les schémas bizarres
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="URL invalide (http/https uniquement).")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context()

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            page.goto(url, wait_until="domcontentloaded")
            # on attend que le réseau se calme un peu (utile pour SPA)
            page.wait_for_load_state("networkidle")
            if wait_ms:
                page.wait_for_timeout(wait_ms)

            # Texte "visible" (proche de Ctrl+A -> Copier)
            text = page.evaluate("document.body.innerText")

            browser.close()

            # Nettoyage léger
            text = (text or "").strip()
            if not text:
                return {"url": url, "text": "", "note": "Texte vide (login requis ou contenu non rendu?)"}

            return {"url": url, "text": text}

    except PWTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout Playwright (page trop lente ou bloquée).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {type(e).__name__}: {e}")
