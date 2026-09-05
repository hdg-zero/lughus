/**
 * Direct Stream Client: communicates with POST /ui/stream via NDJSON.
 */

import { state } from "/ui/assets/ui_state.js";
import { appendEventToActiveRun, updateActiveRunStatus } from "/ui/assets/ui_history.js";
import { readStreamLines, handleRunError } from "/ui/assets/ui_utils.js";

export async function runStreamedDirect(attachments) {
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
    handleRunError(error);
    return;
  }

  const events = document.querySelector("#events");
  if (!response.ok) {
    let errText = "Request failed";
    try {
      const payload = await response.json();
      if (payload.error) errText = payload.error;
    } catch (_) {}
    if (events) events.innerHTML = "";
    appendEventToActiveRun({ type: "error", text: errText });
    updateActiveRunStatus("error");
    return;
  }

  if (!response.body) return;
  if (events) events.innerHTML = "";

  try {
    await readStreamLines(response.body, (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        const item = JSON.parse(trimmed);
        appendEventToActiveRun(item);
        if (item.type === "error") {
          updateActiveRunStatus("error");
        }
      } catch (_) {}
    });

    const run = state.runs.find((r) => r.id === state.activeRunId);
    if (run && run.status === "running") {
      updateActiveRunStatus("done");
    }
  } catch (error) {
    handleRunError(error);
  }
}
