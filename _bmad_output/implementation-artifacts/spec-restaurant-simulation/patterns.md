# Simulator patterns

Starting weights. All of them live in one config object in the workflow code and are meant to be tuned.

## Visitors (CAP-6)

| Persona | Bots | Share of runs | Location | Notes |
|---|---|---|---|---|
| Regular | 10 | 50% | one favourite, 80% of their bookings | two favourite dishes |
| Occasional | 30 | 50% | any, uniform | rare visits |
| Staff (waiter) | 1 | own workflow | all | decides on requests |

Bots `booking-bot-1` to `booking-bot-4` keep their accounts; a migration adds guest bots 5 to 40
with varied first and last names and one staff bot.

## When (CAP-5)

- Lead time: same day 35%, next day 25%, 2 to 3 days 20%, 4 to 14 days 20%.
- Start hour weight (Asia/Tbilisi): 10:00 to 11:30 low, 12:30 to 14:30 lunch peak, 15:00 to 17:30 low,
  18:30 to 21:00 dinner peak.
- Day of week: Friday and Saturday 1.5, Sunday 1.2, Monday to Thursday 1.

## Party size (CAP-5, CAP-9)

| Day | 1 | 2 | 3 | 4 | 5 to 8 (request) |
|---|---|---|---|---|---|
| Weekday | 15% | 48% | 20% | 15% | 2% |
| Weekend | 5% | 35% | 22% | 28% | 10% |
| 14 February | 0% | 90% | 4% | 4% | 2% |
| 8 March | 5% | 30% | 25% | 25% | 15% |
| 31 December | 0% | 10% | 10% | 30% | 50% |

## Pre-order (CAP-7)

- Right after a confirmed booking (or an approval seen on a later run), only when the start is more
  than 30 minutes away.
- Per person: one `MAIN_COURSE` (90%), an `APPETIZER` (50%), a `DESSERT` (40%); quantities add up per dish.
- Lunch lowers desserts to 25%; dinner raises appetizers to 60%.
- Each location boosts three dishes (weight 3); each regular boosts two favourite dishes (weight 3).
  Both come from a stable hash of the location id or bot number, so no state is kept between runs.

## Cancellations (CAP-8)

- About 15% of runs cancel one of the bot's future bookings more than 30 minutes away instead of booking.

## Waiter (CAP-10)

- Runs every 5 minutes, but skips a run with 40% probability, so reaction time varies.
- Decides each pending request: approve 80%, reject 20%; prefers the earliest request when several
  compete for one table and time.
- Leaves requests whose start is more than 3 days away for a later run with 50% probability, so some
  wait long and a few reach the 2-hour auto-reject.
