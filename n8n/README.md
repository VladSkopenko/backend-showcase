# Booking simulator and waiter bot in a local n8n

n8n plays the restaurant's guests through the REST API: they book tables, ask for large tables,
pre-order food and cancel, with the time, day and party patterns of a real restaurant, so dev
fills with data worth a dashboard ([ADR 14](../docs/adr/0014-booking-simulator-on-dev.md)). A
second workflow plays a waiter who approves or rejects the large-party requests. Both workflows
drive the public dev API only. This folder also runs n8n on the developer machine, to try the
workflows before they go to the n8n on the VM.

- `compose.yml`: the local n8n, editor on `http://localhost:5678` (loopback only).
- `workflows/booking-simulator.json`: the guests' workflow, kept in git.
- `workflows/waiter-bot.json`: the waiter's workflow, kept in git
  ([The waiter bot](#the-waiter-bot)).
- `package.json`, `tests/`: the checks of both workflows without the API, as `node:test` tests
  with no dependencies; `npm test` in `n8n/` runs them (Node 20 or newer).
  - `tests/booking-simulator.test.mjs`: checks the guests' weights against the patterns
    ([The plan check](#the-plan-check)).
  - `tests/waiter-bot.test.mjs`: checks the waiter's weights and decisions
    ([The waiter check](#the-waiter-check)).
  - `tests/support/`: their shared helpers: loading Code nodes from the workflow JSON, the seeded
    random, the share assertions, the execution emulator and the stub staff API.
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

## Import and export the workflows

Load a file from git into n8n:

```bash
docker compose -f n8n/compose.yml exec -u node n8n \
  n8n import:workflow --input=/home/node/workflows/booking-simulator.json
docker compose -f n8n/compose.yml exec -u node n8n \
  n8n import:workflow --input=/home/node/workflows/waiter-bot.json
```

Each workflow has a fixed id, `BookingSimul8tor` and `WaiterBotDecides`, so an import overwrites
the copy in n8n, including any edits made in the editor and not exported yet. Import also leaves
the workflow inactive (`--activeState` defaults to `false`): turn it on in the editor when the
bots should run on schedule.

The n8n in the platform stack on the VM has no shell access, so the file goes in through the
editor:

1. Open `https://backend-showcase-platform.tail88eb36.ts.net:5678` (on the tailnet) and open the
   workflow (`Booking simulator` or `Waiter bot`), or create a new workflow if it is not there
   yet. The waiter is a workflow of its own: never import it over the simulator.
2. In the workflow menu choose **Import from File** and pick
   `n8n/workflows/booking-simulator.json` or `n8n/workflows/waiter-bot.json` from a checkout of
   the merged branch.
3. Open the `Log in` node and check that it shows the `Booking bot password` credential; select it
   if it does not.
4. Save, then publish (activate) the workflow so the schedule runs.

Write the editor's version back to git:

```bash
docker compose -f n8n/compose.yml exec -u node n8n \
  n8n export:workflow --id=BookingSimul8tor --pretty \
  --output=/home/node/workflows/booking-simulator.json
docker compose -f n8n/compose.yml exec -u node n8n \
  n8n export:workflow --id=WaiterBotDecides --pretty \
  --output=/home/node/workflows/waiter-bot.json
```

`workflows/` is mounted into the container as `/home/node/workflows`, so the exported file lands
in the repository. Review the diff before committing: n8n writes its own layout and extra fields.

## The bot password credential

The `Log in` node of each workflow signs in with a Custom Auth credential, so the password never
appears in the workflow file. In n8n, create a credential of type **Custom Auth** named exactly
`Booking bot password` with this JSON:

```json
{"body": {"password": "..."}}
```

n8n merges the `body` into the login request, next to the `email` the workflow sends. All bots,
the waiter included, share this one password. Keep it outside the repository. If the `Log in`
node shows no credential after an import, select `Booking bot password` there once.

## Bots

On dev 40 booking bots come from migrations, all verified and with the password from the
credential: `0011` adds `booking-bot-1@example.com` to `booking-bot-4@example.com` (named
`Booking Bot 1` to `Booking Bot 4`), and `0020` adds `booking-bot-5@example.com` to
`booking-bot-40@example.com` with distinct human first and last names. The workflow plays all
40; which of them are regulars is its own choice (`CONFIG.personas`), nothing in the database
marks it.

The waiter is `waiter-bot@example.com`, a verified staff user from migration `0018` on dev and
local, with the same password. Locally it needs no registration.

The local database gets no booking bots from migrations. To try the workflow locally, register
all 40 with the script below through the API, with the same password; locally `/auth/register`
echoes the code as `debug_code`. They are named `Booking Bot 1` to `Booking Bot 40` there:

```bash
read -rs -p 'Bot password: ' BOT_PASSWORD; echo
for n in $(seq 1 40); do
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

`CONFIG.apiBaseUrl` in `Plan the visit` (simulator) and in `Plan the round` (waiter) is the public
dev API, `https://backend-showcase-dev.duckdns.org/api/v1`. To try a workflow on the local n8n,
change it in the editor to `http://host.docker.internal:8000/api/v1`, which reaches the API
running on the host from inside the container, and never commit that value: an export writes it
into the file.
Never point it at staging or prod: the bots would take real guests' tables.

## What the simulator does

Every 2 minutes one run plays one bot. Half of the runs go to the 10 regulars (bots 1 to 10), half
to the 30 occasional guests (bots 11 to 40). A run may first pre-order for an approved large-party
request, then cancels one of the bot's bookings (about 15% of runs) or books (the rest). The steps
run in this order because each one is connected to the next: every fork ends in two gates of
which exactly one passes, so the order does not depend on where the nodes sit on the canvas.

- **Booking.** The date follows the lead-time shares, weighted by the day of the week; the party
  size follows the table for that date (weekday, weekend from Friday to Sunday, or a holiday:
  14 February, 8 March, 31 December). The start is a weighted pick by hour among the starts that
  are free and still ahead. A run that draws today after the last start (21:30) books nothing. A
  regular books at their favourite location 80% of the time, an occasional guest anywhere.
- **Instant booking, 1 to 4 people.** Only where at least 4 fitting tables are free at that
  location and start, so real guests always keep a choice (ADR 14). The answer is `CONFIRMED`.
- **Large-party request, 5 to 8 people.** Only for starts more than 2 hours ahead, since the API
  refuses closer ones; a run that draws today with no start that far ahead sends nothing. A
  request holds no table, so one free fitting table is enough and the 4-free-tables rule does not
  apply. The answer is `PENDING`; staff decide it later.
- **Pre-order.** Right after a confirmed booking that starts more than 30 minutes ahead, and, with
  a set chance per run, for one of the bot's approved requests (a confirmed booking above 4
  people) that has no submitted part and an empty draft cart. A draft left by a broken run is
  never mixed into a new pre-order: that request is skipped. Per person: a main course 90%, an
  appetizer 50%, a dessert 40%; at lunch desserts drop to 25%, at dinner appetizers rise to 60%.
  Only available dishes; each location prefers three dishes, each regular two favourites. Each
  dish goes into the cart with its quantity; a dish answered with 409 (sold out meanwhile) is
  skipped, and the cart is submitted when anything went in.
- **Cancel.** One of the bot's own `CONFIRMED` or `PENDING` bookings that starts more than 30
  minutes ahead (the cancel cutoff).

Favourite locations and dishes come from a stable hash of the bot number or the location id, so
the workflow keeps no state between runs.

Expected refusals end a step quietly: a 409 when a guest took the slot, the bot already holds an
overlapping booking, a request came too late, the pre-order closed or a dish sold out. Any other
status fails the execution, so a broken simulator shows up in n8n. So does a menu longer than one
page of 50 dishes, which the workflow would otherwise read only in part.

| Node | What it does |
|---|---|
| Every 2 minutes | Schedule trigger, in `Asia/Tbilisi` like the booking grid. |
| Plan the visit | Holds `CONFIG`. Picks the persona and bot, the action, whether to look for an approved request, the date, the party size and a random key per possible start. |
| Log in | `POST /auth/login` with the bot's email and the password from the credential; keeps the full response for its headers. |
| Keep the session | Turns the `Set-Cookie` headers into one `Cookie` header for the next requests. |
| List my bookings | `GET /bookings` for the bot. |
| Load the menu | `GET /menu/dishes`, up to 50 dishes, the whole menu in one page. |
| Gather the visit | Puts the plan, the session, the bookings and the dishes into one item. Fails the run when the menu has more dishes than the page. |
| Find approved requests | With `approvedPreorderChance`, lists the bot's own confirmed bookings above 4 people that start more than 30 minutes ahead. |
| Check approved requests / No approved request | Gates: one item per request found, or straight on to the action when there is none. |
| Read my pre-orders | `GET /bookings/{id}/my-pre-order` for each request. |
| Note the parts | Notes how many parts each request has submitted. |
| Read the carts | `GET /bookings/{id}/cart` for each request. |
| Pick an approved request | Picks one with no submitted part and an empty cart; always one item, with or without a request, so the run goes on. |
| Compose the pre-order | Draws the dishes for every person and adds up the quantities into one order; empty without a booking. Shared by both pre-order paths. |
| Order the dishes / Nothing to order | Gates: one item per dish, or on to the next step when the order is empty. |
| Add the dishes | `PUT /bookings/{id}/cart/items/{dish_id}` with the quantity, for each dish. |
| Check the dishes | Counts the dishes added; a 409 skips its dish, any other status but 200 fails the run. |
| Anything added? / Nothing added | Gates: submit when a dish went in, otherwise on to the next step. |
| Submit the pre-order | `POST /bookings/{id}/cart/submit`. |
| Check the submit answer | Lets 200 and 409 through and fails the run on any other status. |
| After the pre-order | After an approved request's pre-order goes on to the action; after a new booking's pre-order ends the run. |
| Cancel this time? | When the action is `cancel`, picks one of the bot's own `CONFIRMED` or `PENDING` bookings more than 30 minutes ahead. |
| Cancel | `POST /bookings/{id}/cancel`, keeping any status for the next node. |
| Check the cancel answer | Lets 200 and 409 through and fails the run on any other status. |
| Book this time? | Passes the visit on when the action is `book` and some start is still possible. |
| List locations | `GET /locations`. |
| Choose the location | The regular's favourite (or another location), or any location for an occasional guest. |
| Search tables | `GET /bookings/tables` for the date, party size and location, up to 50 tables. |
| Pick a free slot | Keeps the starts with enough free fitting tables (4 for an instant booking, 1 for a request), takes the one with the highest plan key, and a random free table in it. Stops when none qualifies. |
| Book | `POST /bookings`, keeping any status for the next node. |
| Check the booking answer | 409 ends the run quietly, any status but 201 fails it. Passes a `CONFIRMED` booking more than 30 minutes ahead on to the pre-order. |

The plan key per start, `u^(1/weight)` with a random `u`, turns "the free start with the highest
key" into a pick weighted by `startWeights` among whichever starts the search finds free.

## Simulator CONFIG

Every number that tunes the bots lives in the `CONFIG` object at the top of `Plan the visit`, with
the starting weights of
[patterns.md](../_bmad_output/implementation-artifacts/spec-restaurant-simulation/patterns.md);
the later nodes read it from the plan.

| Key | What it tunes |
|---|---|
| `apiBaseUrl`, `timeZone` | The API the bots use and the restaurant's time zone. |
| `personas` | Bot ranges, share of runs, how often a regular books at the favourite location, how many favourite dishes. |
| `cancelShare` | Share of runs that cancel instead of booking. |
| `approvedPreorderChance` | Chance per run to look for an approved request to pre-order for. |
| `leadTime`, `dayWeights` | How many days ahead a booking is made, and how much each day of the week weighs. |
| `startWeights` | Weight of every start on the booking grid: lunch and dinner peaks. |
| `weekendDays`, `partySizes` | Party size shares for weekdays, weekends and the holidays by `MM-DD`; `request` is the share of 5 to 8 people. |
| `requestPartySizes` | How a request splits into 5, 6, 7 and 8 people. |
| `maxInstantPartySize`, `minFreeTables` | The instant booking limit and the free tables rule. |
| `requestLeadMinutes`, `cancelLeadMinutes`, `preorderLeadMinutes` | The API's own limits, so the bots do not send what it refuses. |
| `preorder` | Chances per person and category, the lunch and dinner overrides, and the dish weights. |

Changing an API limit in the backend means changing the matching key here.

## The plan check

```bash
cd n8n
npm test                                        # both workflows
node --test tests/booking-simulator.test.mjs    # the simulator only
```

Runs the workflow's own Code nodes from the JSON on simulated clocks with stub inputs, without the
API. Over 10 000 plans it checks that the persona split, cancel share, lead times, booking dates
per weekday (by the day weights) and party sizes for weekdays, weekends and each holiday follow
patterns.md, and that start hours, the request party split and the approved pre-order chance
follow `CONFIG`, with every lunch and dinner peak start above every low-hour start. A share passes
within 4 standard errors of its expected value. It also checks that `apiBaseUrl` is the dev API,
that requests are sent exactly when a start beyond 2 hours exists and never closer, the
4-free-tables rule, the favourite location share, the pre-order chances per person with the lunch
and dinner overrides and the dish weights, the answer checks (409 quiet, other errors fail, no
pre-order for a request or a start within 30 minutes), the approved-request filter and the menu
page guard.

Every run prints its seed and every failing test names it; `SIMULATOR_SEED=<seed> npm test` repeats
a run exactly. It exits non-zero on a failed check. After tuning `CONFIG`, update patterns.md and
the `PATTERNS` table in `tests/booking-simulator.test.mjs` together.

## The waiter bot

`workflows/waiter-bot.json` (`Waiter bot`) decides the large-party requests the simulator sends,
the way a busy waiter would, so dev gets staff decisions, approved large bookings and some
requests that wait until the API rejects them on its own 2 hours before the start. It signs in
as `waiter-bot@example.com` through the staff routes of the dev API and keeps no state between
runs.

Every 5 minutes a run first decides whether to do anything at all: 40% of the runs end right
there, before signing in, so the time until a decision varies. Otherwise it reads one page of
pending requests (`GET /staff/booking-requests?limit=50`) in the API's order, earliest start
first, then oldest request; more requests than a page wait for later runs. It goes through the
page one request at a time:

- **Far ahead.** A request starting more than 3 days from now is left for a later run with
  chance 0.5, so some wait long and a few reach the auto-reject.
- **Decided.** Any other request is approved with chance 0.8 and rejected otherwise.
- **Competing requests.** Approving a request rejects the other pending requests for the same
  table and time on the API side. Since the earliest request comes first, the waiter prefers it;
  a later competitor then answers 409 `REQUEST_NOT_PENDING` and is skipped.
- **Table taken.** An approval refused with 409 `SLOT_UNAVAILABLE` (the table got a confirmed
  booking meanwhile) is followed by a rejection of that request.
- **Too late.** 409 `REQUEST_NOT_PENDING` (decided meanwhile, also by the auto-reject) or
  `REQUEST_EXPIRED` (it now starts within the 2-hour lead) skips the request quietly.

The run goes on with the next request after each of these. Any other status, a failed sign-in
included, fails the execution, so a broken waiter shows up in n8n.

The requests go one at a time through `Each request` (Loop Over Items with a batch size of 1),
because an HTTP Request node sends the requests of all its items at once, and the earliest of
several competing requests has to be decided before the later ones. Every path through the loop
ends back in `Each request`: each fork ends in two gates of which exactly one passes, so the
order does not depend on where the nodes sit on the canvas.

| Node | What it does |
|---|---|
| Every 5 minutes | Schedule trigger, in `Asia/Tbilisi` like the booking grid. |
| Plan the round | Holds `CONFIG`. Ends a skipped run; otherwise passes the email and `CONFIG` on. |
| Log in | `POST /auth/login` as the waiter with the password from the credential; keeps the full response for its headers. |
| Keep the session | Turns the `Set-Cookie` headers into one `Cookie` header for the next requests. |
| List pending requests | `GET /staff/booking-requests` with `limit` from `CONFIG.pageSize`. |
| Split the page | One item per request, in the API's order. Nothing follows an empty page, so the run ends. |
| Each request | Hands the requests on one at a time; after the last one the run ends. |
| Decide the request | Leaves a far request with `farDeferralChance`; otherwise approves with `approveChance` or rejects. |
| Leave for later / Answer now | Gates: back to `Each request` for a request left, on to the decision otherwise. |
| Send the decision | `POST /staff/booking-requests/{id}/approve` or `/reject`, keeping any status for the next node. |
| Check the decision | 200, `REQUEST_NOT_PENDING` and `REQUEST_EXPIRED` finish the request; an approval refused with `SLOT_UNAVAILABLE` goes on to a rejection; any other status fails the run. |
| Table taken? / Next request | Gates: on to the rejection, or back to `Each request`. |
| Reject instead | `POST /staff/booking-requests/{id}/reject` after `SLOT_UNAVAILABLE`. |
| Check the rejection | 200, `REQUEST_NOT_PENDING` and `REQUEST_EXPIRED` go back to `Each request`; any other status fails the run. |

### Waiter CONFIG

Every number that tunes the waiter lives in the `CONFIG` object at the top of `Plan the round`,
with the waiter weights of
[patterns.md](../_bmad_output/implementation-artifacts/spec-restaurant-simulation/patterns.md).

| Key | What it tunes |
|---|---|
| `apiBaseUrl`, `email` | The API the waiter uses and the staff bot it signs in as. |
| `skipChance` | Share of runs that do nothing (0.4). |
| `approveChance` | Share of decided requests that are approved (0.8); the rest are rejected. |
| `farThresholdDays`, `farDeferralChance` | Requests starting more than this many days ahead (3) are left for a later run with this chance (0.5). |
| `pageSize` | Requests read per run (50, the API's maximum page). |

### The waiter check

```bash
cd n8n
npm test                                        # both workflows
node --test tests/waiter-bot.test.mjs           # the waiter only
```

Runs the waiter's own Code nodes from the JSON with a seeded random, without the API. Over
10 000 runs and 4 000 decisions it checks the share of skipped runs, the approval share for near
and far requests, the far deferral share and the 3-day threshold on both sides of it. It then
runs whole executions along the workflow's connections against a stub staff API, emulating the
HTTP nodes and the Loop Over Items node, for each case above: a skipped run makes no call, an
empty page ends after the list, near and far requests are approved, rejected or left, the later
of two competing requests is skipped, `SLOT_UNAVAILABLE` leads to a rejection, `REQUEST_EXPIRED`
is skipped, the run goes on after each of these and every other status fails it, and only one
page of 50 is decided, in the API's order. It also checks the workflow id, the 5-minute schedule
and time zone, that `apiBaseUrl` is the dev API and that no Code node keeps workflow static data.

Every run prints its seed and every failing test names it; `WAITER_SEED=<seed> npm test` repeats a
run exactly. It exits non-zero on a failed check. After tuning `CONFIG`, update patterns.md and the
`EXPECTED` table in `tests/waiter-bot.test.mjs` together.
