class BookingOpenApiTags:
    BOOKING = "Booking"

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
