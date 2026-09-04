/**
 * UI Utilities: HTML escaping, JSON syntax highlighting, stream decoding, and error handling.
 */

import { appendEventToActiveRun, updateActiveRunStatus } from "/ui/assets/ui_history.js";

export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

export function formatElapsed(ms) {
  const val = Number(ms) || 0;
  return val >= 1000 ? `${(val / 1000).toFixed(2)}s (${val}ms)` : `${val}ms`;
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

export function formatJSONString(val) {
  if (typeof val === "string") {
    try {
      return syntaxHighlight(JSON.parse(val));
    } catch (_) {
      return escapeHtml(val);
    }
  }
  return syntaxHighlight(val);
}

/**
 * DRY Stream Reader: reads text lines from a ReadableStream (NDJSON or SSE).
 * @param {ReadableStream} stream
 * @param {(line: string) => void} onLine
 */
export async function readStreamLines(stream, onLine) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        onLine(line);
      }
    }

    buffer += decoder.decode();
    if (buffer) {
      onLine(buffer);
    }
  } finally {
    try {
      await reader.cancel();
    } catch (_) {}
  }
}

/**
 * DRY Error Handler: detects cancellation vs errors and updates run status.
 * @param {Error|any} error
 * @param {string} [prefix]
 */
export function handleRunError(error, prefix = "") {
  const isCancelled =
    error &&
    (error.name === "AbortError" ||
      (typeof error.message === "string" && error.message.toLowerCase().includes("cancelled")));

  const text = isCancelled
    ? "Execution cancelled by user"
    : prefix
    ? `${prefix}: ${error.message || String(error)}`
    : error.message || String(error);

  appendEventToActiveRun({ type: "error", text });
  updateActiveRunStatus("error");
}
