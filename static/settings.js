// Settings - CRUD for the two reference lists (people, categories) that
// every other page reads. Deliberately plain: inline rows, no accordion.

const peopleListEl = document.getElementById("people-list");
const catListEl = document.getElementById("cat-list");

// --- people -------------------------------------------------------

function personRow(p) {
  const nameInput = Global.el("input", { type: "text", value: p.name });
  const colorInput = Global.el("input", { type: "color", value: p.color });

  const save = Global.el("button", {
    type: "button",
    class: "secondary-btn",
    text: "Save",
    onclick: async () => {
      try {
        await fetchJSON(`${API}/people/${p.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: nameInput.value.trim(), color: colorInput.value }),
        });
        Global.showMessage("Saved.", "success");
        refresh();
      } catch (err) {
        Global.showMessage(err.message, "error");
      }
    },
  });
  const del = Global.el("button", {
    type: "button",
    class: "danger-btn",
    text: "Delete",
    onclick: async () => {
      if (!confirm(`Delete "${p.name}"?`)) return;
      try {
        await fetchJSON(`${API}/people/${p.id}`, { method: "DELETE" });
        Global.showMessage("Deleted.", "success");
        refresh();
      } catch (err) {
        Global.showMessage(err.message, "error");
      }
    },
  });

  return Global.el("div", { class: "fin-settings-row" }, [colorInput, nameInput, save, del]);
}

document.getElementById("add-person-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await fetchJSON(`${API}/people`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: form.name.value.trim(), color: form.color.value }),
    });
    form.reset();
    form.color.value = "#3a6ea5";
    refresh();
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
});

// --- categories -------------------------------------------------

function catRow(c, index, all) {
  const nameInput = Global.el("input", { type: "text", value: c.name });
  const colorInput = Global.el("input", { type: "color", value: c.color });
  const textSel = Global.el("select", {}, [
    Global.el("option", { value: "dark", text: "Dark text" }),
    Global.el("option", { value: "light", text: "Light text" }),
  ]);
  textSel.value = c.text_color;

  const preview = Global.el("span", { class: "fin-chip", text: c.name || "Preview" });
  const syncPreview = () => {
    preview.textContent = nameInput.value.trim() || "Preview";
    preview.style.background = colorInput.value;
    preview.style.color = textSel.value === "light" ? "#fff" : "#1c1c1c";
  };
  [nameInput, colorInput, textSel].forEach((elm) => {
    elm.addEventListener("input", syncPreview);
    elm.addEventListener("change", syncPreview);
  });
  syncPreview();

  const save = Global.el("button", {
    type: "button",
    class: "secondary-btn",
    text: "Save",
    onclick: async () => {
      try {
        await fetchJSON(`${API}/categories/${c.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: nameInput.value.trim(),
            color: colorInput.value,
            text_color: textSel.value,
          }),
        });
        Global.showMessage("Saved.", "success");
        refresh();
      } catch (err) {
        Global.showMessage(err.message, "error");
      }
    },
  });
  const del = Global.el("button", {
    type: "button",
    class: "danger-btn",
    text: "Delete",
    onclick: async () => {
      if (!confirm(`Delete "${c.name}"?`)) return;
      try {
        await fetchJSON(`${API}/categories/${c.id}`, { method: "DELETE" });
        Global.showMessage("Deleted.", "success");
        refresh();
      } catch (err) {
        Global.showMessage(err.message, "error");
      }
    },
  });

  const move = async (dir) => {
    const order = all.map((x) => x.id);
    const j = index + dir;
    if (j < 0 || j >= order.length) return;
    [order[index], order[j]] = [order[j], order[index]];
    try {
      await fetchJSON(`${API}/categories/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ordered_ids: order }),
      });
      refresh();
    } catch (err) {
      Global.showMessage(err.message, "error");
    }
  };
  const up = Global.el("button", { type: "button", class: "fin-move", text: "▲", title: "Move up", onclick: () => move(-1) });
  const down = Global.el("button", { type: "button", class: "fin-move", text: "▼", title: "Move down", onclick: () => move(1) });

  return Global.el("div", { class: "fin-settings-row fin-cat-row" }, [
    Global.el("span", { class: "fin-move-group" }, [up, down]),
    colorInput,
    nameInput,
    textSel,
    preview,
    save,
    del,
  ]);
}

document.getElementById("add-cat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await fetchJSON(`${API}/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: form.name.value.trim(), color: form.color.value, text_color: "light" }),
    });
    form.reset();
    form.color.value = "#3f7d5c";
    refresh();
  } catch (err) {
    Global.showMessage(err.message, "error");
  }
});

// --- load -----------------------------------------------------

async function refresh() {
  const [people, categories] = await Promise.all([loadPeople(true), loadCategories(true)]);
  peopleListEl.innerHTML = "";
  people.forEach((p) => peopleListEl.appendChild(personRow(p)));
  catListEl.innerHTML = "";
  categories.forEach((c, i) => catListEl.appendChild(catRow(c, i, categories)));
}

refresh();
