---
title: 'Assistant: frontend task document and Figma mockup'
type: 'chore'
created: '2026-11-18'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/assistant.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/stories/4b-assistant-streamed-turn.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/stories/4c-assistant-global-limits.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The frontend developer has never seen this backend and the chat has no picture to build from.

**Approach:** One task document in `docs/` with the routes, events, shapes, errors and the Next.js proxy rules of stories 4a to 4c, and a simple chat mockup in Figma (CAP-9 for the read part, CAP-10). Story 5 extends the document with the card, apply and cancel.

## Boundaries & Constraints

**Always:**
- `docs/assistant-frontend-task.md`, in English, for a developer who sees only the frontend repository: the flow in one paragraph; the four routes with request and response bodies and the session and message shapes; the event sequence `thinking → chunk … → done` and the `error` event, with every payload; the error table (401 `NOT_AUTHENTICATED`, 403 `EMAIL_NOT_VERIFIED`, 404 `ASSISTANT_SESSION_NOT_FOUND`, 422 `VALIDATION_ERROR`, 429 `ASSISTANT_BUSY` and `ASSISTANT_BUDGET_EXHAUSTED` with `retry_after` and the `Retry-After` header, 503 `ASSISTANT_UNAVAILABLE`) and what to show for each, the budget case included (a notice with the reset time, the input stays usable); the Next.js rules: one route handler per route like the existing ones, the messages handler passes the upstream stream through (`fetch` with the browser's cookie header, `Accept: text/event-stream`, return `response.body` with `Content-Type`, `Cache-Control: no-cache` and `X-Accel-Buffering: no`, never `request.json()` on the response) and declares `export const maxDuration = 300`; the `next.config.ts` rewrite fallback is not used for the stream; the browser reads the stream with `fetch` and a reader, not `EventSource`, since the request is a `POST`; a note that story 5 adds the `action` event and the card; scenarios to check.
- The mockup: a new Figma file in the same project as the design copy, never inside it, named after the chat; modelled on the reference frontend's components (a panel at the right edge with a header, a message list, a thinking indicator, a pill input with a send button) in family-rest's tokens (Poppins, `--accent #0f7a37`, `--bg-yellow #f7f7ec`, `--border #e6e6e6`, `--text #232323`, `--text-muted #6b6b6b`); frames: the empty state, a conversation with user and assistant bubbles, the thinking state, the budget notice, and the action card in each status `pending`, `applied`, `cancelled`, `expired`, `failed` (the shape from `assistant.md`, drawn now so story 5 has it). Mobile width 375 and desktop 1440 as the design copy's container.
- The document is written after 4c's code is reviewed, so it describes shipped routes; the mockup is drawn by Claude after this spec is approved, with the Figma MCP, and Vlad is asked for screenshots when the Starter limit stops the session.

**Never:** Frontend code; any backend change; the design copy file touched; translations of the document.

</frozen-after-approval>

## Code Map

- `~/Desktop/platform-core-back/docs/ai-assistant-actions-frontend-task.md` -- the reference task document (read-only): short declarative prose, event sequences in code blocks, a JSON example followed by a key table, tables for statuses, routes and errors, numbered rules, scenario bullets.
- `~/Desktop/family-rest/app/api/v1/bookings/route.ts:7-29`, `app/api/_utils/{cookieHeaders,toNextResponse,handleError}.ts`, `lib/api/clientApi.ts:26-80`, `next.config.ts:17-28` -- how the frontend proxies today (one handler per route, the raw cookie header forwarded, errors passed through, a 401 refresh-and-retry interceptor, the `/api/v1/:path*` rewrite fallback); the document must fit this shape.
- `~/Desktop/platform-web/apps/web/src/modules/ai-assistant/components/` and `actions/components/ActionCard/` -- the components to model the mockup on (drawer 400 px at the right edge, header with title and close, message list with a user bubble at 70 % and a plain assistant block with an icon, thinking dots, pill input with a send button, a 420 px card with title, status badge, fields, notices and the footer per status).
- `~/Desktop/family-rest/app/globals.css:1-23,78-98` -- the tokens and container widths.
- Figma: the design copy is file `nwwfWswg9sGcjG8olVRF0U` (Claude memory `figma-design-file`); `create_new_file` in its project, then `create_session`.
- `README.md:142`, `README.uk.md` -- unchanged until story 5.

## Tasks & Acceptance

**Execution:**
- [x] `docs/assistant-frontend-task.md` -- the document -- record.
- [x] Figma file with the frames above -- design, by Claude in the Figma MCP, outside the subagent's dispatch.

**Acceptance Criteria:**
- Given the document and the local API of 4c, when every route, body, event and error it names is tried with curl, then each matches.
- Given the Figma file, when Vlad opens it, then the frames are there and the design copy is untouched.

## Implementation Notes

- 2026-11-18: the task document shipped with #47 and was updated with #49 (rewrite streaming checked on dev, new tools). The Figma mockup was drawn by Claude in a new file in Vlad's Drafts (Claude memory `figma-design-file`; the design copy's project id is unknown, Vlad can move it): conversation with the thinking state, an answer with a pending card, the empty state with the budget and busy notices, and the action card in five statuses as one component. Two `use_figma` calls; the send and close glyphs were redrawn as SVG because Poppins lacks them. The design copy was not touched.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Spec review: the reference task document has no path | low | not in this repository | patch: path given |
| Spec review: rewrite or route handlers for the stream undecided | medium | `family-rest/next.config.ts` fallback rewrite; Vercel rewrite streaming unverified; only a handler sets `maxDuration` | patch: handlers |
| Spec review: CAP-9 is complete only after story 5 | low | cards deferred | patch: Intent |

## Verification

**Manual checks (if no CLI):**
- Every curl in the document's scenarios answers as written against the local API of 4c.
- The Figma project lists the new file beside the design copy; the copy's last-modified time is unchanged.
