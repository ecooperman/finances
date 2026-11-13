// Scenarios - saved "what-if" bundles. Each adjustment adds a hypothetical
// recurring line, one-time payment (on a date) or sinking fund, or removes /
// scales an existing recurring item, fund or real one-off transaction.
// Recurring and one-time adjustments move the Overview's cash-flow net; fund
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
let TRANSACTIONS = []; // recent + upcoming one-offs, for the remove/modify picker

// MONTH_OPTIONS comes from common.js (loaded first).
const recurringName = (id) => {
  const r = RECURRING.find((x) => x.id === id);
  return r ? r.name : `item #${id}`;
};
const transactionName = (a) => {
  const t = a.target_transaction || TRANSACTIONS.find((x) => x.id === a.target_transaction_id);
  return t ? `${t.description} (${t.date})` : `one-time #${a.target_transaction_id}`;
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
  const targetName =
    a.target_fund_id != null ? `${fundName(a.target_fund_id)} (fund)`
    : a.target_transaction_id != null ? transactionName(a)
    : recurringName(a.target_recurring_id);
  if (a.kind === "add") {
    if (a.add_kind === "fund") return `Add fund "${a.name}" — ${fmtMoney(a.amount_cents)}/yr set aside`;
    if (a.add_kind === "one_time") {
      return `Add one-time "${a.name}" — ${fmtMoney(a.amount_cents)} ${a.direction === "in" ? "in" : "out"} on ${a.date}`;
    }
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
        ${opt("remove", "Remove an existing item or one-time payment")}
        ${opt("modify", "Scale / override an existing item or one-time payment")}
      </select>
    </div>

    <div class="fin-adj-group" data-group="add">
      <div class="field-row">
        <div class="field">
          <label>Add a</label>
          <select name="add_kind">${opt("recurring", "Recurring line")}${opt("one_time", "One-time payment")}${opt("fund", "Sinking fund")}</select>
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
      <div class="field-row fin-adj-onetime-only hidden">
        <div class="field">
          <label>Date</label>
          <input name="date" type="date" />
        </div>
      </div>
      <div class="field-row fin-adj-freq-only">
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
        <label>Which item, fund or one-time payment</label>
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

    <div class="field">
      <label>Notes</label>
      <textarea name="notes" rows="2" placeholder="Optional - e.g. quote from the moving company, link, where it came from"></textarea>
    </div>

    <div class="item-actions">
      <button type="submit" class="save-btn">Add change</button>
      <button type="button" class="cancel-btn" data-act="cancel-adj">Cancel</button>
    </div>`;
}

function wireAdjustmentForm(form, scenarioId, existing = null, onDone = null) {
  const kind = form.querySelector('[name="kind"]');
  const addKind = form.querySelector('[name="add_kind"]');
  const freq = form.querySelector('[name="frequency"]');
  const anchorField = form.querySelector(".fin-anchor-field");
  const addAmountLabel = form.querySelector('[data-label="add_amount"]');
  const recurringOnly = form.querySelectorAll(".fin-adj-recurring-only"); // hidden for a fund
  const freqOnly = form.querySelector(".fin-adj-freq-only"); // hidden for a fund / one-time
  const oneTimeOnly = form.querySelector(".fin-adj-onetime-only");
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
      ...TRANSACTIONS.map((t) => ({
        value: `t:${t.id}`,
        label: `${t.date} · ${t.description} (${fmtMoney(t.amount_cents)} ${t.direction}) — one-time`,
      })),
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
    const isOneTime = addKind.value === "one_time";
    recurringOnly.forEach((n) => n.classList.toggle("hidden", isFund));
    freqOnly.classList.toggle("hidden", isFund || isOneTime);
    oneTimeOnly.classList.toggle("hidden", !isOneTime);
    addAmountLabel.textContent = isFund ? "Amount ($) per year" : "Amount ($)";
    anchorField.classList.toggle("hidden", isFund || isOneTime || !isSubMonthlyFreq(freq.value));
    modifyLabel.textContent = modifyMode.value === "multiplier" ? "Factor (e.g. 0.5)" : "Amount ($)";
  };
  kind.addEventListener("change", sync);
  addKind.addEventListener("change", sync);
  freq.addEventListener("change", sync);
  modifyMode.addEventListener("change", sync);
  sync();

  // Editing: start from the line as it is now. The same form builds either an
  // add (POST) or, with `existing`, a full replace of that line (PATCH).
  if (existing) {
    const field = (n) => form.querySelector(`[name="${n}"]`);
    const set = (n, v) => {
      if (v !== null && v !== undefined) field(n).value = String(v);
    };
    set("kind", existing.kind);
    set("notes", existing.notes);
    if (existing.kind === "add") {
      set("add_kind", existing.add_kind || "recurring");
      set("name", existing.name);
      set("amount", existing.amount_cents != null ? centsToInputValue(existing.amount_cents) : "");
      set("direction", existing.direction || "out");
      set("date", existing.date);
      set("frequency", existing.frequency);
      set("anchor_month", existing.anchor_month);
      set("category_id", existing.category_id ?? "");
      set("person_id", existing.person_id ?? "");
    } else {
      const target =
        existing.target_fund_id != null ? `f:${existing.target_fund_id}`
        : existing.target_transaction_id != null ? `t:${existing.target_transaction_id}`
        : `r:${existing.target_recurring_id}`;
      const select = field("target");
      // A one-off older than the list offers (or a deleted target) is still this line's target.
      if (![...select.options].some((o) => o.value === target)) select.appendChild(new Option(describeAdjustment(existing), target));
      select.value = target;
      if (existing.kind === "modify") {
        if (existing.override_amount_cents != null) {
          set("modify_mode", "override");
          set("modify_value", centsToInputValue(existing.override_amount_cents));
        } else {
          set("modify_mode", "multiplier");
          set("modify_value", existing.multiplier);
        }
      }
    }
    sync();
    form.querySelector(".save-btn").textContent = "Save change";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const g = (n) => form.querySelector(`[name="${n}"]`);
    const k = g("kind").value;
    const notes = g("notes").value.trim() || null;
    let body = { kind: k };
    if (k === "add") {
      const addKindValue = g("add_kind").value;
      const isFund = addKindValue === "fund";
      const isOneTime = addKindValue === "one_time";
      body = {
        kind: "add",
        add_kind: addKindValue,
        name: g("name").value.trim(),
        amount_cents: dollarsToCents(g("amount").value),
        category_id: g("category_id").value || null,
        person_id: g("person_id").value || null,
      };
      if (!isFund) body.direction = g("direction").value;
      if (isOneTime) {
        body.date = g("date").value;
        if (!body.date) return Global.showMessage("A one-time payment needs a date.", "error");
      } else if (!isFund) {
        body.frequency = g("frequency").value;
        body.anchor_month = isSubMonthlyFreq(g("frequency").value) ? Number(g("anchor_month").value) : null;
      }
      if (!body.name || body.amount_cents == null || body.amount_cents <= 0) {
        return Global.showMessage("A new line needs a name and a positive amount.", "error");
      }
    } else {
      const raw = g("target").value;
      if (!raw) return Global.showMessage("Pick an item, fund or one-time payment.", "error");
      const [prefix, id] = raw.split(":");
      const targetField = { f: "target_fund_id", t: "target_transaction_id", r: "target_recurring_id" }[prefix];
      body[targetField] = Number(id);
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
    body.notes = notes;
    try {
      await fetchJSON(existing ? `${API}/adjustments/${existing.id}` : `${API}/scenarios/${scenarioId}/adjustments`, {
        method: existing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      Global.showMessage(existing ? "Change saved." : "Change added.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });

  form.querySelector('[data-act="cancel-adj"]').addEventListener("click", () => {
    if (onDone) return onDone(); // editing: put the line back
    form.classList.add("hidden");
    form.previousElementSibling?.classList.remove("hidden"); // show the "+ add change" button again
  });
}

// --- order of a scenario's lines ---------------------------------------

// How the changes are listed. Remembered on this device; the default is by date.
const ORDER_CHOICES = [
  ["date", "Date"],
  ["amount", "Amount (largest first)"],
  ["name", "Name"],
  ["added", "Order added"],
];

function savedOrder() {
  try {
    const v = localStorage.getItem("fin.scenarioOrder");
    return ORDER_CHOICES.some(([k]) => k === v) ? v : "date";
  } catch (err) {
    return "date";
  }
}

function saveOrder(v) {
  try {
    localStorage.setItem("fin.scenarioOrder", v);
  } catch (err) {
    // blocked storage just forgets the choice
  }
}

// By date: lines with a date (one-time payments) first, soonest first; the
// rest (recurring lines, funds, edits to real rows) follow in the order added.
function orderAdjustments(list, mode) {
  const money = (a) => a.amount_cents ?? a.override_amount_cents ?? 0;
  const label = (a) => (a.name || describeAdjustment(a)).toLowerCase();
  const byAdded = (a, b) => a.id - b.id;
  const sorted = list.slice();
  if (mode === "added") return sorted.sort(byAdded);
  if (mode === "name") return sorted.sort((a, b) => label(a).localeCompare(label(b)) || byAdded(a, b));
  if (mode === "amount") return sorted.sort((a, b) => money(b) - money(a) || byAdded(a, b));
  return sorted.sort((a, b) => {
    const da = a.add_kind === "one_time" ? a.date : null;
    const db = b.add_kind === "one_time" ? b.date : null;
    if (da && db) return da < db ? -1 : da > db ? 1 : byAdded(a, b);
    if (da) return -1;
    if (db) return 1;
    return byAdded(a, b);
  });
}

// --- one-time total --------------------------------------------------

// What the scenario's one-time lines add up to, overall and month by month
// (the server works it out: see schemas.OneTimeSummary).
function oneTimeSummary(oneTime) {
  const el_ = Global.el;
  const parts = [`${oneTime.count} one-time line${oneTime.count === 1 ? "" : "s"}`];
  if (oneTime.in_cents) parts.push(`${fmtMoney(oneTime.out_cents)} out, ${fmtMoney(oneTime.in_cents)} in`);
  const box = el_("div", { class: "fin-adj-total" }, [
    el_("div", { class: "fin-adj-total-head" }, [
      el_("span", { class: "fin-adj-total-label", text: "Total cost" }),
      el_("span", { class: "fin-adj-total-amount", text: fmtMoney(oneTime.cost_cents) }),
    ]),
    el_("div", { class: "fin-adj-total-sub", text: parts.join(" · ") }),
  ]);
  if (oneTime.by_month.length > 1) {
    box.appendChild(
      el_("div", { class: "fin-adj-total-months" }, oneTime.by_month.map((m) =>
        el_("span", { class: "fin-adj-total-month", text: `${monthLabel(m.month)}: ${fmtMoney(m.out_cents - m.in_cents)}` })
      ))
    );
  }
  return box;
}

// --- scenario card ------------------------------------------------

function card(scenario) {
  const el_ = Global.el;
  const wrap = el_("div", { class: "item-card" });
  wrap.dataset.id = scenario.id;
  const n = scenario.adjustments.length;
  const oneTime = scenario.one_time;

  const summary = el_("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el_("span", { class: "item-summary-title", text: scenario.name }),
    el_("span", { class: "item-badge item-badge-muted", text: `${n} change${n === 1 ? "" : "s"}` }),
    // The one-time lines' total, visible without opening the card.
    oneTime.count ? el_("span", { class: "item-badge item-badge-accent", title: "What the one-time lines add up to", text: `${fmtMoney(oneTime.cost_cents)} one-time` }) : null,
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

  // adjustments list: ordered as chosen (by date unless changed), each line
  // with Edit (swaps the line for the form, filled in) and Remove.
  const adjList = el_("div", { class: "fin-adj-list" });
  function renderAdjList() {
    adjList.replaceChildren();
    if (!n) adjList.appendChild(el_("p", { class: "empty-state", text: "No changes yet." }));
    for (const a of orderAdjustments(scenario.adjustments, savedOrder())) {
      const row = el_("div", { class: "fin-adj-row" }, [
        el_("div", { class: "fin-adj-body" }, [
          el_("span", { class: "fin-adj-text", text: describeAdjustment(a) }),
          a.notes ? el_("span", { class: "fin-adj-note", text: a.notes }) : null,
        ]),
        el_("div", { class: "fin-adj-actions" }, [
          el_("button", {
            type: "button",
            class: "secondary-btn",
            text: "Edit",
            onclick: () => {
              const form = el_("form", { class: "add-card fin-adj-form" });
              form.innerHTML = adjustmentFormHTML();
              wireAdjustmentForm(form, scenario.id, a, () => form.replaceWith(row));
              row.replaceWith(form);
              form.querySelector("input, select")?.focus();
            },
          }),
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
        ]),
      ]);
      adjList.appendChild(row);
    }
    if (typeof applyIcons === "function") applyIcons(adjList);
  }
  renderAdjList();

  const orderSelect = el_("select", { "aria-label": "Order the changes by" }, ORDER_CHOICES.map(([value, text]) => el_("option", { value, text })));
  orderSelect.value = savedOrder();
  orderSelect.addEventListener("change", () => {
    saveOrder(orderSelect.value);
    renderAdjList();
  });
  const changesHead = el_("div", { class: "fin-adj-head" }, [
    el_("h3", { text: "Changes" }),
    n > 1 ? el_("label", { class: "fin-adj-order" }, [el_("span", { text: "Order by" }), orderSelect]) : null,
  ]);

  const addChangeBtn = el_("button", { type: "button", class: "secondary-btn", text: "+ Add change" });
  const adjForm = el_("form", { class: "add-card hidden fin-adj-form" });
  adjForm.innerHTML = adjustmentFormHTML();
  addChangeBtn.addEventListener("click", () => {
    adjForm.classList.remove("hidden");
    addChangeBtn.classList.add("hidden");
  });
  wireAdjustmentForm(adjForm, scenario.id);

  inner.appendChild(metaForm);
  inner.appendChild(changesHead);
  if (oneTime.count) inner.appendChild(oneTimeSummary(oneTime));
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
    // one-offs from the last 6 months on (a scenario about something older is rare)
    const since = new Date();
    since.setDate(since.getDate() - 180);
    const sinceISO = `${since.getFullYear()}-${String(since.getMonth() + 1).padStart(2, "0")}-${String(since.getDate()).padStart(2, "0")}`;
    const [scenarios, recurring, funds, transactions] = await Promise.all([
      fetchJSON(`${API}/scenarios`),
      fetchJSON(`${API}/recurring`),
      fetchJSON(`${API}/funds`),
      fetchJSON(`${API}/transactions?date_from=${sinceISO}`),
    ]);
    RECURRING = recurring;
    FUNDS = funds;
    TRANSACTIONS = transactions.sort((a, b) => (a.date < b.date ? 1 : -1)); // newest first
    // Saving, adding or removing a line reloads the list: keep the cards that were open open.
    const wasOpen = new Set([...listEl.querySelectorAll(".item-card.expanded")].map((c) => c.dataset.id));
    listEl.innerHTML = "";
    scenarios.forEach((s) => {
      const c = card(s);
      listEl.appendChild(c);
      if (wasOpen.has(String(s.id))) c.querySelector(".item-summary").click();
    });
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
