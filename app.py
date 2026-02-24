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
    timeout_ms: int = Query(240000, ge=5000, le=300000),
    settle_ms: int = Query(4000, ge=0, le=30000),
    open_tasks: bool = Query(True, description="Ouvre toutes les tasks avant extraction"),
    max_tasks: int = Query(20, ge=1, le=100),
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

            # 2) Attends que la room soit rendue
            page.wait_for_function(
                """
                () => {
                  const t = (document.body && document.body.innerText) ? document.body.innerText : "";
                  return t.includes("Room progress") && t.includes("Task 1");
                }
                """,
                timeout=timeout_ms
            )

            # 3) Join Room si bouton présent
            joined = False
            try:
                for label in ["Join Room", "Join this room"]:
                    btn = page.get_by_role("button", name=label)
                    if btn.count() > 0:
                        btn.first.click()
                        joined = True
                        page.wait_for_timeout(5000)
                        break
            except Exception:
                pass

            # 4) Ouvrir toutes les tasks (lazy-load)
            opened = 0
            if open_tasks:
                # Clique sur "Task 1", "Task 2", ..., jusqu'à max_tasks si présent
                for i in range(1, max_tasks + 1):
                    try:
                        task_text = f"Task {i}"
                        # On clique sur le texte visible "Task X" (souvent en header d'accordéon)
                        loc = page.get_by_text(task_text, exact=True)
                        if loc.count() == 0:
                            # plus de tasks
                            break
                        loc.first.click()
                        opened += 1
                        # petit délai pour que le contenu se charge
                        page.wait_for_timeout(1200)
                    except Exception:
                        # si une task ne clique pas, on continue
                        continue

                # laisse React finir de remplir
                page.wait_for_timeout(3000)

            # 5) Stabilisation
            if settle_ms:
                page.wait_for_timeout(settle_ms)

            # 6) Texte complet
            text = page.evaluate("document.body.innerText") or ""
            browser.close()

        # nettoyage
        text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

        return {
            "url": url,
            "joined": joined,
            "tasks_opened": opened,
            "text": text
        }

    except PWTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout Playwright (page trop lente ou bloquée).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {type(e).__name__}: {e}")
