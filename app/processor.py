import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional, Union

from .database import init_db
from .models import WebhookEvent, WebhookResult


CLIENT_STATUS_RANK = {
    "initiated": 10,
    "ringing": 10,
    "answered": 20,
    "completed": 30,
    "failed": 30,
}


class EventProcessor:
    def __init__(
        self,
        conn: sqlite3.Connection,
        lead_book_path: Optional[Union[str, Path]] = None,
    ):
        self.conn = conn
        init_db(conn)
        self.leads = self._load_leads(lead_book_path)

    def process(self, payload: dict[str, Any]) -> WebhookResult:
        event = WebhookEvent.parse_obj(payload)
        event_key = self._event_key(payload, event)
        encoded = json.dumps(payload, sort_keys=True)

        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO processed_events (
                        event_key, event_type, call_control_id, event_timestamp, payload
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_key, event.event, event.call_control_id, event.ts, encoded),
                )
                self._apply(event)
        except sqlite3.IntegrityError:
            return WebhookResult(processed=False, duplicate=True, event_key=event_key)

        return WebhookResult(processed=True, event_key=event_key)

    def state(self) -> dict[str, Any]:
        agents = []
        for agent in self.conn.execute(
            "SELECT * FROM agent_lines ORDER BY created_at, id"
        ).fetchall():
            legs = []
            for leg in self.conn.execute(
                """
                SELECT * FROM client_legs
                WHERE agent_line_id = ?
                ORDER BY created_at, call_control_id
                """,
                (agent["id"],),
            ).fetchall():
                legs.append(self._leg_to_dict(leg))
            agents.append(
                {
                    "id": agent["id"],
                    "call_control_id": agent["call_control_id"],
                    "status": agent["status"],
                    "updated_at": agent["updated_at"],
                    "client_legs": legs,
                }
            )

        unattached = [
            self._leg_to_dict(row)
            for row in self.conn.execute(
                """
                SELECT * FROM client_legs
                WHERE agent_line_id IS NULL
                ORDER BY created_at, call_control_id
                """
            ).fetchall()
        ]
        return {"agent_lines": agents, "unattached_client_legs": unattached}

    def _apply(self, event: WebhookEvent) -> None:
        if event.event == "agent_leg.answered":
            self._upsert_agent_line(event)
        elif event.event == "client_leg.initiated":
            self._upsert_client_leg(
                event=event,
                direction="outbound",
                status="initiated",
                client_id=event.client_id,
                phone=event.to,
            )
        elif event.event == "client_leg.answered":
            self._transition_client_leg(event, "answered")
        elif event.event == "client_leg.hangup":
            self._transition_client_leg(event, "completed")
        elif event.event == "sip.failure":
            self._transition_client_leg(event, "failed")
        elif event.event == "inbound.ringing":
            self._upsert_client_leg(
                event=event,
                direction="inbound",
                status="ringing",
                phone=event.from_,
            )
        elif event.event == "lookup.result":
            self._apply_lookup(event)
        elif event.event == "process.restart":
            return

    def _upsert_agent_line(self, event: WebhookEvent) -> None:
        self.conn.execute(
            """
            INSERT INTO agent_lines (id, call_control_id, status, updated_at)
            VALUES (?, ?, 'active', CURRENT_TIMESTAMP)
            ON CONFLICT(call_control_id) DO UPDATE SET
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            """,
            (event.call_control_id, event.call_control_id),
        )

    def _upsert_client_leg(
        self,
        event: WebhookEvent,
        direction: str,
        status: str,
        client_id: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> None:
        existing = self._get_leg(event.call_control_id)
        rank = CLIENT_STATUS_RANK[status]
        agent_line_id = existing["agent_line_id"] if existing else self._active_agent_line_id()
        identity_status = "known" if client_id else "unknown"

        if existing and existing["status_rank"] > rank:
            return

        self.conn.execute(
            """
            INSERT INTO client_legs (
                call_control_id, agent_line_id, client_id, phone, direction,
                status, status_rank, identity_status, last_event_timestamp, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(call_control_id) DO UPDATE SET
                agent_line_id = COALESCE(client_legs.agent_line_id, excluded.agent_line_id),
                client_id = COALESCE(client_legs.client_id, excluded.client_id),
                phone = COALESCE(client_legs.phone, excluded.phone),
                direction = excluded.direction,
                status = excluded.status,
                status_rank = excluded.status_rank,
                identity_status = CASE
                    WHEN client_legs.client_id IS NOT NULL THEN client_legs.identity_status
                    ELSE excluded.identity_status
                END,
                last_event_timestamp = excluded.last_event_timestamp,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                event.call_control_id,
                agent_line_id,
                client_id,
                phone,
                direction,
                status,
                rank,
                identity_status,
                event.ts,
            ),
        )

    def _transition_client_leg(self, event: WebhookEvent, status: str) -> None:
        existing = self._get_leg(event.call_control_id)
        rank = CLIENT_STATUS_RANK[status]
        if existing and existing["status_rank"] > rank:
            return

        if not existing:
            self._upsert_client_leg(
                event=event,
                direction="outbound",
                status=status,
            )
            return

        self.conn.execute(
            """
            UPDATE client_legs
            SET status = ?, status_rank = ?, last_event_timestamp = ?, updated_at = CURRENT_TIMESTAMP
            WHERE call_control_id = ? AND status_rank <= ?
            """,
            (status, rank, event.ts, event.call_control_id, rank),
        )

    def _apply_lookup(self, event: WebhookEvent) -> None:
        matches = event.matches if event.matches is not None else self._lead_ids_for_phone(event.phone)
        identity_status = "unknown"
        client_id = None
        ambiguous = None
        if len(matches) == 1:
            identity_status = "known"
            client_id = matches[0]
        elif len(matches) > 1:
            identity_status = "ambiguous"
            ambiguous = json.dumps(matches)

        self.conn.execute(
            """
            UPDATE client_legs
            SET client_id = ?,
                identity_status = ?,
                ambiguous_client_ids = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE phone = ? AND direction = 'inbound'
            """,
            (client_id, identity_status, ambiguous, event.phone),
        )

    def _active_agent_line_id(self) -> Optional[str]:
        row = self.conn.execute(
            """
            SELECT id FROM agent_lines
            WHERE status = 'active'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        return row["id"] if row else None

    def _get_leg(self, call_control_id: Optional[str]) -> Optional[sqlite3.Row]:
        if call_control_id is None:
            return None
        return self.conn.execute(
            "SELECT * FROM client_legs WHERE call_control_id = ?",
            (call_control_id,),
        ).fetchone()

    def _lead_ids_for_phone(self, phone: Optional[str]) -> list[str]:
        return [lead["id"] for lead in self.leads if lead.get("phone") == phone]

    def _leg_to_dict(self, leg: sqlite3.Row) -> dict[str, Any]:
        ambiguous = (
            json.loads(leg["ambiguous_client_ids"])
            if leg["ambiguous_client_ids"]
            else None
        )
        return {
            "call_control_id": leg["call_control_id"],
            "direction": leg["direction"],
            "status": leg["status"],
            "client_id": leg["client_id"],
            "phone": leg["phone"],
            "identity_status": leg["identity_status"],
            "ambiguous_client_ids": ambiguous,
            "updated_at": leg["updated_at"],
        }

    def _event_key(self, payload: dict[str, Any], event: WebhookEvent) -> str:
        provider_key = payload.get("event_id") or payload.get("id")
        if provider_key:
            return str(provider_key)

        if event.event == "lookup.result":
            matches = ",".join(sorted(event.matches or []))
            return f"lookup.result:{event.phone}:{matches}"
        if event.event == "process.restart":
            return f"process.restart:{event.seq}:{event.ts}"
        if event.call_control_id:
            return f"{event.event}:{event.call_control_id}"

        canonical = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_leads(
        self, lead_book_path: Optional[Union[str, Path]]
    ) -> list[dict[str, Any]]:
        if lead_book_path is None:
            lead_book_path = Path(__file__).resolve().parents[1] / "lead_book.json"
        path = Path(lead_book_path)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))
