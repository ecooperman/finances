// Recurring items - the monthly baseline. Accordion cards for add/edit,
// filterable by person / category / status, with a "known monthly
// baseline" summary at the bottom (non-monthly items smoothed to /month).

const listEl = document.getElementById("list");
const emptyEl = document.getElementById("empty");
const countEl = document.getElementById("count");
const baselineEl = document.getElementById("baseline");
const personSelect = document.getElementById("filter-person");
const categoryMount = document.getElementById("filter-category");
const activeSelect = document.getElementById("filter-active");
const addForm = document.getElementById("add-form");

const filters = { personVal: "", categoryIds: [], status: "active" };

const MONTH_OPTIONS = MONTH_NAMES.map((n, i) => ({ value: i + 1, label: n }));

// --- form markup (shared by the add form and every edit form) ----------

function fieldsHTML(item) {
  const it = item || {};
  const opt = (v, label, cur) => `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${label}</option>`;
  return `
    <div class="field">
      <label>Name <span class="required">*</span></label>
      <input name="name" type="text" required value="${it.name ? it.name.replace(/"/g, "&quot;") : ""}" placeholder="e.g. Mortgage payment" />
    </div>
    <div class="field-row">
      <div class="field">
        <label>Amount ($) <span class="required">*</span></label>
        <input name="amount" type="text" inputmode="decimal" required value="${it.amount_cents != null ? centsToInputValue(it.amount_cents) : ""}" placeholder="3200.00" />
      </div>
      <div class="field">
        <label>Direction</label>
        <select name="direction">
          ${opt("out", "Money out", it.direction || "out")}
          ${opt("in", "Money in", it.direction || "out")}
        </select>
      </div>
    </div>
    <div class="field-row">
      <div class="field">
        <label>Frequency</label>
        <select name="frequency">
          ${opt("monthly", "Monthly", it.frequency || "monthly")}
          ${opt("quarterly", "Quarterly", it.frequency || "monthly")}
          ${opt("semiannual", "Semi-annual", it.frequency || "monthly")}
          ${opt("annual", "Annual", it.frequency || "monthly")}
        </select>
      </div>
      <div class="field fin-anchor-field">
        <label>First month it hits</label>
        <select name="anchor_month">
          ${MONTH_OPTIONS.map((m) => opt(m.value, m.label, it.anchor_month || "")).join("")}
        </select>
      </div>
      <div class="field">
        <label>Day of month</label>
        <input name="day_of_month" type="number" min="1" max="31" value="${it.day_of_month || ""}" placeholder="opt." />
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
    <div class="field-row">
      <div class="field">
        <label>Starts (optional)</label>
        <input name="start_month" type="month" value="${it.start_month || ""}" />
      </div>
      <div class="field">
        <label>Ends (optional)</label>
        <input name="end_month" type="month" value="${it.end_month || ""}" />
      </div>
    </div>
    ${
      item
        ? `<label class="checkbox-label"><input name="active" type="checkbox"${it.active ? " checked" : ""} /> Active</label>`
        : ""
    }
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

function wireFrequencyToggle(scope) {
  const freq = scope.querySelector('[name="frequency"]');
  const anchorField = scope.querySelector(".fin-anchor-field");
  const sync = () => anchorField.classList.toggle("hidden", freq.value === "monthly");
  freq.addEventListener("change", sync);
  sync();
}

function readForm(scope) {
  const g = (n) => scope.querySelector(`[name="${n}"]`);
  const amount_cents = dollarsToCents(g("amount").value);
  const monthly = g("frequency").value === "monthly";
  return {
    name: g("name").value.trim(),
    amount_cents,
    direction: g("direction").value,
    frequency: g("frequency").value,
    anchor_month: monthly ? null : Number(g("anchor_month").value),
    day_of_month: g("day_of_month").value ? Number(g("day_of_month").value) : null,
    category_id: g("category_id").value || null,
    person_id: g("person_id").value || null,
    start_month: g("start_month").value || null,
    end_month: g("end_month").value || null,
    active: g("active") ? g("active").checked : true,
    notes: g("notes").value.trim() || null,
  };
}

function validate(body) {
  if (!body.name) return "Name is required.";
  if (body.amount_cents == null || body.amount_cents <= 0) return "Enter a dollar amount greater than zero.";
  return null;
}

// --- add form --------------------------------------------------------

function buildAddForm() {
  addForm.innerHTML =
    fieldsHTML(null) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Add item</button>
       <button type="button" id="cancel-add" class="cancel-btn">Cancel</button>
     </div>`;
  populateSelects(addForm, null);
  wireFrequencyToggle(addForm);
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
    await fetchJSON(`${API}/recurring`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    addForm.classList.add("hidden");
    buildAddForm();
    Global.showMessage("Recurring item added.", "success");
    load();
  } catch (err2) {
    Global.showMessage(err2.message, "error");
  }
});

document.getElementById("show-add").addEventListener("click", () => {
  addForm.classList.toggle("hidden");
  if (!addForm.classList.contains("hidden")) addForm.querySelector('[name="name"]').focus();
});

// --- card -----------------------------------------------------------

function card(item) {
  const el_ = Global.el;
  const wrap = el_("div", { class: "item-card" + (item.active ? "" : " archived") });

  const summary = el_("button", { class: "item-summary", type: "button", "aria-expanded": "false" }, [
    el_("span", { class: "fin-item-icon", "data-icon": "repeat", "aria-hidden": "true" }),
    el_("span", { class: "item-summary-title", text: item.name }),
    item.frequency !== "monthly" ? el_("span", { class: "fin-cadence", text: freqLabel(item.frequency) }) : null,
    !item.active ? el_("span", { class: "fin-tag fin-tag-removed", text: "paused" }) : null,
    el_("span", { class: "fin-item-amount fin-amount-" + item.direction, text: fmtMoney(item.amount_cents) }),
    el_("span", { class: "item-chevron", "aria-hidden": "true", text: "▸" }),
  ]);

  const meta = el_("div", { class: "fin-card-meta" }, [categoryChip(item.category), personBadge(item.person)]);

  const details = el_("div", { class: "item-details hidden" });
  const inner = el_("div", { class: "item-details-inner" });
  const editForm = el_("form", { class: "fin-edit-form" });
  editForm.innerHTML =
    fieldsHTML(item) +
    `<div class="item-actions">
       <button type="submit" class="save-btn">Save changes</button>
       <button type="button" class="danger-btn" data-act="delete">Delete</button>
     </div>`;
  inner.appendChild(meta);
  inner.appendChild(editForm);
  details.appendChild(inner);
  wrap.appendChild(summary);
  wrap.appendChild(details);

  populateSelects(editForm, item);
  wireFrequencyToggle(editForm);
  Global.wireAccordionToggle(wrap, summary, details);

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = readForm(editForm);
    const err = validate(body);
    if (err) return Global.showMessage(err, "error");
    try {
      await fetchJSON(`${API}/recurring/${item.id}`, {
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

// --- load / render --------------------------------------------------

let PEOPLE = [];
let CATEGORIES = [];

function currentQuery() {
  const p = new URLSearchParams();
  if (filters.personVal === "joint") {
    // API has no "joint" filter for the raw list; filter client-side below.
  } else if (filters.personVal) {
    p.set("person_id", filters.personVal);
  }
  if (filters.status === "active") p.set("active", "true");
  if (filters.status === "inactive") p.set("active", "false");
  return p;
}

async function load() {
  try {
    const items = await fetchJSON(`${API}/recurring?${currentQuery().toString()}`);
    let shown = items;
    if (filters.personVal === "joint") shown = shown.filter((i) => i.person_id == null);
    if (filters.categoryIds.length) {
      const set = new Set(filters.categoryIds.map(String));
      shown = shown.filter((i) => set.has(String(i.category_id)));
    }
    listEl.innerHTML = "";
    shown.forEach((i) => listEl.appendChild(card(i)));
    emptyEl.classList.toggle("hidden", shown.length > 0);
    countEl.textContent = `${shown.length} item${shown.length === 1 ? "" : "s"}`;
    renderBaseline();
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
}

async function renderBaseline() {
  try {
    const s = await fetchJSON(`${API}/recurring/summary`);
    baselineEl.innerHTML = "";
    baselineEl.appendChild(
      Global.el("div", { class: "fin-total-group" }, [
        Global.el("div", { class: "fin-total-title", text: "Known monthly baseline" }),
        Global.el("div", { class: "fin-total-row" }, [
          Global.el("span", { text: "Money in" }),
          Global.el("span", { class: "fin-amount-in", text: fmtMoney(s.in_cents) }),
        ]),
        Global.el("div", { class: "fin-total-row" }, [
          Global.el("span", { text: "Money out" }),
          Global.el("span", { class: "fin-amount-out", text: fmtMoney(s.out_cents) }),
        ]),
        Global.el("div", { class: "fin-total-row fin-total-net" }, [
          Global.el("span", { text: "Net / month" }),
          Global.el("span", {
            class: "fin-net " + (s.net_cents < 0 ? "fin-net-neg" : "fin-net-pos"),
            text: fmtSignedMoney(s.net_cents),
          }),
        ]),
      ])
    );
    baselineEl.appendChild(
      Global.el("p", {
        class: "fin-normalized",
        text: "Non-monthly items (annual, quarterly, ...) are spread evenly across the year here.",
      })
    );
  } catch (err) {
    // non-fatal
  }
}

async function init() {
  [PEOPLE, CATEGORIES] = await Promise.all([loadPeople(), loadCategories()]);

  fillPersonFilter(personSelect, PEOPLE);
  personSelect.addEventListener("change", () => {
    filters.personVal = personSelect.value;
    load();
  });
  activeSelect.addEventListener("change", () => {
    filters.status = activeSelect.value;
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
