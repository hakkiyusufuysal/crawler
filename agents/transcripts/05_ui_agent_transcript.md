# UI Agent — Real Transcript

**Agent:** UI Agent (subagent type: Explore)
**Date:** 2026-04-19

## Prompt Given

> You are the UI Agent. INPUT FROM ARCHITECT: 6 API endpoints, single HTML file, no frameworks, no npm, dark theme, must show queue depth / back pressure / crawl progress / live updating.
>
> Explain 5 design decisions: polling interval choice, diff-based DOM updates, slide-in canvas vs modal, XSS protection, no-framework trade-off.

## Agent's Response (verbatim excerpts)

### Polling Interval (2s)

> "At 500ms, we'd hammer the server with 120 requests per minute per client — wasteful for a crawler monitoring tool where meaningful state changes (job completion, queue shifts) happen on longer timescales. At 10 seconds, users stare at stale queue depth and progress bars, creating anxiety about whether the system is alive. Two seconds feels immediate enough to catch status updates within a reasonable human attention window while keeping server overhead negligible."

### Diff-Based DOM Updates (Direct Response to User's Flicker Complaint)

> "The previous approach — replacing the entire `innerHTML` of status containers every 2 seconds — caused visible flicker because the browser repaints the entire region, losing scroll position, focus state, and element references. The new strategy diffs the incoming data against the current DOM. For the job list, we compare incoming job IDs against rendered ones: we insert new rows at their sort position, remove deleted ones by ID, and update only the cells that actually differ."

### Slide-In Canvas vs Modal

> "A modal overlays and darkens the background, forcing them to close it to return to the queue view. The slide-in approach keeps the job list visible on the left while the detail panel slides in from the right. Users can glance between queue and details without modal fatigue. It also lets users keep the detail panel open while monitoring the queue updating in real-time — they see job status changes live without closing and reopening."

### XSS Protection

> "Page titles crawled from arbitrary sources are treated as hostile strings. Rather than inject them into the DOM via `innerHTML` or `textContent` directly, we use `document.createTextNode()` to wrap them, which guarantees the string is parsed as plain text, never as HTML or script. A title like `<img src=x onerror=alert('xss')>` renders as literal text, not an executable image element."

### No Framework Trade-off

> "What we gave up: automatic reactivity (we hand-code diffing), component scoping (we use naming conventions), and dev tooling (no hot reload, no TypeScript). What we gained: zero runtime overhead, complete control over DOM performance, and zero hidden behavior."

## Human's Decisions

1. **Polling interval — accepted.** 2 seconds is the committed value.

2. **Diff-based updates — accepted and prioritized.** This directly addressed a flicker bug reported during demo. Final implementation tracks `prevJobsJSON` and `prevStatusJSON` in closure variables, skipping DOM updates when the serialized payload is identical.

3. **Slide-in canvas — accepted.** Pattern applied twice: once for Job Details (showing crawled URLs live) and once for Agent Work (showing what each of the 6 agents produced).

4. **XSS protection — accepted with shortcut.** Rather than `document.createTextNode()` everywhere, we use an `escapeHtml()` helper that replaces `&<>"'` with HTML entities. Functionally equivalent for our use case (plain-text titles and URLs) and simpler.

5. **Vanilla JS — accepted.** No framework used. Single `static/index.html` file contains all HTML, CSS, and JS. Verified: `grep -c 'require\|import ' static/index.html` → 0 matches (pure stdlib browser APIs).
