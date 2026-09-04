from __future__ import annotations

from datetime import timedelta

from .db import RuntimeDB, iso, utcnow


class LeaseManager:
    def __init__(self, db: RuntimeDB):
        self.db = db

    def acquire_profile(self, profile_id: str, job_id: str, ttl_sec: int = 30) -> int | None:
        now = utcnow()
        expires = now + timedelta(seconds=max(5, ttl_sec))
        with self.db.immediate() as conn:
            row = conn.execute(
                "SELECT owner_job_id,expires_at,lease_epoch FROM profile_leases WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
            if row:
                if row["owner_job_id"] == job_id:
                    epoch = int(row["lease_epoch"])
                    conn.execute(
                        "UPDATE profile_leases SET heartbeat_at=?,expires_at=? WHERE profile_id=? AND owner_job_id=? AND lease_epoch=?",
                        (iso(now), iso(expires), profile_id, job_id, epoch),
                    )
                    return epoch
                if row["expires_at"] > iso(now):
                    return None
                # Expiry alone is not enough to steal a live profile. Recovery owns stale-lease eviction.
                return None
            conn.execute(
                """
                INSERT INTO profile_leases(
                    profile_id,owner_job_id,owner_browser_process_id,acquired_at,heartbeat_at,expires_at,lease_epoch
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (profile_id, job_id, None, iso(now), iso(now), iso(expires), 1),
            )
            return 1

    def bind_profile_process(self, profile_id: str, job_id: str, epoch: int, browser_process_id: str) -> bool:
        with self.db.immediate() as conn:
            cur = conn.execute(
                """
                UPDATE profile_leases SET owner_browser_process_id=?
                WHERE profile_id=? AND owner_job_id=? AND lease_epoch=?
                """,
                (browser_process_id, profile_id, job_id, epoch),
            )
            return cur.rowcount == 1

    def heartbeat_profile(self, profile_id: str, job_id: str, epoch: int, ttl_sec: int = 30) -> bool:
        now = utcnow()
        expires = now + timedelta(seconds=max(5, ttl_sec))
        with self.db.immediate() as conn:
            cur = conn.execute(
                """
                UPDATE profile_leases SET heartbeat_at=?,expires_at=?
                WHERE profile_id=? AND owner_job_id=? AND lease_epoch=?
                """,
                (iso(now), iso(expires), profile_id, job_id, epoch),
            )
            return cur.rowcount == 1

    def release_profile(self, profile_id: str, job_id: str, epoch: int) -> bool:
        with self.db.immediate() as conn:
            cur = conn.execute(
                "DELETE FROM profile_leases WHERE profile_id=? AND owner_job_id=? AND lease_epoch=?",
                (profile_id, job_id, epoch),
            )
            return cur.rowcount == 1

    def acquire_control(
        self,
        browser_session_id: str,
        job_id: str,
        owner_type: str,
        ttl_sec: int = 30,
    ) -> int | None:
        now = utcnow()
        expires = now + timedelta(seconds=max(5, ttl_sec))
        with self.db.immediate() as conn:
            row = conn.execute(
                "SELECT owner_job_id,owner_type,expires_at,lease_epoch FROM control_leases WHERE browser_session_id=?",
                (browser_session_id,),
            ).fetchone()
            if row:
                if row["owner_job_id"] == job_id and row["owner_type"] == owner_type:
                    epoch = int(row["lease_epoch"])
                    conn.execute(
                        "UPDATE control_leases SET heartbeat_at=?,expires_at=? WHERE browser_session_id=? AND owner_job_id=? AND lease_epoch=?",
                        (iso(now), iso(expires), browser_session_id, job_id, epoch),
                    )
                    return epoch
                return None
            conn.execute(
                """
                INSERT INTO control_leases(
                    browser_session_id,owner_job_id,owner_type,acquired_at,heartbeat_at,expires_at,lease_epoch
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (browser_session_id, job_id, owner_type, iso(now), iso(now), iso(expires), 1),
            )
            return 1

    def heartbeat_control(self, browser_session_id: str, job_id: str, epoch: int, ttl_sec: int = 30) -> bool:
        now = utcnow()
        expires = now + timedelta(seconds=max(5, ttl_sec))
        with self.db.immediate() as conn:
            cur = conn.execute(
                """
                UPDATE control_leases SET heartbeat_at=?,expires_at=?
                WHERE browser_session_id=? AND owner_job_id=? AND lease_epoch=?
                """,
                (iso(now), iso(expires), browser_session_id, job_id, epoch),
            )
            return cur.rowcount == 1

    def release_control(self, browser_session_id: str, job_id: str, epoch: int) -> bool:
        with self.db.immediate() as conn:
            cur = conn.execute(
                "DELETE FROM control_leases WHERE browser_session_id=? AND owner_job_id=? AND lease_epoch=?",
                (browser_session_id, job_id, epoch),
            )
            return cur.rowcount == 1

    def list_stale_profiles(self) -> list[dict[str, object]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM profile_leases WHERE expires_at <= ? ORDER BY expires_at",
                (iso(),),
            ).fetchall()
        return [dict(row) for row in rows]
