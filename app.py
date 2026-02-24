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
    # sécurité basique sur l'URL
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="URL invalide (http/https uniquement).")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            # ✅ Utilise ta session TryHackMe si le fichier existe
            if os.path.exists("storage_state.json"):
                context = browser.new_context(storage_state="storage_state.json")
            else:
                context = browser.new_context()

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # IMPORTANT: ne pas utiliser networkidle sur TryHackMe
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Attendre que le body ait du contenu (sans bloquer sur le réseau)
            page.wait_for_function(
                "document.body && document.body.innerText && document.body.innerText.length > 200",
                timeout=timeout_ms
            )

            # Laisser quelques secondes pour que le contenu se stabilise
            if settle_ms:
                page.wait_for_timeout(settle_ms)

            # Texte visible (proche Ctrl+A)
            text = page.evaluate("document.body.innerText") or ""

            browser.close()

        # Nettoyage: enlève les lignes vides + espaces inutiles
        text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

        if not text:
            return {"url": url, "text": "", "note": "Texte vide (login requis ou rendu bloqué)."}

        return {"url": url, "text": text}

    except PWTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout Playwright (page trop lente ou bloquée).")
    except Exception as e:
        # utile pour déboguer proprement
        raise HTTPException(status_code=500, detail=f"Erreur: {type(e).__name__}: {e}")
