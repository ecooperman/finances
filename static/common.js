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
