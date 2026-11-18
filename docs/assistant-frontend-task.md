# AI assistant chat (frontend task)

A signed-in guest with a verified email chats with the restaurant's assistant on the website. The
assistant answers about the menu, the locations, free tables and the guest's own bookings and
pre-order, and books a table through a confirmation card the guest applies or cancels. Editing
and cancelling a booking and changing the cart through cards come next, on the same card. This
document is the contract for the chat and the card.

## Flow

The guest opens the chat panel. The frontend lists the guest's sessions, opens the latest one or
creates a new one, and shows its messages. When the guest sends a message, the frontend posts it
and reads the answer as a stream: a thinking indicator, then the text growing piece by piece, then
the final message id. The question shows at once; the answer bubble grows while the stream runs.

Only signed-in users with a verified email get the chat. A guest who joined through an invite
link and has only the `guest_token` cookie does not: hide the chat entry for them.

## Endpoints

All paths are under `/api/v1`, authenticated by the usual session cookies.

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/assistant/sessions` | none | `201` Session |
| `GET` | `/assistant/sessions` | none | `200` Session[], latest activity first, not paginated |
| `GET` | `/assistant/sessions/{session_id}` | none | `200` Session with `messages` |
| `POST` | `/assistant/sessions/{session_id}/messages` | `{"text": "…"}` | `200` `text/event-stream` |
| `GET` | `/assistant/sessions/{session_id}/actions/{action_id}` | none | `200` Action |
| `POST` | `/assistant/sessions/{session_id}/actions/{action_id}/cancel` | none | `200` Action |
| `POST` | `/assistant/sessions/{session_id}/actions/{action_id}/apply` | none | `200` `text/event-stream` |

Session:

```json
{
  "id": "f8b5809a-b282-4763-8e9d-618106874264",
  "title": "What desserts do you have, and which one is the cheapest?",
  "created_at": "2026-11-18T13:46:11.168763Z",
  "updated_at": "2026-11-18T13:46:30.757456Z"
}
```

The detail adds `messages`, oldest first:

```json
{ "id": "…", "role": "USER", "text": "What is in the sorbet?", "created_at": "…", "action": null }
```

| Key | Meaning |
|---|---|
| `title` | `"New chat"` until the first message; then the first message cut to 60 characters. It never changes after that. |
| `updated_at` | Moves with every message. Sort and group the history by it. |
| `role` | `USER` or `ASSISTANT`. |
| `text` | Plain text. The assistant is told not to use markdown; render it as text with line breaks. |
| `action` | The confirmation card the assistant proposed with this message (an Action, see below), or `null`. Render it under the bubble. |

`text` in the request is 1 to 2000 characters after trimming whitespace. A session without a new
message for 7 days is deleted on the server, so a stored session id can turn into a 404.

## Streaming

The answer arrives as Server-Sent Events over a `POST` response, so `EventSource` cannot be used.
Read it with `fetch` and `response.body.getReader()`, split on blank lines, and parse each block's
`event:` and `data:` lines. Every `data` is JSON.

```text
thinking → chunk … → done
thinking → thinking → chunk … → done        (the assistant looked something up first)
thinking → thinking → chunk … → action → done   (the assistant proposed a booking)
thinking → chunk … → error                  (the turn failed midway)
```

| Event | `data` | What to do |
|---|---|---|
| `thinking` | `{}` | Show the thinking indicator. It comes again each time the assistant looks something up: the menu, the locations, free tables, the guest's bookings or pre-order. |
| `chunk` | `{"text": "…"}` | Append to the answer bubble. Pieces are small, often part of a word. |
| `action` | an Action | A confirmation card for this answer. Show it under the bubble. It comes after the last `chunk` and before `done`, at most once per answer. |
| `done` | `{"message_id": "…", "created_at": "…"}` | The answer is saved. Stop the indicator; give the bubble this id. |
| `error` | `{"code": "…", "message": "…"}` | The turn ended without a saved answer. Keep any text already shown, mark the bubble as failed and offer to ask again. |

`error` codes: `ASSISTANT_TIMEOUT` (the turn ran past its time cap), `ASSISTANT_PROVIDER_ERROR` (the
model provider failed), `SERVER_ERROR` (anything else). After `error` the question stays in the
session and the title is already set, but no answer is saved; a reload shows the question alone.

If a turn hits the server's cap on lookups, the answer is a fixed English sentence asking to try
again in smaller steps; it arrives as an ordinary `chunk` and `done`.

## Confirmation cards

The assistant never changes data by itself. When the guest has named a table, a date, a time and
the party size, the assistant checks every booking rule and proposes the booking as a card. Nothing
is booked until the guest presses the card's button; the guest may also cancel it or simply ignore
it. A session has at most one pending card: a newer card makes the older pending one `CANCELLED`.

Action:

```json
{
  "id": "4b1c…",
  "kind": "booking.create",
  "status": "PENDING",
  "created_at": "2026-11-18T15:02:11Z",
  "expires_at": "2026-11-19T15:02:11Z",
  "result": null,
  "error": null,
  "card": {
    "title": "Book a table",
    "confirm_label": "Book",
    "notice": null,
    "fields": [
      { "label": "Location", "value": "48 Rustaveli Avenue" },
      { "label": "Table", "value": "Table 2, up to 4 guests" },
      { "label": "Date", "value": "Fri, 20 Nov 2026" },
      { "label": "Time", "value": "19:00 – 20:30" },
      { "label": "Guests", "value": "4" }
    ]
  }
}
```

| Key | Meaning |
|---|---|
| `kind` | What the card does. Only `booking.create` today; render every kind the same way from `card`. |
| `card.title` | The card's heading. |
| `card.fields` | Label and value pairs, in order. Show them as they are; the text is English and already formatted (times are restaurant time). |
| `card.notice` | A line under the fields, or `null`. For a large party: "Sent as a request; the restaurant confirms it." |
| `card.confirm_label` | The text of the main button ("Book"). The second button is "Cancel". |
| `expires_at` | After this moment the card can no longer be applied. |
| `result` | After a successful apply: `{"booking_id": "…", "status": "CONFIRMED"}` (or `"PENDING"` for a request). Link to the booking. |
| `error` | After a failed apply: `{"code": "…", "message": "…"}`, e.g. `SLOT_UNAVAILABLE` when someone took the table meanwhile. |

Statuses, with the uppercase label of the Figma file:

| `status` | Looks like |
|---|---|
| `PENDING` | Both buttons active. |
| `APPLIED` | Label "APPLIED", buttons gone, a link to the booking from `result.booking_id`. |
| `CANCELLED` | Label "CANCELLED", buttons gone, card dimmed. |
| `EXPIRED` | Label "EXPIRED", buttons gone, card dimmed. |
| `FAILED` | Label "FAILED", buttons gone, `error.message` under the fields. |

The server shows a pending card past `expires_at` as `EXPIRED` everywhere. A card already on screen
does not update itself: once `expires_at` passes, show it as `EXPIRED` on the client too.

### Apply

`POST …/actions/{action_id}/apply` with no body. The outcome is decided and saved before the
response starts, so a refusal is plain JSON (check the status first). On `200` the body is a stream:

```text
action → thinking → chunk … → done      (applied or failed, then the assistant's comment)
action → thinking → error               (the outcome stands; only the comment failed)
action → done                           (the card was applied before; nothing ran again)
```

| Event | What to do |
|---|---|
| `action` | Replace the card with this Action: `APPLIED` with `result`, or `FAILED` with `error`. |
| `thinking`, `chunk`, `done`, `error` | As in a turn: a new assistant bubble with the comment on the outcome. After `error` the card keeps the outcome from `action`. |

A repeated apply (a double click, a retry after a lost connection) executes nothing and streams
`action` (`APPLIED`) and `done` with `"message_id": null` and `"created_at": null`: update the card
and add no new bubble when `message_id` is `null`.

Disable the button while the apply request runs. The apply route needs the same streaming route
handler as the messages route (see the Next.js proxy).

### Cancel and read

- `POST …/actions/{action_id}/cancel` answers the Action as `CANCELLED`; nothing else changes.
  Cancelling a card already cancelled answers the same again.
- `GET …/actions/{action_id}` answers the Action as it is now, for example to refresh a card after
  a reload; the session read-back also carries each message's `action`.

### Card errors

| Status | `code` | When | Show |
|---|---|---|---|
| 404 | `ASSISTANT_ACTION_NOT_FOUND` | unknown id, or a card outside this session or user | reload the session |
| 422 | `VALIDATION_ERROR` | a session or action id that is not a UUID | reload the session |
| 409 | `ASSISTANT_ACTION_NOT_PENDING` | apply of a cancelled, failed or expired card; cancel of an applied, failed or expired one | refresh the card with `GET` and show its status |

The access errors (401, 403, 503) are the same as for the other assistant routes.

## Errors before the stream

Every refusal answers plain JSON with `{"code", "message"}` before any stream starts, so check the
status first and read the body as a stream only on `200`.

| Status | `code` | When | Show |
|---|---|---|---|
| 401 | `NOT_AUTHENTICATED` | no valid access cookie | refresh the session once and retry, as `clientApi` does; then the sign-in prompt |
| 403 | `EMAIL_NOT_VERIFIED` | the email is not verified | should not happen for a signed-in user; treat as sign-in needed |
| 404 | `ASSISTANT_SESSION_NOT_FOUND` | unknown, deleted or another user's session | drop the stored id, open a new session |
| 422 | `VALIDATION_ERROR` | empty or too long `text`, bad id | keep the input, show the message |
| 503 | `ASSISTANT_UNAVAILABLE` | the assistant is not configured on this environment | hide the chat or show "unavailable" |

Coming next, same shape: `429` with `ASSISTANT_BUDGET_EXHAUSTED` when the day's budget for the whole
site is spent, and `429` with `ASSISTANT_BUSY` when too many people chat at once. Both carry
`retry_after` in seconds and a `Retry-After` header. Show a notice with the time the chat comes
back and keep the input usable.

## Next.js proxy

The frontend reaches the API through its own route handlers, one file per route, forwarding the
browser's `cookie` header (`app/api/_utils/cookieHeaders.ts`). Add six handlers under
`app/api/v1/assistant/`, one per route in the endpoints table: the sessions, the session, the
messages, the action, cancel and apply. The JSON routes follow the existing pattern with axios.

The messages and apply routes must pass the stream through instead of reading the whole body.
The apply handler, `app/api/v1/assistant/sessions/[id]/actions/[actionId]/apply/route.ts`, is the
streaming handler below with the action id in the path and no request body:

```ts
// app/api/v1/assistant/sessions/[id]/messages/route.ts
export const maxDuration = 300; // Vercel Hobby with fluid compute; the backend caps a turn at 240 s

type Context = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Context) {
  const { id } = await params;
  const upstream = await fetch(
    `${process.env.API_URL}/assistant/sessions/${encodeURIComponent(id)}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...cookieHeaders(request),
      },
      body: await request.text(),
    },
  );
  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
```

Rules:

1. Use `fetch`, not axios, for this handler: axios buffers the whole response.
2. Never call `response.json()` or `response.text()` on a `200` upstream; return its body as is.
3. Keep `maxDuration = 300` on this handler. Without it Vercel cuts the stream early.
4. Keep the handler even though the `next.config.ts` rewrite fallback already forwards this path
   and streams: on 2026-11-18 a browser `fetch` through the rewrite on dev received the chunks over
   about a second, not in one piece. Only a handler sets `maxDuration`, and the time limit of a
   rewrite to an external host is unchecked.
5. In the browser, call `/api/v1/assistant/sessions/{id}/messages` with `fetch`, pass an
   `AbortController` so closing the panel or switching sessions stops the read, and handle `401`
   by the same single shared refresh `clientApi` uses before retrying once.

## Design

The Figma mockup of the chat panel, the messages, the thinking state and the confirmation card in
every status is shared separately. Follow it and the tokens in `app/globals.css`.

## Scenarios to check

- A new guest opens the chat: an empty session, "New chat", the input focused.
- Ask "What desserts do you have?": thinking, a second thinking, text growing, done; the session
  title becomes the question.
- Ask a follow-up in the same session: the assistant uses the earlier answer; the title stays.
- Ask "Is there a table for four on Friday at 19:00?" and "What are my bookings?": the answers
  match the booking search and the reservations page.
- Reload: the session lists first and its messages read back in order.
- Ask in Ukrainian: the answer is in Ukrainian.
- Close the panel during an answer: the request is aborted, no error toast.
- Open a stored session id that no longer exists: 404, a new session opens.
- Sign in as a guest with only the invite cookie: no chat entry.
- Ask "Book a table for four on Friday at 19:00": thinking, text, a card with the table, date, time
  and guests, done; the reservations page shows nothing new yet.
- Press Book: the card turns `APPLIED`, a short comment follows, the booking is on the reservations
  page. Press it again (or replay the request): no second booking, no new bubble.
- Ask for a party of six: the card shows the request notice; after Book the booking is pending.
- Get a card, then ask for another time: the first card shows `CANCELLED`, the new one is pending.
- Press Cancel: the card turns `CANCELLED`; pressing Book on it answers 409.
- Leave a card for longer than a day: it shows `EXPIRED`; Book answers 409.
- Take the table in another tab before pressing Book: the card turns `FAILED` with the reason and
  the assistant comments on it.
- Reload after any of these: each card reads back with its status under its message.
