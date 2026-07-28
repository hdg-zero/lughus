/**
 * OpenTelemetry trace loader module.
 */

import { syntaxHighlight, escapeHtml } from "/ui/assets/ui_events.js";

export function initOtelForm() {
  const otelForm = document.querySelector("#otel-form");
  const otelUrl = document.querySelector("#otel-url");
  const otelOutput = document.querySelector("#otel-output");
  const loadOtel = document.querySelector("#load-otel");

  if (!otelForm || !otelOutput) return;

  otelForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (loadOtel) loadOtel.disabled = true;
    otelOutput.textContent = "Loading OpenTelemetry traces...";
    
    try {
      const response = await fetch("/ui/otel/traces", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: otelUrl ? otelUrl.value : "" }),
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
      if (loadOtel) loadOtel.disabled = false;
    }
  });
}
