# Telephony Dialer State Prototype

Small FastAPI + SQLite prototype for the PBG backend challenge. It focuses on the state-management core of a dialer where the agent line is persistent while separate client call legs enter and leave.

## What Is Implemented

- `POST /webhooks` accepts the challenge webhook events, persists an idempotency key, and updates state.
- `GET /state` returns agent lines and their client legs.
- SQLite is the source of truth, so state and processed-event history survive process restarts.
- Inbound phone numbers that match multiple leads are represented as ambiguous.

The supplied challenge data remains in:

- `webhooks.jsonl`
- `lead_book.json`
- `number_reputation.csv`

## Minimal State Machine

Agent line:

- `agent_leg.answered` creates or refreshes an `active` agent line.
- Client-leg termination does not change the agent line.

Client leg:

- `client_leg.initiated` creates an outbound leg with `initiated`.
- `inbound.ringing` creates an inbound leg with `ringing`.
- `client_leg.answered` moves a leg to `answered`.
- `client_leg.hangup` moves a leg to terminal `completed`.
- `sip.failure` moves a leg to terminal `failed`.

Terminal states have a higher rank than earlier states, so a late `answered` event cannot move a completed or failed leg backwards.

## Identity Model

The schema keeps these concepts separate:

- Agent line identity: `agent_lines.call_control_id`
- Call leg identity: `client_legs.call_control_id`
- Lead/customer identity: `client_legs.client_id`
- Phone number: `client_legs.phone`

For inbound lookups, one phone may map to many leads. In that case `client_id` remains `null`, `identity_status` becomes `ambiguous`, and the candidate lead IDs are stored in `ambiguous_client_ids`.

## Idempotency

`processed_events.event_key` is `UNIQUE`. Each webhook is inserted before applying business changes. If the insert fails, the webhook is a durable duplicate and its side effects are skipped.

The challenge payloads do not include a provider event ID, so the fallback key is semantic for the events in this dataset, for example `client_leg.answered:C-101`. In production, this should use the telephony provider's immutable event or delivery ID.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The default database is `dialer.sqlite3`. Override it with `DIALER_DB_PATH` if needed.

## Replay The Supplied Webhooks

With the server running:

```powershell
python .\scripts\replay_webhooks.py
```

Or post a single event:

```powershell
curl -X POST http://127.0.0.1:8000/webhooks -H "Content-Type: application/json" -d "{\"event\":\"agent_leg.answered\",\"call_control_id\":\"A-1\",\"ts\":\"13:00:00.100Z\"}"
```

## Example State

After replaying `webhooks.jsonl`, `GET /state` returns this shape:

```json
{
  "agent_lines": [
    {
      "id": "A-1",
      "call_control_id": "A-1",
      "status": "active",
      "updated_at": "2026-09-30 13:00:00",
      "client_legs": [
        {
          "call_control_id": "C-101",
          "direction": "outbound",
          "status": "completed",
          "client_id": "L101",
          "phone": "+15551110001",
          "identity_status": "known",
          "ambiguous_client_ids": null
        },
        {
          "call_control_id": "C-102",
          "direction": "outbound",
          "status": "failed",
          "client_id": "L102",
          "phone": "+15551110002",
          "identity_status": "known",
          "ambiguous_client_ids": null
        },
        {
          "call_control_id": "I-201",
          "direction": "inbound",
          "status": "ringing",
          "client_id": null,
          "phone": "+15552220000",
          "identity_status": "ambiguous",
          "ambiguous_client_ids": ["L201", "L202"]
        }
      ]
    }
  ],
  "unattached_client_legs": []
}
```

## Tests

```powershell
python -m pytest
```

The tests cover duplicate processing, out-of-order terminal protection, restart recovery, agent/client state separation, and ambiguous inbound identity.

## Tradeoffs

- Only challenge event types are implemented.
- There is no authentication, job queue, Redis, Docker, or SQLAlchemy.
- A real system would use provider event IDs, stricter timestamp parsing, retry/dead-letter handling, richer state transitions, migrations, observability, and concurrency tests around simultaneous webhook delivery.
