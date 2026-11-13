---
id: SPEC-restaurant-simulation
companions:
  - patterns.md
  - dashboards.md
  - ../../../docs/adr/0013-table-booking-slots-and-double-booking.md
  - ../../../docs/adr/0014-booking-simulator-on-dev.md
  - ../../../docs/adr/0015-platform-as-code.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Live restaurant simulation and its Grafana presentation

## Why

Vision: a reviewer opens a public Grafana and sees a restaurant that lives: when people book, what
they eat, what checks look like, who comes back, and how fast staff answer large-party requests.
Dev already runs an n8n booking simulator, but it books uniformly at random with four bots and
orders nothing. This initiative adds the missing product piece (large-party requests approved by
staff), makes the bots behave with patterns, adds a waiter bot, and presents the live dev data in
Grafana. Data accumulates from now on; staging and prod stay on paper.

## Capabilities

- **CAP-1**
  - **intent:** A guest can request a booking for 5 to 8 people.
  - **success:** The request is stored as pending without holding the table; two guests can request the same table and time.
- **CAP-2**
  - **intent:** Staff decide on large-party requests.
  - **success:** A staff member lists pending requests and approves or rejects one; approving rejects the overlapping pending requests; approving a request whose table was taken meanwhile fails and leaves it pending.
- **CAP-3**
  - **intent:** Participants learn the decision on their request.
  - **success:** Each decision creates an in-app notification the user can list and mark read, and an email, except to `example.com` addresses.
- **CAP-4**
  - **intent:** Nobody waits on an unanswered request until it is too late.
  - **success:** A request still pending 2 hours before its start is rejected automatically and notified like a staff rejection.
- **CAP-5**
  - **intent:** Bot bookings follow the time, day and holiday patterns of a real restaurant.
  - **success:** After a day, bookings by start hour show lunch and dinner peaks, party of 2 is the largest group, weekends have larger parties.
- **CAP-6**
  - **intent:** Bots are distinct visitors and a staff member.
  - **success:** About 40 guest bots (regulars and occasional) and one staff bot exist on dev only.
- **CAP-7**
  - **intent:** Bots pre-order food the way their party would.
  - **success:** Most bookings made more than 30 minutes ahead get a submitted pre-order with about one main course per person and location-specific top dishes.
- **CAP-8**
  - **intent:** Bots cancel some bookings.
  - **success:** Roughly one booking in seven ends cancelled.
- **CAP-9**
  - **intent:** Bots send large-party requests on weekends and holidays.
  - **success:** Pending requests appear daily, more on Friday, Saturday and holidays.
- **CAP-10**
  - **intent:** A waiter bot answers requests like a busy waiter.
  - **success:** Requests get decisions after a varying delay, most approved, some auto-rejected by the 2-hour rule.
- **CAP-11**
  - **intent:** Anyone can look at the restaurant's numbers without an account, without seeing personal data.
  - **success:** Grafana opens at `backend-showcase-grafana.duckdns.org` as anonymous Viewer; its database role cannot read user emails or names beyond what visitor charts need.
- **CAP-12**
  - **intent:** The numbers are presented as dashboards.
  - **success:** The five dashboards in `dashboards.md` render from live dev data.

## Constraints

- Instant online bookings stay at 1 to 4 people; 5 to 8 go through a request; 8 is the largest table, tables are never combined.
- A pending request never blocks anyone: confirmed bookings keep the no-overlap rule of ADR 13, requests do not count toward it.
- Booking invariants are checked in the service layer with row locks; database constraints are only a backstop.
- Auto-reject runs as a periodic task inside the API process (one API process per environment).
- No email is sent to `example.com`; in-app notifications have no push yet (WebSocket comes with the order tracker).
- Bots use only the public dev API (ADR 14), never staging or prod; the 4-free-tables rule stays; the bot password is unchanged and new bots reuse its hash.
- Bots and the staff bot come from data migrations gated on `APP_ENVIRONMENT=dev`.
- All simulator weights live in one config object at the top of the workflow code; workflows are kept in git.
- Grafana reads dev, not prod: a deviation from AD-13 recorded in an ADR. Infra files follow ADR 15 and are written one at a time with Vlad.

## Non-goals

- Parties above 8 and combining tables.
- Push notifications and WebSocket.
- Generating past data.
- Staging and prod data, Prometheus metrics.
- Rotating the bot password; cleaning old `refresh_tokens` rows.

## Success signal

- A reviewer outside the tailnet opens the public Grafana and, without signing in, sees bookings by hour and weekday, top dishes per location, average check by category, frequent visitors and party sizes, and staff reaction time with approval rate, all moving with the live dev simulation.

## Assumptions

- The guest simulator runs every 2 minutes and the waiter bot every 5 minutes.
- The staff role is a single `STAFF` flag on users; finer roles (kitchen, manager) come with the order tracker.
