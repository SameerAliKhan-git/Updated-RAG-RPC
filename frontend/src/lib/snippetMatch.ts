/** Fuzzy matching of a citation snippet against a PDF page's text items.
 *
 * PDF text extraction mangles ligatures, hyphenation, and whitespace, so exact
 * matching fails. Strategy: normalize both sides (NFKD, ligature map,
 * de-hyphenate, collapse whitespace) while keeping a char-offset map back to
 * text items, then exact-substring → anchor match (first/last words) → give up
 * gracefully (page navigation still works).
 */

export interface TextItemRef {
  itemIndex: number;
  start: number; // char offset in normalized page string
  end: number;
}

const LIGATURES: Record<string, string> = {
  "ﬀ": "ff",
  "ﬁ": "fi",
  "ﬂ": "fl",
  "ﬃ": "ffi",
  "ﬄ": "ffl",
};

export function normalizeText(text: string): string {
  let out = text.normalize("NFKD");
  for (const [lig, repl] of Object.entries(LIGATURES)) out = out.replaceAll(lig, repl);
  out = out.replace(/(\w)-\s+(\w)/g, "$1$2"); // de-hyphenate line breaks
  out = out.toLowerCase().replace(/\s+/g, " ").trim();
  return out;
}

/** Build one normalized string from page text items plus an offset→item map. */
export function buildPageString(items: string[]): { page: string; refs: TextItemRef[] } {
  const refs: TextItemRef[] = [];
  let page = "";
  items.forEach((raw, itemIndex) => {
    const norm = normalizeText(raw);
    if (!norm) {
      refs.push({ itemIndex, start: page.length, end: page.length });
      return;
    }
    if (page && !page.endsWith(" ")) page += " ";
    const start = page.length;
    page += norm;
    refs.push({ itemIndex, start, end: page.length });
  });
  return { page, refs };
}

function words(s: string, n: number, fromEnd = false): string {
  const parts = s.split(" ").filter(Boolean);
  return (fromEnd ? parts.slice(-n) : parts.slice(0, n)).join(" ");
}

/** Locate the snippet in the normalized page string. Returns [start, end) or null. */
export function findSnippetRange(pageNorm: string, snippet: string): [number, number] | null {
  const target = normalizeText(snippet);
  if (!target) return null;

  const exact = pageNorm.indexOf(target);
  if (exact >= 0) return [exact, exact + target.length];

  // Anchor match: first-8 and last-8 words
  const head = words(target, 8);
  const tail = words(target, 8, true);
  const headIdx = pageNorm.indexOf(head);
  if (headIdx >= 0) {
    const tailIdx = pageNorm.indexOf(tail, headIdx);
    if (tailIdx > headIdx && tailIdx - headIdx < target.length * 2) {
      return [headIdx, tailIdx + tail.length];
    }
    return [headIdx, Math.min(headIdx + target.length, pageNorm.length)];
  }
  // Head miss — try just the tail
  const tailIdx = pageNorm.indexOf(tail);
  if (tailIdx >= 0) {
    return [Math.max(0, tailIdx + tail.length - target.length), tailIdx + tail.length];
  }
  return null;
}

/** Item indexes whose normalized span overlaps [start, end). */
export function itemsInRange(refs: TextItemRef[], start: number, end: number): number[] {
  return refs.filter((r) => r.end > start && r.start < end).map((r) => r.itemIndex);
}
