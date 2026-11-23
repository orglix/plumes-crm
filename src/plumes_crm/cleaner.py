import base64
import re
from bs4 import BeautifulSoup
import html2text


def _decode_base64url(data: str) -> str:
  if not data:
    return ""
  padded = data + "=" * (-len(data) % 4)
  try:
    raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw_bytes.decode("utf-8", errors="replace")
  except Exception:
    return ""


def extract_raw_bodies(payload: dict) -> tuple[str, str]:
  """Extrait (text_plain, text_html) depuis un payload Gmail."""
  plain_parts: list[str] = []
  html_parts: list[str] = []

  def _walk(part: dict) -> None:
    mime_type = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data")

    if data:
      decoded = _decode_base64url(data)
      if mime_type == "text/plain":
        plain_parts.append(decoded)
      elif mime_type == "text/html":
        html_parts.append(decoded)

    for child in part.get("parts", []) or []:
      _walk(child)

  if isinstance(payload, dict):
    _walk(payload)

  return "\n".join(plain_parts).strip(), "\n".join(html_parts).strip()


def html_to_clean_text(html_content: str) -> str:
  """Nettoie le HTML avec BeautifulSoup puis le convertit en texte avec html2text."""
  soup = BeautifulSoup(html_content, "html.parser")

  for tag in soup(["script", "style", "head", "meta", "link"]):
    tag.decompose()

  # Retire les éléments explicitement cachés
  for hidden in soup.find_all(
    style=re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
  ):
    hidden.decompose()

  maker = html2text.HTML2Text()
  maker.ignore_links = False
  maker.ignore_images = True
  maker.body_width = 0  # Pas de découpage artificiel à 80 colonnes
  maker.single_line_break = False

  text = maker.handle(str(soup))
  return text


def strip_quoted_replies_and_noise(text: str) -> str:
  """Coupe les citations de réponses précédentes et normalise les espaces."""
  lines = text.splitlines()
  cleaned_lines: list[str] = []

  quote_markers = (
    re.compile(r"^Le\s+.{5,80}\s+a\s+écrit\s*:\s*$", re.I),
    re.compile(r"^On\s+.{5,80}\s+wrote\s*:\s*$", re.I),
    re.compile(r"^-{2,}\s*Message original\s*-{2,}$", re.I),
    re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}$", re.I),
  )

  for line in lines:
    stripped = line.strip()

    # Arrête dès qu'on atteint l'en-tête d'une réponse citée
    if any(pattern.match(stripped) for pattern in quote_markers):
      break

    # Ignore les lignes de citation classiques commençant par '>'
    if stripped.startswith(">"):
      continue

    cleaned_lines.append(line.rstrip())

  result = "\n".join(cleaned_lines)
  # Réduit les suites de plus de 2 lignes vides
  result = re.sub(r"\n{3,}", "\n\n", result)
  return result.strip()


def clean_gmail_payload(raw_payload: dict | str) -> str:
  """Point d'entrée principal : raw_payload Gmail -> texte propre prêt pour l'IA."""
  if not raw_payload:
    return ""

  if isinstance(raw_payload, str):
    import json

    try:
      raw_payload = json.loads(raw_payload)
    except Exception:
      return ""

  payload = raw_payload.get("payload", raw_payload)
  plain_text, html_text = extract_raw_bodies(payload)

  if html_text:
    text = html_to_clean_text(html_text)
  elif plain_text:
    text = plain_text
  else:
    text = raw_payload.get("snippet", "") or ""

  return strip_quoted_replies_and_noise(text)
