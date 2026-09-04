/**
 * Agent Card Modal Controller: opens modal, fetches /.well-known/agent-card.json, copies JSON, and closes.
 */

import { escapeHtml, syntaxHighlight } from "/ui/assets/ui_utils.js";

export function initAgentCardModal() {
  const agentCardBtn = document.querySelector("#agent-card-btn");
  const agentCardModal = document.querySelector("#agent-card-modal");
  const agentCardJson = document.querySelector("#agent-card-json");
  const closeCardBtn = document.querySelector("#close-card-btn");
  const copyCardBtn = document.querySelector("#copy-card-btn");

  if (agentCardBtn && agentCardModal) {
    agentCardBtn.addEventListener("click", async () => {
      agentCardModal.showModal();
      if (agentCardJson) agentCardJson.innerHTML = "<code>Loading Agent Card...</code>";
      try {
        const res = await fetch("/.well-known/agent-card.json");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        if (agentCardJson) {
          agentCardJson.innerHTML = `<code>${syntaxHighlight(data)}</code>`;
        }
      } catch (err) {
        if (agentCardJson) {
          agentCardJson.innerHTML = `<code>Error loading agent card: ${escapeHtml(err.message)}</code>`;
        }
      }
    });
  }

  if (closeCardBtn && agentCardModal) {
    closeCardBtn.addEventListener("click", () => agentCardModal.close());
    agentCardModal.addEventListener("click", (e) => {
      if (e.target === agentCardModal) agentCardModal.close();
    });
  }

  if (copyCardBtn && agentCardJson) {
    copyCardBtn.addEventListener("click", () => {
      const text = agentCardJson.textContent || "";
      navigator.clipboard.writeText(text).then(() => {
        const prev = copyCardBtn.textContent;
        copyCardBtn.textContent = "Copied!";
        setTimeout(() => (copyCardBtn.textContent = prev), 1500);
      });
    });
  }
}
