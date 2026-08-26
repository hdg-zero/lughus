/**
 * Log rendering, JSON formatting, filtering, and auto-scroll logic.
 */

import { state } from "/ui/assets/ui_state.js";

export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

export function syntaxHighlight(json) {
  if (typeof json !== "string") {
    json = JSON.stringify(json, undefined, 2);
  }
  if (!json) return "";
  json = json.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    function (match) {
      let cls = "number";
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = "key";
        } else {
          cls = "string";
        }
      } else if (/true|false/.test(match)) {
        cls = "boolean";
      } else if (/null/.test(match)) {
        cls = "null";
      }
      if (cls === "key") {
        return `<span class="json-key">${match.replace(/[":]/g, "")}</span>:`;
      }
      return `<span class="json-${cls}">${match}</span>`;
    }
  );
}

export function parseMarkdown(text) {
  if (!text) return "";
  let html = escapeHtml(text);

  // Fenced code blocks with placeholder extraction
  const codeBlocks = [];
  html = html.replace(/```([a-z0-9_-]*)\n([\s\S]*?)```/g, (_match, _lang, code) => {
    const placeholder = `___CODE_BLOCK_${codeBlocks.length}___`;
    codeBlocks.push(`<pre class="md-code-block"><code>${code.trim()}</code></pre>`);
    return placeholder;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>');

  // Headers
  html = html.replace(/^### (.*$)/gim, '<h4 class="md-h3">$1</h4>');
  html = html.replace(/^## (.*$)/gim, '<h3 class="md-h2">$1</h3>');
  html = html.replace(/^# (.*$)/gim, '<h2 class="md-h1">$1</h2>');

  // Bold & Italic
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // Unordered Lists
  html = html.replace(/^\s*[-*]\s+(.*$)/gim, '<li class="md-li">$1</li>');

  // Links
  html = html.replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/|#)[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>');

  // Line breaks
  html = html.replace(/\n/g, '<br>');

  // Restore code blocks without corrupting them with <br>
  codeBlocks.forEach((block, index) => {
    html = html.replace(`___CODE_BLOCK_${index}___`, block);
  });

  return html;
}

export function formatJSONString(str) {
  if (typeof str !== "string") {
    return syntaxHighlight(str);
  }
  try {
    const parsed = JSON.parse(str);
    return syntaxHighlight(parsed);
  } catch (e) {
    return escapeHtml(str);
  }
}

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
  allEvents.forEach(el => applyFilterToEvent(el, state.currentFilter, state.searchQuery));
}

export function appendEvent(
  event,
  listContainer = document.querySelector("#events"),
  eventIndex = null,
) {
  if (!listContainer) return;

  const item = document.createElement("article");
  item.className = `event ${event.type}`;
  if (eventIndex !== null) item.dataset.eventIndex = String(eventIndex);
  
  if (event.type === "tool_start" || event.type === "tool_result") {
    item.classList.add("tool");
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
      `<strong>otel_attributes:</strong>\n${syntaxHighlight(otel)}`
    ].join("\n");
  } else if (event.type === "tool_start") {
    body.innerHTML = `<strong>arguments:</strong>\n${formatJSONString(event.arguments)}`;
  } else if (event.type === "tool_result") {
    const lines = [
      `<strong>status:</strong> ${escapeHtml(event.status || "ok")}`,
      `<strong>elapsed:</strong> ${event.elapsed_ms ?? 0}ms`,
    ];
    if (event.error_type) {
      lines.push(`<strong>error:</strong> ${escapeHtml(event.error_type)}`);
    }
    lines.push(`<strong>output:</strong>\n${formatJSONString(event.output)}`);
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

    // Interactive approval card: Approve / Reject buttons POST to the
    // decision endpoint and render the recorded outcome in place.
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
