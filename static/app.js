// Overview - the month dashboard. Combines the recurring items that land in
// the selected month with any one-time transactions dated that month, split
// into money-in / money-out, with a net at the bottom. An optional saved
// scenario is overlaid server-side (see /api/monthly) and its net is shown
// next to the real one. The "+ Add" here is the same unified form as the
// Budget page (common.js) - a Repeats toggle picks transaction vs recurring.

const state = {
  month: thisMonth(),
  personVal: "", // "" everyone | "joint" | numeric person id
  categoryIds: [], // array of string ids
  scenarioId: new URLSearchParams(location.search).get("scenario") || "", // "" = actual
};

const monthLabelEl = document.getElementById("month-label");
const personSelect = document.getElementById("filter-person");
const categoryMount = document.getElementById("filter-category");
const scenarioSelect = document.getElementById("filter-scenario");
const inList = document.getElementById("money-in");
const outList = document.getElementById("money-out");
const inCount = document.getElementById("in-count");
const outCount = document.getElementById("out-count");
const totalsEl = document.getElementById("totals");

// --- rows --------------------------------------------------------------

// "2026-09" -> "Sep" (short, for tags); monthLabel() gives the long form.
function shortMonth(ym) {
  return MONTH_NAMES[Number(ym.slice(5, 7)) - 1].slice(0, 3);
}

// A daily-spread day counts at what was logged, else at its allowance.
function dailyEffective(d) {
  return d.entries.length ? d.spent_cents : d.allowance_cents;
}

// Scenario-removed and carried-to-next-month rows are shown but not counted.
function countsInTotals(r) {
  return r.effect !== "removed" && r.effect !== "deferred";
}

function row(r) {
  const node = el("div", { class: "fin-item fin-item-" + r.effect });

  const main = el("div", { class: "fin-item-main" });
  if (r.kind === "recurring") {
    main.appendChild(el("span", { class: "fin-item-icon", "data-icon": "repeat", "aria-hidden": "true" }));
  }
  main.appendChild(el("span", { class: "fin-item-name", text: r.name }));
  if (r.kind === "recurring" && r.frequency && r.frequency !== "monthly") {
    const n = r.occurrence_days ? r.occurrence_days.length : 0;
    main.appendChild(el("span", {
      class: "fin-cadence",
      text: freqLabel(r.frequency) + (n > 1 ? ` · ${n}×` : ""),
      title: n > 1 ? `${n} pay days this month, ${fmtMoney(r.face_amount_cents)} each` : "",
    }));
  }
  if (r.daily) {
    const logged = r.daily.filter((d) => d.entries.length).length;
    main.appendChild(el("span", {
      class: "fin-cadence",
      text: `Daily · ${fmtMoney(r.daily[0].allowance_cents)}/day` + (logged ? ` · ${logged} logged` : ""),
      title: "Spread across every day of the month. Click a day on the calendar to log what you spent.",
    }));
  }
  if (r.effect === "added") main.appendChild(el("span", { class: "fin-tag fin-tag-added", text: "added" }));
  if (r.effect === "removed") main.appendChild(el("span", { class: "fin-tag fin-tag-removed", text: "removed" }));
  if (r.effect === "modified") main.appendChild(el("span", { class: "fin-tag fin-tag-modified", text: "changed" }));
  if (r.kind === "carryover") {
    main.appendChild(el("span", { class: "fin-tag fin-tag-carry", text: `carried from ${shortMonth(r.carried_from)}` }));
  }
  if (r.effect === "deferred") {
    main.appendChild(el("span", { class: "fin-tag fin-tag-deferred", text: `carried to ${shortMonth(r.deferred_to)}` }));
  }

  const meta = el("div", { class: "fin-item-meta" }, [categoryChip(r.category), personBadge(r.person)]);

  const amountText = fmtMoney(r.amount_cents);
  const amount = el("div", { class: "fin-item-amount fin-amount-" + r.direction });
  if (r.effect === "modified" && r.original_amount_cents != null) {
    amount.appendChild(el("span", { class: "fin-amount-was", text: fmtMoney(r.original_amount_cents) }));
    amount.appendChild(el("span", { text: amountText }));
  } else {
    amount.appendChild(el("span", { text: amountText }));
  }

  node.appendChild(el("div", { class: "fin-item-left" }, [main, meta]));
  node.appendChild(amount);
  return node;
}

// Rows are grouped under a tiny date gutter ("Fri / 16"). Weekly/biweekly
// items with a weekday sit in a per-weekday group ("Fri ↻"); items with no
// day at all go last under "—".
function dayGroupOf(r) {
  const [y, m] = state.month.split("-").map(Number);
  if (r.daily) {
    return { key: "daily", order: 99, top: "Daily", bottom: "↻", title: "Spent every day" };
  }
  if (r.day != null) {
    const dt = new Date(y, m - 1, r.day);
    return {
      key: "d" + r.day, order: r.day, top: CAL_WEEKDAYS[dt.getDay()], bottom: String(r.day),
      title: dt.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }),
    };
  }
  if (r.occurrence_days && r.occurrence_days.length && r.day_of_week != null) {
    return {
      key: "w" + r.day_of_week, order: 100 + r.day_of_week, top: CAL_WEEKDAYS[r.day_of_week],
      bottom: "↻", title: `Repeats on ${WEEKDAY_NAMES[r.day_of_week]}s`,
    };
  }
  return { key: "none", order: 1000, top: "—", bottom: "", title: "No day set" };
}

function renderList(container, rows) {
  container.innerHTML = "";
  if (!rows.length) {
    container.appendChild(el("p", { class: "empty-state", text: "Nothing here for this month." }));
    return;
  }
  const groups = new Map();
  for (const r of rows) {
    const g = dayGroupOf(r);
    if (!groups.has(g.key)) groups.set(g.key, { ...g, rows: [] });
    groups.get(g.key).rows.push(r);
  }
  for (const g of [...groups.values()].sort((x, y) => x.order - y.order)) {
    container.appendChild(el("div", { class: "fin-daygroup" }, [
      el("div", { class: "fin-daygroup-date", title: g.title }, [
        el("span", { class: "fin-daygroup-top", text: g.top }),
        el("span", { class: "fin-daygroup-num", text: g.bottom }),
      ]),
      el("div", { class: "fin-daygroup-items" }, g.rows.map(row)),
    ]));
  }
  if (typeof applyIcons === "function") applyIcons(container);
}

// --- payment calendar (top of the page, built from the same month data) ---

const CAL_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const CAL_ENTRY_CAP = 4;
let CAL_BY_DAY = new Map();
let CAL_MONTH = "";
let CAL_RUN = new Map(); // day -> month-to-date net after that day

// Net of a day's entries; scenario-removed rows don't count.
function dayNet(entries) {
  return entries
    .filter(countsInTotals)
    .reduce((s, r) => s + (r.direction === "in" ? r.amount_cents : -r.amount_cents), 0);
}

function calEntry(r) {
  const effect = r.effect && r.effect !== "normal" ? " fin-cal-e-" + r.effect : "";
  const carry = r.kind === "carryover";
  return el("div", {
    class: "fin-cal-entry fin-cal-amt-" + r.direction + effect + (carry ? " fin-cal-e-carry" : ""),
    title: `${r.name} · ${fmtMoney(r.amount_cents)}`
      + (carry ? ` (carried over from ${monthLabel(r.carried_from)})` : "")
      + (r.effect === "deferred" ? ` (carried to ${monthLabel(r.deferred_to)})` : effect && !carry ? ` (${r.effect})` : ""),
    text: (carry ? "↪ " : "") + r.name,
  });
}

// One chip per day for all the daily-spread items together. Muted when a
// past day has an item with nothing logged (it's counting the allowance).
function dailyChip(dailies, pastDay) {
  const live = dailies.filter(countsInTotals);
  const total = live.reduce((s, r) => s + r.amount_cents, 0);
  const anyLogged = live.some((r) => r.daily_day.entries.length);
  const assumed = pastDay && live.some((r) => !r.daily_day.entries.length);
  return el("div", {
    class: "fin-cal-entry fin-cal-amt-out fin-cal-daily" + (assumed ? " fin-cal-daily-assumed" : ""),
    title: dailies
      .map((r) => `${r.name} · ${fmtMoney(r.amount_cents)} `
        + (r.daily_day.entries.length ? "(logged)" : `(planned${assumed ? ", nothing logged" : ""})`))
      .join("\n"),
    text: `${anyLogged ? "✎ " : ""}Daily ${fmtMoney(total)}`,
  });
}

function renderCalendar(month, rows) {
  const cal = document.getElementById("calendar");
  const noDayEl = document.getElementById("cal-noday");
  cal.innerHTML = "";

  const [y, m] = month.split("-").map(Number);
  const byDay = new Map();
  CAL_BY_DAY = byDay;
  CAL_MONTH = month;
  const noDay = [];
  const addToDay = (d, r) => {
    if (!byDay.has(d)) byDay.set(d, []);
    byDay.get(d).push(r);
  };
  for (const r of rows) {
    // daily-spread: one entry per day (effective amount), tagged so the
    // cell can fold them into a single "Daily $X" chip
    if (r.daily) {
      for (const d of r.daily) {
        addToDay(d.day, { ...r, day: d.day, amount_cents: dailyEffective(d), daily_day: d });
      }
      continue;
    }
    // weekly / biweekly with a weekday set: the server gives the real pay
    // days; each shows the real per-payment amount (not the smoothed one).
    if (r.occurrence_days && r.occurrence_days.length) {
      const amt = r.face_amount_cents != null ? r.face_amount_cents : r.amount_cents;
      for (const d of r.occurrence_days) addToDay(d, { ...r, amount_cents: amt, day: d });
      continue;
    }
    if (r.day == null) {
      noDay.push(r);
      continue;
    }
    addToDay(r.day, r);
  }

  // Running total: month-to-date net (starts at $0 on the 1st) over every
  // dated item, so a payday lifts it and the loans around it pull it down.
  CAL_RUN = new Map();
  let running = 0;
  for (let d = 1; d <= new Date(y, m, 0).getDate(); d++) {
    running += dayNet(byDay.get(d) || []);
    CAL_RUN.set(d, running);
  }

  const head = el("div", { class: "fin-cal-head" });
  for (const w of CAL_WEEKDAYS) head.appendChild(el("div", { class: "fin-cal-hcell", text: w }));
  cal.appendChild(head);

  const startDow = new Date(y, m - 1, 1).getDay();
  const daysInMonth = new Date(y, m, 0).getDate();
  const cellCount = Math.ceil((startDow + daysInMonth) / 7) * 7;
  const todayDay = month === thisMonth() ? new Date().getDate() : -1;

  const grid = el("div", { class: "fin-cal-grid" });
  for (let i = 0; i < cellCount; i++) {
    const dayNum = i - startDow + 1;
    const inMonth = dayNum >= 1 && dayNum <= daysInMonth;
    const cell = el("div", {
      class:
        "fin-cal-cell" +
        (inMonth ? "" : " fin-cal-out") +
        (dayNum === todayDay ? " fin-cal-today" : ""),
    });
    if (inMonth) {
      cell.appendChild(el("div", { class: "fin-cal-date", text: String(dayNum) }));
      const entries = byDay.get(dayNum) || [];
      const plain = entries.filter((r) => !r.daily_day);
      for (const r of plain.slice(0, CAL_ENTRY_CAP)) cell.appendChild(calEntry(r));
      const dailies = entries.filter((r) => r.daily_day);
      if (dailies.length) {
        const pastDay = month < thisMonth() || (month === thisMonth() && dayNum < todayDay);
        cell.appendChild(dailyChip(dailies, pastDay));
      }
      if (plain.length > CAL_ENTRY_CAP) {
        cell.appendChild(el("div", {
          class: "fin-cal-more",
          text: `+${plain.length - CAL_ENTRY_CAP} more`,
          title: plain
            .slice(CAL_ENTRY_CAP)
            .map((r) => `${r.name} · ${fmtMoney(r.amount_cents)}`)
            .join("\n"),
        }));
      }
      if (entries.length) {
        cell.classList.add("fin-cal-clickable");
        cell.setAttribute("role", "button");
        cell.setAttribute("tabindex", "0");
        cell.setAttribute("aria-label", `Details for day ${dayNum}`);
        cell.addEventListener("click", () => openDayModal(dayNum));
        cell.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openDayModal(dayNum);
          }
        });
        const net = dayNet(entries);
        const run = CAL_RUN.get(dayNum);
        cell.appendChild(el("div", {
          class: "fin-cal-net " + (net < 0 ? "fin-net-neg" : "fin-net-pos"),
          text: fmtSignedMoney(net),
          title: "Net for the day",
        }));
        cell.appendChild(el("div", {
          class: "fin-cal-run " + (run < 0 ? "fin-net-neg" : "fin-net-pos"),
          text: "Σ " + fmtSignedMoney(run),
          title: "Running total for the month through this day",
        }));
      }
    }
    grid.appendChild(cell);
  }
  cal.appendChild(grid);

  renderCarryNote(month, rows);

  if (noDay.length) {
    noDayEl.classList.remove("hidden");
    noDayEl.textContent = "No set day (not in the running total): " + noDay.map((r) => r.name).join(", ");
  } else {
    noDayEl.classList.add("hidden");
  }
}

// One line under the calendar: what rolled in from last month, and what was
// pushed to next month (neither is hidden in the lists - this is the summary).
function renderCarryNote(month, rows) {
  const note = document.getElementById("cal-carry");
  const carriedIn = rows.filter((r) => r.kind === "carryover" && r.effect !== "deferred");
  const pushed = rows.filter((r) => r.effect === "deferred");
  const sum = (list) => list.reduce((s, r) => s + r.amount_cents, 0);
  const parts = [];
  if (carriedIn.length) {
    parts.push(`Carried in from last month: ${carriedIn.length} item${carriedIn.length === 1 ? "" : "s"}, `
      + `${fmtMoney(sum(carriedIn))} (counted this month)`);
  }
  if (pushed.length) {
    parts.push(`Carried to ${monthLabel(pushed[0].deferred_to)}: ${pushed.length} item${pushed.length === 1 ? "" : "s"}, `
      + `${fmtMoney(sum(pushed))} (not counted this month)`);
  }
  note.textContent = parts.join(" · ");
  note.classList.toggle("hidden", !parts.length);
}

function totalsBlock(title, totals, { muted } = {}) {
  return el("div", { class: "fin-total-group" + (muted ? " fin-total-muted" : "") }, [
    el("div", { class: "fin-total-title", text: title }),
    el("div", { class: "fin-total-row" }, [
      el("span", { text: "Money in" }),
      el("span", { class: "fin-amount-in", text: fmtMoney(totals.in_cents) }),
    ]),
    el("div", { class: "fin-total-row" }, [
      el("span", { text: "Money out" }),
      el("span", { class: "fin-amount-out", text: fmtMoney(totals.out_cents) }),
    ]),
    el("div", { class: "fin-total-row fin-total-net" }, [
      el("span", { text: "Net" }),
      el("span", {
        class: "fin-net " + (totals.net_cents < 0 ? "fin-net-neg" : "fin-net-pos"),
        text: fmtSignedMoney(totals.net_cents),
      }),
    ]),
  ]);
}

function renderTotals(data) {
  totalsEl.innerHTML = "";
  totalsEl.appendChild(totalsBlock("This month (cash flow)", data.totals));
  totalsEl.appendChild(
    el("p", { class: "fin-normalized" }, [
      "Provisioned — recurring smoothed + funds + trips: ",
      el("strong", { text: fmtSignedMoney(data.normalized.net_cents) }),
    ])
  );
  if (FUNDS_STATUS) {
    const f = FUNDS_STATUS;
    let text = `Funds: ${f.active_count} active · ${fmtMoney(f.monthly_total_cents)}/mo set aside · ${fmtMoney(f.banked_total_cents)} banked`;
    if (TRIPS_STATUS && TRIPS_STATUS.upcoming_count) {
      text += `  ·  Trips: ${TRIPS_STATUS.upcoming_count} upcoming, ${fmtMoney(TRIPS_STATUS.monthly_total_cents)}/mo`;
    }
    totalsEl.appendChild(el("p", { class: "fin-normalized", text }));
  }

  if (data.scenario) {
    totalsEl.appendChild(totalsBlock(`Scenario: ${data.scenario.name}`, data.scenario.totals));
    const d = data.scenario.delta;
    const nd = data.scenario.normalized_delta;
    const deltaLine = (label, cents) =>
      el("p", { class: "fin-delta" }, [
        `${label} `,
        el("strong", { class: cents < 0 ? "fin-net-neg" : "fin-net-pos", text: fmtSignedMoney(cents) }),
      ]);
    totalsEl.appendChild(deltaLine("Scenario changes cash-flow net by", d.net_cents));
    if (nd.net_cents !== d.net_cents) {
      totalsEl.appendChild(deltaLine("… and provisioned net by", nd.net_cents));
    }
  }
}

// --- data ------------------------------------------------------------------

function buildQuery() {
  const p = new URLSearchParams();
  p.set("month", state.month);
  if (state.personVal === "joint") p.set("joint", "true");
  else if (state.personVal) p.set("person_id", state.personVal);
  for (const id of state.categoryIds) p.append("category_ids", id);
  if (state.scenarioId) p.set("scenario_id", state.scenarioId);
  return p.toString();
}

let FUNDS_STATUS = null;
let TRIPS_STATUS = null;

async function render() {
  monthLabelEl.textContent = monthLabel(state.month);
  try {
    const [data, fundsSummary, tripsSummary] = await Promise.all([
      fetchJSON(`${API}/monthly?${buildQuery()}`),
      fetchJSON(`${API}/funds/summary?month=${state.month}`).catch(() => null),
      fetchJSON(`${API}/trips/summary?month=${state.month}`).catch(() => null),
    ]);
    FUNDS_STATUS = fundsSummary;
    TRIPS_STATUS = tripsSummary;
    const inRows = data.scenario ? data.scenario.money_in : data.money_in;
    const outRows = data.scenario ? data.scenario.money_out : data.money_out;
    renderCalendar(state.month, [...inRows, ...outRows]);
    renderList(inList, inRows);
    renderList(outList, outRows);
    inCount.textContent = `${inRows.length} item${inRows.length === 1 ? "" : "s"}`;
    outCount.textContent = `${outRows.length} item${outRows.length === 1 ? "" : "s"}`;
    renderTotals(data);
    loadPaycheck();
    loadToday();
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
}

// --- filters -------------------------------------------------------------

let PEOPLE = [];
let CATEGORIES = [];
let FUNDS = [];

async function initFilters() {
  const [people, categories, scenarios, funds] = await Promise.all([
    loadPeople(),
    loadCategories(),
    loadScenarios(),
    fetchJSON(`${API}/funds`),
  ]);
  PEOPLE = people;
  CATEGORIES = categories;
  FUNDS = funds;

  fillPersonFilter(personSelect, people);
  personSelect.value = state.personVal;
  personSelect.addEventListener("change", () => {
    state.personVal = personSelect.value;
    render();
  });

  const multi = Global.buildMultiSelect({
    options: categories.map((c) => ({ value: c.id, label: c.name, color: c.color })),
    selected: state.categoryIds,
    placeholder: "All categories",
    onChange: (selected) => {
      state.categoryIds = selected;
      render();
    },
  });
  categoryMount.replaceWith(multi);

  fillSelect(
    scenarioSelect,
    scenarios.map((s) => ({ value: s.id, label: s.name })),
    { blankLabel: "Actual (no scenario)" }
  );
  scenarioSelect.value = state.scenarioId;
  scenarioSelect.addEventListener("change", () => {
    state.scenarioId = scenarioSelect.value;
    render();
  });
}

// --- month stepper -----------------------------------------------------

document.getElementById("month-prev").addEventListener("click", () => {
  state.month = shiftMonth(state.month, -1);
  render();
});
document.getElementById("month-next").addEventListener("click", () => {
  state.month = shiftMonth(state.month, 1);
  render();
});
document.getElementById("month-today").addEventListener("click", () => {
  state.month = thisMonth();
  render();
});

// --- unified quick-add (transaction or recurring item) ----------------

const addForm = document.getElementById("add-entry-form");

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

document.getElementById("show-add").addEventListener("click", () => {
  addForm.classList.toggle("hidden");
  if (!addForm.classList.contains("hidden")) addForm.querySelector('[name="name"]').focus();
});

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
    render();
  } catch (err2) {
    Global.showMessage(err2.message, "error");
  }
});

// --- go ----------------------------------------------------------------

initFilters().then(() => {
  buildAddForm();
  render();
});


// --- day detail modal (click a calendar day) ---

// --- logging real costs against a daily-spread item ---

function isoDay(month, day) {
  return `${month}-${String(day).padStart(2, "0")}`;
}

async function logSpend(itemId, isoDate, amountText, noteText) {
  const cents = dollarsToCents(amountText);
  if (cents == null || cents <= 0) {
    Global.showMessage("Enter a dollar amount greater than zero.", "error");
    return false;
  }
  try {
    await fetchJSON(`${API}/daily-spend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recurring_item_id: itemId, date: isoDate, amount_cents: cents, note: noteText.trim() || null,
      }),
    });
    return true;
  } catch (err) {
    Global.showMessage(err.message, "error");
    return false;
  }
}

async function removeSpend(entryId) {
  try {
    await fetchJSON(`${API}/daily-spend/${entryId}`, { method: "DELETE" });
    return true;
  } catch (err) {
    Global.showMessage(err.message, "error");
    return false;
  }
}

// "$18.00 airport  x" lines plus an add row - shared by the day modal and
// the Today card. `onChange` re-renders after any add/remove.
function spendEntriesEditor(itemId, isoDate, entries, onChange) {
  const list = el("div", { class: "fin-spend-list" }, entries.map((e) =>
    el("div", { class: "fin-spend-entry" }, [
      el("span", { class: "fin-spend-amt", text: fmtMoney(e.amount_cents) }),
      el("span", { class: "fin-spend-note", text: e.note || "" }),
      el("button", {
        type: "button", class: "fin-spend-del", title: "Remove this cost", "aria-label": "Remove this cost",
        text: "×", onclick: async () => { if (await removeSpend(e.id)) onChange(); },
      }),
    ])));
  const amount = el("input", { type: "text", inputmode: "decimal", placeholder: "$ spent", "aria-label": "Amount spent" });
  const note = el("input", { type: "text", placeholder: "note (optional)", "aria-label": "Note" });
  const submit = async () => {
    if (await logSpend(itemId, isoDate, amount.value, note.value)) onChange();
  };
  const add = el("form", { class: "fin-spend-add" }, [
    amount, note, el("button", { type: "submit", class: "fin-spend-btn", text: "Add" }),
  ]);
  add.addEventListener("submit", (ev) => { ev.preventDefault(); submit(); });
  return el("div", { class: "fin-spend-editor" }, [list, add]);
}

function overUnderText(cents) {
  return cents > 0 ? `${fmtMoney(cents)} over` : cents < 0 ? `${fmtMoney(-cents)} under` : "on budget";
}

function dailyItemBlock(r, dayNum) {
  const d = r.daily_day;
  const logged = d.entries.length > 0;
  const diff = d.spent_cents - d.allowance_cents;
  const head = el("div", { class: "fin-day-item-head" }, [
    el("span", { class: "fin-day-item-name", text: r.name }),
    el("span", { class: "fin-day-item-amt fin-amount-out", text: "−" + fmtMoney(r.amount_cents) }),
  ]);
  const chips = [
    el("span", { class: "fin-cadence", text: "Daily" }),
    categoryChip(r.category),
    personBadge(r.person),
  ];
  const summary = el("div", { class: "fin-day-item-detail" }, [
    `Allowance ${fmtMoney(d.allowance_cents)} · `,
    logged
      ? el("span", { class: diff > 0 ? "fin-net-neg" : "fin-net-pos", text: `spent ${fmtMoney(d.spent_cents)} (${overUnderText(diff)})` })
      : "nothing logged - counting the allowance",
  ]);
  const editor = spendEntriesEditor(r.id, isoDay(CAL_MONTH, dayNum), d.entries, async () => {
    await render();
    openDayModal(dayNum);
  });
  return el("div", { class: "fin-day-item fin-day-item-daily" }, [
    head, el("div", { class: "fin-day-item-chips" }, chips), summary, editor,
  ]);
}

async function changeDeferral(dayNum, send) {
  try {
    await send();
    await render();
    openDayModal(dayNum);
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
}

// "Couldn't pay this" / "undo" buttons for one item in the day modal.
function deferralActions(r, dayNum) {
  const post = (body) => fetchJSON(`${API}/deferrals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const button = (text, onClick, cls = "") => el("button", {
    type: "button", class: "fin-day-action " + cls, text, onclick: onClick,
  });
  const next = monthLabel(shiftMonthStr(CAL_MONTH, 1));

  if (r.effect === "deferred" && r.deferral_id != null) {
    return button(`Undo - I'll pay it in ${shortMonth(CAL_MONTH)}`, () =>
      changeDeferral(dayNum, () => fetchJSON(`${API}/deferrals/${r.deferral_id}`, { method: "DELETE" })));
  }
  if (r.effect !== "normal" || r.direction !== "out" || r.daily) return null;
  if (r.kind === "carryover") {
    return button(`Couldn't pay this either - carry to ${next}`, () =>
      changeDeferral(dayNum, () => post({ origin_id: r.carry_source_id })), "fin-day-action-warn");
  }
  if (r.kind === "recurring" && r.id > 0) {
    return button(`Couldn't pay this - carry to ${next}`, () =>
      changeDeferral(dayNum, () => post({ recurring_item_id: r.id, month: CAL_MONTH })), "fin-day-action-warn");
  }
  if (r.kind === "transaction") {
    return button(`Couldn't pay this - carry to ${next}`, () =>
      changeDeferral(dayNum, () => post({ transaction_id: r.id })), "fin-day-action-warn");
  }
  return null;
}

function shiftMonthStr(ym, delta) {
  const [y, m] = ym.split("-").map(Number);
  const idx = y * 12 + (m - 1) + delta;
  return `${String(Math.floor(idx / 12)).padStart(4, "0")}-${String((idx % 12) + 1).padStart(2, "0")}`;
}

function dayItemBlock(r, dayNum) {
  const isIn = r.direction === "in";
  const weekly = r.frequency === "weekly" || r.frequency === "biweekly";
  const head = el("div", { class: "fin-day-item-head" }, [
    el("span", { class: "fin-day-item-name", text: r.name }),
    el("span", { class: "fin-day-item-amt " + (isIn ? "fin-amount-in" : "fin-amount-out"),
      text: (isIn ? "+" : "−") + fmtMoney(r.amount_cents) }),
  ]);
  const chips = [
    r.kind === "carryover"
      ? null
      : el("span", { class: "fin-cadence", text: r.kind === "transaction" ? "One-time" : freqLabel(r.frequency) }),
    categoryChip(r.category),
    personBadge(r.person),
  ].filter(Boolean);
  if (r.kind === "carryover") {
    chips.push(el("span", { class: "fin-tag fin-tag-carry", text: `carried over from ${monthLabel(r.carried_from)}` }));
  }
  if (r.effect === "deferred") {
    chips.push(el("span", { class: "fin-tag fin-tag-deferred", text: `carried to ${monthLabel(r.deferred_to)}` }));
  } else if (r.effect && r.effect !== "normal") {
    chips.push(el("span", { class: "fin-tag fin-tag-" + (r.effect === "modified" ? "modified" : r.effect), text: r.effect }));
  }
  const details = [];
  if (r.kind === "recurring") {
    if (weekly && r.day_of_week != null) {
      details.push(`${r.frequency === "biweekly" ? "Every other" : "Every"} ${WEEKDAY_NAMES[r.day_of_week]}, per payment`);
    } else if (r.day != null) {
      details.push(`Due on day ${r.day} of the month`);
    }
    if (r.start_month || r.end_month) {
      details.push(
        r.start_month && r.end_month ? `Runs ${monthLabel(r.start_month)} – ${monthLabel(r.end_month)}`
        : r.end_month ? `Ends ${monthLabel(r.end_month)}` : `Started ${monthLabel(r.start_month)}`
      );
    }
    if (r.reference_id) details.push(`Reference ID: ${r.reference_id}`);
  } else {
    if (r.account_name) details.push(`Account: ${r.account_name}`);
  }
  if (r.notes) details.push(`Notes: ${r.notes}`);

  const action = deferralActions(r, dayNum);

  return el("div", { class: "fin-day-item" + (r.effect === "deferred" ? " fin-day-item-deferred" : "") }, [
    head,
    el("div", { class: "fin-day-item-chips" }, chips),
    ...details.map((d) => el("div", { class: "fin-day-item-detail", text: d })),
    action,
  ]);
}

function ordinal(n) {
  const v = n % 100;
  const suffix = ["th", "st", "nd", "rd"][(v - 20) % 10] || ["th", "st", "nd", "rd"][v] || "th";
  return n + suffix;
}

function openDayModal(dayNum) {
  const [y, m] = CAL_MONTH.split("-").map(Number);
  const entries = (CAL_BY_DAY.get(dayNum) || [])
    .slice()
    .sort((a, b) => (a.direction === b.direction ? 0 : a.direction === "in" ? -1 : 1));
  const live = entries.filter(countsInTotals);
  const inTotal = live.filter((r) => r.direction === "in").reduce((s, r) => s + r.amount_cents, 0);
  const outTotal = live.filter((r) => r.direction === "out").reduce((s, r) => s + r.amount_cents, 0);
  const net = inTotal - outTotal;

  document.getElementById("day-modal-title").textContent = new Date(y, m - 1, dayNum)
    .toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });

  const body = document.getElementById("day-modal-body");
  body.innerHTML = "";
  body.appendChild(el("div", { class: "fin-day-summary" }, [
    el("div", { class: "fin-day-net " + (net < 0 ? "fin-net-neg" : "fin-net-pos") }, [
      el("span", { class: "fin-day-net-label", text: net < 0 ? "Net out" : "Net in" }),
      el("span", { text: fmtMoney(Math.abs(net)) }),
    ]),
    el("div", { class: "fin-day-split" }, [
      el("span", {}, ["In ", el("strong", { class: "fin-amount-in", text: fmtMoney(inTotal) })]),
      el("span", {}, ["Out ", el("strong", { class: "fin-amount-out", text: fmtMoney(outTotal) })]),
    ]),
  ]));
  const run = CAL_RUN.get(dayNum);
  if (run != null) {
    body.appendChild(el("div", { class: "fin-day-run" }, [
      el("span", { text: `Running total for the month, through the ${ordinal(dayNum)}` }),
      el("strong", {
        class: run < 0 ? "fin-net-neg" : "fin-net-pos",
        text: fmtSignedMoney(run),
      }),
    ]));
  }
  body.appendChild(el("div", { class: "fin-day-items" }, entries.map((r) =>
    r.daily_day ? dailyItemBlock(r, dayNum) : dayItemBlock(r, dayNum))));
  Global.openModal("day-modal");
}

// --- "until next paycheck" card (always about today, not the month shown) ---

const paycheckPersonSelect = document.getElementById("paycheck-person");
const paycheckBody = document.getElementById("paycheck-body");

function localISODate(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtLongDate(iso) {
  const [yy, mm, dd] = iso.split("-").map(Number);
  return new Date(yy, mm - 1, dd).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

async function loadPaycheck() {
  const p = new URLSearchParams({ on: localISODate() });
  if (paycheckPersonSelect.value) p.set("person_id", paycheckPersonSelect.value);
  let d;
  try {
    d = await fetchJSON(`${API}/until-paycheck?${p.toString()}`);
  } catch (err) {
    paycheckBody.textContent = "Couldn't load the paycheck lookahead.";
    return;
  }
  paycheckBody.innerHTML = "";

  if (!d.next_paycheck) {
    paycheckBody.appendChild(el("p", { class: "empty-state", text:
      "No upcoming paycheck found. Give an income item a day (monthly) or a day of the week (weekly/biweekly) and it will show up here." }));
    return;
  }
  const nx = d.next_paycheck;
  const when = nx.days_away === 1 ? "tomorrow" : `in ${nx.days_away} days`;
  paycheckBody.appendChild(el("div", { class: "fin-paycheck-next" }, [
    el("span", { text: `Next: ${nx.name} · ${fmtLongDate(nx.date)} (${when}) · ` }),
    el("strong", { class: "fin-amount-in", text: `+${fmtMoney(nx.amount_cents)}` }),
  ]));

  paycheckBody.appendChild(el("div", { class: "fin-paycheck-total" }, [
    el("div", { class: "fin-paycheck-big fin-amount-out", text: fmtMoney(d.before_total_cents) }),
    el("div", { class: "fin-paycheck-label", text: "left to pay before then" }),
  ]));
  if (d.on_payday.length) {
    paycheckBody.appendChild(el("div", { class: "fin-paycheck-sub", text:
      `+ ${fmtMoney(d.on_payday_total_cents)} also due on payday (${d.on_payday.map((e) => e.name).join(", ")})` }));
  }

  if (d.before.length) {
    const list = el("div", { class: "fin-paycheck-list" });
    for (const e of d.before) {
      list.appendChild(el("div", { class: "fin-paycheck-row" }, [
        el("span", { class: "fin-paycheck-date", text: fmtLongDate(e.date) }),
        el("span", { class: "fin-paycheck-name", text: e.name }),
        el("span", { class: "fin-amount-out", text: fmtMoney(e.amount_cents) }),
      ]));
    }
    paycheckBody.appendChild(el("details", { class: "fin-paycheck-details" }, [
      el("summary", { text: `${d.before.length} payment${d.before.length === 1 ? "" : "s"}` }),
      list,
    ]));
  }

  if (d.undated.length) {
    paycheckBody.appendChild(el("p", { class: "fin-paycheck-warn", text:
      `Not counted (no day set): ${d.undated.map((u) => u.name).join(", ")}.` }));
  }
}

async function initPaycheck() {
  const people = await loadPeople();
  fillSelect(paycheckPersonSelect, people.map((x) => ({ value: x.id, label: `${x.name}'s` })), { blankLabel: "Anyone's" });
  paycheckPersonSelect.addEventListener("change", loadPaycheck);
}
initPaycheck();


// --- "today" card: daily-spread items, allowance vs. what's been spent ---

const todayCard = document.getElementById("today-card");
const todayBody = document.getElementById("today-body");

async function loadToday() {
  let d;
  try {
    d = await fetchJSON(`${API}/daily-budget?on=${localISODate()}`);
  } catch (err) {
    todayCard.classList.add("hidden");
    return;
  }
  todayBody.innerHTML = "";
  todayCard.classList.toggle("hidden", !d.items.length);
  document.getElementById("today-date").textContent = fmtLongDate(d.as_of);
  for (const it of d.items) todayBody.appendChild(todayItem(it, d.as_of));
}

function todayItem(it, asOf) {
  const over = it.left_today_cents < 0;
  const pct = it.allowance_cents > 0 ? Math.min(100, Math.round((it.spent_today_cents / it.allowance_cents) * 100)) : 0;
  const left = el("div", { class: "fin-today-left " + (over ? "fin-net-neg" : "fin-net-pos") }, [
    el("strong", { text: fmtMoney(Math.abs(it.left_today_cents)) }),
    el("span", { text: over ? " over today" : " left today" }),
  ]);
  const month = [
    `${fmtMoney(it.month_left_cents)} left of ${fmtMoney(it.monthly_cents)} this month`,
    it.per_day_left_cents != null
      ? `${fmtMoney(it.per_day_left_cents)}/day for the next ${it.days_left} day${it.days_left === 1 ? "" : "s"}`
      : null,
    it.logged_over_under_cents ? `${overUnderText(it.logged_over_under_cents)} on logged days` : null,
  ].filter(Boolean).join(" · ");

  return el("div", { class: "fin-today-item" }, [
    el("div", { class: "fin-today-head" }, [
      el("span", { class: "fin-today-name" }, [it.name, " ", personBadge(it.person)]),
      left,
    ]),
    el("div", { class: "fin-today-bar" + (over ? " fin-today-bar-over" : "") }, [
      el("div", { class: "fin-today-bar-fill", style: `width:${pct}%` }),
    ]),
    el("div", { class: "fin-today-sub", text: `Spent ${fmtMoney(it.spent_today_cents)} of ${fmtMoney(it.allowance_cents)} allowed today` }),
    spendEntriesEditor(it.item_id, asOf, it.entries_today, render),
    el("div", { class: "fin-today-month", text: month }),
  ]);
}
