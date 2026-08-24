/** Build an inspectable execution timeline from the actual stream event sequence. */

import { state } from "/ui/assets/ui_state.js";
import { applyFilterToAllLogs } from "/ui/assets/ui_events.js";

function toolName(event) {
  return event.tool_name || event.name || "tool";
}

function eventLabel(event) {
  if (event.type === "progress") {
    return String(event.text || "Working");
  }
  if (event.type === "completion") return "Execution completed";
  if (event.type === "error") return "Run failed";
  if (event.type === "tool_result") return `${toolName(event)} result`;
  if (event.type === "telemetry") return "Run metrics";
  return toolName(event);
}

function eventDetail(event) {
  if (event.type === "tool_result") {
    return event.status === "error"
      ? event.error_type || "Tool error"
      : `${event.elapsed_ms ?? 0} ms`;
  }
  if (event.type === "tool_start") return "Calling tool";
  if (event.type === "completion") return "Artifact or final output ready";
  return event.text || "";
}

function eventStatus(event) {
  if (event.type === "error" || event.status === "error") return "error";
  if (event.type === "tool_start") return "active";
  return "done";
}

export function deriveAgentSteps(events) {
  const steps = [];

  events.forEach((event, eventIndex) => {
    steps.push({
      detail: eventDetail(event),
      eventIndex,
      label: eventLabel(event),
      status: eventStatus(event),
      type: event.type,
    });
  });

  return steps;
}

function focusEvent(eventIndex) {
  state.currentFilter = "all";
  state.searchQuery = "";
  const search = document.querySelector("#event-search");
  if (search) search.value = "";
  document.querySelectorAll(".filter-btn").forEach(button => {
    button.classList.toggle("active", button.dataset.filter === "all");
  });
  applyFilterToAllLogs();
  const target = document.querySelector(`.event[data-event-index="${eventIndex}"]`);
  if (!target) return;
  const details = target.querySelector("details");
  if (details) details.open = true;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("event-focused");
  window.setTimeout(() => target.classList.remove("event-focused"), 1600);
}

export function renderAgentFlow(events = []) {
  const container = document.querySelector("#agent-flow-steps");
  const detail = document.querySelector("#agent-flow-detail");
  if (!container || !detail) return;

  const steps = deriveAgentSteps(events);
  container.replaceChildren();
  if (!steps.length) {
    detail.textContent = "Waiting for a run";
    container.innerHTML = '<span class="agent-flow-empty">Steps will appear as the agent works.</span>';
    return;
  }

  const lastStep = steps.at(-1);
  detail.textContent = `${steps.length} execution step${steps.length === 1 ? "" : "s"} · click a step for details`;
  for (const [position, step] of steps.entries()) {
    const button = document.createElement("button");
    button.className = `agent-flow-step ${step.status}`;
    button.type = "button";
    button.setAttribute("role", "listitem");
    button.title = step.detail || step.label;

    const index = document.createElement("span");
    index.className = "flow-index";
    index.textContent = String(position + 1);
    const copy = document.createElement("span");
    copy.className = "flow-copy";
    const label = document.createElement("strong");
    label.textContent = step.label;
    const stepDetail = document.createElement("small");
    stepDetail.textContent = step.detail || "Completed";
    copy.append(label, stepDetail);
    button.append(index, copy);
    button.addEventListener("click", () => focusEvent(step.eventIndex));
    if (step === lastStep) button.classList.add("latest");
    container.appendChild(button);
  }
}
