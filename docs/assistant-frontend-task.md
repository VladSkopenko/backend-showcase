# AI assistant chat (frontend task)

A signed-in guest with a verified email chats with the restaurant's assistant on the website. The
assistant answers about the menu now; tables, the guest's bookings and pre-order come next, then
changes through confirmation cards. This document is the contract for the read-only chat. The
backend part is live on dev.

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
{ "id": "…", "role": "USER", "text": "What is in the sorbet?", "created_at": "…" }
```

| Key | Meaning |
|---|---|
| `title` | `"New chat"` until the first message; then the first message cut to 60 characters. It never changes after that. |
| `updated_at` | Moves with every message. Sort and group the history by it. |
| `role` | `USER` or `ASSISTANT`. |
| `text` | Plain text. The assistant is told not to use markdown; render it as text with line breaks. |

`text` in the request is 1 to 2000 characters after trimming whitespace. A session without a new
message for 7 days is deleted on the server, so a stored session id can turn into a 404.

## Streaming

The answer arrives as Server-Sent Events over a `POST` response, so `EventSource` cannot be used.
Read it with `fetch` and `response.body.getReader()`, split on blank lines, and parse each block's
`event:` and `data:` lines. Every `data` is JSON.

```text
thinking → chunk … → done
thinking → thinking → chunk … → done        (the assistant looked something up first)
thinking → chunk … → error                  (the turn failed midway)
```

| Event | `data` | What to do |
|---|---|---|
| `thinking` | `{}` | Show the thinking indicator. It can come again after text, when the assistant checks the menu. |
| `chunk` | `{"text": "…"}` | Append to the answer bubble. Pieces are small, often part of a word. |
| `done` | `{"message_id": "…", "created_at": "…"}` | The answer is saved. Stop the indicator; give the bubble this id. |
| `error` | `{"code": "…", "message": "…"}` | The turn ended without a saved answer. Keep any text already shown, mark the bubble as failed and offer to ask again. |

`error` codes: `ASSISTANT_TIMEOUT` (the turn ran past its time cap), `ASSISTANT_PROVIDER_ERROR` (the
model provider failed), `SERVER_ERROR` (anything else). After `error` the question stays in the
session and the title is already set, but no answer is saved; a reload shows the question alone.

If a turn hits the server's cap on lookups, the answer is a fixed English sentence asking to try
again in smaller steps; it arrives as an ordinary `chunk` and `done`.

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
browser's `cookie` header (`app/api/_utils/cookieHeaders.ts`). Add four handlers under
`app/api/v1/assistant/`. The three JSON routes follow the existing pattern with axios.

The messages route must pass the stream through instead of reading the whole body:

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
4. Do not rely on the `next.config.ts` rewrite fallback for this route. It would forward the path
   without a handler, but it cannot set `maxDuration`, and whether it streams on Vercel is
   unchecked.
5. In the browser, call `/api/v1/assistant/sessions/{id}/messages` with `fetch`, pass an
   `AbortController` so closing the panel or switching sessions stops the read, and handle `401`
   by the same single shared refresh `clientApi` uses before retrying once.

## Design

A chat mockup follows in the Figma project next to the main design: a panel at the right edge
with a header, the message list, the thinking state, the input, and the confirmation card for the
next step. Until then, follow the existing modals and drawers and the tokens in `app/globals.css`.

## Scenarios to check

- A new guest opens the chat: an empty session, "New chat", the input focused.
- Ask "What desserts do you have?": thinking, a second thinking, text growing, done; the session
  title becomes the question.
- Ask a follow-up in the same session: the assistant uses the earlier answer; the title stays.
- Reload: the session lists first and its messages read back in order.
- Ask in Ukrainian: the answer is in Ukrainian.
- Close the panel during an answer: the request is aborted, no error toast.
- Open a stored session id that no longer exists: 404, a new session opens.
- Sign in as a guest with only the invite cookie: no chat entry.
