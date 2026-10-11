"""Notification centre.

In-app notification log with optional Windows desktop toast. Email/Telegram
are intentionally NOT implemented in this release (no secrets handling, no
network exposure). Duplicate suppression and quiet hours are enforced here.
Failed deliveries are recorded; the app continues if a provider is unavailable.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, time

log = logging.getLogger(__name__)


@dataclass
class NotificationPrefs:
    desktop_toast: bool = True
    quiet_hours_start: str = "22:00"  # IST HH:MM
    quiet_hours_end: str = "07:00"
    min_severity: str = "INFO"  # INFO | WARNING | CRITICAL


SEVERITY_ORDER = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


class NotificationCenter:
    """Stores notifications in SQLite and optionally fires desktop toasts."""

    def __init__(self, conn: sqlite3.Connection, prefs: NotificationPrefs | None = None) -> None:
        self.conn = conn
        self.prefs = prefs or NotificationPrefs()
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                trigger_key TEXT,
                delivered INTEGER DEFAULT 0,
                delivery_error TEXT
            )"""
        )
        self.conn.commit()

    def _in_quiet_hours(self, now_ist: datetime | None = None) -> bool:
        from zoneinfo import ZoneInfo

        now = now_ist or datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata"))
        try:
            start = time(*map(int, self.prefs.quiet_hours_start.split(":")))
            end = time(*map(int, self.prefs.quiet_hours_end.split(":")))
        except ValueError:
            return False
        t = now.time()
        if start <= end:
            return start <= t < end
        return t >= start or t < end  # wraps midnight

    def _severity_ok(self, severity: str) -> bool:
        return SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(self.prefs.min_severity, 0)

    def _is_duplicate(self, trigger_key: str, within_minutes: int = 60) -> bool:
        row = self.conn.execute(
            "SELECT ts FROM notifications WHERE trigger_key = ? ORDER BY id DESC LIMIT 1",
            (trigger_key,),
        ).fetchone()
        if not row:
            return False
        try:
            last = datetime.fromisoformat(row["ts"])
            return (datetime.now(UTC) - last).total_seconds() < within_minutes * 60
        except ValueError:
            return False

    def notify(
        self,
        symbol: str,
        severity: str,
        title: str,
        detail: str = "",
        trigger_key: str = "",
        force: bool = False,
    ) -> dict:
        """Record a notification. Returns status dict.

        Respects quiet hours (unless force=True), severity filter and
        duplicate suppression. Desktop toast is best-effort and failures
        are recorded, never raised.
        """
        key = trigger_key or f"{symbol}:{title[:40]}"
        if not force:
            if not self._severity_ok(severity):
                return {"sent": False, "reason": "below severity filter"}
            if self._in_quiet_hours():
                return {"sent": False, "reason": "quiet hours"}
            if self._is_duplicate(key):
                return {"sent": False, "reason": "duplicate within cooldown"}

        delivered = 0
        delivery_error = None
        if self.prefs.desktop_toast and not self._in_quiet_hours():
            ok, err = self._send_desktop_toast(title, detail, severity)
            delivered = 1 if ok else 0
            delivery_error = err

        ts = datetime.now(UTC).isoformat()
        with self.conn:
            self.conn.execute(
                "INSERT INTO notifications (ts, symbol, severity, title, detail, "
                "trigger_key, delivered, delivery_error) VALUES (?,?,?,?,?,?,?,?)",
                (ts, symbol.upper(), severity, title, detail, key, delivered, delivery_error),
            )
        return {"sent": True, "delivered": bool(delivered), "error": delivery_error}

    def _send_desktop_toast(
        self, title: str, detail: str, severity: str
    ) -> tuple[bool, str | None]:
        """Best-effort Windows toast via PowerShell. Never raises.

        Uses a fixed PowerShell command template; title/detail are escaped
        for single-quoted strings. No user-controlled executable path.
        """
        try:
            import subprocess

            t = title.replace("'", "''")[:80]
            d = (detail or "")[:120].replace("'", "''")
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, "
                "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
                "$template = [Windows.UI.Notifications.ToastNotificationManager]"
                "::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                "$text = $template.GetElementsByTagName('text'); "
                "$text.Item(0).AppendChild($template.CreateTextNode('" + t + "')) > $null; "
                "$text.Item(1).AppendChild($template.CreateTextNode('" + d + "')) > $null; "
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                "[Windows.UI.Notifications.ToastNotificationManager]"
                "::CreateToastNotifier("
                "'Swing Trader India').Show($toast);"
            )
            # noqa: S603,S607 — fixed local PowerShell, escaped strings only
            r = subprocess.run(  # noqa: S603
                ["powershell", "-NoProfile", "-Command", ps],  # noqa: S607
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                return True, None
            return False, (r.stderr or "toast failed").strip()[:200]
        except Exception as exc:
            return False, f"toast unavailable: {exc}"

    def history(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_delivered(self, notif_id: int, error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE notifications SET delivered=?, delivery_error=? WHERE id=?",
                (0 if error else 1, error, notif_id),
            )
