// Ad-hoc transactions - dated one-offs. Accordion cards for add/edit,
// filterable by month / person / category, with an in / out / net total
// for whatever is currently shown.

const listEl = document.getElementById("list");
const emptyEl = document.getElementById("empty");
const countEl = document.getElementById("count");
const totalsEl = document.getElementById("totals");
const monthInput = document.getElementById("filter-month");
const personSelect = document.getElementById("filter-person");
const categoryMount = document.getElementById("filter-category");
const addForm = document.getElementById("add-form");

const filters = { month: "", personVal: "", categoryIds: [] };

let PEOPLE = [];
let CATEGORIES = [];

// --- form markup ------------------------------------------------------

function fieldsHTML(item) {
  const it = item || {};
  const opt = (v, label, cur) => `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${label}</option>`;
  const today = new Date().toISOString().slice(0, 10);
  return `
    <div class="field-row">
      <div class="field">
        <label>Date <span class="required">*</span></label>
        <input name="date" type="date" required value="${it.date || today}" />
      </div>
      <div class="field">
        <label>Amount ($) <span class="required">*</span></label>
        <input name="amount" type="text" inputmode="decimal" required value="${it.amount_cents != null ? centsToInputValue(it.amount_cents) : ""}" placeholder="1200.00" />
      </div>
      <div class="field">
        <label>Direction</label>
        <select name="direction">
          ${opt("out", "Money out", it.direction || "out")}
          ${opt("in", "Money in", it.direction || "out")}
        </select>
      </div>
    </div>
    <div class="field">
      <label>Description <span class="required">*</span></label>
      <input name="description" type="text" required value="${it.description ? it.description.replace(/"/g, "&quot;") : ""}" placeholder="e.g. New water heater" />
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
      <div class="field">
        <label>Account (optional)</label>
        <input name="account_name" type="text" value="${it.account_name ? it.account_name.replace(/"/g, "&quot;") : ""}" placeholder="e.g. Chase checking" />
      </div>
    </div>
    <div class="field">
      <label>Notes</label>
      <textarea name="notes" rows="2" placeholder="Optional">${it.notes ? it.notes.replace(/</g, "&lt;") : ""}</textarea>
    </div>`;
}

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

function readForm(scope) {
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

function validate(body) {
  if (!body.date) return "Date is required.";
  if (!body.description) return "Description is required.";
  if (body.amount_cents == null || body.amount_cents <= 0) return "Enter a dollar amount greater than zero.";
  return null;
}

// --- add form -------------------------------------------------------

function buildAddForm() {
  addForm.innerHTML =
    fieldsHTML(null) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Add transaction</button>
       <button type="button" id="cancel-add" class="cancel-btn">Cancel</button>
     </div>`;
  populateSelects(addForm, null);
  addForm.querySelector("#cancel-add").addEventListener("click", () => {
    addForm.classList.add("hidden");
    buildAddForm();
  });
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = readForm(addForm);
  const err = validate(body);
  if (err) return Global.showMessage(err, "error");
  try {
    await fetchJSON(`${API}/transactions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    addForm.classList.add("hidden");
    buildAddForm();
    Global.showMessage("Transaction added.", "success");
    load();
  } catch (err2) {
    Global.showMessage(err2.message, "error");
  }
});

document.getElementById("show-add").addEventListener("click", () => {
  addForm.classList.toggle("hidden");
  if (!addForm.classList.contains("hidden")) addForm.querySelector('[name="description"]').focus();
});

// --- card ----------------------------------------------------------

function card(txn) {
  const el_ = Global.el;
  const wrap = el_("div", { class: "item-card" });

  const summary = el_("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el_("span", { class: "item-badge item-badge-date", text: Global.formatDateBadge(txn.date) || txn.date }),
    el_("span", { class: "item-summary-title", text: txn.description }),
    el_("span", { class: "fin-item-amount fin-amount-" + txn.direction, text: fmtMoney(txn.amount_cents) }),
    el_("span", { class: "item-chevron", "aria-hidden": "true", text: "▸" }),
  ]);

  const meta = el_("div", { class: "fin-card-meta" }, [categoryChip(txn.category), personBadge(txn.person)]);

  const details = el_("div", { class: "item-details hidden" });
  const inner = el_("div", { class: "item-details-inner" });
  const editForm = el_("form", { class: "fin-edit-form" });
  editForm.innerHTML =
    fieldsHTML(txn) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Save changes</button>
       <button type="button" class="danger-btn" data-act="delete">Delete</button>
     </div>`;
  inner.appendChild(meta);
  inner.appendChild(editForm);
  details.appendChild(inner);
  wrap.appendChild(summary);
  wrap.appendChild(details);

  populateSelects(editForm, txn);
  Global.wireAccordionToggle(wrap, summary, details);

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = readForm(editForm);
    const err = validate(body);
    if (err) return Global.showMessage(err, "error");
    try {
      await fetchJSON(`${API}/transactions/${txn.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      Global.showMessage("Saved.", "success");
      load();
    } catch (err2) {
      Global.showMessage(err2.message, "error");
    }
  });

  editForm.querySelector('[data-act="delete"]').addEventListener("click", async () => {
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

// --- load / render -----------------------------------------------

function currentQuery() {
  const p = new URLSearchParams();
  if (filters.month) p.set("month", filters.month);
  if (filters.personVal === "joint") {
    // filtered client-side
  } else if (filters.personVal) {
    p.set("person_id", filters.personVal);
  }
  return p;
}

function renderTotals(rows) {
  const inC = rows.filter((r) => r.direction === "in").reduce((a, r) => a + r.amount_cents, 0);
  const outC = rows.filter((r) => r.direction === "out").reduce((a, r) => a + r.amount_cents, 0);
  totalsEl.innerHTML = "";
  totalsEl.appendChild(
    Global.el("div", { class: "fin-total-group" }, [
      Global.el("div", { class: "fin-total-title", text: filters.month ? monthLabel(filters.month) : "All shown transactions" }),
      Global.el("div", { class: "fin-total-row" }, [
        Global.el("span", { text: "Money in" }),
        Global.el("span", { class: "fin-amount-in", text: fmtMoney(inC) }),
      ]),
      Global.el("div", { class: "fin-total-row" }, [
        Global.el("span", { text: "Money out" }),
        Global.el("span", { class: "fin-amount-out", text: fmtMoney(outC) }),
      ]),
      Global.el("div", { class: "fin-total-row fin-total-net" }, [
        Global.el("span", { text: "Net" }),
        Global.el("span", {
          class: "fin-net " + (inC - outC < 0 ? "fin-net-neg" : "fin-net-pos"),
          text: fmtSignedMoney(inC - outC),
        }),
      ]),
    ])
  );
}

async function load() {
  try {
    let rows = await fetchJSON(`${API}/transactions?${currentQuery().toString()}`);
    if (filters.personVal === "joint") rows = rows.filter((r) => r.person_id == null);
    if (filters.categoryIds.length) {
      const set = new Set(filters.categoryIds.map(String));
      rows = rows.filter((r) => set.has(String(r.category_id)));
    }
    listEl.innerHTML = "";
    rows.forEach((r) => listEl.appendChild(card(r)));
    emptyEl.classList.toggle("hidden", rows.length > 0);
    countEl.textContent = `${rows.length} item${rows.length === 1 ? "" : "s"}`;
    renderTotals(rows);
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
}

async function init() {
  [PEOPLE, CATEGORIES] = await Promise.all([loadPeople(), loadCategories()]);

  filters.month = thisMonth();
  monthInput.value = filters.month;
  monthInput.addEventListener("change", () => {
    filters.month = monthInput.value;
    load();
  });
  document.getElementById("filter-clear").addEventListener("click", () => {
    filters.month = "";
    monthInput.value = "";
    load();
  });

  fillPersonFilter(personSelect, PEOPLE);
  personSelect.addEventListener("change", () => {
    filters.personVal = personSelect.value;
    load();
  });

  const multi = Global.buildMultiSelect({
    options: CATEGORIES.map((c) => ({ value: c.id, label: c.name, color: c.color })),
    placeholder: "All categories",
    onChange: (selected) => {
      filters.categoryIds = selected;
      load();
    },
  });
  categoryMount.replaceWith(multi);

  buildAddForm();
  load();
}

init();
