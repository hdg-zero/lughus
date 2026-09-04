/**
 * Log rendering, filtering, and event card DOM construction.
 */

import { state } from "/ui/assets/ui_state.js";
import { escapeHtml, syntaxHighlight, formatJSONString, formatElapsed } from "/ui/assets/ui_utils.js";
import { parseMarkdown } from "/ui/assets/ui_markdown.js";

// Re-export utilities for backward compatibility
export { escapeHtml, syntaxHighlight, formatJSONString, formatElapsed, parseMarkdown };

export function renderEmpty(text) {
  const container = document.querySelector("#events");
  if (container) {
    container.innerHTML = `<div class="empty">${escapeHtml(text)}</div>`;
  }
}

export function applyFilterToEvent(eventElement, filter = state.currentFilter, query = state.searchQuery) {
  let matchesFilter = false;
  if (filter === "all") {
    matchesFilter = true;
  } else {
    const isProgress = eventElement.classList.contains("progress");
    const isTool = eventElement.classList.contains("tool_start") || eventElement.classList.contains("tool_result");
    const isTelemetry = eventElement.classList.contains("telemetry");
    const isError = eventElement.classList.contains("error");

    if (filter === "progress" && isProgress) matchesFilter = true;
    else if (filter === "tool" && isTool) matchesFilter = true;
    else if (filter === "telemetry" && isTelemetry) matchesFilter = true;
    else if (filter === "error" && isError) matchesFilter = true;
    else if (filter === "a2a") {
      matchesFilter =
        eventElement.classList.contains("a2a_request") || eventElement.classList.contains("a2a_response");
    }
  }

  const textContent = eventElement.textContent.toLowerCase();
  const matchesSearch = !query || textContent.includes(query);

  if (matchesFilter && matchesSearch) {
    eventElement.style.display = "flex";
  } else {
    eventElement.style.display = "none";
  }
}

export function applyFilterToAllLogs() {
  const container = document.querySelector("#events");
  if (!container) return;
  const allEvents = container.querySelectorAll(".event");
  allEvents.forEach((el) => applyFilterToEvent(el, state.currentFilter, state.searchQuery));
}

/**
 * DRY Factory for event card shell.
 */
function createEventCardSkeleton(event, eventIndex) {
  const item = document.createElement("article");
  item.className = `event ${event.type}`;
  if (eventIndex !== null) item.dataset.eventIndex = String(eventIndex);

  if (event.type === "tool_start" || event.type === "tool_result") {
    item.classList.add("tool");
  }
  if (event.type === "a2a_request" || event.type === "a2a_response") {
    item.classList.add("a2a");
  }
  if (event.status === "error") {
    item.classList.add("error");
  }

  const meta = document.createElement("div");
  meta.className = "event-meta";

  const badge = document.createElement("span");
  badge.className = "event-type-badge";
  badge.textContent = (event.type || "event").replace("_", " ");

  const timeSpan = document.createElement("span");
  timeSpan.className = "event-time";
  const date = event.timestamp ? new Date(event.timestamp) : new Date();
  timeSpan.textContent = date.toLocaleTimeString();

  meta.append(badge, timeSpan);
  const body = document.createElement("pre");

  return { item, meta, body };
}

export function appendEvent(
  event,
  listContainer = document.querySelector("#events"),
  eventIndex = null,
) {
  if (!listContainer) return;

  const { item, meta, body } = createEventCardSkeleton(event, eventIndex);

  if (event.type === "telemetry") {
    const tokens = event.tokens || {};
    const tools = event.tools || {};
    const otel = event.otel_attributes || {};
    body.innerHTML = [
      `<strong>model:</strong> ${escapeHtml(event.model || "")}`,
      `<strong>request_elapsed:</strong> ${event.request_elapsed_ms ?? 0}ms`,
      `<strong>loop_elapsed:</strong> ${event.loop_elapsed_s ?? ""}s`,
      `<strong>iterations:</strong> ${event.iterations ?? ""}`,
      `<strong>tokens:</strong> total=${tokens.total ?? 0}, prompt=${tokens.prompt ?? 0}, completion=${tokens.completion ?? 0}, cached=${tokens.cached ?? 0}`,
      `<strong>tools:</strong> count=${tools.count ?? 0}, errors=${tools.errors ?? 0}, elapsed=${tools.elapsed_ms ?? 0}ms`,
      `<strong>called_tools:</strong> ${(tools.names || []).map(escapeHtml).join(", ") || "none"}`,
      `<strong>otel_attributes:</strong>\n${syntaxHighlight(otel)}`,
    ].join("\n");
  } else if (event.type === "tool_start") {
    body.innerHTML = `<strong>arguments:</strong>\n${formatJSONString(event.arguments)}`;
  } else if (event.type === "tool_result") {
    const lines = [
      `<strong>status:</strong> ${escapeHtml(event.status || "ok")}`,
      `<strong>elapsed:</strong> ${formatElapsed(event.elapsed_ms)}`,
    ];
    if (event.error_type) {
      lines.push(`<strong>error:</strong> ${escapeHtml(event.error_type)}`);
    }
    lines.push(`<strong>output:</strong>\n${formatJSONString(event.output)}`);
    body.innerHTML = lines.join("\n");
  } else if (event.type === "a2a_request") {
    const lines = [
      `<strong>agent:</strong> ${escapeHtml(event.target_agent || "")}`,
      `<strong>url:</strong> ${escapeHtml(event.url || "")}`,
      `<strong>method:</strong> ${escapeHtml(event.method || "message/send")}`,
    ];
    if (event.tool_name) lines.push(`<strong>tool:</strong> ${escapeHtml(event.tool_name)}`);
    if (event.file_count) {
      lines.push(`<strong>files attached:</strong> ${event.file_count}`);
    }
    lines.push(`<strong>objective sent:</strong>\n${escapeHtml(event.objective || "")}`);
    body.innerHTML = lines.join("\n");
  } else if (event.type === "a2a_response") {
    const isError = event.status === "error";
    item.classList.add(isError ? "error" : "done");
    let elapsed = Number(event.elapsed_ms) || 0;
    if (elapsed <= 0) {
      const activeRun = state.runs.find((r) => r.id === state.activeRunId);
      if (activeRun && activeRun.timestamp && event.timestamp && event.timestamp >= activeRun.timestamp) {
        elapsed = event.timestamp - activeRun.timestamp;
        event.elapsed_ms = elapsed;
      }
    }
    const lines = [
      `<strong>agent:</strong> ${escapeHtml(event.target_agent || "")}`,
      `<strong>status:</strong> ${escapeHtml(event.status || "ok")}`,
      `<strong>elapsed:</strong> ${formatElapsed(elapsed)}`,
    ];
    if (event.remote_task_id) lines.push(`<strong>remote task:</strong> ${escapeHtml(event.remote_task_id)}`);
    if (event.error_code) lines.push(`<strong>error:</strong> ${escapeHtml(event.error_code)}`);
    lines.push(`<strong>response text:</strong>\n${escapeHtml(event.text || "(none)")}`);
    body.innerHTML = lines.join("\n");
  } else if (event.type === "completion") {
    const rawText = event.text || "";
    if (state.renderMarkdown) {
      body.className = "markdown-rendered";
      body.innerHTML = parseMarkdown(rawText);
    } else {
      body.className = "";
      body.innerHTML = escapeHtml(rawText);
    }
  } else if (event.type === "error" && event.code === "approval_required") {
    body.className = "";
    const lines = [];
    if (event.request_id) lines.push(`<strong>request:</strong> ${escapeHtml(event.request_id)}`);
    if (event.tool_name) lines.push(`<strong>tool:</strong> ${escapeHtml(event.tool_name)}`);
    if (event.text) lines.push(`<strong>message:</strong> ${escapeHtml(event.text)}`);
    body.innerHTML = lines.join("\n") || "Approval required";

    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const requestId = event.request_id || "";
    if (requestId) {
      const mkBtn = (label, approvedValue) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `approval-btn ${approvedValue ? "approve" : "reject"}`;
        btn.textContent = label;
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          const sibling = actions.querySelector(".approval-btn:not([disabled])");
          if (sibling) sibling.disabled = true;
          try {
            const res = await fetch(`/ui/approvals/${encodeURIComponent(requestId)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ approved: approvedValue, subject: "ui-operator" }),
            });
            const data = await res.json();
            const outcome = document.createElement("p");
            outcome.className = "approval-outcome";
            outcome.textContent = res.ok
              ? `Decision recorded: ${data.status} by ${data.decided_by}`
              : `Decision failed: ${data.error || res.statusText}`;
            item.append(outcome);
          } catch (err) {
            const outcome = document.createElement("p");
            outcome.className = "approval-outcome";
            outcome.textContent = `Decision failed: ${err.message || err}`;
            item.append(outcome);
          }
        });
        return btn;
      };
      actions.append(mkBtn("Approve", true), mkBtn("Reject", false));
      item.classList.add("approval_request");
    }
    body.append(actions);
  } else if (event.type === "error") {
    body.className = "";
    const lines = [];
    if (event.code) lines.push(`<strong>code:</strong> ${escapeHtml(event.code)}`);
    if (event.text) lines.push(`<strong>message:</strong> ${escapeHtml(event.text)}`);
    body.innerHTML = lines.join("\n") || "Unknown error";
  } else {
    body.className = "";
    body.innerHTML = escapeHtml(event.text || "");
  }

  if (event.type === "tool_start" || event.type === "tool_result") {
    const details = document.createElement("details");
    details.className = "event-details";
    details.open = event.status === "error";

    const summary = document.createElement("summary");
    if (event.type === "tool_start") {
      summary.textContent = "Show tool arguments";
    } else if (event.status === "error") {
      summary.textContent = "Show tool error details";
    } else {
      summary.textContent = "Show tool result";
    }
    details.append(summary, body);
    item.append(meta, details);
  } else {
    item.append(meta, body);
  }

  if (event.artifacts && event.artifacts.length) {
    const artSection = document.createElement("div");
    artSection.className = "artifacts-section";

    const artTitle = document.createElement("div");
    artTitle.className = "artifacts-title";
    artTitle.textContent = "Generated Artifacts";

    const artList = document.createElement("div");
    artList.className = "artifacts";

    for (const artifact of event.artifacts) {
      const link = document.createElement("a");
      link.download = artifact.name;
      link.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg> ${escapeHtml(artifact.name)}`;
      link.href = `data:${artifact.mime_type};base64,${artifact.data_base64}`;
      artList.appendChild(link);
    }
    artSection.append(artTitle, artList);
    item.appendChild(artSection);
  }

  listContainer.appendChild(item);
  applyFilterToEvent(item, state.currentFilter, state.searchQuery);
  listContainer.scrollTop = listContainer.scrollHeight;
}
