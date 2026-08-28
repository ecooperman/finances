// Scenarios - saved "what-if" bundles. Each scenario holds a list of
// adjustments (add a hypothetical line / remove an existing recurring item
// / scale or override one). The Monthly page overlays a scenario and shows
// its net next to the real net. Adjustments are add + delete here; editing
// one = delete and re-add.

const listEl = document.getElementById("list");
const emptyEl = document.getElementById("empty");
const countEl = document.getElementById("count");
const addForm = document.getElementById("add-form");

let PEOPLE = [];
let CATEGORIES = [];
let RECURRING = [];

const MONTH_OPTIONS = MONTH_NAMES.map((n, i) => ({ value: i + 1, label: n }));
const recurringName = (id) => {
  const r = RECURRING.find((x) => x.id === id);
  return r ? r.name : `item #${id}`;
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
  if (a.kind === "add") {
    const bits = [freqLabel(a.frequency || "monthly").toLowerCase(), a.direction === "in" ? "in" : "out"];
    return `Add "${a.name}" — ${fmtMoney(a.amount_cents)} ${bits.join(" ")}`;
  }
  if (a.kind === "remove") return `Remove "${recurringName(a.target_recurring_id)}"`;
  if (a.kind === "modify") {
    if (a.override_amount_cents != null) {
      return `Set "${recurringName(a.target_recurring_id)}" to ${fmtMoney(a.override_amount_cents)}`;
    }
    return `Scale "${recurringName(a.target_recurring_id)}" ×${a.multiplier}`;
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
      <div class="field">
        <label>Name</label>
        <input name="name" type="text" placeholder="e.g. Car payment" />
      </div>
      <div class="field-row">
        <div class="field">
          <label>Amount ($)</label>
          <input name="amount" type="text" inputmode="decimal" placeholder="450.00" />
        </div>
        <div class="field">
          <label>Direction</label>
          <select name="direction">${opt("out", "Money out")}${opt("in", "Money in")}</select>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Frequency</label>
          <select name="frequency">
            ${opt("monthly", "Monthly")}${opt("quarterly", "Quarterly")}${opt("semiannual", "Semi-annual")}${opt("annual", "Annual")}
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
        <label>Which recurring item</label>
        <select name="target_recurring_id"></select>
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
  const freq = form.querySelector('[name="frequency"]');
  const anchorField = form.querySelector(".fin-anchor-field");
  const modifyMode = form.querySelector('[name="modify_mode"]');
  const modifyLabel = form.querySelector('[data-label="modify_value"]');
  const groups = form.querySelectorAll(".fin-adj-group");

  fillSelect(form.querySelector('[name="category_id"]'), CATEGORIES.map((c) => ({ value: c.id, label: c.name })), { blankLabel: "— none —" });
  fillSelect(form.querySelector('[name="person_id"]'), PEOPLE.map((p) => ({ value: p.id, label: p.name })), { blankLabel: "Joint" });
  fillSelect(
    form.querySelector('[name="target_recurring_id"]'),
    RECURRING.map((r) => ({ value: r.id, label: `${r.name} (${fmtMoney(r.amount_cents)} ${r.direction})` })),
    { blankLabel: "— pick one —" }
  );

  const sync = () => {
    const k = kind.value;
    groups.forEach((g) => {
      const name = g.dataset.group;
      const show = (k === "add" && name === "add") || ((k === "remove" || k === "modify") && name === "target") || (k === "modify" && name === "modify");
      g.classList.toggle("hidden", !show);
    });
    anchorField.classList.toggle("hidden", freq.value === "monthly");
    modifyLabel.textContent = modifyMode.value === "multiplier" ? "Factor (e.g. 0.5)" : "Amount ($)";
  };
  kind.addEventListener("change", sync);
  freq.addEventListener("change", sync);
  modifyMode.addEventListener("change", sync);
  sync();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const g = (n) => form.querySelector(`[name="${n}"]`);
    const k = g("kind").value;
    let body = { kind: k };
    if (k === "add") {
      body = {
        kind: "add",
        name: g("name").value.trim(),
        amount_cents: dollarsToCents(g("amount").value),
        direction: g("direction").value,
        frequency: g("frequency").value,
        anchor_month: g("frequency").value === "monthly" ? null : Number(g("anchor_month").value),
        category_id: g("category_id").value || null,
        person_id: g("person_id").value || null,
      };
      if (!body.name || body.amount_cents == null || body.amount_cents <= 0) {
        return Global.showMessage("A new line needs a name and a positive amount.", "error");
      }
    } else {
      const target = Number(g("target_recurring_id").value);
      if (!target) return Global.showMessage("Pick a recurring item.", "error");
      body.target_recurring_id = target;
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
    el_("a", { class: "item-summary-icon-link", href: `/?scenario=${scenario.id}`, title: "Open in Monthly view", "data-icon": "calendar", "aria-hidden": "true" }),
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
    const [scenarios, recurring] = await Promise.all([
      fetchJSON(`${API}/scenarios`),
      fetchJSON(`${API}/recurring`),
    ]);
    RECURRING = recurring;
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
