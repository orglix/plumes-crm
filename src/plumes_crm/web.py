import asyncio
import logging
import uuid
from pydantic import BaseModel
from plumes_crm.assistant import run_chat_turn
import litellm
from fastapi import Form, Request, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from plumes_crm.merge_service import (
    find_duplicate_candidates,
    ignore_duplicate_pair,
    merge_contacts,
)
import json
import html

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
  datefmt="%H:%M:%S",
)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from pathlib import Path
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Plumes Créatives — Assistant CRM")


STATIC_DIR = Path(__file__).resolve().parent / "static"

# Si tu as aussi des assets (CSS/JS/images) dans static :
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Stockage simple des historiques par session (en mémoire)
SESSIONS: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
  message: str
  session_id: str | None = None


class ChatResponse(BaseModel):
  reply: str
  session_id: str


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
  candidates = find_duplicate_candidates(limit=30)
  index_file = STATIC_DIR / "index.html"
  content = index_file.read_text(encoding="utf-8").replace(
      "__DUPLICATE_COUNT__", str(len(candidates))
  )
  return HTMLResponse(content=content)

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
  session_id = req.session_id or str(uuid.uuid4())
  history = SESSIONS.setdefault(session_id, [])
  try:
    reply, updated_history = await run_chat_turn(history, req.message)
  except (litellm.ServiceUnavailableError, litellm.Timeout, Exception) as exc:
    raise HTTPException(
      status_code=503,
      detail="Les modèles Gemini sont temporairement surchargés (503). Réessaie dans quelques secondes.",
    ) from exc

  SESSIONS[session_id] = updated_history
  return ChatResponse(reply=reply, session_id=session_id)


@app.post("/api/reset")
async def reset(req: ChatRequest) -> dict[str, str]:
  if req.session_id and req.session_id in SESSIONS:
    del SESSIONS[req.session_id]
  return {"status": "ok"}


@app.get("/duplicates", response_class=HTMLResponse)
async def duplicates_page(msg: str | None = None):
  candidates = find_duplicate_candidates(limit=30)
  template_path = STATIC_DIR / "duplicates.html"
  raw_html = template_path.read_text(encoding="utf-8")

  safe_msg = (
      html.escape(msg or "", quote=True)
      .replace("\\", "\\\\")
      .replace("\n", " ")
  )
  payload = json.dumps(candidates, default=str, ensure_ascii=False).replace(
      "</", "<\\/"
  )

  rendered = raw_html.replace("__FLASH_MSG__", safe_msg).replace(
      "__CANDIDATES_JSON__", payload
  )
  return HTMLResponse(content=rendered)


@app.post("/duplicates/merge")
async def handle_merge(
    master_id: int = Form(...),
    duplicate_id: int = Form(...),
):
  try:
    merge_contacts(master_id=master_id, duplicate_id=duplicate_id)
  except ValueError as exc:
    msg = urllib.parse.quote(str(exc))
    return RedirectResponse(url=f"/duplicates?msg={msg}", status_code=303)

  return RedirectResponse(
      url=f"/duplicates?msg=Contact+%23{duplicate_id}+fusionn%C3%A9+dans+%23{master_id}",
      status_code=303,
  )

@app.post("/duplicates/ignore")
async def handle_ignore(
    id_a: int = Form(...),
    id_b: int = Form(...),
):
  ignore_duplicate_pair(id_a, id_b)
  return RedirectResponse(
      url="/duplicates?msg=Paire+ignor%C3%A9e",
      status_code=303,
  )
