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

  // 0. Extract math expressions BEFORE escapeHtml (LaTeX may contain < > &)
  const mathExprs = [];
  // Display math: $$...$$
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_match, latex) => {
    const placeholder = `@@@MDMATH${mathExprs.length}@@@`;
    mathExprs.push({ latex, display: true });
    return placeholder;
  });
  // Inline math: $...$  (single $ — avoid matching $$ already extracted)
  text = text.replace(/\$([^\$\n]+?)\$/g, (_match, latex) => {
    const placeholder = `@@@MDMATH${mathExprs.length}@@@`;
    mathExprs.push({ latex, display: false });
    return placeholder;
  });

  let html = escapeHtml(text);

  // 1. Extract Fenced Code Blocks
  const codeBlocks = [];
  html = html.replace(/(?:^|\n)```([a-zA-Z0-9_-]*)[ \t]*\n([\s\S]*?)\n```[ \t]*(?:\n|$)/g, (_match, lang, code) => {
    const placeholder = `\n@@@MDCODEBLOCK${codeBlocks.length}@@@\n`;
    const langAttr = lang ? ` data-lang="${escapeHtml(lang)}"` : "";
    codeBlocks.push(`<pre class="md-code-block"><code${langAttr}>${code}</code></pre>`);
    return placeholder;
  });

  function inlineMarkdown(s) {
    return s
      .replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/(?:^|\W)_([^_]+)_(?:\W|$)/g, " <em>$1</em> ")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>")
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/|#)[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>');
  }

  // 2. Extract Tables (GFM) with alignment support
  // Requires pipe-delimited rows: | col1 | col2 | (supports 1+ columns)
  const tables = [];
  html = html.replace(
    /(?:^|\n)([ \t]*\|[^\n]+\|[ \t]*\n[ \t]*\|[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)*\|[ \t]*\n(?:[ \t]*\|[^\n]+\|[ \t]*(?:\n|$))*)/g,
    (match, block) => {
      const rows = block.trim().split("\n");
      if (rows.length < 2) return match;
      const splitRow = (row) =>
        row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

      const alignSpecs = splitRow(rows[1]).map((cell) => {
        const left = cell.startsWith(":");
        const right = cell.endsWith(":");
        if (left && right) return ' style="text-align: center;"';
        if (right) return ' style="text-align: right;"';
        if (left) return ' style="text-align: left;"';
        return "";
      });

      const headerCells = splitRow(rows[0]);
      const thead = `<tr>${headerCells.map((c, i) => `<th${alignSpecs[i] || ""}>${inlineMarkdown(c)}</th>`).join("")}</tr>`;

      const bodyRows = rows.slice(2).map(splitRow);
      const tbody = bodyRows
        .map((cells) => `<tr>${cells.map((c, i) => `<td${alignSpecs[i] || ""}>${inlineMarkdown(c)}</td>`).join("")}</tr>`)
        .join("");

      const placeholder = `\n@@@MDTABLE${tables.length}@@@\n`;
      tables.push(
        `<div class="md-table-wrap"><table class="md-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`
      );
      return placeholder;
    }
  );

  // 3. Extract Blockquotes & GitHub-style Alerts
  const blockquotes = [];
  html = html.replace(/(?:^|\n)((?:>[^\n]*\n?)+)/g, (_match, block) => {
    const lines = block.split("\n").map((l) => l.replace(/^>\s?/, ""));
    const rawContent = lines.join("\n").trim();
    const alertMatch = rawContent.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\n?([\s\S]*)$/i);
    const placeholder = `\n@@@MDQUOTE${blockquotes.length}@@@\n`;
    if (alertMatch) {
      const type = alertMatch[1].toLowerCase();
      const body = inlineMarkdown(alertMatch[2].trim());
      blockquotes.push(
        `<div class="md-alert md-alert-${type}"><div class="md-alert-title">${alertMatch[1].toUpperCase()}</div><div>${body}</div></div>`
      );
    } else {
      blockquotes.push(`<blockquote class="md-quote">${inlineMarkdown(rawContent)}</blockquote>`);
    }
    return placeholder;
  });

  // 4. Horizontal rules (---, ***, ___)
  html = html.replace(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/gim, '<hr class="md-hr">');

  // 5. Headers (h1-h6)
  html = html.replace(/^#{1,6}\s+(.*$)/gim, (match, content) => {
    const level = match.trim().split(/\s+/)[0].length;
    const tagLevel = Math.min(level + 1, 6);
    const cls = `md-h${level <= 3 ? level : 4}`;
    return `<h${tagLevel} class="${cls}">${inlineMarkdown(content)}</h${tagLevel}>`;
  });

  // 6. Lists (unordered, ordered, task lists)
  html = html.replace(/^\s*([-*]|\d+\.)\s+\[([ xX])\]\s+(.*$)/gim, (_m, _bullet, check, content) => {
    const checked = check.toLowerCase() === "x" ? " checked" : "";
    return `<li class="md-li md-task"><input type="checkbox" disabled${checked}> ${inlineMarkdown(content)}</li>`;
  });
  html = html.replace(/^\s*[-*]\s+(.*$)/gim, (_m, content) => `<li class="md-li">${inlineMarkdown(content)}</li>`);
  html = html.replace(/^\s*(\d+)\.\s+(.*$)/gim, (_m, _num, content) => `<li class="md-li md-ol-item">${inlineMarkdown(content)}</li>`);

  // Wrap consecutive <li> in <ul> / <ol>
  html = html.replace(/(<li class="md-li(?: md-ol-item| md-task)?">[^]*?<\/li>(?:\n|$))+/g, (match) => {
    if (match.includes("md-ol-item")) {
      return `<ol class="md-ol">\n${match.trim()}\n</ol>\n`;
    }
    return `<ul class="md-ul">\n${match.trim()}\n</ul>\n`;
  });

  // 7. Inline formatting — apply ONLY to plain-text lines
  //    Headers, lists, tables, blockquotes already applied inlineMarkdown during extraction.
  const PLACEHOLDER_RE = /^\s*@@@MD(CODEBLOCK|TABLE|QUOTE|MATH)\d+@@@\s*$/;
  const BLOCK_TAG_RE = /^\s*<(h[1-6]|hr|ul|ol|li|blockquote|div)\b/;
  const CLOSE_TAG_RE = /^\s*<\//;
  html = html.split("\n").map((line) => {
    const trimmed = line.trim();
    if (!trimmed || PLACEHOLDER_RE.test(trimmed) || BLOCK_TAG_RE.test(trimmed) || CLOSE_TAG_RE.test(trimmed)) {
      return line;
    }
    return inlineMarkdown(line);
  }).join("\n");

  // 8. Line breaks & spacing — skip block elements AND placeholders
  const outLines = [];
  const rawLines = html.split("\n");
  for (const line of rawLines) {
    const trimmed = line.trim();
    if (
      !trimmed ||
      PLACEHOLDER_RE.test(trimmed) ||
      BLOCK_TAG_RE.test(trimmed) ||
      CLOSE_TAG_RE.test(trimmed)
    ) {
      outLines.push(line);
    } else {
      outLines.push(line + "<br>");
    }
  }
  html = outLines.join("\n");

  // 9. Restore placeholders
  codeBlocks.forEach((block, index) => {
    html = html.replace(`@@@MDCODEBLOCK${index}@@@`, block);
  });
  tables.forEach((table, index) => {
    html = html.replace(`@@@MDTABLE${index}@@@`, table);
  });
  blockquotes.forEach((quote, index) => {
    html = html.replace(`@@@MDQUOTE${index}@@@`, quote);
  });
  mathExprs.forEach(({ latex, display }, index) => {
    let rendered;
    if (typeof katex !== "undefined") {
      try {
        rendered = katex.renderToString(latex, { displayMode: display, throwOnError: false });
      } catch (_e) {
        rendered = `<code class="md-inline-code">${escapeHtml(display ? `$$${latex}$$` : `$${latex}$`)}</code>`;
      }
    } else {
      rendered = `<code class="md-inline-code">${escapeHtml(display ? `$$${latex}$$` : `$${latex}$`)}</code>`;
    }
    html = html.replace(`@@@MDMATH${index}@@@`, rendered);
  });

  // Clean redundant linebreaks
  html = html.replace(/(<br>\s*){3,}/g, "<br><br>");
  return html.trim();
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
    const lines = [
      `<strong>agent:</strong> ${escapeHtml(event.target_agent || "")}`,
      `<strong>status:</strong> ${escapeHtml(event.status || "ok")}`,
      `<strong>elapsed:</strong> ${event.elapsed_ms ?? 0}ms`,
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
