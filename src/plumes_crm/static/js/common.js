export function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function initDuplicateBadge(selector = "#dup-count") {
  const badge = document.querySelector(selector);
  if (!badge) return;
  const count = parseInt(badge.textContent, 10) || 0;
  if (count > 0) {
    badge.classList.add("has-items");
  }
}
