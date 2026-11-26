import argparse
import json
import logging
import sys

from plumes_crm.crm_tools import get_contact_messages
from plumes_crm.summaries import generate_thread_summaries, complete_summary_prompt

logger = logging.getLogger(__name__)


def _fetch_messages_for_contact(contact_id: int, limit: int | None = None) -> list[dict]:
  effective_limit = limit if limit is not None else 10000
  raw_json = get_contact_messages(
    contact_id=contact_id,
    limit=effective_limit,
    max_chars=0,
  )
  data = json.loads(raw_json)
  return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(
    description="Génère les résumés et catégories par thread de contact."
  )
  parser.add_argument(
    "--contact-id",
    type=int,
    action="append",
    dest="contact_ids",
    help="ID d'un contact précis à traiter (répétable : --contact-id 12 --contact-id 34).",
  )
  parser.add_argument(
    "--limit-messages",
    type=int,
    default=None,
    help="Limite optionnelle du nombre de messages lus par contact.",
  )
  parser.add_argument(
    "--force",
    action="store_true",
    help="Régénère même si l'empreinte des messages du thread n'a pas changé.",
  )
  parser.add_argument(
    "--verbose",
    action="store_true",
    help="Active les logs en mode DEBUG.",
  )
  parser.add_argument(
    "--delay",
    type=float,
    default=2.0,
    help="Pause minimale en secondes entre deux appels LLM (défaut: 2.0).",
  )
  args = parser.parse_args(argv)

  logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
  )
  for noisy_logger in ("LiteLLM", "litellm", "httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

  # À brancher sur ta fonction litellm dédiée sans TOOLS :
  stats = generate_thread_summaries(
    complete_llm=complete_summary_prompt,
    fetch_messages=_fetch_messages_for_contact,
    contact_ids=args.contact_ids,
    messages_limit_per_contact=args.limit_messages,
    min_interval_sec=args.delay,
    force=args.force,
  )
  logger.info(
    "Bilan résumés : contacts=%d | threads_vus=%d | mis_a_jour=%d | ignores_inchanges=%d | echecs=%d",
    stats.contacts_processed,
    stats.threads_found,
    stats.threads_updated,
    stats.threads_skipped_unchanged,
    stats.threads_failed,
  )
  if stats.threads_failed > 0:
    logger.warning(
      "%d thread(s) non résumés resteront éligibles au prochain passage.",
      stats.threads_failed,
    )


if __name__ == "__main__":
  sys.exit(main())
