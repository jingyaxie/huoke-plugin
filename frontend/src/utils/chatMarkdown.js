function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInline(text) {
  let s = text;
  s = s.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return s;
}

function renderBlock(block) {
  const trimmed = block.trim();
  if (!trimmed) return "";

  if (trimmed.startsWith("<pre")) return trimmed;
  if (/^<h[1-3]>/.test(trimmed)) return trimmed;

  const lines = trimmed.split("\n");
  if (lines.every((line) => /^[-*]\s+/.test(line.trim()))) {
    const items = lines
      .map((line) => line.trim().replace(/^[-*]\s+/, ""))
      .filter(Boolean)
      .map((item) => `<li>${renderInline(item)}</li>`)
      .join("");
    return `<ul>${items}</ul>`;
  }

  if (lines.every((line) => /^\d+\.\s+/.test(line.trim()))) {
    const items = lines
      .map((line) => line.trim().replace(/^\d+\.\s+/, ""))
      .filter(Boolean)
      .map((item) => `<li>${renderInline(item)}</li>`)
      .join("");
    return `<ol>${items}</ol>`;
  }

  if (lines.every((line) => /^>\s?/.test(line.trim()))) {
    const quote = lines
      .map((line) => line.trim().replace(/^>\s?/, ""))
      .join(" ");
    return `<blockquote>${renderInline(quote)}</blockquote>`;
  }

  const html = lines.map((line) => renderInline(line)).join("<br>");
  return `<p>${html}</p>`;
}

export function renderChatMarkdown(text) {
  if (!text) return "";

  const placeholders = [];
  let source = escapeHtml(text);

  source = source.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const token = `__CODE_BLOCK_${placeholders.length}__`;
    const langClass = lang ? ` language-${lang}` : "";
    placeholders.push(
      `<pre class="code-block"><code class="code-body${langClass}">${code.trim()}</code></pre>`,
    );
    return token;
  });

  source = source.replace(/^### (.+)$/gm, (_, title) => `<h3>${title}</h3>`);
  source = source.replace(/^## (.+)$/gm, (_, title) => `<h2>${title}</h2>`);
  source = source.replace(/^# (.+)$/gm, (_, title) => `<h1>${title}</h1>`);

  const html = source
    .split(/\n{2,}/)
    .map(renderBlock)
    .join("");

  return placeholders.reduce(
    (acc, block, index) => acc.replace(`__CODE_BLOCK_${index}__`, block),
    html,
  );
}
