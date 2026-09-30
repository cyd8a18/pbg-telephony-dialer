import json

from app.database import connect
from app.processor import EventProcessor


def processor(tmp_path):
    db_path = tmp_path / "dialer.sqlite3"
    lead_path = tmp_path / "lead_book.json"
    lead_path.write_text(
        json.dumps(
            [
                {"id": "L101", "phone": "+15551110001"},
                {"id": "L201", "phone": "+15552220000"},
                {"id": "L202", "phone": "+15552220000"},
            ]
        ),
        encoding="utf-8",
    )
    conn = connect(db_path)
    return EventProcessor(conn, lead_path), db_path, lead_path


def test_processing_same_webhook_twice_is_idempotent(tmp_path):
    proc, _, _ = processor(tmp_path)
    event = {
        "seq": 1,
        "ts": "13:00:00.100Z",
        "event": "agent_leg.answered",
        "call_control_id": "A-1",
        "from": "+15550000001",
    }

    first = proc.process(event)
    second = proc.process(event)

    assert first.processed is True
    assert second.processed is False
    assert second.duplicate is True
    assert len(proc.state()["agent_lines"]) == 1


def test_out_of_order_event_does_not_move_completed_leg_backwards(tmp_path):
    proc, _, _ = processor(tmp_path)
    proc.process({"event": "agent_leg.answered", "call_control_id": "A-1", "ts": "1"})
    proc.process(
        {
            "event": "client_leg.initiated",
            "call_control_id": "C-101",
            "client_id": "L101",
            "to": "+15551110001",
            "ts": "2",
        }
    )
    proc.process({"event": "client_leg.hangup", "call_control_id": "C-101", "ts": "4"})
    proc.process({"event": "client_leg.answered", "call_control_id": "C-101", "ts": "3"})

    leg = proc.state()["agent_lines"][0]["client_legs"][0]
    assert leg["status"] == "completed"


def test_state_survives_reopened_connection(tmp_path):
    proc, db_path, lead_path = processor(tmp_path)
    proc.process({"event": "agent_leg.answered", "call_control_id": "A-1", "ts": "1"})
    proc.conn.close()

    reopened = EventProcessor(connect(db_path), lead_path)

    assert reopened.state()["agent_lines"][0]["call_control_id"] == "A-1"


def test_ending_client_leg_does_not_end_agent_line(tmp_path):
    proc, _, _ = processor(tmp_path)
    proc.process({"event": "agent_leg.answered", "call_control_id": "A-1", "ts": "1"})
    proc.process(
        {
            "event": "client_leg.initiated",
            "call_control_id": "C-101",
            "client_id": "L101",
            "to": "+15551110001",
            "ts": "2",
        }
    )
    proc.process({"event": "client_leg.hangup", "call_control_id": "C-101", "ts": "3"})

    state = proc.state()
    assert state["agent_lines"][0]["status"] == "active"
    assert state["agent_lines"][0]["client_legs"][0]["status"] == "completed"


def test_inbound_number_with_multiple_leads_is_ambiguous(tmp_path):
    proc, _, _ = processor(tmp_path)
    proc.process({"event": "agent_leg.answered", "call_control_id": "A-1", "ts": "1"})
    proc.process(
        {
            "event": "inbound.ringing",
            "call_control_id": "I-201",
            "from": "+15552220000",
            "ts": "2",
        }
    )
    proc.process(
        {
            "event": "lookup.result",
            "phone": "+15552220000",
            "matches": ["L201", "L202"],
            "ts": "3",
        }
    )

    inbound = proc.state()["agent_lines"][0]["client_legs"][0]
    assert inbound["identity_status"] == "ambiguous"
    assert inbound["client_id"] is None
    assert inbound["ambiguous_client_ids"] == ["L201", "L202"]
