import type { ChatMessage, Citation } from "../api/types";

/** Export a conversation as Markdown with numbered footnotes + BibTeX appendix. */
export function exportConversation(title: string, messages: ChatMessage[]): void {
  const footnotes = new Map<string, { n: number; citation: Citation }>();

  const keyOf = (c: Citation) => `${c.arxiv_id}|${c.section}|${c.page ?? ""}`;

  const registerCitations = (citations: Citation[]) => {
    for (const c of citations) {
      const key = keyOf(c);
      if (!footnotes.has(key)) footnotes.set(key, { n: footnotes.size + 1, citation: c });
    }
  };

  const lines: string[] = [
    `# ${title}`,
    "",
    `*Exported from Corpus on ${new Date().toISOString().slice(0, 10)} — every claim cited to its source.*`,
    "",
  ];

  for (const msg of messages) {
    if (msg.role === "user") {
      lines.push(`**You:** ${msg.content}`, "");
      continue;
    }
    const citations = msg.citations ?? [];
    registerCitations(citations);
    // Rewrite local [N] markers to global footnotes [^n]
    const content = msg.content.replace(/\[(\d+)\]/g, (match, num) => {
      const local = citations.find((c) => c.id === Number(num));
      if (!local) return match;
      const entry = footnotes.get(keyOf(local));
      return entry ? `[^${entry.n}]` : match;
    });
    lines.push(`**Corpus:**`, "", content, "");
    if (msg.groundingNote) lines.push(`> Grounding: ${msg.groundingNote}`, "");
  }

  if (footnotes.size > 0) {
    lines.push("---", "", "## Sources", "");
    for (const { n, citation } of [...footnotes.values()].sort((a, b) => a.n - b.n)) {
      const authors = citation.authors.slice(0, 3).join(", ") + (citation.authors.length > 3 ? " et al." : "");
      const page = citation.page ? `, p. ${citation.page}` : "";
      lines.push(
        `[^${n}]: ${authors}. *${citation.paper_title}*. arXiv:${citation.arxiv_id}, ${citation.section}${page}. ${citation.arxiv_url}`,
      );
    }

    lines.push("", "## BibTeX", "", "```bibtex");
    const seen = new Set<string>();
    for (const { citation } of footnotes.values()) {
      if (seen.has(citation.arxiv_id)) continue;
      seen.add(citation.arxiv_id);
      const year = citation.arxiv_id.startsWith("20") || citation.arxiv_id.startsWith("19")
        ? ""
        : `20${citation.arxiv_id.slice(0, 2)}`;
      lines.push(
        `@misc{arxiv_${citation.arxiv_id.replace(/\./g, "_")},`,
        `  title={${citation.paper_title}},`,
        `  author={${citation.authors.join(" and ")}},`,
        year ? `  year={${year}},` : "",
        `  eprint={${citation.arxiv_id}},`,
        `  archivePrefix={arXiv},`,
        `  url={${citation.arxiv_url}}`,
        `}`,
        "",
      );
    }
    lines.push("```");
  }

  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40).replace(/^-|-$/g, "") || "conversation";
  const blob = new Blob([lines.filter((l) => l !== undefined).join("\n")], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `corpus-${slug}-${new Date().toISOString().slice(0, 10)}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}
