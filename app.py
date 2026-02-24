import os
import re
from fastapi import FastAPI, Query, HTTPException
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

app = FastAPI()

@app.get("/")
def root():
    return {"ok": True, "usage": "/extract_structured?url=https://tryhackme.com/room/defensivesecurityintro"}

def _clean_text(s: str) -> str:
    s = s or ""
    lines = [ln.strip() for ln in s.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)

@app.get("/extract_structured")
def extract_structured(
    url: str = Query(...),
    timeout_ms: int = Query(240000, ge=5000, le=300000),
    settle_ms: int = Query(1500, ge=0, le=15000),
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

            # session TryHackMe si dispo
            if os.path.exists("storage_state.json"):
                context = browser.new_context(storage_state="storage_state.json")
            else:
                context = browser.new_context()

            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # 1) Ouvre la room
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3000)

            # 2) Attends que la room soit rendue
            page.wait_for_function(
                """() => {
                    const t = document.body?.innerText || "";
                    return t.includes("Room progress") && t.includes("Task 1");
                }""",
                timeout=timeout_ms
            )

            # 3) Clique Join Room si présent (sinon déjà joined)
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

            # 4) Récupère titre + description (best effort)
            title = ""
            desc = ""
            try:
                title = page.get_by_role("heading").first.inner_text()
            except Exception:
                title = ""
            try:
                # description visible sous le titre, best effort
                t = page.evaluate("document.body.innerText") or ""
                # on prend quelques lignes autour du titre (pas parfait mais ok)
                desc = t
            except Exception:
                desc = ""

            # 5) Pour chaque Task: ouvrir le vrai bouton accordéon, attendre contenu, extraire panneau
            tasks = []
            opened = 0

            for i in range(1, max_tasks + 1):
                task_label = f"Task {i}"

                # Le bouton accordéon est souvent un élément cliquable; on tente plusieurs stratégies.
                clicked = False

                # Stratégie A: chercher un bouton/élément avec le texte exact "Task X"
                try:
                    loc = page.get_by_text(task_label, exact=True)
                    if loc.count() > 0:
                        loc.first.click()
                        clicked = True
                except Exception:
                    pass

                # Stratégie B (fallback): chercher un élément contenant "Task X" (si exact rate)
                if not clicked:
                    try:
                        loc = page.get_by_text(re.compile(rf"^{re.escape(task_label)}$"))
                        if loc.count() > 0:
                            loc.first.click()
                            clicked = True
                    except Exception:
                        pass

                if not clicked:
                    # plus de tasks (ou structure différente)
                    break

                opened += 1

                # Attendre que du contenu “task” apparaisse (au moins "Answer the questions below" ou "View Site" ou texte long)
                try:
                    page.wait_for_function(
                        """(n) => {
                            const t = document.body?.innerText || "";
                            // On veut s'assurer qu'on est bien dans une task ouverte
                            // et pas juste la liste.
                            const hasTask = t.includes("Task " + n);
                            const hasBody = t.includes("Answer the questions below") || t.includes("View Site") || t.length > 1500;
                            return hasTask && hasBody;
                        }""",
                        arg=i,
                        timeout=timeout_ms
                    )
                except Exception:
                    # même si ça time-out, on tente l’extraction quand même
                    pass

                if settle_ms:
                    page.wait_for_timeout(settle_ms)

                # EXTRACTION PROPRE: on prend le panneau ouvert le plus “gros” contenant "Task i"
                task_text = page.evaluate(
                    """(taskLabel) => {
                        // On collecte des blocs plausibles (sections/panels/main)
                        const candidates = Array.from(document.querySelectorAll('main, section, article, [role="main"], div'))
                          .filter(el => el && (el.innerText || "").includes(taskLabel));

                        if (!candidates.length) return "";

                        // Choisir le bloc qui a le plus de texte (souvent le panel ouvert)
                        candidates.sort((a,b) => ((b.innerText||"").length - (a.innerText||"").length));
                        return candidates[0].innerText || "";
                    }""",
                    task_label
                ) or ""

                task_text = _clean_text(task_text)

                # Petite extraction du titre de task (souvent la ligne après "Task i")
                task_title = ""
                if task_text:
                    lines = task_text.splitlines()
                    # Cherche la première ligne qui n'est pas "Task i"
                    for ln in lines:
                        if ln.strip() and ln.strip() != task_label:
                            task_title = ln.strip()
                            break

                tasks.append({
                    "task_number": i,
                    "task_label": task_label,
                    "task_title": task_title,
                    "content": task_text
                })

            browser.close()

        # Nettoyage titre/desc minimal
        return {
            "url": url,
            "joined_clicked": joined,
            "tasks_opened": opened,
            "tasks_found": len(tasks),
            "title_guess": title,
            "tasks": tasks
        }

    except PWTimeoutError:
        raise HTTPException(status_code=504, detail="Timeout Playwright (page trop lente ou bloquée).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {type(e).__name__}: {e}")
