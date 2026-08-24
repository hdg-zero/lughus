/**
 * Central State & Status Indicator management.
 */

export const state = {
  runs: [],
  activeRunId: null,
  activeAbortController: null,
  currentFilter: "all",
  searchQuery: "",
  renderMarkdown: false,
};

// Load runs from localStorage
try {
  const saved = localStorage.getItem("lughus_runs");
  if (saved) {
    state.runs = JSON.parse(saved);
    state.runs.forEach(r => {
      if (r.status === "running") r.status = "error";
    });
  }
} catch (e) {
  console.error("Failed to load runs from localStorage", e);
}

export function updateStatus(status) {
  const statusText = document.querySelector("#status");
  const statusIndicator = document.querySelector("#status-indicator");
  const appViewport = document.querySelector(".app-viewport");
  if (statusText) statusText.textContent = status;
  if (statusIndicator) statusIndicator.className = "status-dot " + status;
  if (appViewport) appViewport.dataset.status = status;
  document.documentElement.dataset.agentStatus = status;
}

export function saveRuns() {
  try {
    localStorage.setItem("lughus_runs", JSON.stringify(state.runs.slice(0, 50)));
  } catch (e) {
    console.error("Failed to save runs", e);
  }
}
