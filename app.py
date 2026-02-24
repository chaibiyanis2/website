import os
from fastapi import FastAPI, Query, HTTPException
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

app = FastAPI()

@app.get("/")
def root():
    return {"ok": True, "usage": "/extract?url=https://tryhackme.com/room/defensivesecurityintro"}

@app.get("/extract")
def extract(
    url: str = Query(...),
    timeout_ms: int = Query(120000, ge=5000, le=180000),  # 2 min par défaut
    settle_ms: int = Query(4000, ge=0, le=30000),         # laisse le JS rendre
):
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="URL invalide (http/https uniquement).")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            # (optionnel) session si tu ajoutes storage_state.json
            if os.path.exists("storage_state.json"):
                context = browser.new_context(storage_state="storage_state.json")
            else:
                context = browser.new_context()

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # IMPORTANT: ne pas utiliser networkidle sur TryHackMe
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Attendre que le body ait du contenu (sans bloquer sur le réseau)
            page.wait_for_function("document.body && document.body.innerText.length > 200", timeout=timeout_ms)

            # Laisser quelques secondes pour que le contenu se stabilise
            if settle_ms:
                page.wait_for_timeout(settle_ms)

            text = page.evaluate("document.body.innerText") or ""
            browser.close()

        text = text.strip()
        if not text:
            return {"url": url, "text": "", "note": "Texte vide (login requis ou rendu bloqué)."}

        return {"url": url, "text": text}

    except PWTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout Playwright (page trop lente ou bloquée).")
