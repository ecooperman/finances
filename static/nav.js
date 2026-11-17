// The bottom tab bar, built once here and mounted on every page via
// Global.buildNav (shared-assets/theme.js). Only the "which page is active"
// logic is app-specific and lives here.

function currentNavActive() {
  const path = window.location.pathname;
  if (path === "/budget.html") return "budget";
  if (path === "/scenarios.html") return "scenarios";
  if (path === "/settings.html") return "settings";
  if (path === "/users.html") return "users";
  return "overview";
}

const active = currentNavActive();

// Built straight away, then rebuilt once we know who is signed in: only an administrator can let people in, so only
// they get a Users tab.
function buildFinancesNav(me) {
  const items = [
    { href: "/", icon: "calendar", label: "Overview", active: active === "overview" },
    { href: "/budget.html", icon: "wallet", label: "Budget", active: active === "budget" },
    { href: "/scenarios.html", icon: "sliders", label: "Scenarios", active: active === "scenarios" },
    { href: "/settings.html", icon: "settings", label: "Settings", active: active === "settings" },
    { icon: "refresh", label: "Refresh", onclick: () => location.reload() },
  ];
  if (me && me.is_admin) items.splice(4, 0, { href: "/users.html", icon: "users", label: "Users", active: active === "users" });
  Global.buildNav(items);
}

buildFinancesNav(null);
Global.currentUser().then((me) => {
  if (me && me.is_admin) buildFinancesNav(me);
});

// The signed-in person's email and a Log out link in the page header (this app signs in through the shared
// front door; /api/me says where Log out goes).
Global.mountUserBadge();
