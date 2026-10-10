import { Children, isValidElement, useEffect, useState, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { docsHref, imageUrl, PAGE_IDS, PAGES, resolveLink, slug, titleOf } from "./guide";

const text = (n: ReactNode): string =>
  Children.toArray(n).map((c) => (typeof c === "string" || typeof c === "number" ? String(c) : isValidElement(c) ? text((c.props as { children?: ReactNode }).children) : "")).join("");

export const pageFromUrl = () => {
  const p = new URLSearchParams(location.search).get("page") ?? "index";
  return PAGES[p] !== undefined ? p : "index";
};

/** A19 Docs tab: renders docs/user-guide with react-markdown (raw HTML is not rendered,
 * unsafe URLs are dropped), keeps relative .md links inside the tab and deep-linkable. */
export function DocsTab() {
  const [page, setPage] = useState(pageFromUrl);
  useEffect(() => {
    const onPop = () => setPage(pageFromUrl());
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);
  useEffect(() => {
    const h = decodeURIComponent(location.hash.slice(1));
    if (h) document.getElementById(h)?.scrollIntoView();
    else scrollTo(0, 0);
  }, [page]);
  const go = (p: string, hash?: string) => {
    history.pushState(null, "", docsHref(p, hash));
    setPage(p);
    if (p === page && hash) document.getElementById(hash)?.scrollIntoView();
  };
  const heading = (Tag: "h1" | "h2" | "h3" | "h4") => ({ children }: { children?: ReactNode }) => <Tag id={slug(text(children))}>{children}</Tag>;
  const components: Components = {
    h1: heading("h1"), h2: heading("h2"), h3: heading("h3"), h4: heading("h4"),
    a: ({ href, children }) => {
      const l = resolveLink(href);
      if (l.kind === "page") return <a href={docsHref(l.page, l.hash)} onClick={(e) => { e.preventDefault(); go(l.page, l.hash); }}>{children}</a>;
      if (l.kind === "hash") return <a href={`#${l.hash}`}>{children}</a>;
      if (l.kind === "external") return <a href={l.href} target="_blank" rel="noopener noreferrer">{children}</a>;
      return <span>{children}</span>;
    },
    img: ({ src, alt }) => {
      const u = imageUrl(typeof src === "string" ? src : undefined);
      return u ? <img src={u} alt={alt ?? ""} loading="lazy" /> : <span className="hint">[image: {alt}]</span>;
    },
    table: ({ children }) => <div className="doc-table"><table>{children}</table></div>,
  };
  return (
    <div className="docs" data-testid="docs">
      <nav className="card docs-nav" aria-label="User guide">
        <h2 className="card-title">User guide</h2>
        <ol>
          {PAGE_IDS.map((p) => (
            <li key={p}>
              <a href={docsHref(p)} aria-current={p === page ? "page" : undefined} onClick={(e) => { e.preventDefault(); go(p); }} data-testid={`docs-nav-${p}`}>
                {p === "index" ? "Overview" : titleOf(p)}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <article className="card doc" data-testid={`docs-page-${page}`}>
        <Markdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
          {PAGES[page]}
        </Markdown>
      </article>
    </div>
  );
}
