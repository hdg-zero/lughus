/**
 * Markdown & Math Rendering Engine for Lughus Developer Console.
 * Supports GFM tables, alerts, fenced code blocks, lists, and KaTeX math.
 */

import { escapeHtml } from "/ui/assets/ui_utils.js";

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
      .replace(
        /\[([^\]]+)\]\(((?:https?:\/\/|\/|#)[^)"\s]+)\)/g,
        (_match, text, url) => {
          const cleanUrl = url.replace(/"/g, "&quot;");
          return `<a href="${cleanUrl}" target="_blank" rel="noopener noreferrer" class="md-link">${text}</a>`;
        }
      );
  }

  // 2. Extract Tables (GFM) with alignment support
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
