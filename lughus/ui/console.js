/**
 * Main Developer UI Entrypoint — Orchestrates state, history, execution mode, and UI events.
 */

import { state, updateStatus } from "/ui/assets/ui_state.js";
import { renderEmpty, applyFilterToAllLogs } from "/ui/assets/ui_events.js";
import {
  renderHistory,
  selectRun,
  addRunToHistory,
  updateActiveRunStatus,
  appendEventToActiveRun,
} from "/ui/assets/ui_history.js";
import { renderAgentFlow } from "/ui/assets/ui_agent_flow.js";
import { initTheme } from "/ui/assets/ui_theme.js";
import { runStreamedDirect } from "/ui/assets/ui_client_direct.js";
import { runStreamedA2A, cancelA2ATask } from "/ui/assets/ui_client_a2a.js";
import { initAgentCardModal } from "/ui/assets/ui_modal_card.js";

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
    filterButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        filterButtons.forEach((b) => b.classList.remove("active"));
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

  // Execution Mode Switcher (Direct vs A2A Protocol)
  const modeDirectBtn = document.querySelector("#mode-direct-btn");
  const modeA2aBtn = document.querySelector("#mode-a2a-btn");

  function setMode(mode) {
    state.executionMode = mode;
    localStorage.setItem("lughus_ui_mode", mode);
    if (modeDirectBtn && modeA2aBtn) {
      if (mode === "a2a") {
        modeA2aBtn.classList.add("active");
        modeDirectBtn.classList.remove("active");
        if (runBtn) runBtn.textContent = "Run (A2A)";
      } else {
        modeDirectBtn.classList.add("active");
        modeA2aBtn.classList.remove("active");
        if (runBtn) runBtn.textContent = "Run Agent";
      }
    }
  }

  if (modeDirectBtn) {
    modeDirectBtn.addEventListener("click", () => setMode("direct"));
  }
  if (modeA2aBtn) {
    modeA2aBtn.addEventListener("click", () => setMode("a2a"));
  }
  setMode(state.executionMode || "direct");

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
        if (state.executionMode === "a2a") {
          await runStreamedA2A(attachments);
        } else {
          await runStreamedDirect(attachments);
        }
      } catch (error) {
        if (events) events.innerHTML = "";
        appendEventToActiveRun({
          type: "error",
          text: error instanceof Error ? error.message : String(error),
        });
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
      if (state.executionMode === "a2a") {
        cancelA2ATask();
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

  initAgentCardModal();
  initTheme();

  // Initial Render
  renderHistory();
  if (state.runs.length > 0) {
    selectRun(state.runs[0].id);
  }
  updateStatus("idle");
});
