// Budget - the single place to add and manage every money event:
// recurring rules, one-off transactions, and sinking funds (money set
// aside monthly for costs you know are coming but can't schedule). The
// segmented control picks which of the first two you're looking at; the
// Funds section is always shown. The "+ Add" form (common.js) has a
// One-time / Recurring / Fund toggle. Footer shows the provisioning
// baseline: recurring smoothed to /month, plus fund set-asides.

const segEl = document.getElementById("view-seg");
const personSelect = document.getElementById("filter-person");
const categoryMount = document.getElementById("filter-category");
const activeSelect = document.getElementById("filter-active");
const statusFilter = document.getElementById("status-filter");
const monthFilter = document.getElementById("month-filter");
const monthInput = document.getElementById("filter-month");
const allTimeBtn = document.getElementById("filter-alltime");
const addForm = document.getElementById("add-form");

const secRecurring = document.getElementById("sec-recurring");
const secOnetime = document.getElementById("sec-onetime");
const recurringList = document.getElementById("recurring-list");
const onetimeList = document.getElementById("onetime-list");
const recurringEmpty = document.getElementById("recurring-empty");
const onetimeEmpty = document.getElementById("onetime-empty");
const recurringCount = document.getElementById("recurring-count");
const onetimeSub = document.getElementById("onetime-sub");
const fundsList = document.getElementById("funds-list");
const fundsEmpty = document.getElementById("funds-empty");
const fundsCount = document.getElementById("funds-count");
const tripsList = document.getElementById("trips-list");
const tripsEmpty = document.getElementById("trips-empty");
const tripsCount = document.getElementById("trips-count");
const baselineEl = document.getElementById("baseline");

const state = {
  view: "all", // all | recurring | onetime
  personVal: "",
  categoryIds: [],
  status: "active", // active | all | inactive
  month: thisMonth(),
  allTime: false,
};

let PEOPLE = [];
let CATEGORIES = [];
let FUNDS = [];

// --- shared helpers ---------------------------------------------------

function populateSelects(scope, item) {
  const cat = scope.querySelector('[name="category_id"]');
  const per = scope.querySelector('[name="person_id"]');
  fillSelect(cat, CATEGORIES.map((c) => ({ value: c.id, label: c.name })), { blankLabel: "— none —" });
  fillSelect(per, PEOPLE.map((p) => ({ value: p.id, label: p.name })), { blankLabel: "Joint" });
  const fundSel = scope.querySelector('[name="fund_id"]');
  if (fundSel) fillSelect(fundSel, FUNDS.map((f) => ({ value: f.id, label: f.name })), { blankLabel: "— none —" });
  if (item) {
    cat.value = item.category_id || "";
    per.value = item.person_id || "";
    if (fundSel) fundSel.value = item.fund_id || "";
  }
}

function wireAnchor(scope) {
  const freq = scope.querySelector('[name="frequency"]');
  const anchorField = scope.querySelector(".fin-anchor-field");
  if (!freq || !anchorField) return;
  const sync = () => anchorField.classList.toggle("hidden", !isSubMonthlyFreq(freq.value));
  freq.addEventListener("change", sync);
  sync();
}

function passesClientFilters(row) {
  if (state.personVal === "joint" && row.person_id != null) return false;
  if (state.categoryIds.length) {
    const set = new Set(state.categoryIds.map(String));
    if (!set.has(String(row.category_id))) return false;
  }
  return true;
}

// --- add form (unified) --------------------------------------------

function buildAddForm() {
  addForm.innerHTML =
    entryAddFieldsHTML() +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Add</button>
       <button type="button" id="cancel-add" class="cancel-btn">Cancel</button>
     </div>`;
  wireEntryForm(addForm, PEOPLE, CATEGORIES, FUNDS);
  addForm.querySelector("#cancel-add").addEventListener("click", () => {
    addForm.classList.add("hidden");
    buildAddForm();
  });
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const entry = readEntryForm(addForm);
  const err = entryValidationError(entry);
  if (err) return Global.showMessage(err, "error");
  try {
    await submitEntry(entry);
    addForm.classList.add("hidden");
    buildAddForm();
    Global.showMessage(ENTRY_ADDED_MESSAGE[entry.type], "success");
    load();
  } catch (err2) {
    Global.showMessage(err2.message, "error");
  }
});

document.getElementById("show-add").addEventListener("click", () => {
  addForm.classList.toggle("hidden");
  if (!addForm.classList.contains("hidden")) addForm.querySelector('[name="name"]').focus();
});

// --- recurring edit card ------------------------------------------

function recurringEditHTML(it) {
  const opt = (v, l, cur) => `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${l}</option>`;
  return `
    <div class="field">
      <label>Name <span class="required">*</span></label>
      <input name="name" type="text" required value="${escAttr(it.name)}" />
    </div>
    <div class="field-row">
      <div class="field">
        <label>Amount ($) <span class="required">*</span></label>
        <input name="amount" type="text" inputmode="decimal" required value="${centsToInputValue(it.amount_cents)}" />
      </div>
      <div class="field">
        <label>Direction</label>
        <select name="direction">${opt("out", "Money out", it.direction)}${opt("in", "Money in", it.direction)}</select>
      </div>
    </div>
    ${recurringScheduleBlockHTML(it)}
    <div class="field-row">
      <div class="field"><label>Category</label><select name="category_id"></select></div>
      <div class="field"><label>Person</label><select name="person_id"></select></div>
    </div>
    <label class="checkbox-label"><input name="active" type="checkbox"${it.active ? " checked" : ""} /> Active</label>
    <div class="field"><label>Notes</label><textarea name="notes" rows="2">${escText(it.notes)}</textarea></div>`;
}

function readRecurring(scope) {
  const g = (n) => scope.querySelector(`[name="${n}"]`);
  const freq = g("frequency").value;
  return {
    name: g("name").value.trim(),
    amount_cents: dollarsToCents(g("amount").value),
    direction: g("direction").value,
    frequency: freq,
    anchor_month: isSubMonthlyFreq(freq) ? Number(g("anchor_month").value) : null,
    day_of_month: g("day_of_month").value ? Number(g("day_of_month").value) : null,
    category_id: g("category_id").value || null,
    person_id: g("person_id").value || null,
    start_month: g("start_month").value || null,
    end_month: g("end_month").value || null,
    reference_id: g("reference_id").value.trim() || null,
    active: g("active").checked,
    notes: g("notes").value.trim() || null,
  };
}

function recurringCard(item) {
  const wrap = el("div", { class: "item-card" + (item.active ? "" : " archived") });
  const summary = el("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el("span", { class: "fin-item-icon", "data-icon": "repeat", "aria-hidden": "true" }),
    el("span", { class: "item-summary-title", text: item.name }),
    item.frequency !== "monthly" ? el("span", { class: "fin-cadence", text: freqLabel(item.frequency) }) : null,
    !item.active ? el("span", { class: "fin-tag fin-tag-removed", text: "paused" }) : null,
    el("span", { class: "fin-item-amount fin-amount-" + item.direction, text: fmtMoney(item.amount_cents) }),
    el("span", { class: "item-chevron", "aria-hidden": "true", text: "▸" }),
  ]);
  const meta = el("div", { class: "fin-card-meta" }, [
    categoryChip(item.category),
    personBadge(item.person),
    item.reference_id ? el("span", { class: "item-badge item-badge-muted", text: `Ref ${item.reference_id}` }) : null,
  ]);

  const details = el("div", { class: "item-details hidden" });
  const inner = el("div", { class: "item-details-inner" });
  const form = el("form", { class: "fin-edit-form" });
  form.innerHTML =
    recurringEditHTML(item) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Save changes</button>
       <button type="button" class="secondary-btn" data-act="to-onetime">Convert to one-time</button>
       <button type="button" class="danger-btn" data-act="delete">Delete</button>
     </div>`;
  inner.appendChild(meta);
  inner.appendChild(form);
  details.appendChild(inner);
  wrap.appendChild(summary);
  wrap.appendChild(details);

  populateSelects(form, item);
  wireAnchor(form);
  Global.wireAccordionToggle(wrap, summary, details);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = readRecurring(form);
    if (!body.name) return Global.showMessage("Name is required.", "error");
    if (body.amount_cents == null || body.amount_cents <= 0) return Global.showMessage("Enter a dollar amount greater than zero.", "error");
    try {
      await fetchJSON(`${API}/recurring/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      Global.showMessage("Saved.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });
  form.querySelector('[data-act="delete"]').addEventListener("click", async () => {
    if (!confirm(`Delete "${item.name}"?`)) return;
    try {
      await fetchJSON(`${API}/recurring/${item.id}`, { method: "DELETE" });
      Global.showMessage(`Deleted "${item.name}".`, "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });
  form.querySelector('[data-act="to-onetime"]').addEventListener("click", async () => {
    const today = new Date().toISOString().slice(0, 10);
    if (!confirm(`Turn "${item.name}" into a single one-time transaction dated ${today}? (You can change the date afterward.)`)) return;
    try {
      await fetchJSON(`${API}/recurring/${item.id}/convert-to-transaction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: today }),
      });
      Global.showMessage(`"${item.name}" is now a one-time transaction on ${today}.`, "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });

  if (typeof applyIcons === "function") applyIcons(wrap);
  return wrap;
}

// --- one-time (transaction) edit card ---------------------------

function txnEditHTML(t) {
  const opt = (v, l, cur) => `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${l}</option>`;
  return `
    <div class="field-row">
      <div class="field">
        <label>Date <span class="required">*</span></label>
        <input name="date" type="date" required value="${t.date || ""}" />
      </div>
      <div class="field">
        <label>Amount ($) <span class="required">*</span></label>
        <input name="amount" type="text" inputmode="decimal" required value="${centsToInputValue(t.amount_cents)}" />
      </div>
      <div class="field">
        <label>Direction</label>
        <select name="direction">${opt("out", "Money out", t.direction)}${opt("in", "Money in", t.direction)}</select>
      </div>
    </div>
    <div class="field">
      <label>Description <span class="required">*</span></label>
      <input name="description" type="text" required value="${escAttr(t.description)}" />
    </div>
    <div class="field-row">
      <div class="field"><label>Category</label><select name="category_id"></select></div>
      <div class="field"><label>Person</label><select name="person_id"></select></div>
      <div class="field"><label>Account (optional)</label><input name="account_name" type="text" value="${escAttr(t.account_name)}" /></div>
      <div class="field"><label>Draw from fund (optional)</label><select name="fund_id"></select></div>
    </div>
    <div class="field"><label>Notes</label><textarea name="notes" rows="2">${escText(t.notes)}</textarea></div>`;
}

function readTxn(scope) {
  const g = (n) => scope.querySelector(`[name="${n}"]`);
  return {
    date: g("date").value,
    description: g("description").value.trim(),
    amount_cents: dollarsToCents(g("amount").value),
    direction: g("direction").value,
    category_id: g("category_id").value || null,
    person_id: g("person_id").value || null,
    account_name: g("account_name").value.trim() || null,
    fund_id: g("fund_id").value ? Number(g("fund_id").value) : null,
    notes: g("notes").value.trim() || null,
  };
}

function txnCard(txn) {
  const wrap = el("div", { class: "item-card" });
  const summary = el("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el("span", { class: "item-badge item-badge-date", text: Global.formatDateBadge(txn.date) || txn.date }),
    el("span", { class: "item-summary-title", text: txn.description }),
    el("span", { class: "fin-item-amount fin-amount-" + txn.direction, text: fmtMoney(txn.amount_cents) }),
    el("span", { class: "item-chevron", "aria-hidden": "true", text: "▸" }),
  ]);
  const meta = el("div", { class: "fin-card-meta" }, [categoryChip(txn.category), personBadge(txn.person)]);

  const details = el("div", { class: "item-details hidden" });
  const inner = el("div", { class: "item-details-inner" });
  const form = el("form", { class: "fin-edit-form" });
  form.innerHTML =
    txnEditHTML(txn) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Save changes</button>
       <button type="button" class="secondary-btn" data-act="to-recurring">Convert to recurring</button>
       <button type="button" class="danger-btn" data-act="delete">Delete</button>
     </div>`;
  inner.appendChild(meta);
  inner.appendChild(form);
  details.appendChild(inner);
  wrap.appendChild(summary);
  wrap.appendChild(details);

  populateSelects(form, txn);
  Global.wireAccordionToggle(wrap, summary, details);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = readTxn(form);
    if (!body.date) return Global.showMessage("Date is required.", "error");
    if (!body.description) return Global.showMessage("Description is required.", "error");
    if (body.amount_cents == null || body.amount_cents <= 0) return Global.showMessage("Enter a dollar amount greater than zero.", "error");
    try {
      await fetchJSON(`${API}/transactions/${txn.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      Global.showMessage("Saved.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });
  form.querySelector('[data-act="delete"]').addEventListener("click", async () => {
    if (!confirm("Delete this transaction?")) return;
    try {
      await fetchJSON(`${API}/transactions/${txn.id}`, { method: "DELETE" });
      Global.showMessage("Deleted.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });
  form.querySelector('[data-act="to-recurring"]').addEventListener("click", async () => {
    if (!confirm(`Turn "${txn.description}" into a monthly recurring item? (Open it under Recurring afterward to change the frequency or schedule.)`)) return;
    try {
      await fetchJSON(`${API}/transactions/${txn.id}/convert-to-recurring`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frequency: "monthly" }),
      });
      Global.showMessage(`"${txn.description}" is now a monthly recurring item.`, "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });

  return wrap;
}

// --- fund cards ------------------------------------------------

const FUND_UNITS = [
  ["year", "per year"],
  ["month", "per month"],
  ["weeks", "every N weeks"],
  ["months", "every N months"],
  ["times_year", "N times per year"],
];

function fundFieldsHTML(f) {
  f = f || {};
  const unit = f.entry_unit || "year";
  const optu = (v, l) => `<option value="${v}"${v === unit ? " selected" : ""}>${l}</option>`;
  // If we don't have the original entry, show the annual amount as "per year".
  const amount =
    f.entry_amount_cents != null ? centsToInputValue(f.entry_amount_cents)
    : f.annual_amount_cents != null ? centsToInputValue(f.annual_amount_cents)
    : "";
  return `
    <div class="field">
      <label>Name <span class="required">*</span></label>
      <input name="name" type="text" required value="${escAttr(f.name)}" />
    </div>
    <div class="field-row">
      <div class="field">
        <label>Amount ($) <span class="required">*</span></label>
        <input name="fund_amount" type="text" inputmode="decimal" required value="${amount}" placeholder="85.00" />
      </div>
      <div class="field">
        <label>How often</label>
        <select name="fund_unit">${FUND_UNITS.map(([v, l]) => optu(v, l)).join("")}</select>
      </div>
      <div class="field fin-fund-n-field${["weeks", "months", "times_year"].includes(unit) ? "" : " hidden"}">
        <label>N</label>
        <input name="fund_period_n" type="number" min="1" value="${f.entry_period_n || ""}" placeholder="7" />
      </div>
    </div>
    <p class="fin-fund-preview">≈ <strong data-role="fund-preview">$0.00</strong> / month set aside</p>
    <div class="field-row">
      <div class="field"><label>Category</label><select name="category_id"></select></div>
      <div class="field"><label>Person</label><select name="person_id"></select></div>
      <div class="field"><label>Accrual starts</label><input name="fund_start_month" type="month" value="${f.start_month || ""}" /></div>
    </div>
    <label class="checkbox-label"><input name="active" type="checkbox"${f.active ? " checked" : ""} /> Active</label>
    <div class="field"><label>Notes</label><textarea name="notes" rows="2">${escText(f.notes)}</textarea></div>`;
}

function wireFundForm(scope) {
  const unit = scope.querySelector('[name="fund_unit"]');
  const nField = scope.querySelector(".fin-fund-n-field");
  const amount = scope.querySelector('[name="fund_amount"]');
  const n = scope.querySelector('[name="fund_period_n"]');
  const preview = scope.querySelector('[data-role="fund-preview"]');
  const refresh = () => {
    nField.classList.toggle("hidden", !["weeks", "months", "times_year"].includes(unit.value));
    const annual = fundAnnualCents(dollarsToCents(amount.value), unit.value, n.value);
    preview.textContent = annual == null ? "$0.00" : fmtMoney(Math.round(annual / 12));
  };
  unit.addEventListener("change", refresh);
  amount.addEventListener("input", refresh);
  n.addEventListener("input", refresh);
  refresh();
}

function readFund(scope) {
  const g = (name) => scope.querySelector(`[name="${name}"]`);
  const unit = g("fund_unit").value;
  const nVal = g("fund_period_n").value ? Number(g("fund_period_n").value) : null;
  const entry_amount_cents = dollarsToCents(g("fund_amount").value);
  return {
    name: g("name").value.trim(),
    annual_amount_cents: fundAnnualCents(entry_amount_cents, unit, nVal),
    entry_amount_cents,
    entry_unit: unit,
    entry_period_n: nVal,
    category_id: g("category_id").value || null,
    person_id: g("person_id").value || null,
    start_month: g("fund_start_month").value || null,
    active: g("active").checked,
    notes: g("notes").value.trim() || null,
  };
}

function fundCard(fund) {
  const wrap = el("div", { class: "item-card" + (fund.active ? "" : " archived") });
  const negative = fund.balance_cents < 0;
  const summary = el("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el("span", { class: "item-summary-title", text: fund.name }),
    !fund.active ? el("span", { class: "fin-tag fin-tag-removed", text: "paused" }) : null,
    el("span", {
      class: "fin-balance-pill " + (negative ? "fin-balance-neg" : "fin-balance-pos"),
      text: negative ? `${fmtMoney(fund.balance_cents)} over` : `${fmtMoney(fund.balance_cents)} banked`,
    }),
    el("span", { class: "fin-item-amount fin-amount-out", text: `${fmtMoney(fund.monthly_contribution_cents)}/mo` }),
    el("span", { class: "item-chevron", "aria-hidden": "true", text: "▸" }),
  ]);
  const meta = el("div", { class: "fin-card-meta" }, [categoryChip(fund.category), personBadge(fund.person)]);
  const status = el("p", { class: "fin-fund-status", text:
    `This year: set aside ${fmtMoney(fund.monthly_contribution_cents * 12)}/yr · spent ${fmtMoney(fund.spent_ytd_cents)}` });

  const details = el("div", { class: "item-details hidden" });
  const inner = el("div", { class: "item-details-inner" });
  const form = el("form", { class: "fin-edit-form" });
  form.innerHTML =
    fundFieldsHTML(fund) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Save changes</button>
       <button type="button" class="danger-btn" data-act="delete">Delete</button>
     </div>`;
  inner.appendChild(meta);
  inner.appendChild(status);
  inner.appendChild(form);
  details.appendChild(inner);
  wrap.appendChild(summary);
  wrap.appendChild(details);

  populateSelects(form, fund);
  wireFundForm(form);
  Global.wireAccordionToggle(wrap, summary, details);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = readFund(form);
    if (!body.name) return Global.showMessage("Name is required.", "error");
    if (body.annual_amount_cents == null || body.annual_amount_cents <= 0)
      return Global.showMessage("Enter a positive amount (and an N for 'every N ...').", "error");
    try {
      await fetchJSON(`${API}/funds/${fund.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      Global.showMessage("Saved.", "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });
  form.querySelector('[data-act="delete"]').addEventListener("click", async () => {
    if (!confirm(`Delete the "${fund.name}" fund? Transactions tagged to it stay, just untagged.`)) return;
    try {
      await fetchJSON(`${API}/funds/${fund.id}`, { method: "DELETE" });
      Global.showMessage(`Deleted "${fund.name}".`, "success");
      load();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  });

  return wrap;
}

// --- provisioning footer --------------------------------------------

async function renderBaseline() {
  try {
    const [rec, funds, trips] = await Promise.all([
      fetchJSON(`${API}/recurring/summary`),
      fetchJSON(`${API}/funds/summary`),
      fetchJSON(`${API}/trips/summary?month=${state.month}`).catch(() => ({ monthly_total_cents: 0 })),
    ]);
    const outTotal = rec.out_cents + funds.monthly_total_cents + trips.monthly_total_cents;
    const net = rec.in_cents - outTotal;
    baselineEl.innerHTML = "";
    baselineEl.appendChild(
      el("div", { class: "fin-total-group" }, [
        el("div", { class: "fin-total-title", text: "Provisioning baseline (per month)" }),
        el("div", { class: "fin-total-row" }, [el("span", { text: "Money in" }), el("span", { class: "fin-amount-in", text: fmtMoney(rec.in_cents) })]),
        el("div", { class: "fin-total-row" }, [el("span", { text: "Recurring out (smoothed)" }), el("span", { class: "fin-amount-out", text: fmtMoney(rec.out_cents) })]),
        el("div", { class: "fin-total-row" }, [el("span", { text: "Funds set aside" }), el("span", { class: "fin-amount-out", text: fmtMoney(funds.monthly_total_cents) })]),
        el("div", { class: "fin-total-row" }, [el("span", { text: "Trips (spread)" }), el("span", { class: "fin-amount-out", text: fmtMoney(trips.monthly_total_cents) })]),
        el("div", { class: "fin-total-row fin-total-net" }, [
          el("span", { text: "Net / month" }),
          el("span", { class: "fin-net " + (net < 0 ? "fin-net-neg" : "fin-net-pos"), text: fmtSignedMoney(net) }),
        ]),
      ])
    );
    baselineEl.appendChild(
      el("p", { class: "fin-normalized", text:
        "Non-monthly recurring items are spread evenly across the year; one-off transactions are not counted here." })
    );
  } catch (err) {
    /* non-fatal */
  }
}

// --- load / render --------------------------------------------

async function loadRecurring() {
  const p = new URLSearchParams();
  if (state.personVal && state.personVal !== "joint") p.set("person_id", state.personVal);
  if (state.status === "active") p.set("active", "true");
  if (state.status === "inactive") p.set("active", "false");
  let items = await fetchJSON(`${API}/recurring?${p.toString()}`);
  items = items.filter(passesClientFilters);
  recurringList.innerHTML = "";
  items.forEach((i) => recurringList.appendChild(recurringCard(i)));
  recurringEmpty.classList.toggle("hidden", items.length > 0);
  recurringCount.textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;
}

async function loadOnetime() {
  const p = new URLSearchParams();
  if (!state.allTime && state.month) p.set("month", state.month);
  if (state.personVal && state.personVal !== "joint") p.set("person_id", state.personVal);
  let rows = await fetchJSON(`${API}/transactions?${p.toString()}`);
  rows = rows.filter(passesClientFilters);
  onetimeList.innerHTML = "";
  rows.forEach((r) => onetimeList.appendChild(txnCard(r)));
  onetimeEmpty.classList.toggle("hidden", rows.length > 0);
  const scope = state.allTime ? "all time" : monthLabel(state.month);
  onetimeSub.textContent = `${rows.length} · ${scope}`;
}

async function loadFunds() {
  const p = new URLSearchParams();
  if (state.personVal && state.personVal !== "joint") p.set("person_id", state.personVal);
  let funds = await fetchJSON(`${API}/funds?${p.toString()}`);
  FUNDS = funds; // keep the shared list current for the add form / txn pickers
  const addFundSel = addForm.querySelector('[name="fund_id"]');
  if (addFundSel) {
    const prev = addFundSel.value;
    fillSelect(addFundSel, FUNDS.map((f) => ({ value: f.id, label: f.name })), { blankLabel: "— none —" });
    addFundSel.value = prev;
  }
  if (state.personVal === "joint") funds = funds.filter((f) => f.person_id == null);
  if (state.categoryIds.length) {
    const set = new Set(state.categoryIds.map(String));
    funds = funds.filter((f) => set.has(String(f.category_id)));
  }
  fundsList.innerHTML = "";
  funds.forEach((f) => fundsList.appendChild(fundCard(f)));
  fundsEmpty.classList.toggle("hidden", funds.length > 0);
  fundsCount.textContent = `${funds.length} fund${funds.length === 1 ? "" : "s"}`;
}

// --- trip forecast cards ------------------------------------

function tripCard(t, { excluded = false, noDate = false } = {}) {
  const wrap = el("div", { class: "item-card fin-trip-card" + (excluded ? " archived" : "") });

  const line1 = el("div", { class: "fin-trip-line" }, [
    el("span", { class: "fin-item-name", text: t.name }),
    noDate
      ? el("span", { class: "fin-tag fin-tag-removed", text: "no date" })
      : el("span", { class: "fin-cadence", text: monthLabel(t.trip_month) }),
    excluded ? el("span", { class: "fin-tag fin-tag-removed", text: "excluded" }) : null,
  ]);

  let detail;
  if (noDate) {
    detail = "Set a start date in trip-planning to fold this into the monthly forecast.";
  } else if (t.total_cents <= 0) {
    detail = "No cost yet — add activity/stay costs in trip-planning, or set an override below.";
  } else {
    detail = `Total ${fmtMoney(t.total_cents)} · ${fmtMoney(t.monthly_contribution_cents)}/mo`
      + (t.months_remaining ? ` for ${t.months_remaining} month${t.months_remaining === 1 ? "" : "s"}` : "");
  }
  const line2 = el("div", { class: "fin-trip-detail", text: detail });

  // override input
  const overrideInput = el("input", {
    type: "text", inputmode: "decimal", class: "fin-trip-override",
    placeholder: "override total ($)",
    value: t.override_amount_cents != null ? centsToInputValue(t.override_amount_cents) : "",
  });
  const saveOverride = el("button", {
    type: "button", class: "secondary-btn", text: "Set",
    onclick: async () => {
      const cents = dollarsToCents(overrideInput.value);
      try {
        await fetchJSON(`${API}/trips/${t.trip_id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ override_amount_cents: cents && cents > 0 ? cents : null }),
        });
        Global.showMessage("Trip override updated.", "success");
        load();
      } catch (err) {
        Global.showMessage(err.message, "error");
      }
    },
  });

  const actions = el("div", { class: "fin-trip-actions" }, [
    overrideInput,
    saveOverride,
    el("button", {
      type: "button", class: "secondary-btn", text: excluded ? "Include" : "Exclude",
      onclick: async () => {
        try {
          await fetchJSON(`${API}/trips/${t.trip_id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ excluded: !excluded }),
          });
          load();
        } catch (err) {
          Global.showMessage(err.message, "error");
        }
      },
    }),
    !excluded && !noDate
      ? el("button", {
          type: "button", class: "save-btn", text: "Mark fully paid",
          onclick: async () => {
            const today = new Date().toISOString().slice(0, 10);
            const amt = t.total_cents;
            if (amt <= 0) return Global.showMessage("Set a cost or override first.", "error");
            if (!confirm(`Record ${fmtMoney(amt)} spent on "${t.name}" as a one-time transaction dated ${today}, and drop it from the forecast?`)) return;
            try {
              await fetchJSON(`${API}/trips/${t.trip_id}/settle`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ date: today }),
              });
              Global.showMessage(`"${t.name}" marked paid.`, "success");
              load();
            } catch (err) {
              Global.showMessage(err.message, "error");
            }
          },
        })
      : null,
  ]);

  wrap.append(line1, line2, actions);
  return wrap;
}

async function loadTrips() {
  let data;
  try {
    data = await fetchJSON(`${API}/trips?month=${state.month}`);
  } catch (err) {
    tripsList.innerHTML = "";
    tripsEmpty.textContent = "Trips unavailable — is the trip-planning app running?";
    tripsEmpty.classList.remove("hidden");
    tripsCount.textContent = "";
    return;
  }
  const rows = [
    ...data.upcoming.map((t) => tripCard(t)),
    ...data.no_date.map((t) => tripCard(t, { noDate: true })),
    ...data.excluded.map((t) => tripCard(t, { excluded: true })),
  ];
  tripsList.innerHTML = "";
  rows.forEach((r) => tripsList.appendChild(r));
  const total = data.upcoming.length + data.no_date.length + data.excluded.length;
  tripsEmpty.textContent = "No upcoming trips.";
  tripsEmpty.classList.toggle("hidden", total > 0);
  tripsCount.textContent = total ? `${data.upcoming.length} upcoming` : "";
}

async function load() {
  const showRec = state.view === "all" || state.view === "recurring";
  const showOne = state.view === "all" || state.view === "onetime";
  secRecurring.classList.toggle("hidden", !showRec);
  secOnetime.classList.toggle("hidden", !showOne);
  statusFilter.classList.toggle("hidden", !showRec);
  monthFilter.classList.toggle("hidden", !showOne);
  allTimeBtn.classList.toggle("hidden", !showOne);

  try {
    const jobs = [renderBaseline(), loadFunds(), loadTrips()];
    if (showRec) jobs.push(loadRecurring());
    if (showOne) jobs.push(loadOnetime());
    await Promise.all(jobs);
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
}

// --- filter wiring ------------------------------------------

function setView(view) {
  state.view = view;
  [...segEl.children].forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  load();
}

async function init() {
  [PEOPLE, CATEGORIES, FUNDS] = await Promise.all([
    loadPeople(),
    loadCategories(),
    fetchJSON(`${API}/funds`),
  ]);

  [...segEl.children].forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  fillPersonFilter(personSelect, PEOPLE);
  personSelect.addEventListener("change", () => {
    state.personVal = personSelect.value;
    load();
  });
  activeSelect.addEventListener("change", () => {
    state.status = activeSelect.value;
    load();
  });

  monthInput.value = state.month;
  monthInput.addEventListener("change", () => {
    state.month = monthInput.value;
    state.allTime = false;
    load();
  });
  allTimeBtn.addEventListener("click", () => {
    state.allTime = !state.allTime;
    allTimeBtn.classList.toggle("active", state.allTime);
    load();
  });

  const multi = Global.buildMultiSelect({
    options: CATEGORIES.map((c) => ({ value: c.id, label: c.name, color: c.color })),
    placeholder: "All categories",
    onChange: (selected) => {
      state.categoryIds = selected;
      load();
    },
  });
  categoryMount.replaceWith(multi);

  buildAddForm();
  load();
}

init();
