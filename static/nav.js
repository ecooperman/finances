// The bottom tab bar, built once here and mounted on every page via
// Global.buildNav (shared-assets/theme.js). Only the "which page is active"
// logic is app-specific and lives here.

function currentNavActive() {
  const path = window.location.pathname;
  if (path === "/budget.html") return "budget";
  if (path === "/scenarios.html") return "scenarios";
  if (path === "/settings.html") return "settings";
  return "overview";
}

const active = currentNavActive();
Global.buildNav([
  { href: "/", icon: "calendar", label: "Overview", active: active === "overview" },
  { href: "/budget.html", icon: "wallet", label: "Budget", active: active === "budget" },
  { href: "/scenarios.html", icon: "sliders", label: "Scenarios", active: active === "scenarios" },
  { href: "/settings.html", icon: "settings", label: "Settings", active: active === "settings" },
  { icon: "refresh", label: "Refresh", onclick: () => location.reload() },
]);
