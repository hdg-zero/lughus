/**
 * Main Developer UI Entrypoint — Orchestrates state, history, streaming, and events.
 */

import { state, updateStatus } from "/ui/assets/ui_state.js";
import {
  appendEvent,
  renderEmpty,
  applyFilterToAllLogs,
} from "/ui/assets/ui_events.js";
import {
  renderHistory,
  selectRun,
  addRunToHistory,
  updateActiveRunStatus,
  appendEventToActiveRun,
} from "/ui/assets/ui_history.js";
import { renderAgentFlow } from "/ui/assets/ui_agent_flow.js";
import { initTheme } from "/ui/assets/ui_theme.js";

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

async function runStreamed(attachments) {
  const objective = document.querySelector("#objective");
  let response;
  try {
    response = await fetch("/ui/stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        objective: objective ? objective.value : "",
        files: attachments,
      }),
      signal: state.activeAbortController ? state.activeAbortController.signal : null,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      appendEventToActiveRun({ type: "error", text: "Execution cancelled by user" });
      updateActiveRunStatus("error");
    } else {
      appendEventToActiveRun({ type: "error", text: error.message });
      updateActiveRunStatus("error");
    }
    return;
  }

  const events = document.querySelector("#events");
  if (!response.ok) {
    const payload = await response.json();
    if (events) events.innerHTML = "";
    const errEvent = { type: "error", text: payload.error || "Request failed" };
    appendEventToActiveRun(errEvent);
    updateActiveRunStatus("error");
    return;
  }

  if (!response.body) {
    return;
  }

  if (events) events.innerHTML = "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;

      buffer += decoder.decode(chunk.value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim()) continue;
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

    const run = state.runs.find(r => r.id === state.activeRunId);
    if (run && run.status === "running") {
      updateActiveRunStatus("done");
    }
  } catch (error) {
    if (error.name === "AbortError" || (error.message && error.message.includes("cancelled"))) {
      appendEventToActiveRun({ type: "error", text: "Execution cancelled by user" });
      updateActiveRunStatus("error");
    } else {
      appendEventToActiveRun({ type: "error", text: error.message });
      updateActiveRunStatus("error");
    }
    try {
      await reader.cancel();
    } catch (e) {}
  }
}

// DOM Initialization
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#form");
  const objective = document.querySelector("#objective");
  const filesInput = document.querySelector("#files");
  const fileCount = document.querySelector("#file-count");
  const runBtn = document.querySelector("#run");
  const cancelBtn = document.querySelector("#cancel");
  const clearHistoryBtn = document.querySelector("#clear-history");
  const filterButtons = document.querySelectorAll(".filter-btn");
  const eventSearchInput = document.querySelector("#event-search");
  const dropzone = document.querySelector(".file-dropzone");

  if (filesInput && fileCount) {
    filesInput.addEventListener("change", () => {
      const count = filesInput.files.length;
      fileCount.textContent = `${count} file${count === 1 ? "" : "s"} attached`;
    });
  }

  if (objective && form) {
    objective.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        form.requestSubmit();
      }
    });
  }

  if (dropzone && filesInput) {
    dropzone.addEventListener("dragenter", () => dropzone.classList.add("dragover"));
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", () => dropzone.classList.remove("dragover"));
  }

  if (filterButtons) {
    filterButtons.forEach(btn => {
      btn.addEventListener("click", () => {
        filterButtons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.currentFilter = btn.getAttribute("data-filter");
        applyFilterToAllLogs();
      });
    });
  }

  if (eventSearchInput) {
    eventSearchInput.addEventListener("input", (e) => {
      state.searchQuery = e.target.value.toLowerCase().trim();
      applyFilterToAllLogs();
    });
  }

  const toggleMarkdownBtn = document.querySelector("#toggle-markdown");
  if (toggleMarkdownBtn) {
    toggleMarkdownBtn.addEventListener("click", () => {
      state.renderMarkdown = !state.renderMarkdown;
      if (state.renderMarkdown) {
        toggleMarkdownBtn.classList.add("active");
        toggleMarkdownBtn.textContent = "Markdown: On";
      } else {
        toggleMarkdownBtn.classList.remove("active");
        toggleMarkdownBtn.textContent = "Markdown: Off";
      }
      if (state.activeRunId) {
        selectRun(state.activeRunId);
      }
    });
  }

  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!objective || !objective.value.trim()) return;

      if (runBtn) runBtn.disabled = true;
      if (cancelBtn) cancelBtn.disabled = false;

      const events = document.querySelector("#events");
      if (events) events.innerHTML = "";

      addRunToHistory(objective.value);
      updateStatus("running");
      renderEmpty("Running agent loop...");

      state.activeAbortController = new AbortController();

      try {
        const attachments = filesInput ? await Promise.all(Array.from(filesInput.files).map(readFile)) : [];
        await runStreamed(attachments);
      } catch (error) {
        if (events) events.innerHTML = "";
        appendEventToActiveRun({ type: "error", text: error instanceof Error ? error.message : String(error) });
        updateActiveRunStatus("error");
      } finally {
        if (runBtn) runBtn.disabled = false;
        if (cancelBtn) cancelBtn.disabled = true;
        state.activeAbortController = null;
      }
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      if (state.activeAbortController) {
        state.activeAbortController.abort();
        cancelBtn.disabled = true;
      }
    });
  }

  if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", () => {
      state.runs = [];
      state.activeRunId = null;
      localStorage.removeItem("lughus_runs");
      renderHistory();
      renderAgentFlow();
      renderEmpty("Execute the agent to see logs here");
      updateStatus("idle");
    });
  }

  initTheme();

  // Initial Render
  renderHistory();
  if (state.runs.length > 0) {
    selectRun(state.runs[0].id);
  }
  updateStatus("idle");
});
