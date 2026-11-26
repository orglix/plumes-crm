import { initDuplicateBadge } from "./common.js";

initDuplicateBadge();

const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const resetBtn = document.getElementById("reset-session-btn");

let sessionId = localStorage.getItem("crm_session_id") || "";

function appendMessage(text, role) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

resetBtn?.addEventListener("click", () => {
  sessionId = "";
  localStorage.removeItem("crm_session_id");
  messagesEl.innerHTML = "";
});

form?.addEventListener("submit", async (e) => {
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
