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
  executionMode: localStorage.getItem("lughus_ui_mode") || "direct",
};

// Load runs from localStorage
try {
  const saved = localStorage.getItem("lughus_runs");
  if (saved) {
    state.runs = JSON.parse(saved);
    state.runs.forEach((r) => {
      if (r.status === "running") r.status = "error";
      if (r.events && r.timestamp) {
        r.events.forEach((ev) => {
          if (
            (ev.type === "a2a_response" || ev.type === "tool_result") &&
            (!ev.elapsed_ms || Number(ev.elapsed_ms) <= 0)
          ) {
            if (ev.timestamp && ev.timestamp >= r.timestamp) {
              ev.elapsed_ms = Math.max(1, ev.timestamp - r.timestamp);
            }
          }
        });
      }
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
