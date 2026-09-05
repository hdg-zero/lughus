/**
 * A2A Protocol Simulation Client: communicates with POST / via JSON-RPC 2.0 message/stream.
 */

import { state } from "/ui/assets/ui_state.js";
import { appendEventToActiveRun, updateActiveRunStatus } from "/ui/assets/ui_history.js";
import { readStreamLines, handleRunError } from "/ui/assets/ui_utils.js";

let activeA2ATaskId = null;

export function getActiveA2ATaskId() {
  return activeA2ATaskId;
}

export function cancelA2ATask() {
  if (activeA2ATaskId) {
    fetch("/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: String(Date.now()),
        method: "tasks/cancel",
        params: { taskId: activeA2ATaskId },
      }),
    }).catch(() => {});
  }
}

export async function runStreamedA2A(attachments) {
  const startedAt = performance.now();
  const objectiveEl = document.querySelector("#objective");
  const objectiveText = objectiveEl ? objectiveEl.value.trim() : "";
  const messageId = "msg_" + Math.random().toString(36).slice(2, 11);
  const rpcId = String(Date.now());
  activeA2ATaskId = null;

  const parts = [{ kind: "text", text: objectiveText }];
  for (const file of attachments) {
    parts.push({
      kind: "file",
      file: {
        name: file.name,
        mimeType: file.mime_type,
        bytes: file.content_base64,
      },
    });
  }

  const payload = {
    jsonrpc: "2.0",
    id: rpcId,
    method: "message/stream",
    params: {
      message: {
        role: "user",
        parts: parts,
        messageId: messageId,
        kind: "message",
      },
    },
  };

  appendEventToActiveRun({
    type: "a2a_request",
    target_agent: "local-a2a",
    url: "/",
    method: "message/stream",
    file_count: attachments.length,
    objective: objectiveText,
  });

  let response;
  try {
    response = await fetch("/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: state.activeAbortController ? state.activeAbortController.signal : null,
    });
  } catch (error) {
    handleRunError(error, "A2A connection failed");
    return;
  }

  const events = document.querySelector("#events");
  if (!response.ok) {
    let errText = `A2A Request failed (${response.status})`;
    try {
      const errJson = await response.json();
      if (errJson.error && errJson.error.message) errText = errJson.error.message;
    } catch (_) {}
    if (events) events.innerHTML = "";
    const elapsedMs = Math.round(performance.now() - startedAt);
    appendEventToActiveRun({
      type: "a2a_response",
      target_agent: "local-a2a",
      status: "error",
      elapsed_ms: elapsedMs,
      error_code: `HTTP_${response.status}`,
      text: errText,
    });
    updateActiveRunStatus("error");
    return;
  }

  if (!response.body) return;
  if (events) events.innerHTML = "";

  const collectedArtifacts = [];
  let completionText = "";
  let hasEmittedResponse = false;

  try {
    await readStreamLines(response.body, (line) => {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith("data:")) return;
      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr) return;

      let frame;
      try {
        frame = JSON.parse(jsonStr);
      } catch (_) {
        return;
      }

      if (frame.error) {
        hasEmittedResponse = true;
        const elapsedMs = Math.round(performance.now() - startedAt);
        appendEventToActiveRun({
          type: "a2a_response",
          target_agent: "local-a2a",
          status: "error",
          elapsed_ms: elapsedMs,
          error_code: frame.error.code ? String(frame.error.code) : "protocol_error",
          text: frame.error.message || "A2A Protocol Error",
        });
        updateActiveRunStatus("error");
        return;
      }

      const res = frame.result;
      if (!res) return;
      if (res.taskId) activeA2ATaskId = res.taskId;

      if (res.kind === "status-update") {
        const status = res.status || {};
        const msg = status.message;
        if (msg && msg.parts) {
          for (const part of msg.parts) {
            if (part.kind === "text" && part.text) {
              if (status.state === "completed") {
                completionText = part.text;
              } else if (status.state === "failed") {
                appendEventToActiveRun({ type: "error", text: part.text });
                updateActiveRunStatus("error");
              } else {
                appendEventToActiveRun({ type: "progress", text: part.text });
              }
            }
          }
        }
        if (res.final) {
          hasEmittedResponse = true;
          const elapsedMs = Math.round(performance.now() - startedAt);
          if (status.state === "completed") {
            appendEventToActiveRun({
              type: "completion",
              text: completionText || "A2A task completed successfully.",
              artifacts: collectedArtifacts,
            });
            appendEventToActiveRun({
              type: "a2a_response",
              target_agent: "local-a2a",
              status: "completed",
              elapsed_ms: elapsedMs,
              remote_task_id: activeA2ATaskId || "",
              text: completionText,
            });
            updateActiveRunStatus("done");
          } else if (status.state === "failed") {
            appendEventToActiveRun({
              type: "a2a_response",
              target_agent: "local-a2a",
              status: "error",
              elapsed_ms: elapsedMs,
              remote_task_id: activeA2ATaskId || "",
              text: completionText || "Task failed",
            });
            updateActiveRunStatus("error");
          }
        }
      } else if (res.kind === "artifact-update") {
        const art = res.artifact || {};
        const parts = art.parts || [];
        for (const p of parts) {
          if (p.kind === "file" && p.file) {
            collectedArtifacts.push({
              name: p.file.name || art.name || "artifact",
              mime_type: p.file.mimeType || "application/octet-stream",
              data_base64: p.file.bytes || "",
            });
          }
        }
      }
    });

    if (!hasEmittedResponse && completionText) {
      const elapsedMs = Math.round(performance.now() - startedAt);
      appendEventToActiveRun({
        type: "a2a_response",
        target_agent: "local-a2a",
        status: "completed",
        elapsed_ms: elapsedMs,
        remote_task_id: activeA2ATaskId || "",
        text: completionText,
      });
    }

    const run = state.runs.find((r) => r.id === state.activeRunId);
    if (run && run.status === "running") {
      updateActiveRunStatus("done");
    }
  } catch (error) {
    handleRunError(error);
  }
}
