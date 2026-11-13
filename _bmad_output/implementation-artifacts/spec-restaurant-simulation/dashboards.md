# Dashboards (CAP-12)

All read the dev database through Grafana's read-only role. Time ranges and a location filter on
every dashboard.

| Dashboard | Panels |
|---|---|
| Bookings | bookings per day; heatmap weekday × start hour; lead time distribution; cancellation rate; occupancy per location |
| Dishes | top dishes overall and per location; dish popularity by hour of day; category mix by lunch and dinner |
| Checks | average check per booking and per person; check by category; check by location and weekday; revenue per day |
| Visitors | party size distribution over time (holidays visible); regulars vs occasional; top visitors by bookings (display name only); repeat rate |
| Staff | pending requests now; time to decision (median, p90); approval rate; auto-rejected share; requests per day |

The role sees bookings, participants, tables, locations, dishes, pre-order items and requests, and
user ids with display names; never emails, password hashes or tokens.
