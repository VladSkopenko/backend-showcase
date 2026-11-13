class BookingOpenApiTags:
    BOOKING = "Booking"
    STAFF = "Staff"

    METADATA = [
        {
            "name": BOOKING,
            "description": (
                "Booking a table: a public search for free tables with their day grid of start "
                "times, then creating, listing, editing and cancelling one's own bookings, which "
                "needs sign-in. Lists and views cover owned and joined bookings with their "
                "participants; the view of one booking is also open to guests without an account "
                "by the `guest_token` cookie. Only the owner edits or cancels. Times are in the "
                "restaurant's time zone."
            ),
        },
    ]

    STAFF_METADATA = [
        {
            "name": STAFF,
            "description": (
                "Restaurant staff decide on large-party booking requests: list the pending ones "
                "with how many other requests compete for the same table and time, then approve "
                "or reject one. Approving confirms the request and rejects the competing ones. "
                "Needs sign-in as a staff member; staff are flagged by a migration or an "
                "operator, never through the API. Times are in the restaurant's time zone."
            ),
        },
    ]
