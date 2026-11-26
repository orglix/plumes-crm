import { initDuplicateBadge } from "./common.js";

initDuplicateBadge();

const flashMsg = typeof window.FLASH_MSG === "string" ? window.FLASH_MSG : "";
const candidates = Array.isArray(window.CANDIDATES) ? window.CANDIDATES : [];

const flashContainer = document.getElementById("flash-container");
if (flashContainer && flashMsg) {
  const div = document.createElement("div");
  div.className = "flash";
  div.textContent = flashMsg;
  flashContainer.appendChild(div);
}

const titleEl = document.getElementById("candidates-title");
const containerEl = document.getElementById("candidates-container");
if (titleEl) {
  titleEl.textContent = `Doublons suggérés (${candidates.length})`;
}

function makeHiddenForm(action, fields) {
  const form = document.createElement("form");
  form.method = "post";
  form.action = action;
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  return form;
}

function makeContactCol(labelPrefix, contact) {
  const col = document.createElement("div");
  col.className = "contact-col";

  const title = document.createElement("strong");
  const displayName = contact.name || "Sans nom";
  title.textContent = `${labelPrefix} : #${contact.id} — ${displayName}`;
  col.appendChild(title);

  const countP = document.createElement("p");
  countP.textContent = `${contact.message_count} message(s)`;
  col.appendChild(countP);

  const ul = document.createElement("ul");
  for (const ch of contact.channels || []) {
    const li = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = ch.channel;
    li.appendChild(code);
    li.appendChild(document.createTextNode(` : ${ch.identifier}`));
    ul.appendChild(li);
  }
  col.appendChild(ul);

  return col;
}

function contactLabel(contact) {
  const ids = (contact.channels || [])
    .map((ch) => ch.identifier)
    .filter(Boolean);
  if (ids.length > 0) {
    return ids.join(", ");
  }
  return contact.name || `#${contact.id}`;
}

if (containerEl) {
  if (!candidates.length) {
    const p = document.createElement("p");
    p.textContent = "Aucun doublon détecté automatiquement pour le moment.";
    containerEl.appendChild(p);
  } else {
    for (const item of candidates) {
      const card = document.createElement("div");
      card.className = "pair-card";

      const badgesDiv = document.createElement("div");
      for (const reason of item.reasons || []) {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = reason;
        badgesDiv.appendChild(badge);
      }
      card.appendChild(badgesDiv);

      const grid = document.createElement("div");
      grid.className = "grid";
      grid.appendChild(makeContactCol("Fiche A (Maître)", item.master));
      grid.appendChild(makeContactCol("Fiche B (Doublon)", item.duplicate));
      card.appendChild(grid);

      const actions = document.createElement("div");
      actions.className = "actions";

      const labelA = contactLabel(item.master);
      const labelB = contactLabel(item.duplicate);

      const formMergeBA = makeHiddenForm("/duplicates/merge", {
        master_id: item.master.id,
        duplicate_id: item.duplicate.id,
      });
      const btnBA = document.createElement("button");
      btnBA.type = "submit";
      btnBA.className = "btn btn-primary";
      btnBA.textContent = `Fusionner ${labelB} dans ${labelA}`;
      formMergeBA.appendChild(btnBA);
      actions.appendChild(formMergeBA);

      const formMergeAB = makeHiddenForm("/duplicates/merge", {
        master_id: item.duplicate.id,
        duplicate_id: item.master.id,
      });
      const btnAB = document.createElement("button");
      btnAB.type = "submit";
      btnAB.className = "btn btn-secondary";
      btnAB.textContent = `Inverser : Fusionner ${labelA} dans ${labelB}`;
      formMergeAB.appendChild(btnAB);
      actions.appendChild(formMergeAB);

      const formIgnore = makeHiddenForm("/duplicates/ignore", {
        id_a: item.master.id,
        id_b: item.duplicate.id,
      });
      const btnIgnore = document.createElement("button");
      btnIgnore.type = "submit";
      btnIgnore.className = "btn btn-ghost";
      btnIgnore.textContent = "Ignorer (personnes différentes)";
      formIgnore.appendChild(btnIgnore);
      actions.appendChild(formIgnore);

      card.appendChild(actions);
      containerEl.appendChild(card);
    }
  }
}
