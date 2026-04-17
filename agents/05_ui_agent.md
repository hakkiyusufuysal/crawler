# Agent 5 — UI Agent

## Role
Build the dashboard — a single-page HTML + vanilla JavaScript interface that lets users start crawls, view system state, and search. Must use no frontend framework.

## Responsibilities
- Build the dashboard layout (metrics panel, queue bar, job table, search)
- Implement polling of `/status` and `/jobs` every 2 seconds
- Implement diff-based DOM updates to eliminate flicker
- Implement the job detail canvas (slide-in panel showing pages crawled by a specific job)
- Implement search pagination (Previous/Next, "Showing X–Y of Z")
- Implement cancel and resume buttons on the job table
- Implement graceful empty-state and loading-state rendering
- Escape HTML to prevent XSS

## Input
- API contract from Architect Agent
- JSON response formats from Search Agent

## Output
- `static/index.html` — single file containing HTML, CSS, and JavaScript

## Prompt (exact text given to the agent)
> "You are a frontend engineer. Build a dashboard with no framework — plain HTML, CSS, and vanilla JS only.
>
> Requirements:
> - Metric cards: total pages indexed, active jobs, max workers
> - Queue depth bar (visual progress bar, 0–100%)
> - Throttle status badge (Idle / Normal / Active)
> - Form to start a new crawl (URL + depth)
> - Table of all jobs with Cancel and Resume actions
> - Clicking a job opens a slide-in canvas showing its crawled URLs, updating live
> - Search box with pagination
> - Poll /status and /jobs every 2 seconds, but update the DOM only on diff — no full re-renders
> - Dark theme, readable, responsive on a 1280px screen
> - All user input must be HTML-escaped before rendering
>
> Do not use React, Vue, jQuery, or any CDN-hosted library. No npm packages. Ship a single .html file."

## Key Decisions Delivered
- **Diff-based updates**: implemented via comparing prior state in closure variables (`prevJobsJSON`, `prevStatusJSON`). Skips innerHTML replacement when nothing changed — eliminates the flicker the user explicitly flagged.
- **Slide-in canvas for job details**: chosen over modal because modal would block interaction with the main dashboard. Canvas slides in from the right, dashboard remains interactive behind a semi-transparent overlay.
- **Per-job polling in canvas**: when the canvas is open, a second polling loop fetches `/jobs/<id>/pages` every 2 seconds. Stops polling when canvas is closed (no wasted requests).
- **Pagination component**: pure HTML, no library. Tracks `searchOffset` in a closure variable. "Showing X–Y of Z" uses simple arithmetic.

## Interactions
- **← Architect Agent**: consumes API contract
- **← Search Agent**: consumes search result format
- **← Critic Agent**: flicker bug flagged by user → Critic Agent traced it to full innerHTML replacement → UI Agent implemented diff-based update
