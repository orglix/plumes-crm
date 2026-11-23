import json
import os, logging, time
import litellm
from plumes_crm.crm_tools import (
  get_contact_messages,
  list_inactive_contacts,
  search_contacts,
)

logger = logging.getLogger("plumes_crm.assistant")

litellm.disable_streaming_logging = True
litellm.turn_off_message_logging = True

DEFAULT_MODEL = os.getenv("CRM_LLM_MODEL", "")
FALLBACK_MODELS = [m.strip() for m in os.getenv("CRM_LLM_FALLBACKS", "").split(",") if m.strip()]

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "")


TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "search_contacts",
      "description": "Recherche des contacts dans le CRM par nom ou adresse e-mail.",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Nom, prénom, entreprise ou e-mail"},
          "limit": {"type": "integer", "description": "Nombre max de résultats", "default": 10},
        },
        "required": ["query"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "get_contact_messages",
      "description": "Récupère les messages nettoyés récents d'un contact à partir de son id.",
      "parameters": {
        "type": "object",
        "properties": {
          "contact_id": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Identifiants numériques du contact",
          },
          "limit": {"type": "integer", "description": "Nombre max de messages", "default": 15},
        },
        "required": ["contact_id"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "list_inactive_contacts",
      "description": "Liste les contacts sans échange récent depuis au moins min_days jours.",
      "parameters": {
        "type": "object",
        "properties": {
          "min_days": {
            "type": "integer",
            "description": "Nombre minimum de jours d'inactivité",
            "default": 14,
          },
          "limit": {"type": "integer", "description": "Nombre max de contacts", "default": 20},
        },
        "required": [],
      },
    },
  },
]

TOOL_REGISTRY = {
  "search_contacts": search_contacts,
  "get_contact_messages": get_contact_messages,
  "list_inactive_contacts": list_inactive_contacts,
}


async def run_chat_turn(
  history: list[dict],
  user_message: str,
  model: str | None = None,
  max_tool_steps: int = 5,
) -> tuple[str, list[dict]]:
  """Exécute un tour de chat complet (avec appels d'outils éventuels) et retourne (réponse, historique mis à jour)."""
  active_model = model or DEFAULT_MODEL
  messages = list(history)

  if not messages or messages[0].get("role") != "system":
    messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

  messages.append({"role": "user", "content": user_message})

  for step in range(1, max_tool_steps + 1):
    t0 = time.perf_counter()
    logger.info(
      "Étape %d/%d — appel LLM (%s, %d messages)...",
      step,
      max_tool_steps,
      active_model,
      len(messages),
    )
    response = await litellm.acompletion(
      model=active_model,
      fallbacks=FALLBACK_MODELS,
      messages=messages,
      tools=TOOLS,
      tool_choice="auto",
      #      reasoning_efforts="none",
      timeout=30,
      num_retries=1,
    )
    logger.info("Réponse LLM reçue en %.2fs", time.perf_counter() - t0)
    msg = response.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []

    # Ajoute le message de l'assistant (avec ou sans tool_calls) à l'historique
    assistant_entry: dict = {
      "role": "assistant",
      "content": msg.content or "",
    }
    if tool_calls:
      assistant_entry["tool_calls"] = [
        {
          "id": tc.id,
          "type": "function",
          "function": {
            "name": tc.function.name,
            "arguments": tc.function.arguments,
          },
        }
        for tc in tool_calls
      ]
    messages.append(assistant_entry)

    # Si le modèle n'appelle plus d'outil, on a notre réponse finale
    if not tool_calls:
      return (msg.content or "").strip(), messages

    # Sinon, on exécute chaque outil demandé et on renvoie son résultat
    for tc in tool_calls:
      fn_name = tc.function.name
      raw_args = tc.function.arguments or "{}"
      try:
        args = json.loads(raw_args)
      except json.JSONDecodeError:
        args = {}

      fn = TOOL_REGISTRY.get(fn_name)
      t_tool = time.perf_counter()
      logger.info("Exécution outil %s(%s)...", fn_name, args)
      if fn is None:
        tool_result = json.dumps({"error": f"Outil inconnu : {fn_name}"})
      else:
        try:
          tool_result = fn(**args)
        except Exception as exc:
          tool_result = json.dumps({"error": str(exc)}, ensure_ascii=False)
      logger.info(
        "Outil %s terminé en %.3fs (%d chars retournés)",
        fn_name,
        time.perf_counter() - t_tool,
        len(tool_result),
      )
      messages.append(
        {
          "role": "tool",
          "tool_call_id": tc.id,
          "name": fn_name,
          "content": tool_result,
        }
      )

  return "Limite d'appels d'outils atteinte sans réponse finale.", messages
