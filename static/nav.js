// The bottom tab bar, built once here and mounted on every page via
// Global.buildNav (shared-assets/theme.js). Only the "which page is active"
// logic is app-specific and lives here.

function currentNavActive() {
  const path = window.location.pathname;
  if (path === "/recurring.html") return "recurring";
  if (path === "/transactions.html") return "transactions";
  if (path === "/scenarios.html") return "scenarios";
  if (path === "/settings.html") return "settings";
  return "monthly";
}

const active = currentNavActive();
Global.buildNav([
  { href: "/", icon: "calendar", label: "Monthly", active: active === "monthly" },
  { href: "/recurring.html", icon: "repeat", label: "Recurring", active: active === "recurring" },
  { href: "/transactions.html", icon: "wallet", label: "Transactions", active: active === "transactions" },
  { href: "/scenarios.html", icon: "sliders", label: "Scenarios", active: active === "scenarios" },
  { href: "/settings.html", icon: "settings", label: "Settings", active: active === "settings" },
  { icon: "refresh", label: "Refresh", onclick: () => location.reload() },
]);
