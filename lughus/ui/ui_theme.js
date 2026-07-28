/** Persisted light/dark theme handling for the Developer Test UI. */

const STORAGE_KEY = "lughus_ui_theme";

function nextTheme(theme) {
  return theme === "light" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = document.querySelector("#theme-toggle");
  if (!button) return;
  const isLight = theme === "light";
  button.setAttribute("aria-label", `Switch to ${isLight ? "dark" : "light"} theme`);
  button.querySelector(".theme-icon").textContent = isLight ? "☾" : "☀";
  button.querySelector(".theme-label").textContent = isLight ? "Dark" : "Light";
}

export function initTheme() {
  const saved = localStorage.getItem(STORAGE_KEY);
  const initialTheme = saved === "light" || saved === "dark" ? saved : "dark";
  applyTheme(initialTheme);

  const button = document.querySelector("#theme-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    const theme = nextTheme(document.documentElement.dataset.theme);
    localStorage.setItem(STORAGE_KEY, theme);
    applyTheme(theme);
  });
}
