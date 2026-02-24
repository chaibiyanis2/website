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
    timeout_ms: int = Query(180000, ge=5000, le=240000),
    settle_ms: int = Query(8000, ge=0, le=30000),
):
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="URL invalide (http/https uniquement).")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            # session TryHackMe
            if os.path.exists("storage_state.json"):
                context = browser.new_context(storage_state="storage_state.json")
            else:
                context = browser.new_context()

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # 1) Ouvre la page
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3000)

            # 2) Attends que la room soit bien rendue
            page.wait_for_function(
                """
                () => {
                  const t = (document.body && document.body.innerText) ? document.body.innerText : "";
                  const keywords = ["Defensive Security", "Room progress", "Task 1", "Room Info"];
                  const hasRoomKeyword = keywords.some(k => t.includes(k));
                  return hasRoomKeyword && t.length > 1200;
                }
                """,
                timeout=timeout_ms
            )

            # 3) Si bouton "Join Room" existe, clique dessus
            # (on le fait en "best effort", si ça n'existe pas on continue)
            join_clicked = False
            try:
                # essaie plusieurs variantes de texte possibles
                for label in ["Join Room", "Join this room"]:
                    btn = page.get_by_role("button", name=label)
                    if btn.count() > 0:
                        btn.first.click()
                        join_clicked = True
                        break
            except Exception:
                pass

            # 4) Attends stabilisation après le clic
            if join_clicked:
                # laisse le temps aux requêtes + rerender
                page.wait_for_timeout(5000)

            if settle_ms:
                page.wait_for_timeout(settle_ms)

            # 5) Récupère texte visible
            text = page.evaluate("document.body.innerText") or ""
            browser.close()

        # nettoyage
        text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

        return {"url": url, "joined": join_clicked, "text": text}

    except PWTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout Playwright (page trop lente ou bloquée).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {type(e).__name__}: {e}")
