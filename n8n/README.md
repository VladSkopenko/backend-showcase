# Booking simulator in a local n8n

n8n plays visitors who book and cancel tables through the REST API, so the booking grid on dev
shows a live flow ([ADR 14](../docs/adr/0014-booking-simulator-on-dev.md)). This folder runs n8n on
the developer machine to build and tune the workflow against the local API. Running n8n in the
platform stack on the VM is a later step.

- `compose.yml`: the local n8n, editor on `http://localhost:5678` (loopback only).
- `workflows/booking-simulator.json`: the workflow, kept in git.
- `data/`: n8n's SQLite database, encryption key and saved credentials. Git-ignored. Deleting it
  loses the owner account, the credential and the encryption key.

## Start and stop

From the repository root:

```bash
docker compose -f n8n/compose.yml up -d     # start
docker compose -f n8n/compose.yml down      # stop; data/ stays
```

Open `http://localhost:5678` in Chrome, not Safari. n8n sets its session cookie as `Secure`;
Chrome accepts it on `http://localhost`, Safari drops it and the sign-in never sticks.

On the first start n8n asks for an owner account. It lives only in `data/` and is unrelated to the
API's users.

## Import and export the workflow

Load the file from git into n8n:

```bash
docker compose -f n8n/compose.yml exec -u node n8n \
  n8n import:workflow --input=/home/node/workflows/booking-simulator.json
```

The workflow has a fixed id, `BookingSimul8tor`, so an import overwrites the copy in n8n,
including any edits made in the editor and not exported yet. Import also leaves the workflow
inactive (`--activeState` defaults to `false`): turn it on in the editor when the bots should
run on schedule.

Write the editor's version back to git:

```bash
docker compose -f n8n/compose.yml exec -u node n8n \
  n8n export:workflow --id=BookingSimul8tor --pretty \
  --output=/home/node/workflows/booking-simulator.json
```

`workflows/` is mounted into the container as `/home/node/workflows`, so the exported file lands
in the repository. Review the diff before committing: n8n writes its own layout and extra fields.

## The bot password credential

The `Log in` node signs in with a Custom Auth credential, so the password never appears in the
workflow file. In n8n, create a credential of type **Custom Auth** named exactly
`Booking bot password` with this JSON:

```json
{"body": {"password": "..."}}
```

n8n merges the `body` into the login request, next to the `email` the workflow sends. All bots
share this one password. Keep it outside the repository. If the `Log in` node shows no credential
after an import, select `Booking bot password` there once.

## Bots

On dev 40 booking bots come from migrations, all verified and with the password from the
credential: `0011` adds `booking-bot-1@example.com` to `booking-bot-4@example.com` (named
`Booking Bot 1` to `Booking Bot 4`), and `0020` adds `booking-bot-5@example.com` to
`booking-bot-40@example.com` with distinct human first and last names. The current workflow
uses bots 1 to 4 only; bots 5 to 40 wait for the simulator story.

The local database gets no booking bots from migrations, so it has only bots 1 to 4, registered
by the script below through the API with the same password; locally `/auth/register` echoes the
code as `debug_code`:

```bash
read -rs -p 'Bot password: ' BOT_PASSWORD; echo
for n in 1 2 3 4; do
  code=$(curl -s -X POST http://localhost:8000/api/v1/auth/register \
    -H 'Content-Type: application/json' \
    -d "$(jq -n --arg n "$n" --arg p "$BOT_PASSWORD" '{first_name: "Booking",
         last_name: "Bot \($n)", email: "booking-bot-\($n)@example.com",
         password: $p, password_confirmation: $p}')" \
    | jq -r '.debug_code // empty')
  [ -n "$code" ] || { echo "booking-bot-$n: not registered (already exists?)"; continue; }
  curl -s -X POST http://localhost:8000/api/v1/auth/verify-email \
    -H 'Content-Type: application/json' \
    -d "{\"email\": \"booking-bot-$n@example.com\", \"code\": \"$code\"}"
done
```

## API base URL

`Plan the visit` sets `apiBaseUrl`. The committed value, `http://host.docker.internal:8000/api/v1`,
reaches the API running on the host from inside the container. Point it at the dev API to drive
dev. Never point it at staging or prod: the bots would take real guests' tables.

## What the workflow does

Every run picks one bot and either books a table (about 80% of runs) or cancels one of its
bookings (about 20%).

| Node | What it does |
|---|---|
| Every 5 minutes | Schedule trigger, in `Asia/Tbilisi` like the booking grid. |
| Plan the visit | Picks a random bot (1 to 4), a date from today to 7 days ahead in restaurant time, a party of 1 to 4 and the action, `book` or `cancel`. |
| Log in | `POST /auth/login` with the bot's email and the password from the credential; keeps the full response for its headers. |
| Keep the session | Turns the `Set-Cookie` headers into one `Cookie` header for the next requests. |
| Book this time? | Passes the visit on only when the action is `book`. |
| Search tables | `GET /bookings/tables` for the date and party size, up to 50 tables, so every location comes in one page. |
| Pick a free slot | Groups free tables by location and start time, keeps only the groups with at least 4 free tables, then picks a random start and a random table in it. Stops when no group qualifies. |
| Book | `POST /bookings`, keeping any status for the next node. |
| Check the booking answer | Lets 201 and 409 through: a 409, when a guest took the slot meanwhile or the bot already holds an overlapping booking, is just a lost visit. Any other status fails the run, so a broken simulator shows up as a failed execution. |
| Cancel this time? | Passes the visit on only when the action is `cancel`. |
| List my bookings | `GET /bookings` for the bot. |
| Pick a booking to cancel | Keeps the bot's `CONFIRMED` bookings that start more than 30 minutes from now (the cancel cutoff) and picks one. Stops when there are none. |
| Cancel | `POST /bookings/{id}/cancel`, keeping any status for the next node. |
| Check the cancel answer | Lets 200 and 409 through and fails the run on any other status. |

The 4-free-tables rule leaves real guests a choice: the bots book only where at least 4 fitting
tables are free at one location and one start time, so they never take the last tables of a slot.
