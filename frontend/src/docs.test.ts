/** A19 Docs tab: bundled guide, safe rendering, in-tab relative links and images. */
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import { describe, expect, it } from "vitest";
import { docsHref, imageUrl, PAGE_IDS, PAGES, resolveLink, slug } from "./docs/guide";

describe("Docs tab (A19)", () => {
  it("bundles every guide page, index first", () => {
    expect(PAGE_IDS[0]).toBe("index");
    expect(PAGE_IDS).toContain("05-understanding-the-numbers");
    expect(PAGE_IDS.length).toBeGreaterThanOrEqual(8);
  });

  it("every relative .md link and image in the guide resolves inside the tab", () => {
    for (const [id, md] of Object.entries(PAGES)) {
      for (const [, href] of md.matchAll(/\]\(([^)\s]+)\)/g)) {
        if (/^https?:/.test(href)) continue;
        if (href.startsWith("images/")) expect(imageUrl(href), `${id}: ${href}`).toBeTruthy();
        else {
          const l = resolveLink(href);
          expect(l.kind, `${id}: ${href}`).not.toBe("blocked");
          if (l.kind === "page" && l.hash) expect(PAGES[l.page].split("\n").some((x) => /^#+ /.test(x) && slug(x.replace(/^#+ /, "")) === l.hash), `${id}: ${href}`).toBe(true);
        }
      }
    }
  });

  it("links: .md → deep link; javascript:/data:/unknown pages blocked; http(s) external", () => {
    expect(resolveLink("05-understanding-the-numbers.md#latency-delay")).toEqual({ kind: "page", page: "05-understanding-the-numbers", hash: "latency-delay" });
    expect(docsHref("05-understanding-the-numbers")).toBe("?tab=docs&page=05-understanding-the-numbers");
    expect(resolveLink("javascript:alert(1)").kind).toBe("blocked");
    expect(resolveLink("data:text/html,x").kind).toBe("blocked");
    expect(resolveLink("99-nope.md").kind).toBe("blocked");
    expect(resolveLink("https://example.com").kind).toBe("external");
    expect(imageUrl("https://evil/x.png")).toBeUndefined();
    expect(imageUrl("images/../../x.png")).toBeUndefined();
  });

  it("raw HTML in Markdown is not rendered (skipHtml)", () => {
    const html = renderToStaticMarkup(h(Markdown, { skipHtml: true }, 'hi <script>alert(1)</script> <img src=x onerror="alert(1)">'));
    expect(html).not.toContain("<script");
    expect(html).not.toContain("onerror");
  });
});
