const form = document.querySelector("#form");
const objective = document.querySelector("#objective");
const filesInput = document.querySelector("#files");
const fileCount = document.querySelector("#file-count");
const events = document.querySelector("#events");
const statusText = document.querySelector("#status");
const statusIndicator = document.querySelector("#status-indicator");
const runBtn = document.querySelector("#run");
const cancelBtn = document.querySelector("#cancel");
const clearHistoryBtn = document.querySelector("#clear-history");
const runList = document.querySelector("#run-list");
const otelForm = document.querySelector("#otel-form");
const otelUrl = document.querySelector("#otel-url");
const otelOutput = document.querySelector("#otel-output");
const loadOtel = document.querySelector("#load-otel");

let runs = [];
let activeRunId = null;
let activeAbortController = null;
let currentFilter = "all";

// Load runs from localStorage if available
try {
  const saved = localStorage.getItem("lughus_runs");
  if (saved) {
    runs = JSON.parse(saved);
    // Sanitize any running tasks from a previous session to error/done
    runs.forEach(r => {
      if (r.status === "running") r.status = "error";
    });
  }
} catch (e) {
  console.error("Failed to load runs from localStorage", e);
}

// Initialize file selection display
filesInput.addEventListener("change", () => {
  const count = filesInput.files.length;
  fileCount.textContent = `${count} file${count === 1 ? "" : "s"} attached`;
});

// Setup drag and drop styles
const dropzone = document.querySelector(".file-dropzone");
if (dropzone) {
  const fileInput = dropzone.querySelector("input");
  fileInput.addEventListener("dragenter", () => dropzone.classList.add("dragover"));
  fileInput.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  fileInput.addEventListener("drop", () => dropzone.classList.remove("dragover"));
}

function updateStatus(status) {
  statusText.textContent = status;
  statusIndicator.className = "status-dot " + status;
}

// JSON syntax highlighter
function syntaxHighlight(json) {
  if (typeof json !== "string") {
    json = JSON.stringify(json, undefined, 2);
  }
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
      // Keep key quotes cleaner or wrap in span
      if (cls === "key") {
        return `<span class="json-key">${match.replace(/[":]/g, "")}</span>:`;
      }
      return `<span class="json-${cls}">${match}</span>`;
    }
  );
}

function formatJSONString(str) {
  try {
    const parsed = JSON.parse(str);
    return syntaxHighlight(parsed);
  } catch (e) {
    return escapeHtml(str);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderEmpty(text) {
  events.innerHTML = `<div class="empty">${text}</div>`;
}

function appendEvent(event, listContainer = events) {
  const item = document.createElement("article");
  item.className = `event ${event.type}`;
  
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
  badge.textContent = event.type.replace("_", " ");

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
  } else if (event.type === "progress" || event.type === "error") {
    body.innerHTML = escapeHtml(event.text || "");
  } else {
    body.innerHTML = escapeHtml(event.text || "");
  }

  item.append(meta, body);

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
  applyFilterToEvent(item, currentFilter);
}

function saveRuns() {
  try {
    localStorage.setItem("lughus_runs", JSON.stringify(runs.slice(0, 50))); // limit history to 50
  } catch (e) {
    console.error("Failed to save runs", e);
  }
}

function renderHistory() {
  runList.innerHTML = "";
  if (runs.length === 0) {
    runList.innerHTML = '<div class="empty-history">No runs in this session</div>';
    return;
  }

  runs.forEach(run => {
    const item = document.createElement("div");
    item.className = `history-item ${run.id === activeRunId ? "active" : ""}`;
    item.addEventListener("click", () => selectRun(run.id));

    const header = document.createElement("div");
    header.className = "history-header";

    const time = document.createElement("span");
    time.className = "history-time";
    time.textContent = new Date(run.timestamp).toLocaleTimeString();

    const indicator = document.createElement("span");
    indicator.className = `history-status ${run.status}`;

    header.append(time, indicator);

    const obj = document.createElement("span");
    obj.className = "history-objective";
    obj.textContent = run.objective;

    item.append(header, obj);
    runList.appendChild(item);
  });
}

function selectRun(runId) {
  activeRunId = runId;
  renderHistory();
  
  const run = runs.find(r => r.id === runId);
  events.innerHTML = "";
  
  if (!run || run.events.length === 0) {
    renderEmpty("No events recorded for this run");
    return;
  }
  
  run.events.forEach(e => appendEvent(e));
  if (run.status === "running") {
    updateStatus("streaming");
  } else {
    updateStatus(run.status);
  }
}

function addRunToHistory(objectiveText) {
  const id = "run_" + Date.now();
  const newRun = {
    id: id,
    timestamp: Date.now(),
    objective: objectiveText,
    events: [],
    status: "running"
  };
  runs.unshift(newRun);
  activeRunId = id;
  saveRuns();
  renderHistory();
  return newRun;
}

function updateActiveRunStatus(statusVal) {
  const run = runs.find(r => r.id === activeRunId);
  if (run) {
    run.status = statusVal;
    saveRuns();
    renderHistory();
    updateStatus(statusVal);
  }
}

function appendEventToActiveRun(event) {
  const run = runs.find(r => r.id === activeRunId);
  if (run) {
    event.timestamp = Date.now();
    run.events.push(event);
    saveRuns();
    appendEvent(event);
  }
}

// Filtering Logic
const filterButtons = document.querySelectorAll(".filter-btn");
filterButtons.forEach(btn => {
  btn.addEventListener("click", () => {
    filterButtons.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.getAttribute("data-filter");
    applyFilterToAllLogs(currentFilter);
  });
});

function applyFilterToEvent(eventElement, filter) {
  if (filter === "all") {
    eventElement.style.display = "flex";
    return;
  }
  
  const isProgress = eventElement.classList.contains("progress");
  const isTool = eventElement.classList.contains("tool_start") || eventElement.classList.contains("tool_result");
  const isTelemetry = eventElement.classList.contains("telemetry");
  const isError = eventElement.classList.contains("error");

  if (filter === "progress" && isProgress) {
    eventElement.style.display = "flex";
  } else if (filter === "tool" && isTool) {
    eventElement.style.display = "flex";
  } else if (filter === "telemetry" && isTelemetry) {
    eventElement.style.display = "flex";
  } else if (filter === "error" && isError) {
    eventElement.style.display = "flex";
  } else {
    eventElement.style.display = "none";
  }
}

function applyFilterToAllLogs(filter) {
  const allEvents = events.querySelectorAll(".event");
  allEvents.forEach(el => applyFilterToEvent(el, filter));
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve({
        name: file.name || "file",
        mime_type: file.type || "application/octet-stream",
        content_base64: value.includes(",") ? value.split(",", 2)[1] : value,
      });
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function runBuffered(attachments) {
  try {
    const response = await fetch("/ui/run", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({
        objective: objective.value,
        files: attachments,
      }),
      signal: activeAbortController ? activeAbortController.signal : null
    });
    const payload = await response.json();
    events.innerHTML = "";
    if (!response.ok) {
      const errEvent = {type: "error", text: payload.error || "Request failed"};
      appendEventToActiveRun(errEvent);
      updateActiveRunStatus("error");
      return;
    }
    for (const item of payload.events) {
      appendEventToActiveRun(item);
    }
    updateActiveRunStatus("done");
  } catch (error) {
    if (error.name === "AbortError") {
      appendEventToActiveRun({type: "error", text: "Execution cancelled by user"});
      updateActiveRunStatus("error");
    } else {
      appendEventToActiveRun({type: "error", text: error.message});
      updateActiveRunStatus("error");
    }
  }
}

async function runStreamed(attachments) {
  let response;
  try {
    response = await fetch("/ui/stream", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({
        objective: objective.value,
        files: attachments,
      }),
      signal: activeAbortController ? activeAbortController.signal : null
    });
  } catch (error) {
    if (error.name === "AbortError") {
      appendEventToActiveRun({type: "error", text: "Execution cancelled by user"});
      updateActiveRunStatus("error");
    } else {
      appendEventToActiveRun({type: "error", text: error.message});
      updateActiveRunStatus("error");
    }
    return;
  }

  if (!response.ok) {
    const payload = await response.json();
    events.innerHTML = "";
    const errEvent = {type: "error", text: payload.error || "Request failed"};
    appendEventToActiveRun(errEvent);
    updateActiveRunStatus("error");
    return;
  }
  if (!response.body) {
    await runBuffered(attachments);
    return;
  }

  events.innerHTML = "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      buffer += decoder.decode(chunk.value, {stream: true});
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }
        const item = JSON.parse(line);
        appendEventToActiveRun(item);
        if (item.type === "error") {
          updateActiveRunStatus("error");
        }
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      const item = JSON.parse(buffer);
      appendEventToActiveRun(item);
      if (item.type === "error") {
        updateActiveRunStatus("error");
      }
    }
    const run = runs.find(r => r.id === activeRunId);
    if (run && run.status === "running") {
      updateActiveRunStatus("done");
    }
  } catch (error) {
    if (error.name === "AbortError" || (error.message && error.message.includes("cancelled"))) {
      appendEventToActiveRun({type: "error", text: "Execution cancelled by user"});
      updateActiveRunStatus("error");
    } else {
      appendEventToActiveRun({type: "error", text: error.message});
      updateActiveRunStatus("error");
    }
    // Cancel the reader to notify the server stream is closed
    try {
      await reader.cancel();
    } catch (e) {}
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  
  runBtn.disabled = true;
  cancelBtn.disabled = false;
  
  events.innerHTML = "";
  addRunToHistory(objective.value);
  updateStatus("running");
  renderEmpty("Running agent loop...");
  
  activeAbortController = new AbortController();
  
  try {
    const attachments = await Promise.all(Array.from(filesInput.files).map(readFile));
    await runStreamed(attachments);
  } catch (error) {
    events.innerHTML = "";
    appendEventToActiveRun({type: "error", text: error instanceof Error ? error.message : String(error)});
    updateActiveRunStatus("error");
  } finally {
    runBtn.disabled = false;
    cancelBtn.disabled = true;
    activeAbortController = null;
  }
});

cancelBtn.addEventListener("click", () => {
  if (activeAbortController) {
    activeAbortController.abort();
    cancelBtn.disabled = true;
  }
});

clearHistoryBtn.addEventListener("click", () => {
  runs = [];
  activeRunId = null;
  localStorage.removeItem("lughus_runs");
  renderHistory();
  events.innerHTML = "";
  renderEmpty("Execute the agent to see logs here");
  updateStatus("idle");
});

otelForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loadOtel.disabled = true;
  otelOutput.textContent = "Loading OpenTelemetry traces...";
  try {
    const response = await fetch("/ui/otel/traces", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({url: otelUrl.value}),
    });
    const payload = await response.json();
    if (!response.ok) {
      otelOutput.textContent = payload.error || "Trace fetch failed";
      return;
    }
    otelOutput.innerHTML = payload.json !== null && payload.json !== undefined
      ? syntaxHighlight(payload.json)
      : escapeHtml(payload.text);
  } catch (error) {
    otelOutput.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    loadOtel.disabled = false;
  }
});

// Initial Render
renderHistory();
if (runs.length > 0) {
  selectRun(runs[0].id);
}
