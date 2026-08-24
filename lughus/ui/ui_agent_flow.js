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
  if (event.type === "error") {
    const codes = {
      loop_limit: "Iteration limit reached",
      approval_required: "Human approval required",
      agent_timeout: "Agent timed out",
      invalid_input: "Invalid input",
      internal_error: "Internal error",
    };
    return codes[event.code] || "Run failed";
  }
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

function buildStepButton(step, position, lastStep, expanded) {
  const button = document.createElement("button");
  button.className = `agent-flow-step ${step.status}`;
  button.type = "button";
  button.setAttribute("role", "listitem");
  button.title = step.detail || step.label;
  if (step === lastStep) button.classList.add("latest");

  const index = document.createElement("span");
  index.className = "flow-index";
  index.textContent = String(position + 1);

  const copy = document.createElement("span");
  copy.className = "flow-copy";
  const label = document.createElement("strong");
  label.textContent = step.label;
  copy.append(label);

  if (expanded && step.detail) {
    // Expanded mode: full detail on its own line, wrapping instead of ellipsis.
    const stepDetail = document.createElement("small");
    stepDetail.className = "flow-detail-full";
    stepDetail.textContent = step.detail;
    copy.append(stepDetail);
  } else {
    const stepDetail = document.createElement("small");
    stepDetail.textContent = step.detail || "Completed";
    copy.append(stepDetail);
  }

  button.append(index, copy);
  button.addEventListener("click", () => focusEvent(step.eventIndex));
  return button;
}

export function renderAgentFlow(events = []) {
  const section = document.querySelector("#agent-flow");
  const container = document.querySelector("#agent-flow-steps");
  const detail = document.querySelector("#agent-flow-detail");
  if (!container || !detail) return;

  const steps = deriveAgentSteps(events);
  container.replaceChildren();

  const expanded = section ? section.dataset.expanded === "true" : false;

  if (!steps.length) {
    detail.textContent = "Waiting for a run";
    container.innerHTML = '<span class="agent-flow-empty">Steps will appear as the agent works.</span>';
    return;
  }

  const lastStep = steps.at(-1);
  detail.textContent = `${steps.length} execution step${steps.length === 1 ? "" : "s"} · click a step for details`;

  for (const [position, step] of steps.entries()) {
    container.appendChild(buildStepButton(step, position, lastStep, expanded));
  }

  // Smart follow: keep the newest step visible unless the operator scrolled
  // away to inspect history. In expanded (vertical) mode a floating
  // "jump to latest" button lets them return in one click.
  if (lastStep) {
    if (!expanded) {
      if (lastStep.status === "active") {
        lastStep.scrollIntoView?.({ block: "nearest", inline: "end", behavior: "smooth" });
      } else if (typeof container.scrollTo === "function") {
        // Horizontal strip: follow the newest step unless the user scrolled back.
        const nearEnd = container.scrollWidth - container.scrollLeft - container.clientWidth < 240;
        if (nearEnd) container.scrollTo({ left: container.scrollWidth, behavior: "smooth" });
      }
    } else {
      updateJumpToLatest(section, container, lastStep);
    }
  }

  updateFlowToggle(steps.length);
}

function isNearBottom(scroller) {
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 60;
}

function updateJumpToLatest(section, scroller, lastStep) {
  let jumper = section.querySelector(".jump-to-latest");
  const shouldShow = !isNearBottom(scroller);

  if (shouldShow && !jumper) {
    jumper = document.createElement("button");
    jumper.type = "button";
    jumper.className = "agent-flow-expand jump-to-latest";
    jumper.textContent = "↓ Latest";
    jumper.addEventListener("click", () => {
      lastStep.scrollIntoView?.({ block: "end", behavior: "smooth" });
      jumper?.remove();
    });
    section.appendChild(jumper);
  } else if (!shouldShow && jumper) {
    jumper.remove();
  } else if (jumper) {
    // Refresh the captured target so the button always jumps to the true latest.
    jumper.onclick = () => {
      lastStep.scrollIntoView?.({ block: "end", behavior: "smooth" });
      jumper?.remove();
    };
  }
}

function ensureToggle() {
  const section = document.querySelector("#agent-flow");
  if (!section) return null;
  let heading = section.querySelector(".agent-flow-heading");
  if (!heading) return null;
  let toggle = heading.querySelector(".agent-flow-expand");
  if (toggle) return toggle;

  toggle = document.createElement("button");
  toggle.className = "agent-flow-expand";
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");
  toggle.textContent = "Expand";
  toggle.addEventListener("click", () => {
    const isExpanded = section.dataset.expanded === "true";
    section.dataset.expanded = isExpanded ? "false" : "true";
    toggle.setAttribute("aria-expanded", String(!isExpanded));
    toggle.textContent = isExpanded ? "Expand" : "Collapse";
    const run = state.runs.find(r => r.id === state.activeRunId);
    renderAgentFlow(run ? run.events : []);
  });
  heading.appendChild(toggle);
  return toggle;
}

function updateFlowToggle(stepCount) {
  const toggle = ensureToggle();
  if (!toggle) return;
  toggle.style.display = stepCount > 4 ? "" : "none";
}
