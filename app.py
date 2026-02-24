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
    timeout_ms: int = Query(180000, ge=5000, le=240000),  # 3 min par défaut
    settle_ms: int = Query(8000, ge=0, le=30000),         # laisse le JS rendre
):
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

            # 1) Ouvre la page (évite networkidle sur TryHackMe)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # 2) Laisse l'app React démarrer
            page.wait_for_timeout(3000)

            # 3) Attends que le vrai contenu de la room soit chargé
            page.wait_for_function(
                """
                () => {
                  const t = (document.body && document.body.innerText) ? document.body.innerText : "";
                  const keywords = ["Room Info", "Task", "Start Room", "Join Room", "Questions", "Room progress"];
                  const hasRoomKeyword = keywords.some(k => t.includes(k));
                  const longEnough = t.length > 1500;   // plus que navbar + cookies
                  return hasRoomKeyword && longEnough;
                }
                """,
                timeout=timeout_ms
            )

            # 4) Laisse quelques secondes pour stabiliser
            if settle_ms:
                page.wait_for_timeout(settle_ms)

            # 5) Récupère le texte visible (proche Ctrl+A)
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
        raise HTTPException(status_code=500, detail=f"Erreur: {type(e).__name__}: {e}")
