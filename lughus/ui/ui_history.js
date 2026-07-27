/**
 * Execution History & Session Runs component.
 */

import { state, saveRuns, updateStatus } from "/ui/assets/ui_state.js";
import { renderAgentFlow } from "/ui/assets/ui_agent_flow.js";
import { appendEvent, renderEmpty } from "/ui/assets/ui_events.js";

export function renderHistory() {
  const runList = document.querySelector("#run-list");
  if (!runList) return;

  runList.innerHTML = "";
  if (state.runs.length === 0) {
    runList.innerHTML = '<div class="empty-history">No runs in this session</div>';
    return;
  }

  state.runs.forEach(run => {
    const item = document.createElement("div");
    item.className = `history-item ${run.id === state.activeRunId ? "active" : ""}`;
    item.addEventListener("click", () => selectRun(run.id));

    const header = document.createElement("div");
    header.className = "history-header";

    const time = document.createElement("span");
    time.className = "history-time";
    time.textContent = new Date(run.timestamp).toLocaleTimeString();

    const indicator = document.createElement("span");
    indicator.className = `history-status ${run.status}`;

    header.append(time, indicator);

    const obj = document.createElement("div");
    obj.className = "history-objective";
    obj.textContent = run.objective || "No objective";

    item.append(header, obj);
    runList.appendChild(item);
  });
}

export function selectRun(runId) {
  state.activeRunId = runId;
  renderHistory();
  
  const container = document.querySelector("#events");
  const run = state.runs.find(r => r.id === runId);
  if (container) container.innerHTML = "";
  
  if (!run || run.events.length === 0) {
    renderAgentFlow();
    renderEmpty("No events recorded for this run");
    return;
  }
  
  run.events.forEach((event, eventIndex) => appendEvent(event, undefined, eventIndex));
  renderAgentFlow(run.events);
  if (run.status === "running") {
    updateStatus("streaming");
  } else {
    updateStatus("idle");
  }
}

export function addRunToHistory(objectiveText) {
  const id = "run_" + Date.now();
  const newRun = {
    id: id,
    timestamp: Date.now(),
    objective: objectiveText,
    events: [],
    status: "running"
  };
  state.runs.unshift(newRun);
  state.activeRunId = id;
  renderAgentFlow();
  saveRuns();
  renderHistory();
  return newRun;
}

export function updateActiveRunStatus(statusVal) {
  const run = state.runs.find(r => r.id === state.activeRunId);
  if (run) {
    run.status = statusVal;
    saveRuns();
    renderHistory();
    updateStatus(statusVal);
  }
}

export function appendEventToActiveRun(event) {
  const run = state.runs.find(r => r.id === state.activeRunId);
  if (run) {
    event.timestamp = Date.now();
    run.events.push(event);
    saveRuns();
    appendEvent(event, undefined, run.events.length - 1);
    renderAgentFlow(run.events);
  }
}
