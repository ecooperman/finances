// Budget - the single place to add and manage every money event:
// recurring rules (salaries, mortgage, HOA, insurance, ...) AND one-off
// transactions. The segmented control picks which you're looking at; the
// "+ Add" form (common.js) has a Repeats toggle that decides which kind
// you're creating. Footer shows the known monthly baseline (recurring,
// non-monthly items smoothed to /month).

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

// --- shared helpers ---------------------------------------------------

function populateSelects(scope, item) {
  const cat = scope.querySelector('[name="category_id"]');
  const per = scope.querySelector('[name="person_id"]');
  fillSelect(cat, CATEGORIES.map((c) => ({ value: c.id, label: c.name })), { blankLabel: "— none —" });
  fillSelect(per, PEOPLE.map((p) => ({ value: p.id, label: p.name })), { blankLabel: "Joint" });
  if (item) {
    cat.value = item.category_id || "";
    per.value = item.person_id || "";
  }
}

function wireAnchor(scope) {
  const freq = scope.querySelector('[name="frequency"]');
  const anchorField = scope.querySelector(".fin-anchor-field");
  if (!freq || !anchorField) return;
  const sync = () => anchorField.classList.toggle("hidden", freq.value === "monthly");
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
  wireEntryForm(addForm, PEOPLE, CATEGORIES);
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
    Global.showMessage(entry.type === "recurring" ? "Recurring item added." : "Transaction added.", "success");
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
  const monthly = g("frequency").value === "monthly";
  return {
    name: g("name").value.trim(),
    amount_cents: dollarsToCents(g("amount").value),
    direction: g("direction").value,
    frequency: g("frequency").value,
    anchor_month: monthly ? null : Number(g("anchor_month").value),
    day_of_month: g("day_of_month").value ? Number(g("day_of_month").value) : null,
    category_id: g("category_id").value || null,
    person_id: g("person_id").value || null,
    start_month: g("start_month").value || null,
    end_month: g("end_month").value || null,
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
  const meta = el("div", { class: "fin-card-meta" }, [categoryChip(item.category), personBadge(item.person)]);

  const details = el("div", { class: "item-details hidden" });
  const inner = el("div", { class: "item-details-inner" });
  const form = el("form", { class: "fin-edit-form" });
  form.innerHTML =
    recurringEditHTML(item) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Save changes</button>
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

  return wrap;
}

// --- baseline footer --------------------------------------------

async function renderBaseline() {
  try {
    const s = await fetchJSON(`${API}/recurring/summary`);
    baselineEl.innerHTML = "";
    baselineEl.appendChild(
      el("div", { class: "fin-total-group" }, [
        el("div", { class: "fin-total-title", text: "Known monthly baseline" }),
        el("div", { class: "fin-total-row" }, [el("span", { text: "Money in" }), el("span", { class: "fin-amount-in", text: fmtMoney(s.in_cents) })]),
        el("div", { class: "fin-total-row" }, [el("span", { text: "Money out" }), el("span", { class: "fin-amount-out", text: fmtMoney(s.out_cents) })]),
        el("div", { class: "fin-total-row fin-total-net" }, [
          el("span", { text: "Net / month" }),
          el("span", { class: "fin-net " + (s.net_cents < 0 ? "fin-net-neg" : "fin-net-pos"), text: fmtSignedMoney(s.net_cents) }),
        ]),
      ])
    );
    baselineEl.appendChild(
      el("p", { class: "fin-normalized", text: "Recurring only. Non-monthly items (annual, quarterly, ...) are spread evenly across the year here." })
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

async function load() {
  const showRec = state.view === "all" || state.view === "recurring";
  const showOne = state.view === "all" || state.view === "onetime";
  secRecurring.classList.toggle("hidden", !showRec);
  secOnetime.classList.toggle("hidden", !showOne);
  statusFilter.classList.toggle("hidden", !showRec);
  monthFilter.classList.toggle("hidden", !showOne);
  allTimeBtn.classList.toggle("hidden", !showOne);

  try {
    const jobs = [renderBaseline()];
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
  [PEOPLE, CATEGORIES] = await Promise.all([loadPeople(), loadCategories()]);

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
