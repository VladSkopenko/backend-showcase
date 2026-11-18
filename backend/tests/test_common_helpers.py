import hashlib
import json

import pytest

from app.common.ai_tools import Card, CardField, Proposal, ProposalSink
from app.common.hashing import sha256_hex


def test_sha256_hex_matches_the_hashes_stored_before() -> None:
    assert sha256_hex("refresh-token") == hashlib.sha256(b"refresh-token").hexdigest()


def test_a_proposal_is_held_and_answered_with_its_card() -> None:
    sink = ProposalSink()
    card = Card(
        title="Cancel the booking",
        fields=[CardField(label="When", value="19:00")],
        notice=None,
        confirm_label="Yes",
    )

    result = sink.propose(kind="booking.cancel", payload={"booking_id": "b"}, card=card)

    assert json.loads(result) == {
        "status": "awaiting_confirmation",
        "card": {
            "title": "Cancel the booking",
            "fields": [{"label": "When", "value": "19:00"}],
            "notice": None,
            "confirm_label": "Yes",
        },
    }
    assert sink.proposal == Proposal(kind="booking.cancel", payload={"booking_id": "b"}, card=card)
    with pytest.raises(RuntimeError):
        sink.propose(kind="booking.cancel", payload={}, card=card)
