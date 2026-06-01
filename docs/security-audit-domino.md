# Security Audit Report: @mixmark-io/domino@2.2.0

**Date:** 2026-05-30
**Scope:** `.bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/` (20 files)
**Library:** Server-side DOM implementation (Node.js)
**Risk Score:** 34/100 (Moderate-Low)

---

## Summary

`@mixmark-io/domino` is a server-side DOM implementation library. It parses HTML, builds a DOM tree, and provides DOM APIs (querySelector, events, etc.) in Node.js. The library itself is a _facilitator_ — the actual security risks depend entirely on how consuming applications use it. The library faithfully represents parsed HTML without sanitization, which is expected DOM behavior but creates XSS risk when untrusted HTML is parsed and serialized back.

## Vulnerability Details

### XSS / HTML Injection

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | **HIGH** | `Element.js` | innerHTML/outerHTML getters call `serialize()` which returns raw HTML. Scripts, event handlers, `javascript:` URLs from parsed content are faithfully reproduced. No sanitization layer. |
| 2 | **HIGH** | `DocumentFragment.js` | innerHTML getter uses `this.serialize()` — same serialization risk. Raw HTML including scripts/event handlers returned. |
| 3 | **MEDIUM** | `HTMLParser.js` | Parser faithfully processes all HTML including `<script>`, `<iframe>`, `on*` event attributes, `javascript:` URLs. Expected behavior but consumers must sanitize. |
| 4 | **MEDIUM** | `Element.js` | outerHTML setter (partial impl) uses internal parser. If completed with user input, XSS vector via crafted HTML. |

### Open Redirect

| # | Severity | File | Issue |
|---|----------|------|-------|
| 5 | **MEDIUM** | `Location.js` | `assign()` resolves relative URLs without validation. Attacker can redirect to arbitrary origins via `//evil.com` or malformed URLs. |

### Prototype Pollution / Property Injection

| # | Severity | File | Issue |
|---|----------|------|-------|
| 6 | **LOW** | `CSSStyleDeclaration.js` | Proxy `has` trap always returns `true`, bypassing `in` operator for `__proto__`, `constructor`, `toString`. |
| 7 | **LOW** | `CustomEvent.js` | `for...in` loop copies all dictionary properties onto event. User-controlled dict can set `__proto__`. |

### Event Handler Injection

| # | Severity | File | Issue |
|---|----------|------|-------|
| 8 | **LOW** | `EventTarget.js` | `addEventListener()` accepts any object as listener without type validation. Malicious listeners possible if target exposed to untrusted code. |
| 9 | **LOW** | `EventTarget.js` | Handler return values control `preventDefault()` — follows DOM spec but exploitable in SSR context. |

### Information Disclosure

| # | Severity | File | Issue |
|---|----------|------|-------|
| 10 | **LOW** | `Document.js` | `_address` stores document URL. If leaked via serialization, exposes internal paths. |
| 11 | **LOW** | `Event.js` | `Date.now()` for timestamps — server time disclosed in event objects returned to clients. |

---

## Findings by Category

### Hardcoded Secrets
**None found.** No API keys, passwords, tokens, or credentials in the provided source files.

### SQL Injection
**Not applicable.** DOM implementation library — no database interaction or SQL query construction.

### Insecure Dependencies
**Potential concern.** `@mixmark-io/domino@2.2.0` is a fork of the original `domino` package (by fgnass). The `@mixmark-io` scope suggests internal Mixmark fork (likely for Turndown/markdown tooling). Key concerns:
- Unclear maintenance status — no visible recent updates
- May be based on older domino version with known CVEs
- No `package.json` provided in audit scope to verify transitive deps

### Authentication/Authorization
**Not applicable.** Library-level DOM implementation — no auth mechanisms exist.

---

## JSON Report

```json
{
  "vulnerabilities": [
    {
      "severity": "high",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/Element.js",
      "line": 82,
      "description": "innerHTML getter calls serialize() which returns raw HTML including all scripts, event handlers (onerror/onload/onclick), and javascript: URLs from parsed content. Server-side XSS if untrusted HTML is parsed then serialized back to clients without sanitization."
    },
    {
      "severity": "high",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/DocumentFragment.js",
      "line": 61,
      "description": "innerHTML getter delegates to this.serialize() returning raw HTML with embedded scripts and event handlers. Same XSS risk as Element — no sanitization between parse and serialize in the library."
    },
    {
      "severity": "medium",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/HTMLParser.js",
      "line": 1,
      "description": "HTML parser faithfully processes all HTML constructs including <script>, <iframe>, inline event handlers (on*), and javascript: URLs. This is correct DOM behavior but means consuming code must sanitize input before parsing or output after serialization to prevent XSS."
    },
    {
      "severity": "medium",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/Location.js",
      "line": 22,
      "description": "Location.assign() resolves user-provided URLs via URL.resolve() without any origin/protocol validation. Open redirect — attacker can supply '//evil.com' or 'https:evil.com' to redirect users to arbitrary external origins."
    },
    {
      "severity": "medium",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/Element.js",
      "line": 91,
      "description": "outerHTML setter uses internal mozHTMLParser to parse provided HTML string. If the setter was fully implemented (currently partially stubbed), setting outerHTML with user-controlled strings would be a direct XSS injection vector."
    },
    {
      "severity": "low",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/CSSStyleDeclaration.js",
      "line": 14,
      "description": "Proxy 'has' trap always returns true for all property keys including __proto__, constructor, and toString. This bypasses the 'in' operator for security-sensitive property checks and could enable property shadowing attacks in consuming code."
    },
    {
      "severity": "low",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/CustomEvent.js",
      "line": 7,
      "description": "Event constructor iterates dictionary with for...in loop: 'for(var p in dictionary) { this[p] = dictionary[p]; }'. If dictionary is user-controlled, arbitrary properties (including __proto__) can be set on event objects. Risk is low because events are typically short-lived."
    },
    {
      "severity": "low",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/EventTarget.js",
      "line": 25,
      "description": "addEventListener() accepts any object as a listener without type validation. Malicious listener objects with handleEvent methods could be registered if the EventTarget is accessible from untrusted code paths."
    },
    {
      "severity": "low",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/EventTarget.js",
      "line": 83,
      "description": "Handler return values control preventDefault() behavior: mouseover returns true and beforeunload/default return false trigger event.preventDefault(). Follows DOM spec but could be exploited in SSR to alter event flow from user-controlled handlers."
    },
    {
      "severity": "low",
      "file": ".bun/install/cache/@mixmark-io/domino@2.2.0@@@1/lib/Document.js",
      "line": 52,
      "description": "Document._address property stores the document URL. If this value is serialized or leaked in error messages/debug output, it could expose internal server paths or configuration URLs. Low risk — requires explicit access to document internals."
    }
  ],
  "riskScore": 34,
  "recommendations": [
    "Add HTML sanitization between domino parse and serialize pipelines. Use DOMPurify (JSDOM variant) or sanitize-html to strip <script>, event handlers, and dangerous attributes before serializing DOM back to HTML strings.",
    "Validate URLs in Location.assign() against an allowlist of permitted origins and protocols. Reject javascript:, data:, vbscript:, and protocol-relative URLs (//).",
    "Add type-checking in addEventListener() per DOM spec §2.8 — reject non-function, non-EventListener objects. Throw TypeError on invalid listener argument.",
    "Freeze CustomEvent dictionary processing — use Object.defineProperties() with explicit property whitelist instead of for...in copy loop to prevent __proto__ injection.",
    "Fix CSSStyleDeclaration Proxy 'has' trap — delegate to Reflect.has() for standard properties, only return true for known CSS property names (kebab-case pattern match).",
    "Verify @mixmark-io/domino@2.2.0 lineage — run `npm audit` against the consuming project to check for known CVEs in transitive dependencies.",
    "If used for SSR of user-generated content, sanitize HTML BEFORE domino parsing as defense-in-depth, not just after serialization.",
    "Consider migrating to maintained alternatives: linkedom (active, faster, 1/10th size) or jsdom (most mature, widest security review surface)."
  ]
}
```

---

## Methodology

- **Static analysis** of 20 JavaScript source files from domino `lib/` directory
- Searched for: hardcoded credentials (regex), SQL patterns, XSS vectors (innerHTML, document.write, eval, new Function), prototype pollution (__proto__, constructor.prototype), open redirects, event injection
- **Severity**: HIGH = exploitable in common usage patterns, MEDIUM = conditional exploit, LOW = hardening opportunity

## Limitations

- Only 20 files provided. Full audit requires: `package.json`, lockfile, remaining lib files (TreeWalker.js, NodeIterator.js, select.js, etc.), test files
- No dynamic analysis or fuzzing performed
- Consuming application's usage pattern determines exploitability of findings
