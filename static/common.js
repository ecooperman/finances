// Shared helpers for every page in the finances app - money formatting,
// the person/category pill builders, month arithmetic, and cached loaders
// for the small reference lists (people, categories, scenarios) that most
// pages need to populate their filter dropdowns.
//
// Generic DOM/fetch/date helpers come from window.Global (shared-assets'
// theme.js) - only finance-specific stuff lives here.

const API = "/api";
const { el, fetchJSON } = Global;

// --- money -----------------------------------------------------------------

// Everything crosses the API as integer cents. Format for display with two
// decimals and thousands separators; the leading "$" is always shown.
function fmtMoney(cents) {
  const dollars = (cents || 0) / 100;
  return dollars.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

// Net figures: an explicit + / - in front so a positive month reads as
// clearly positive.
function fmtSignedMoney(cents) {
  const sign = cents < 0 ? "-" : "+";
  return sign + fmtMoney(Math.abs(cents));
}

// Parse a user-typed dollar amount ("3200", "3,200.50", "$3,200.5") into
// integer cents. Returns null if it isn't a number.
function dollarsToCents(value) {
  if (value == null) return null;
  const cleaned = String(value).replace(/[$,\s]/g, "");
  if (cleaned === "" || isNaN(Number(cleaned))) return null;
  return Math.round(Number(cleaned) * 100);
}

// Integer cents -> a plain "3200.00" string for pre-filling a number input.
function centsToInputValue(cents) {
  if (cents == null) return "";
  return (cents / 100).toFixed(2);
}

// --- pills ---------------------------------------------------------------

// Pick black or white text for a solid background color, by luminance.
function contrastText(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return "#fff";
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? "#1c1c1c" : "#fff";
}

function categoryChip(category) {
  if (!category) return el("span", { class: "fin-chip fin-chip-none", text: "Uncategorized" });
  const chip = el("span", { class: "fin-chip", text: category.name });
  chip.style.background = category.color;
  chip.style.color = category.text_color === "light" ? "#fff" : contrastText(category.color);
  return chip;
}

function personBadge(person) {
  if (!person) return el("span", { class: "fin-badge fin-badge-joint", text: "Joint" });
  const badge = el("span", { class: "fin-badge", text: person.name });
  badge.style.background = person.color;
  badge.style.color = contrastText(person.color);
  return badge;
}

const FREQ_LABELS = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  semiannual: "Semi-annual",
  annual: "Annual",
};
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function freqLabel(freq) {
  return FREQ_LABELS[freq] || freq || "";
}

// --- month arithmetic ("YYYY-MM" strings) --------------------------------

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(month, delta) {
  let [y, m] = month.split("-").map(Number);
  m += delta;
  while (m < 1) {
    m += 12;
    y -= 1;
  }
  while (m > 12) {
    m -= 12;
    y += 1;
  }
  return `${y}-${String(m).padStart(2, "0")}`;
}

function monthLabel(month) {
  const [y, m] = month.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

// --- cached reference-list loaders -------------------------------------

let _people = null;
let _categories = null;
let _scenarios = null;

async function loadPeople(force) {
  if (!_people || force) _people = await fetchJSON(`${API}/people`);
  return _people;
}
async function loadCategories(force) {
  if (!_categories || force) _categories = await fetchJSON(`${API}/categories`);
  return _categories;
}
async function loadScenarios(force) {
  if (!_scenarios || force) _scenarios = await fetchJSON(`${API}/scenarios`);
  return _scenarios;
}

// Populate a <select> with {value,label} options, keeping any current
// selection if it still exists.
function fillSelect(select, options, { blankLabel } = {}) {
  const prev = select.value;
  select.innerHTML = "";
  if (blankLabel !== undefined) {
    select.appendChild(el("option", { value: "", text: blankLabel }));
  }
  for (const opt of options) {
    select.appendChild(el("option", { value: String(opt.value), text: opt.label }));
  }
  if (prev && [...select.options].some((o) => o.value === prev)) select.value = prev;
}

// Standard "Evan / Spouse / Joint" person <select>. Value "" = everyone,
// "joint" = untagged only, otherwise a numeric person id.
function fillPersonFilter(select, people) {
  fillSelect(
    select,
    [{ value: "joint", label: "Joint only" }, ...people.map((p) => ({ value: p.id, label: p.name }))],
    { blankLabel: "Everyone" }
  );
}

// --- entry forms (recurring items + one-time transactions) --------------
//
// A recurring item and a one-off transaction are different shapes in the
// DB, but you add them from one place: the "+ Add" form below has a
// "Repeats" toggle that swaps the schedule fields in for the date field
// and decides which endpoint the submit hits. Used by the Budget page and
// the Overview quick-add. Edit forms stay type-specific (see budget.js).

const MONTH_OPTIONS = MONTH_NAMES.map((n, i) => ({ value: i + 1, label: n }));
const _opt = (v, label, cur) =>
  `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${label}</option>`;
const escAttr = (s) => (s == null ? "" : String(s).replace(/"/g, "&quot;"));
const escText = (s) => (s == null ? "" : String(s).replace(/</g, "&lt;"));

function recurringScheduleBlockHTML(it) {
  it = it || {};
  return `
    <div class="fin-recurring-block">
      <div class="field-row">
        <div class="field">
          <label>Frequency</label>
          <select name="frequency">
            ${_opt("monthly", "Monthly", it.frequency || "monthly")}
            ${_opt("quarterly", "Quarterly", it.frequency || "monthly")}
            ${_opt("semiannual", "Semi-annual", it.frequency || "monthly")}
            ${_opt("annual", "Annual", it.frequency || "monthly")}
          </select>
        </div>
        <div class="field fin-anchor-field">
          <label>First month it hits</label>
          <select name="anchor_month">${MONTH_OPTIONS.map((m) => _opt(m.value, m.label, it.anchor_month || "")).join("")}</select>
        </div>
        <div class="field">
          <label>Day of month</label>
          <input name="day_of_month" type="number" min="1" max="31" value="${it.day_of_month || ""}" placeholder="opt." />
        </div>
      </div>
      <div class="field-row">
        <div class="field"><label>Starts (optional)</label><input name="start_month" type="month" value="${it.start_month || ""}" /></div>
        <div class="field"><label>Ends (optional)</label><input name="end_month" type="month" value="${it.end_month || ""}" /></div>
      </div>
    </div>`;
}

function onetimeBlockHTML(t) {
  t = t || {};
  const today = new Date().toISOString().slice(0, 10);
  return `
    <div class="fin-onetime-block">
      <div class="field-row">
        <div class="field">
          <label>Date <span class="required">*</span></label>
          <input name="date" type="date" value="${t.date || today}" />
        </div>
        <div class="field">
          <label>Account (optional)</label>
          <input name="account_name" type="text" value="${escAttr(t.account_name)}" placeholder="e.g. Chase checking" />
        </div>
      </div>
    </div>`;
}

// The combined add form body (no <form> wrapper, no action buttons).
function entryAddFieldsHTML() {
  return `
    <label class="checkbox-label"><input name="repeats" type="checkbox" /> Repeats on a schedule</label>
    <div class="field">
      <label><span data-role="name-text">Description</span> <span class="required">*</span></label>
      <input name="name" type="text" required placeholder="e.g. New water heater" />
    </div>
    <div class="field-row">
      <div class="field">
        <label>Amount ($) <span class="required">*</span></label>
        <input name="amount" type="text" inputmode="decimal" required placeholder="1200.00" />
      </div>
      <div class="field">
        <label>Direction</label>
        <select name="direction">${_opt("out", "Money out", "out")}${_opt("in", "Money in", "out")}</select>
      </div>
    </div>
    ${onetimeBlockHTML(null)}
    ${recurringScheduleBlockHTML(null)}
    <div class="field-row">
      <div class="field"><label>Category</label><select name="category_id"></select></div>
      <div class="field"><label>Person</label><select name="person_id"></select></div>
    </div>
    <div class="field"><label>Notes</label><textarea name="notes" rows="2" placeholder="Optional"></textarea></div>`;
}

// Populate selects and wire the Repeats + frequency toggles on a combined
// add form. `scope` is the <form> (or any wrapping element).
function wireEntryForm(scope, people, categories) {
  fillSelect(scope.querySelector('[name="category_id"]'), categories.map((c) => ({ value: c.id, label: c.name })), { blankLabel: "— none —" });
  fillSelect(scope.querySelector('[name="person_id"]'), people.map((p) => ({ value: p.id, label: p.name })), { blankLabel: "Joint" });

  const repeats = scope.querySelector('[name="repeats"]');
  const recBlock = scope.querySelector(".fin-recurring-block");
  const oneBlock = scope.querySelector(".fin-onetime-block");
  const nameText = scope.querySelector('[data-role="name-text"]');
  const freq = scope.querySelector('[name="frequency"]');
  const anchorField = scope.querySelector(".fin-anchor-field");
  const dateInput = scope.querySelector('[name="date"]');

  const sync = () => {
    const r = repeats.checked;
    if (!r) freq.value = "monthly"; // don't carry a stale cadence into a one-off
    recBlock.classList.toggle("hidden", !r);
    oneBlock.classList.toggle("hidden", r);
    nameText.textContent = r ? "Name" : "Description";
    anchorField.classList.toggle("hidden", freq.value === "monthly");
    if (dateInput) dateInput.required = !r;
  };
  repeats.addEventListener("change", sync);
  freq.addEventListener("change", sync);
  sync();
}

// Read a combined add form into { type, body } ready to POST.
function readEntryForm(scope) {
  const g = (n) => scope.querySelector(`[name="${n}"]`);
  const base = {
    amount_cents: dollarsToCents(g("amount").value),
    direction: g("direction").value,
    category_id: g("category_id").value || null,
    person_id: g("person_id").value || null,
    notes: g("notes").value.trim() || null,
  };
  if (g("repeats").checked) {
    const monthly = g("frequency").value === "monthly";
    return {
      type: "recurring",
      body: {
        ...base,
        name: g("name").value.trim(),
        frequency: g("frequency").value,
        anchor_month: monthly ? null : Number(g("anchor_month").value),
        day_of_month: g("day_of_month").value ? Number(g("day_of_month").value) : null,
        start_month: g("start_month").value || null,
        end_month: g("end_month").value || null,
        active: true,
      },
    };
  }
  return {
    type: "transaction",
    body: {
      ...base,
      description: g("name").value.trim(),
      date: g("date").value,
      account_name: g("account_name").value.trim() || null,
    },
  };
}

function entryValidationError({ type, body }) {
  if (type === "recurring" && !body.name) return "Name is required.";
  if (type === "transaction" && !body.description) return "Description is required.";
  if (type === "transaction" && !body.date) return "Date is required.";
  if (body.amount_cents == null || body.amount_cents <= 0) return "Enter a dollar amount greater than zero.";
  return null;
}

async function submitEntry({ type, body }) {
  const path = type === "recurring" ? "recurring" : "transactions";
  return fetchJSON(`${API}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
