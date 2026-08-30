// Scenarios - saved "what-if" bundles. Each adjustment adds a hypothetical
// recurring line or sinking fund, or removes / scales an existing one.
// Recurring/one-off adjustments move the Overview's cash-flow net; fund
// adjustments move its provisioned net. Adjustments are add + delete here;
// editing one = delete and re-add.

const listEl = document.getElementById("list");
const emptyEl = document.getElementById("empty");
const countEl = document.getElementById("count");
const addForm = document.getElementById("add-form");

let PEOPLE = [];
let CATEGORIES = [];
let RECURRING = [];
let FUNDS = [];

// MONTH_OPTIONS comes from common.js (loaded first).
const recurringName = (id) => {
  const r = RECURRING.find((x) => x.id === id);
  return r ? r.name : `item #${id}`;
};
const fundName = (id) => {
  const f = FUNDS.find((x) => x.id === id);
  return f ? f.name : `fund #${id}`;
};

// --- add scenario ---------------------------------------------------

document.getElementById("show-add").addEventListener("click", () => {
  addForm.classList.toggle("hidden");
  if (!addForm.classList.contains("hidden")) document.getElementById("s-name").focus();
});
document.getElementById("cancel-add").addEventListener("click", () => {
  addForm.classList.add("hidden");
  addForm.reset();
});
addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("s-name").value.trim();
  if (!name) return Global.showMessage("Name is required.", "error");
  try {
    await fetchJSON(`${API}/scenarios`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, notes: document.getElementById("s-notes").value.trim() || null }),
    });
    addForm.reset();
    addForm.classList.add("hidden");
    Global.showMessage("Scenario created.", "success");
    load();
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
});

// --- adjustment description --------------------------------------

function describeAdjustment(a) {
  const targetName = a.target_fund_id != null ? `${fundName(a.target_fund_id)} (fund)` : recurringName(a.target_recurring_id);
  if (a.kind === "add") {
    if (a.add_kind === "fund") return `Add fund "${a.name}" — ${fmtMoney(a.amount_cents)}/yr set aside`;
    const bits = [freqLabel(a.frequency || "monthly").toLowerCase(), a.direction === "in" ? "in" : "out"];
    return `Add "${a.name}" — ${fmtMoney(a.amount_cents)} ${bits.join(" ")}`;
  }
  if (a.kind === "remove") return `Remove "${targetName}"`;
  if (a.kind === "modify") {
    if (a.override_amount_cents != null) return `Set "${targetName}" to ${fmtMoney(a.override_amount_cents)}`;
    return `Scale "${targetName}" ×${a.multiplier}`;
  }
  return a.kind;
}

// --- add-adjustment sub-form -----------------------------------

function adjustmentFormHTML() {
  const opt = (v, l) => `<option value="${v}">${l}</option>`;
  return `
    <div class="field">
      <label>Change type</label>
      <select name="kind">
        ${opt("add", "Add a new line")}
        ${opt("remove", "Remove an existing recurring item")}
        ${opt("modify", "Scale / override an existing recurring item")}
      </select>
    </div>

    <div class="fin-adj-group" data-group="add">
      <div class="field-row">
        <div class="field">
          <label>Add a</label>
          <select name="add_kind">${opt("recurring", "Recurring line")}${opt("fund", "Sinking fund")}</select>
        </div>
        <div class="field">
          <label>Name</label>
          <input name="name" type="text" placeholder="e.g. Car payment" />
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label data-label="add_amount">Amount ($)</label>
          <input name="amount" type="text" inputmode="decimal" placeholder="450.00" />
        </div>
        <div class="field fin-adj-recurring-only">
          <label>Direction</label>
          <select name="direction">${opt("out", "Money out")}${opt("in", "Money in")}</select>
        </div>
      </div>
      <div class="field-row fin-adj-recurring-only">
        <div class="field">
          <label>Frequency</label>
          <select name="frequency">
            ${opt("weekly", "Weekly")}${opt("biweekly", "Biweekly")}${opt("monthly", "Monthly")}${opt("quarterly", "Quarterly")}${opt("semiannual", "Semi-annual")}${opt("annual", "Annual")}
          </select>
        </div>
        <div class="field fin-anchor-field">
          <label>First month it hits</label>
          <select name="anchor_month">${MONTH_OPTIONS.map((m) => opt(m.value, m.label)).join("")}</select>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Category</label>
          <select name="category_id"></select>
        </div>
        <div class="field">
          <label>Person</label>
          <select name="person_id"></select>
        </div>
      </div>
    </div>

    <div class="fin-adj-group hidden" data-group="target">
      <div class="field">
        <label>Which item or fund</label>
        <select name="target"></select>
      </div>
    </div>

    <div class="fin-adj-group hidden" data-group="modify">
      <div class="field-row">
        <div class="field">
          <label>How</label>
          <select name="modify_mode">${opt("multiplier", "Multiply by")}${opt("override", "Set to exact amount")}</select>
        </div>
        <div class="field">
          <label data-label="modify_value">Factor (e.g. 0.5)</label>
          <input name="modify_value" type="text" inputmode="decimal" placeholder="0.5" />
        </div>
      </div>
    </div>

    <div class="item-actions">
      <button type="submit" class="save-btn">Add change</button>
      <button type="button" class="cancel-btn" data-act="cancel-adj">Cancel</button>
    </div>`;
}

function wireAdjustmentForm(form, scenarioId) {
  const kind = form.querySelector('[name="kind"]');
  const addKind = form.querySelector('[name="add_kind"]');
  const freq = form.querySelector('[name="frequency"]');
  const anchorField = form.querySelector(".fin-anchor-field");
  const addAmountLabel = form.querySelector('[data-label="add_amount"]');
  const recurringOnly = form.querySelectorAll(".fin-adj-recurring-only");
  const modifyMode = form.querySelector('[name="modify_mode"]');
  const modifyLabel = form.querySelector('[data-label="modify_value"]');
  const groups = form.querySelectorAll(".fin-adj-group");

  fillSelect(form.querySelector('[name="category_id"]'), CATEGORIES.map((c) => ({ value: c.id, label: c.name })), { blankLabel: "— none —" });
  fillSelect(form.querySelector('[name="person_id"]'), PEOPLE.map((p) => ({ value: p.id, label: p.name })), { blankLabel: "Joint" });
  fillSelect(
    form.querySelector('[name="target"]'),
    [
      ...RECURRING.map((r) => ({ value: `r:${r.id}`, label: `${r.name} (${fmtMoney(r.amount_cents)} ${r.direction})` })),
      ...FUNDS.map((f) => ({ value: `f:${f.id}`, label: `${f.name} — fund` })),
    ],
    { blankLabel: "— pick one —" }
  );

  const sync = () => {
    const k = kind.value;
    groups.forEach((g) => {
      const name = g.dataset.group;
      const show = (k === "add" && name === "add") || ((k === "remove" || k === "modify") && name === "target") || (k === "modify" && name === "modify");
      g.classList.toggle("hidden", !show);
    });
    const isFund = addKind.value === "fund";
    recurringOnly.forEach((n) => n.classList.toggle("hidden", isFund));
    addAmountLabel.textContent = isFund ? "Amount ($) per year" : "Amount ($)";
    anchorField.classList.toggle("hidden", isFund || !isSubMonthlyFreq(freq.value));
    modifyLabel.textContent = modifyMode.value === "multiplier" ? "Factor (e.g. 0.5)" : "Amount ($)";
  };
  kind.addEventListener("change", sync);
  addKind.addEventListener("change", sync);
  freq.addEventListener("change", sync);
  modifyMode.addEventListener("change", sync);
  sync();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const g = (n) => form.querySelector(`[name="${n}"]`);
    const k = g("kind").value;
    let body = { kind: k };
    if (k === "add") {
      const isFund = g("add_kind").value === "fund";
      body = {
        kind: "add",
        add_kind: isFund ? "fund" : "recurring",
        name: g("name").value.trim(),
        amount_cents: dollarsToCents(g("amount").value),
        category_id: g("category_id").value || null,
        person_id: g("person_id").value || null,
      };
      if (!isFund) {
        body.direction = g("direction").value;
        body.frequency = g("frequency").value;
        body.anchor_month = isSubMonthlyFreq(g("frequency").value) ? Number(g("anchor_month").value) : null;
      }
      if (!body.name || body.amount_cents == null || body.amount_cents <= 0) {
        return Global.showMessage("A new line needs a name and a positive amount.", "error");
      }
    } else {
      const raw = g("target").value;
      if (!raw) return Global.showMessage("Pick an item or fund.", "error");
      const [prefix, id] = raw.split(":");
      body[prefix === "f" ? "target_fund_id" : "target_recurring_id"] = Number(id);
      if (k === "modify") {
        if (g("modify_mode").value === "multiplier") {
          const mult = Number(g("modify_value").value);
          if (isNaN(mult) || mult < 0) return Global.showMessage("Factor must be a number ≥ 0.", "error");
          body.multiplier = mult;
        } else {
          const cents = dollarsToCents(g("modify_value").value);
          if (cents == null || cents <= 0) return Global.showMessage("Enter a positive amount.", "error");
          body.override_amount_cents = cents;
        }
      }
    }
    try {
      await fetchJSON(`${API}/scenarios/${scenarioId}/adjustments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      Global.showMessage("Change added.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });

  form.querySelector('[data-act="cancel-adj"]').addEventListener("click", () => {
    form.classList.add("hidden");
    form.previousElementSibling?.classList.remove("hidden"); // show the "+ add change" button again
  });
}

// --- scenario card ------------------------------------------------

function card(scenario) {
  const el_ = Global.el;
  const wrap = el_("div", { class: "item-card" });
  const n = scenario.adjustments.length;

  const summary = el_("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el_("span", { class: "item-summary-title", text: scenario.name }),
    el_("span", { class: "item-badge item-badge-muted", text: `${n} change${n === 1 ? "" : "s"}` }),
    el_("a", { class: "item-summary-icon-link", href: `/?scenario=${scenario.id}`, title: "Open in Overview", "data-icon": "calendar", "aria-hidden": "true" }),
    el_("span", { class: "item-chevron", "aria-hidden": "true", text: "▸" }),
  ]);

  const details = el_("div", { class: "item-details hidden" });
  const inner = el_("div", { class: "item-details-inner" });

  // name + notes edit
  const metaForm = el_("form", { class: "fin-edit-form" });
  metaForm.innerHTML = `
    <div class="field">
      <label>Name</label>
      <input name="name" type="text" value="${scenario.name.replace(/"/g, "&quot;")}" />
    </div>
    <div class="field">
      <label>Notes</label>
      <textarea name="notes" rows="2">${scenario.notes ? scenario.notes.replace(/</g, "&lt;") : ""}</textarea>
    </div>
    <div class="item-actions">
      <button type="submit" class="save-btn">Save</button>
      <button type="button" class="danger-btn" data-act="delete">Delete scenario</button>
    </div>`;
  metaForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await fetchJSON(`${API}/scenarios/${scenario.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: metaForm.querySelector('[name="name"]').value.trim(),
          notes: metaForm.querySelector('[name="notes"]').value.trim() || null,
        }),
      });
      Global.showMessage("Saved.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });
  metaForm.querySelector('[data-act="delete"]').addEventListener("click", async () => {
    if (!confirm(`Delete scenario "${scenario.name}"?`)) return;
    try {
      await fetchJSON(`${API}/scenarios/${scenario.id}`, { method: "DELETE" });
      Global.showMessage("Deleted.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });

  // adjustments list
  const adjList = el_("div", { class: "fin-adj-list" });
  if (!n) adjList.appendChild(el_("p", { class: "empty-state", text: "No changes yet." }));
  for (const a of scenario.adjustments) {
    adjList.appendChild(
      el_("div", { class: "fin-adj-row" }, [
        el_("span", { class: "fin-adj-text", text: describeAdjustment(a) }),
        el_("button", {
          type: "button",
          class: "danger-btn",
          text: "Remove",
          onclick: async () => {
            try {
              await fetchJSON(`${API}/adjustments/${a.id}`, { method: "DELETE" });
              load();
            } catch (err) {
              Global.showMessage(err.message, "error");
            }
          },
        }),
      ])
    );
  }

  const addChangeBtn = el_("button", { type: "button", class: "secondary-btn", text: "+ Add change" });
  const adjForm = el_("form", { class: "add-card hidden fin-adj-form" });
  adjForm.innerHTML = adjustmentFormHTML();
  addChangeBtn.addEventListener("click", () => {
    adjForm.classList.remove("hidden");
    addChangeBtn.classList.add("hidden");
  });
  wireAdjustmentForm(adjForm, scenario.id);

  inner.appendChild(metaForm);
  inner.appendChild(el_("h3", { text: "Changes" }));
  inner.appendChild(adjList);
  inner.appendChild(addChangeBtn);
  inner.appendChild(adjForm);
  details.appendChild(inner);
  wrap.appendChild(summary);
  wrap.appendChild(details);

  Global.wireAccordionToggle(wrap, summary, details);
  if (typeof applyIcons === "function") applyIcons(wrap);
  return wrap;
}

// --- load ------------------------------------------------------

async function load() {
  try {
    const [scenarios, recurring, funds] = await Promise.all([
      fetchJSON(`${API}/scenarios`),
      fetchJSON(`${API}/recurring`),
      fetchJSON(`${API}/funds`),
    ]);
    RECURRING = recurring;
    FUNDS = funds;
    listEl.innerHTML = "";
    scenarios.forEach((s) => listEl.appendChild(card(s)));
    emptyEl.classList.toggle("hidden", scenarios.length > 0);
    countEl.textContent = `${scenarios.length} scenario${scenarios.length === 1 ? "" : "s"}`;
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
}

async function init() {
  [PEOPLE, CATEGORIES] = await Promise.all([loadPeople(), loadCategories()]);
  load();
}

init();
