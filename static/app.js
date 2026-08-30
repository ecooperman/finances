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

function row(r) {
  const node = el("div", { class: "fin-item fin-item-" + r.effect });

  const main = el("div", { class: "fin-item-main" });
  if (r.kind === "recurring") {
    main.appendChild(el("span", { class: "fin-item-icon", "data-icon": "repeat", "aria-hidden": "true" }));
  }
  main.appendChild(el("span", { class: "fin-item-name", text: r.name }));
  if (r.kind === "recurring" && r.frequency && r.frequency !== "monthly") {
    main.appendChild(el("span", { class: "fin-cadence", text: freqLabel(r.frequency) }));
  }
  if (r.effect === "added") main.appendChild(el("span", { class: "fin-tag fin-tag-added", text: "added" }));
  if (r.effect === "removed") main.appendChild(el("span", { class: "fin-tag fin-tag-removed", text: "removed" }));
  if (r.effect === "modified") main.appendChild(el("span", { class: "fin-tag fin-tag-modified", text: "changed" }));

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

function renderList(container, rows) {
  container.innerHTML = "";
  if (!rows.length) {
    container.appendChild(el("p", { class: "empty-state", text: "Nothing here for this month." }));
    return;
  }
  for (const r of rows) container.appendChild(row(r));
  if (typeof applyIcons === "function") applyIcons(container);
}

// --- payment calendar (top of the page, built from the same month data) ---

const CAL_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const CAL_ENTRY_CAP = 4;

function calEntry(r) {
  const effect = r.effect && r.effect !== "normal" ? " fin-cal-e-" + r.effect : "";
  return el("div", {
    class: "fin-cal-entry fin-cal-amt-" + r.direction + effect,
    title: `${r.name} · ${fmtMoney(r.amount_cents)}` + (effect ? ` (${r.effect})` : ""),
    text: r.name,
  });
}

function renderCalendar(month, rows) {
  const cal = document.getElementById("calendar");
  const noDayEl = document.getElementById("cal-noday");
  cal.innerHTML = "";

  const [y, m] = month.split("-").map(Number);
  const byDay = new Map();
  const noDay = [];
  const addToDay = (d, r) => {
    if (!byDay.has(d)) byDay.set(d, []);
    byDay.get(d).push(r);
  };
  for (const r of rows) {
    // weekly / biweekly with a chosen weekday: one entry per occurrence,
    // the smoothed monthly amount split across them (totals stay the same).
    if (isWeeklyFreq(r.frequency) && r.day_of_week != null) {
      const occ = weekdayOccurrences(y, m, r.day_of_week, r.week_anchor, r.frequency === "biweekly");
      if (occ.length) {
        const per = Math.round(r.amount_cents / occ.length);
        occ.forEach((d, i) => {
          const amt = i === occ.length - 1 ? r.amount_cents - per * (occ.length - 1) : per;
          addToDay(d, { ...r, amount_cents: amt, day: d });
        });
        continue;
      }
    }
    if (r.day == null) {
      noDay.push(r);
      continue;
    }
    addToDay(r.day, r);
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
      for (const r of entries.slice(0, CAL_ENTRY_CAP)) cell.appendChild(calEntry(r));
      if (entries.length > CAL_ENTRY_CAP) {
        cell.appendChild(el("div", {
          class: "fin-cal-more",
          text: `+${entries.length - CAL_ENTRY_CAP} more`,
          title: entries
            .slice(CAL_ENTRY_CAP)
            .map((r) => `${r.name} · ${fmtMoney(r.amount_cents)}`)
            .join("\n"),
        }));
      }
      if (entries.length) {
        const net = entries.reduce(
          (s, r) => s + (r.direction === "in" ? r.amount_cents : -r.amount_cents),
          0
        );
        cell.appendChild(el("div", {
          class: "fin-cal-net " + (net < 0 ? "fin-net-neg" : "fin-net-pos"),
          text: fmtSignedMoney(net),
        }));
      }
    }
    grid.appendChild(cell);
  }
  cal.appendChild(grid);

  if (noDay.length) {
    noDayEl.classList.remove("hidden");
    noDayEl.textContent = "No set day: " + noDay.map((r) => r.name).join(", ");
  } else {
    noDayEl.classList.add("hidden");
  }
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
