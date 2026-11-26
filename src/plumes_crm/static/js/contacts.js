import { escapeHtml, initDuplicateBadge } from "./common.js";

const searchInput = document.getElementById("contact-search");
const contactsListEl = document.getElementById("contacts-list");
const emptyStateEl = document.getElementById("empty-state");
const selectedContactEl = document.getElementById("selected-contact");
const contactNameEl = document.getElementById("contact-name");
const contactEmailEl = document.getElementById("contact-email");
const contactInstagramEl = document.getElementById("contact-instagram");
const toggleBtn = document.getElementById("toggle-summaries-btn");
const summariesContainer = document.getElementById("summaries-container");

let allContacts = [];
let currentContact = null;
let summariesVisible = false;
const summariesCache = new Map();

function normalize(str) {
  return (str || "")
    .toString()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "");
}

function formatSummaryHtml(rawSummary) {
  const lines = (rawSummary || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) return "";

  let html = "";
  let inList = false;

  for (const line of lines) {
    if (line.startsWith("- ")) {
      if (!inList) {
        html += `<ul class="summary-bullets">`;
        inList = true;
      }
      html += `<li>${escapeHtml(line.slice(2))}</li>`;
    } else {
      if (inList) {
        html += `</ul>`;
        inList = false;
      }
      html += `<p class="summary-heading">${escapeHtml(line)}</p>`;
    }
  }

  if (inList) {
    html += `</ul>`;
  }

  return html;
}

function renderContacts(filterQuery = "") {
  if (!contactsListEl) return;

  const q = normalize(filterQuery.trim());
  const filtered = q
    ? allContacts.filter((c) => {
        const haystack = `${c.name || ""} ${c.email || ""} ${c.instagram || ""}`;
        return normalize(haystack).includes(q);
      })
    : allContacts;

  contactsListEl.innerHTML = "";
  if (!filtered.length) {
    contactsListEl.innerHTML = `<li class="contact-item"><small>Aucun contact trouvé</small></li>`;
    return;
  }

  for (const contact of filtered) {
    const li = document.createElement("li");
    li.className = "contact-item" + (currentContact?.id === contact.id ? " active" : "");
    li.innerHTML = `
      <strong>${escapeHtml(contact.name || "Sans nom")}</strong>
      <small>${escapeHtml(contact.email || contact.instagram || "")}</small>
    `;
    li.addEventListener("click", () => selectContact(contact));
    contactsListEl.appendChild(li);
  }
}

async function selectContact(contact) {
  currentContact = contact;
  summariesVisible = false;
  summariesContainer.innerHTML = "";
  if (toggleBtn) toggleBtn.textContent = "Afficher les résumés";

  if (emptyStateEl) emptyStateEl.hidden = true;
  if (selectedContactEl) selectedContactEl.hidden = false;
  if (contactNameEl) contactNameEl.textContent = contact.name || "Sans nom";
  if (contactEmailEl) contactEmailEl.textContent = contact.email || "";
  if (contactInstagramEl) contactInstagramEl.textContent = contact.instagram || "";

  renderContacts(searchInput?.value || "");
}

async function loadAndRenderSummaries(contactId) {
  summariesContainer.innerHTML = `<p>Chargement des résumés...</p>`;

  let items = summariesCache.get(contactId);
  if (!items) {
    try {
      const resp = await fetch(`/api/contacts/${contactId}/summaries`);
      if (!resp.ok) {
        summariesContainer.innerHTML = `<p>Erreur lors du chargement des résumés.</p>`;
        return;
      }
      items = await resp.json();
      summariesCache.set(contactId, items);
    } catch {
      summariesContainer.innerHTML = `<p>Erreur réseau lors du chargement des résumés.</p>`;
      return;
    }
  }

  if (!items.length) {
    summariesContainer.innerHTML = `<p>Aucun résumé de thread enregistré pour ce contact.</p>`;
    return;
  }

  summariesContainer.innerHTML = items
    .map((item) => {
      const badges = (item.categories || [])
        .map((cat) => `<span class="badge">${escapeHtml(cat)}</span>`)
        .join(" ");
      const dateLabel = item.last_message_at
        ? new Date(item.last_message_at).toLocaleString("fr-FR")
        : "Date inconnue";

      return `
        <article class="summary-card">
          <div class="summary-meta">
            <strong>Thread ${escapeHtml(item.thread_key)}</strong>
            <span>• ${item.message_count ?? 0} msg</span>
            <span>• Dernier message : ${escapeHtml(dateLabel)}</span>
            <div>${badges}</div>
          </div>
          <div class="summary-body">${formatSummaryHtml(item.summary)}</div>
        </article>
      `;
    })
    .join("");
}

toggleBtn?.addEventListener("click", async () => {
  if (!currentContact) return;
  summariesVisible = !summariesVisible;
  if (summariesVisible) {
    toggleBtn.textContent = "Masquer les résumés";
    await loadAndRenderSummaries(currentContact.id);
  } else {
    toggleBtn.textContent = "Afficher les résumés";
    summariesContainer.innerHTML = "";
  }
});

searchInput?.addEventListener("input", (e) => {
  renderContacts(e.target.value);
});

async function initContacts() {
  initDuplicateBadge();
  try {
    const resp = await fetch("/api/contacts");
    if (!resp.ok) {
      contactsListEl.innerHTML = `<li class="contact-item"><small>Impossible de charger les contacts</small></li>`;
      return;
    }
    allContacts = await resp.json();
    renderContacts("");
  } catch {
    contactsListEl.innerHTML = `<li class="contact-item"><small>Erreur réseau lors du chargement</small></li>`;
  }
}

initContacts();
