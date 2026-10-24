import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./Markdown";

function rendered(source: string, allowHtml = true): Document {
  return new DOMParser().parseFromString(renderMarkdown(source, allowHtml), "text/html");
}

describe("untrusted Markdown and HTML", () => {
  it.each([
    '<script>alert(1)</script><p>Keep this text</p>',
    '<img src=x onerror="alert(1)"><svg onload="alert(1)"></svg>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe><object data=x></object>',
    '<form action=x><input name=password><button formaction=x>submit</button></form>',
  ])("removes executable elements and handlers: %s", (source) => {
    const doc = rendered(source);
    expect(doc.querySelector("script,iframe,object,embed,form,input,button,textarea,select")).toBeNull();
    for (const el of doc.querySelectorAll("*")) {
      for (const attr of el.attributes) {
        expect(attr.name).not.toMatch(/^on/i);
        expect(["srcdoc", "formaction"]).not.toContain(attr.name);
      }
    }
  });

  it.each([
    '<a href="javascript:alert(1)">link</a>',
    '<a href="java&#x73;cript:alert(1)">link</a>',
    '[link](javascript:alert%281%29)',
  ])("removes executable link URLs: %s", (source) => {
    for (const link of rendered(source).querySelectorAll("a[href]")) {
      expect(link.getAttribute("href")?.replace(/\s/g, "")).not.toMatch(/^(javascript|vbscript|data):/i);
    }
  });

  it("keeps ordinary content and protects external links", () => {
    const doc = rendered('[safe](https://example.org/) **ข้อความไทย**', false);
    const link = doc.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://example.org/");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(doc.querySelector("strong")?.textContent).toBe("ข้อความไทย");
  });

  it("treats model response HTML as text when HTML is disabled", () => {
    const doc = rendered('<img src=x onerror="alert(1)"><script>alert(1)</script>', false);
    expect(doc.querySelector("img,script")).toBeNull();
    expect(doc.body.textContent).toContain('<img src=x');
  });
});


describe("same-page navigation", () => {
  it.each(["group-input", "group-output", "group-env", "group-ecm", "and"])(
    "keeps #%s in this tab even if source requests a new tab", (anchor) => {
      const link = rendered(`<a href="#${anchor}" target="_blank">หัวข้อ</a>`).querySelector("a")!;
      expect(link.getAttribute("href")).toBe(`#${anchor}`);
      expect(link.getAttribute("target")).toBe("_self");
    });
  it("also keeps Markdown fragments in this tab", () => {
    const link = rendered("[คู่มือ](#and)", false).querySelector("a")!;
    expect(link.getAttribute("target")).toBe("_self");
  });
});
