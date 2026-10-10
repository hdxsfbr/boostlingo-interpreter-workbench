/** A19: the user guide (docs/user-guide) bundled at build time, so it is served from
 * the gated /assets like the rest of the SPA (no extra route, works behind the password). */
const raw = import.meta.glob("../../../docs/user-guide/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const imgs = import.meta.glob("../../../docs/user-guide/images/*.{png,jpg,jpeg,svg,webp,gif}", { query: "?url", import: "default", eager: true }) as Record<string, string>;

const base = (p: string) => p.split("/").pop()!;
export const PAGES: Record<string, string> = Object.fromEntries(Object.entries(raw).map(([p, s]) => [base(p).replace(/\.md$/, ""), s]));
export const IMAGES: Record<string, string> = Object.fromEntries(Object.entries(imgs).map(([p, u]) => [base(p), u]));
export const PAGE_IDS = Object.keys(PAGES).sort((a, b) => (a === "index" ? -1 : b === "index" ? 1 : a.localeCompare(b)));

export const titleOf = (id: string) => (PAGES[id]?.match(/^#\s+(.+)$/m)?.[1] ?? id).replace(/^\d+\.\s*/, "");

/** GitHub-style heading slug, so links like 02-interpreter.md#reading-the-latency-bars resolve. */
export const slug = (s: string) => s.toLowerCase().trim().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s/g, "-");

export type Link = { kind: "page"; page: string; hash?: string } | { kind: "hash"; hash: string } | { kind: "external"; href: string } | { kind: "blocked" };

/** Resolve a link from guide Markdown. Relative .md links stay inside the Docs tab;
 * only http(s)/mailto leave it; anything else (javascript:, data:, unknown pages) is dropped. */
export function resolveLink(href: string | undefined): Link {
  if (!href) return { kind: "blocked" };
  if (href.startsWith("#")) return { kind: "hash", hash: href.slice(1) };
  const m = href.match(/^(?:\.\/)?([\w-]+)\.md(?:#(.*))?$/);
  if (m) return PAGES[m[1]] !== undefined ? { kind: "page", page: m[1], hash: m[2] } : { kind: "blocked" };
  if (/^(https?:|mailto:)/i.test(href)) return { kind: "external", href };
  return { kind: "blocked" };
}

export const imageUrl = (src: string | undefined): string | undefined => {
  const m = src?.match(/^(?:\.\/)?images\/([\w.-]+)$/);
  return m ? IMAGES[m[1]] : undefined;
};

export const docsHref = (page: string, hash?: string) => `?tab=docs&page=${encodeURIComponent(page)}${hash ? `#${hash}` : ""}`;
