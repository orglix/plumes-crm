import asyncio
import logging
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from plumes_crm.assistant import run_chat_turn
import litellm

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
  datefmt="%H:%M:%S",
)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Plumes Créatives — Assistant CRM")

# Stockage simple des historiques par session (en mémoire)
SESSIONS: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
  message: str
  session_id: str | None = None


class ChatResponse(BaseModel):
  reply: str
  session_id: str


HTML_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Plumes Créatives — Assistant CRM</title>
  <style>
    :root { --bg: #f6f7f9; --card: #ffffff; --primary: #2563eb; --text: #1f2937; --muted: #6b7280; --border: #e5e7eb; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); display: flex; flex-direction: column; height: 100vh; }
    header { background: var(--card); border-bottom: 1px solid var(--border); padding: 0.9rem 1.5rem; display: flex; justify-content: space-between; align-items: center; }
    header h1 { font-size: 1.1rem; margin: 0; }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; padding: 0.75rem 1.5rem; background: var(--card); border-bottom: 1px solid var(--border); }
    button.chip { background: #eff6ff; color: var(--primary); border: 1px solid #bfdbfe; border-radius: 999px; padding: 0.35rem 0.85rem; font-size: 0.85rem; cursor: pointer; }
    button.chip:hover { background: #dbeafe; }
    button.reset { background: transparent; border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.75rem; cursor: pointer; color: var(--muted); }
    #messages { flex: 1; overflow-y: auto; padding: 1.25rem 1.5rem; display: flex; flex-direction: column; gap: 1rem; max-width: 900px; width: 100%; margin: 0 auto; }
    .msg { padding: 0.85rem 1.1rem; border-radius: 12px; line-height: 1.5; white-space: pre-wrap; max-width: 82%; }
    .user { align-self: flex-end; background: var(--primary); color: #fff; }
    .bot { align-self: flex-start; background: var(--card); border: 1px solid var(--border); }
    .status { align-self: flex-start; color: var(--muted); font-style: italic; font-size: 0.9rem; }
    form { display: flex; gap: 0.6rem; padding: 1rem 1.5rem; background: var(--card); border-top: 1px solid var(--border); max-width: 900px; width: 100%; margin: 0 auto; }
    input[type="text"] { flex: 1; padding: 0.7rem 0.9rem; border: 1px solid var(--border); border-radius: 8px; font-size: 1rem; }
    button[type="submit"] { background: var(--primary); color: #fff; border: none; border-radius: 8px; padding: 0 1.25rem; font-size: 0.95rem; cursor: pointer; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
  </style>
</head>
<body>
  <header>
    <h1>Plumes Créatives — Assistant CRM</h1>
    <button class="reset" onclick="resetChat()">Nouvelle conversation</button>
  </header>
  <div class="actions">
    <button class="chip" onclick="sendPreset('Quels contacts n\\'ont pas eu d\\'échange depuis plus de 30 jours ?')">Clients à relancer (+30j)</button>
    <button class="chip" onclick="sendPreset('Liste les 10 derniers contacts actifs ou récents')">Derniers contacts</button>
    <button class="chip" onclick="sendPreset('Résume les derniers échanges avec ')">Résumer un contact...</button>
  </div>
  <div id="messages"></div>
  <form id="chat-form">
    <input id="prompt" type="text" placeholder="Pose ta question sur les contacts, échanges ou relances..." autocomplete="off" required />
    <button id="send-btn" type="submit">Envoyer</button>
  </form>
  <script>
    let sessionId = localStorage.getItem("crm_session_id") || "";
    const messagesEl = document.getElementById("messages");
    const form = document.getElementById("chat-form");
    const input = document.getElementById("prompt");
    const sendBtn = document.getElementById("send-btn");

    function appendMessage(text, cls) {
      const div = document.createElement("div");
      div.className = "msg " + cls;
      div.textContent = text;
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return div;
    }

    function sendPreset(text) {
      input.value = text;
      input.focus();
      if (!text.endsWith(" ")) form.requestSubmit();
    }

    async function resetChat() {
      if (sessionId) {
        await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: "", session_id: sessionId }) });
      }
      sessionId = "";
      localStorage.removeItem("crm_session_id");
      messagesEl.innerHTML = "";
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      appendMessage(text, "user");
      const statusEl = appendMessage("Recherche dans le CRM et rédaction en cours...", "status");
      sendBtn.disabled = true;

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, session_id: sessionId || null }),
        });
        const data = await res.json();
        statusEl.remove();
        if (!res.ok) {
          appendMessage("Erreur : " + (data.detail || res.statusText), "bot");
        } else {
          sessionId = data.session_id;
          localStorage.setItem("crm_session_id", sessionId);
          appendMessage(data.reply, "bot");
        }
      } catch (err) {
        statusEl.remove();
        appendMessage("Erreur réseau : " + err.message, "bot");
      } finally {
        sendBtn.disabled = false;
        input.focus();
      }
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
  return HTML_PAGE


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
