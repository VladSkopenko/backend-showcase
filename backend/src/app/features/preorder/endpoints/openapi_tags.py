class PreorderOpenApiTags:
    PREORDER = "Pre-order"

    METADATA = [
        {
            "name": PREORDER,
            "description": (
                "Pre-ordering dishes for a booking: every participant, the owner and guests "
                "alike, keeps their own cart on the server and submits it into the booking's "
                "group pre-order. A submitted part is final for its author, and a new cart can "
                "follow. Each participant sees only their own items; the owner also sees the whole "
                "group's submitted parts. Cart changes and submit are open while the booking is "
                "confirmed and until shortly before its start; the reads (the cart, the own parts "
                "and the owner's group view) stay open. Prices follow the current menu. "
                "Guests without an account are identified by the `guest_token` cookie."
            ),
        },
    ]
