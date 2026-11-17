---
id: SPEC-final-scope
companions:
  - assistant.md
  - ../../../docs/adr/0011-feature-sliced-backend-layout.md
  - ../../../docs/adr/0016-booking-participants-and-guest-identity.md
  - ../../../docs/adr/0017-preorder-parts-per-participant.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Final scope and the AI assistant

## Why

Vision: finish the product with a tight feature set and one standout feature. The restaurant app
ends at the pre-order; orders, payments, invoices, reviews and roles leave the plan. Two gaps in
what exists get closed (the owner cannot see the group's pre-order, and session and code rows grow
without cleanup), then an AI assistant on the website lets a signed-in guest ask about the menu and
the restaurant and book, change a booking or fill the cart through a chat, with every change
confirmed by the person.

## Capabilities

- **CAP-1**
  - **intent:** A reader of the roadmap sees the final product scope.
  - **success:** `docs/roadmap.md` lists none of the dropped features in the Non-goals below; booking, the simulator, the dashboards, pre-order, invites, large-party requests and notifications are ticked.
- **CAP-2**
  - **intent:** The booking owner sees what every participant has pre-ordered.
  - **success:** One new route answers the owner with every participant's submitted parts, grouped by participant with their totals and a grand total; another participant or a guest is refused; drafts never appear.
- **CAP-3**
  - **intent:** Session and verification rows stop piling up.
  - **success:** A periodic task deletes `refresh_tokens` rows past `expires_at` and `verification_codes` rows no rule counts any more; a row still needed for reuse detection or a rate limit survives.
- **CAP-4**
  - **intent:** A registered user with a verified email chats with the assistant on the website.
  - **success:** The user creates a session, sends a message and receives the answer as a stream; the session and its history read back; an unverified user or an invite-link guest is refused.
- **CAP-5**
  - **intent:** The assistant answers from the system's data.
  - **success:** It answers about the menu and a dish's composition, how busy the restaurant is, a free table for given people and time, the user's bookings and the user's cart, from tool results; it cannot read another user's data.
- **CAP-6**
  - **intent:** Spending on the model provider has a hard ceiling for the whole system.
  - **success:** Once the daily budget or the per-minute cap is reached, a new turn is refused before streaming with a code and the reset time; a turn already running finishes.
- **CAP-7**
  - **intent:** The assistant changes data only after the person confirms.
  - **success:** Creating, editing and cancelling a booking, adding and removing a dish in the cart and submitting the user's pre-order part arrive as a card; nothing changes until Apply; Apply re-checks access and rules; a double Apply executes once; the card shows every status in `assistant.md`.
- **CAP-8**
  - **intent:** The assistant talks sensibly in the user's language.
  - **success:** Asked in Ukrainian or Russian, it answers in that language about the same data as in English.
- **CAP-9**
  - **intent:** A frontend developer who never saw the backend can build the chat.
  - **success:** One task document in `docs/` covers the routes, stream events, card fields, statuses, errors and the frontend proxy rules in `assistant.md`.
- **CAP-10**
  - **intent:** The chat has a simple design to build from.
  - **success:** A Figma file shows the chat panel, messages, the thinking state and the action card in every status.

## Constraints

- Do not break the frontend: only new routes; existing paths and response shapes stay; the frontend repository is re-checked before each story.
- Each participant still submits only their own pre-order part (ADR 17); the owner gets no final submit, no editing of others' lines, no removing a guest.
- A rotated refresh token stays until `expires_at`, so reuse detection keeps working.
- Periodic jobs run on the existing in-process task runner; one API process per environment.
- The model provider is OpenAI through LangChain (`langchain-openai`); the model name and token prices live in settings.
- AI orchestration lives in its own module; domain services never import it; tools call the domain services the HTTP routes use and never copy a rule.
- The user's identity reaches tools only from the verified JWT; the model can never pass or change it.
- Limits are global for the system, never per user, and count the provider's reported usage, not estimates.
- No translations: no `/api/v2`, no translated menu data; card text is English only.
- The API runs without `OPENAI_API_KEY`; then only the assistant routes are unavailable. Tests and CI never call the provider.
- Infrastructure files follow ADR 15 and are written one at a time with Vlad.

## Non-goals

- Orders as a state machine, the live tracker and the kitchen screen.
- Payments, even a sandbox; invoices; reviews.
- Guest, staff and manager roles in the product (waiters live only in n8n); menu management routes.
- A "pre-order open" flag in the booking response (the frontend works it out from time).
- Translations of any kind, including localized cards.
- The assistant in Telegram, for invite-link guests or for unverified users.
- Per-user limits; editing values inside a card; a tool router over tool groups.

## Success signal

- On dev, a verified user asks in Ukrainian what is in a dish and for a free table for four on Friday evening, applies the card, and the booking appears in their bookings; the owner of a booking sees the whole group's pre-order; dev's `refresh_tokens` count stops growing; spending stops at the daily budget.

## Assumptions

- The assistant serves guests only; staff request routes get no tools, since staff live only in n8n.
- Further guest read routes (submitted pre-order parts, notifications, the invite link) become tools only if the story 4 spec finds users ask for them.
