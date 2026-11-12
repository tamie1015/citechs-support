#!/usr/bin/env python3
"""CITECHS support site server: static files + SQLite API for admin, technicians, tickets, and chat."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "citechs.db"
HOST = "127.0.0.1"
PORT = 5500

# Your Google Apps Script Web App URL
GOOGLE_SHEET_WEBHOOK_URL = os.environ.get(
    "CITECHS_SHEET_URL",
    "https://script.google.com/macros/s/AKfycbyGEmJktOj-wb16fVuDlDmlPUoS-lkwQS-Ca3acbiE9zRPmj_KaYZ7tVZ8bIgeF5EgTMg/exec",
)

# Temporary default — change in Admin panel or set CITECHS_ADMIN_USER / CITECHS_ADMIN_PASS
DEFAULT_ADMIN_USER = os.environ.get("CITECHS_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("CITECHS_ADMIN_PASS", "ChangeMe@CIS")

_db_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return salt, digest


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    _, digest = hash_password(password, salt)
    return secrets.compare_digest(digest, password_hash)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'technician')),
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    school_id TEXT,
                    role TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT,
                    location TEXT NOT NULL,
                    category TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    chat_token TEXT NOT NULL UNIQUE,
                    assigned_tech_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(assigned_tech_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL,
                    sender_type TEXT NOT NULL CHECK(sender_type IN ('client', 'technician', 'system')),
                    sender_name TEXT NOT NULL,
                    sender_user_id INTEGER,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
                    FOREIGN KEY(sender_user_id) REFERENCES users(id) ON DELETE SET NULL
                );
                """
            )
            row = conn.execute(
                "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone()
            if not row:
                salt, password_hash = hash_password(DEFAULT_ADMIN_PASS)
                conn.execute(
                    """
                    INSERT INTO users (username, display_name, role, salt, password_hash, active, created_at)
                    VALUES (?, ?, 'admin', ?, ?, 1, ?)
                    """,
                    (DEFAULT_ADMIN_USER, "Administrator", salt, password_hash, utc_now()),
                )
            conn.commit()
        finally:
            conn.close()


def user_public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
        "active": bool(row["active"]),
        "createdAt": row["created_at"],
    }


def ticket_public(row: sqlite3.Row, include_chat_token: bool = False) -> dict:
    data = {
        "id": row["id"],
        "fullName": row["full_name"],
        "schoolId": row["school_id"],
        "role": row["role"],
        "email": row["email"],
        "phone": row["phone"],
        "location": row["location"],
        "category": row["category"],
        "priority": row["priority"],
        "subject": row["subject"],
        "description": row["description"],
        "status": row["status"],
        "assignedTechId": row["assigned_tech_id"],
        "createdAt": row["created_at"],
    }
    if include_chat_token:
        data["chatToken"] = row["chat_token"]
    return data


def message_public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "ticketId": row["ticket_id"],
        "senderType": row["sender_type"],
        "senderName": row["sender_name"],
        "senderUserId": row["sender_user_id"],
        "body": row["body"],
        "createdAt": row["created_at"],
    }


def make_ticket_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    return f"CIS-{stamp}-{secrets.randbelow(9000) + 1000}"


def send_to_google_sheet(payload_dict: dict) -> None:
    """Send payload (ticket or staff event) to Google Sheets in a background thread."""
    url = GOOGLE_SHEET_WEBHOOK_URL.strip()
    if not url:
        return

    def _post() -> None:
        try:
            payload = json.dumps(payload_dict).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as exc:  # noqa: BLE001
            print(f"[Google Sheet Sync Warning] Failed to sync: {exc}")

    threading.Thread(target=_post, daemon=True).start()


def sync_staff_event_to_google_sheet(event: str, user_data: dict) -> None:
    """Send staff login or technician creation event to Google Sheets."""
    payload = {
        "recordType": "staff_event",
        "timestamp": utc_now(),
        "event": event,
        "username": user_data.get("username", ""),
        "displayName": user_data.get("displayName", ""),
        "role": user_data.get("role", ""),
    }
    send_to_google_sheet(payload)


class CitechsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _bearer_token(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    def _get_session_user(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        token = self._bearer_token()
        if not token:
            return None
        return conn.execute(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND u.active = 1
            """,
            (token,),
        ).fetchone()

    def _require_role(self, conn: sqlite3.Connection, *roles: str) -> sqlite3.Row | None:
        user = self._get_session_user(conn)
        if not user or user["role"] not in roles:
            self._send_json(401, {"error": "Unauthorized"})
            return None
        return user

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_post(parsed)
            return
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_patch(parsed)
            return
        self._send_json(404, {"error": "Not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_delete(parsed)
            return
        self._send_json(404, {"error": "Not found"})

    def handle_api_get(self, parsed: urllib.parse.ParseResult) -> None:
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        with _db_lock:
            conn = connect()
            try:
                if path == "/api/health":
                    self._send_json(200, {"ok": True, "service": "CITECHS"})
                    return

                if path == "/api/auth/me":
                    user = self._get_session_user(conn)
                    if not user:
                        self._send_json(401, {"error": "Unauthorized"})
                        return
                    self._send_json(200, {"user": user_public(user)})
                    return

                if path == "/api/admin/technicians":
                    user = self._require_role(conn, "admin")
                    if not user:
                        return
                    rows = conn.execute(
                        """
                        SELECT * FROM users
                        WHERE role = 'technician'
                        ORDER BY created_at DESC
                        """
                    ).fetchall()
                    self._send_json(200, {"technicians": [user_public(r) for r in rows]})
                    return

                if path == "/api/tickets":
                    user = self._require_role(conn, "admin", "technician")
                    if not user:
                        return
                    status = (query.get("status") or [""])[0].strip().lower()
                    sql = "SELECT * FROM tickets"
                    params: list = []
                    if status in {"open", "closed"}:
                        sql += " WHERE status = ?"
                        params.append(status)
                    sql += " ORDER BY created_at DESC"
                    rows = conn.execute(sql, params).fetchall()
                    self._send_json(200, {"tickets": [ticket_public(r) for r in rows]})
                    return

                match = re.fullmatch(r"/api/tickets/([^/]+)", path)
                if match:
                    ticket_id = urllib.parse.unquote(match.group(1))
                    chat_token = (query.get("chatToken") or [""])[0].strip()
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    if not row:
                        self._send_json(404, {"error": "Ticket not found"})
                        return
                    staff = self._get_session_user(conn)
                    if staff and staff["role"] in {"admin", "technician"}:
                        self._send_json(200, {"ticket": ticket_public(row)})
                        return
                    if chat_token and secrets.compare_digest(chat_token, row["chat_token"]):
                        self._send_json(
                            200, {"ticket": ticket_public(row, include_chat_token=True)}
                        )
                        return
                    self._send_json(401, {"error": "Unauthorized"})
                    return

                match = re.fullmatch(r"/api/tickets/([^/]+)/messages", path)
                if match:
                    ticket_id = urllib.parse.unquote(match.group(1))
                    chat_token = (query.get("chatToken") or [""])[0].strip()
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    if not row:
                        self._send_json(404, {"error": "Ticket not found"})
                        return
                    staff = self._get_session_user(conn)
                    allowed = False
                    if staff and staff["role"] in {"admin", "technician"}:
                        allowed = True
                    elif chat_token and secrets.compare_digest(chat_token, row["chat_token"]):
                        allowed = True
                    if not allowed:
                        self._send_json(401, {"error": "Unauthorized"})
                        return
                    after_id = int((query.get("afterId") or ["0"])[0] or "0")
                    messages = conn.execute(
                        """
                        SELECT * FROM messages
                        WHERE ticket_id = ? AND id > ?
                        ORDER BY id ASC
                        """,
                        (ticket_id, after_id),
                    ).fetchall()
                    self._send_json(
                        200,
                        {
                            "ticket": ticket_public(row),
                            "messages": [message_public(m) for m in messages],
                        },
                    )
                    return

                self._send_json(404, {"error": "Not found"})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": str(exc)})
            finally:
                conn.close()

    def handle_api_post(self, parsed: urllib.parse.ParseResult) -> None:
        path = parsed.path.rstrip("/") or "/"
        try:
            data = self._read_json()
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        with _db_lock:
            conn = connect()
            try:
                if path == "/api/auth/login":
                    username = str(data.get("username", "")).strip()
                    password = str(data.get("password", ""))
                    user = conn.execute(
                        "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                        (username,),
                    ).fetchone()
                    if (
                        not user
                        or not user["active"]
                        or not verify_password(password, user["salt"], user["password_hash"])
                    ):
                        self._send_json(401, {"error": "Invalid username or password"})
                        return
                    token = secrets.token_urlsafe(32)
                    conn.execute(
                        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                        (token, user["id"], utc_now()),
                    )
                    conn.commit()
                    pub_user = user_public(user)
                    sync_staff_event_to_google_sheet("Staff Login", pub_user)
                    self._send_json(
                        200,
                        {
                            "token": token,
                            "user": pub_user,
                        },
                    )
                    return

                if path == "/api/auth/logout":
                    token = self._bearer_token()
                    if token:
                        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                        conn.commit()
                    self._send_json(200, {"ok": True})
                    return

                if path == "/api/admin/change-password":
                    user = self._require_role(conn, "admin")
                    if not user:
                        return
                    current = str(data.get("currentPassword", ""))
                    new_password = str(data.get("newPassword", ""))
                    if len(new_password) < 8:
                        self._send_json(
                            400, {"error": "New password must be at least 8 characters"}
                        )
                        return
                    if not verify_password(current, user["salt"], user["password_hash"]):
                        self._send_json(400, {"error": "Current password is incorrect"})
                        return
                    salt, password_hash = hash_password(new_password)
                    conn.execute(
                        "UPDATE users SET salt = ?, password_hash = ? WHERE id = ?",
                        (salt, password_hash, user["id"]),
                    )
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
                    token = secrets.token_urlsafe(32)
                    conn.execute(
                        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                        (token, user["id"], utc_now()),
                    )
                    conn.commit()
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "token": token,
                            "message": "Password updated. Other sessions were signed out.",
                        },
                    )
                    return

                if path == "/api/admin/technicians":
                    user = self._require_role(conn, "admin")
                    if not user:
                        return
                    username = str(data.get("username", "")).strip()
                    display_name = str(data.get("displayName", "")).strip() or username
                    password = str(data.get("password", ""))
                    if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", username or ""):
                        self._send_json(
                            400,
                            {
                                "error": "Username must be 3–32 characters (letters, numbers, . _ -)"
                            },
                        )
                        return
                    if len(password) < 8:
                        self._send_json(
                            400, {"error": "Password must be at least 8 characters"}
                        )
                        return
                    exists = conn.execute(
                        "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                        (username,),
                    ).fetchone()
                    if exists:
                        self._send_json(409, {"error": "Username already exists"})
                        return
                    salt, password_hash = hash_password(password)
                    cur = conn.execute(
                        """
                        INSERT INTO users (username, display_name, role, salt, password_hash, active, created_at)
                        VALUES (?, ?, 'technician', ?, ?, 1, ?)
                        """,
                        (username, display_name, salt, password_hash, utc_now()),
                    )
                    conn.commit()
                    row = conn.execute(
                        "SELECT * FROM users WHERE id = ?", (cur.lastrowid,)
                    ).fetchone()
                    pub_tech = user_public(row)
                    sync_staff_event_to_google_sheet("Technician Created", pub_tech)
                    self._send_json(201, {"technician": pub_tech})
                    return

                if path == "/api/tickets":
                    required = [
                        "fullName",
                        "role",
                        "email",
                        "location",
                        "category",
                        "priority",
                        "subject",
                        "description",
                    ]
                    values = {k: str(data.get(k, "")).strip() for k in required}
                    if any(not values[k] for k in required):
                        self._send_json(400, {"error": "Missing required fields"})
                        return
                    email = values["email"]
                    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                        self._send_json(400, {"error": "Invalid email"})
                        return

                    ticket_id = make_ticket_id()
                    while conn.execute(
                        "SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone():
                        ticket_id = make_ticket_id()
                    chat_token = secrets.token_urlsafe(24)
                    created = utc_now()
                    conn.execute(
                        """
                        INSERT INTO tickets (
                            id, full_name, school_id, role, email, phone, location,
                            category, priority, subject, description, status, chat_token,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                        """,
                        (
                            ticket_id,
                            values["fullName"],
                            str(data.get("schoolId", "")).strip(),
                            values["role"],
                            email,
                            str(data.get("phone", "")).strip(),
                            values["location"],
                            values["category"],
                            values["priority"],
                            values["subject"],
                            values["description"],
                            chat_token,
                            created,
                        ),
                    )
                    welcome = (
                        f"Hi {values['fullName']}! Your ticket {ticket_id} was received. "
                        "A CITECHS technician will reply here during support hours."
                    )
                    conn.execute(
                        """
                        INSERT INTO messages (
                            ticket_id, sender_type, sender_name, sender_user_id, body, created_at
                        ) VALUES (?, 'system', 'CITECHS', NULL, ?, ?)
                        """,
                        (ticket_id, welcome, created),
                    )
                    conn.commit()
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    public_ticket = ticket_public(row, include_chat_token=True)
                    send_to_google_sheet(public_ticket)
                    self._send_json(
                        201,
                        {
                            "ticket": public_ticket,
                            "chatUrl": f"chat.html?ticket={urllib.parse.quote(ticket_id)}&token={urllib.parse.quote(chat_token)}",
                        },
                    )
                    return

                match = re.fullmatch(r"/api/tickets/([^/]+)/messages", path)
                if match:
                    ticket_id = urllib.parse.unquote(match.group(1))
                    body = str(data.get("body", "")).strip()
                    if not body:
                        self._send_json(400, {"error": "Message body is required"})
                        return
                    if len(body) > 4000:
                        self._send_json(400, {"error": "Message is too long"})
                        return
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    if not row:
                        self._send_json(404, {"error": "Ticket not found"})
                        return

                    staff = self._get_session_user(conn)
                    chat_token = str(data.get("chatToken", "")).strip()
                    if staff and staff["role"] in {"admin", "technician"}:
                        sender_type = "technician"
                        sender_name = staff["display_name"]
                        sender_user_id = staff["id"]
                        if row["status"] == "open" and not row["assigned_tech_id"]:
                            conn.execute(
                                "UPDATE tickets SET assigned_tech_id = ? WHERE id = ?",
                                (staff["id"], ticket_id),
                            )
                    elif chat_token and secrets.compare_digest(chat_token, row["chat_token"]):
                        if row["status"] == "closed":
                            self._send_json(400, {"error": "This chat is closed"})
                            return
                        sender_type = "client"
                        sender_name = row["full_name"]
                        sender_user_id = None
                    else:
                        self._send_json(401, {"error": "Unauthorized"})
                        return

                    created = utc_now()
                    cur = conn.execute(
                        """
                        INSERT INTO messages (
                            ticket_id, sender_type, sender_name, sender_user_id, body, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ticket_id,
                            sender_type,
                            sender_name,
                            sender_user_id,
                            body,
                            created,
                        ),
                    )
                    conn.commit()
                    msg = conn.execute(
                        "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
                    ).fetchone()
                    self._send_json(201, {"message": message_public(msg)})
                    return

                match = re.fullmatch(r"/api/tickets/([^/]+)/close", path)
                if match:
                    user = self._require_role(conn, "admin", "technician")
                    if not user:
                        return
                    ticket_id = urllib.parse.unquote(match.group(1))
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    if not row:
                        self._send_json(404, {"error": "Ticket not found"})
                        return
                    conn.execute(
                        "UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,)
                    )
                    conn.execute(
                        """
                        INSERT INTO messages (
                            ticket_id, sender_type, sender_name, sender_user_id, body, created_at
                        ) VALUES (?, 'system', 'CITECHS', ?, ?, ?)
                        """,
                        (
                            ticket_id,
                            user["id"],
                            f"Ticket closed by {user['display_name']}.",
                            utc_now(),
                        ),
                    )
                    conn.commit()
                    self._send_json(200, {"ok": True})
                    return

                match = re.fullmatch(r"/api/tickets/([^/]+)/reopen", path)
                if match:
                    user = self._require_role(conn, "admin", "technician")
                    if not user:
                        return
                    ticket_id = urllib.parse.unquote(match.group(1))
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    if not row:
                        self._send_json(404, {"error": "Ticket not found"})
                        return
                    conn.execute(
                        "UPDATE tickets SET status = 'open' WHERE id = ?", (ticket_id,)
                    )
                    conn.execute(
                        """
                        INSERT INTO messages (
                            ticket_id, sender_type, sender_name, sender_user_id, body, created_at
                        ) VALUES (?, 'system', 'CITECHS', ?, ?, ?)
                        """,
                        (
                            ticket_id,
                            user["id"],
                            f"Ticket reopened by {user['display_name']}.",
                            utc_now(),
                        ),
                    )
                    conn.commit()
                    self._send_json(200, {"ok": True})
                    return

                if path == "/api/tickets/lookup":
                    ticket_id = str(data.get("ticketId", "")).strip()
                    email = str(data.get("email", "")).strip().lower()
                    if not ticket_id or not email:
                        self._send_json(400, {"error": "Ticket ID and email are required"})
                        return
                    row = conn.execute(
                        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
                    ).fetchone()
                    stored = (row["email"] if row else "").strip().lower()
                    email_hash = hashlib.sha256(email.encode("utf-8")).digest()
                    stored_hash = hashlib.sha256(stored.encode("utf-8")).digest()
                    if not row or not secrets.compare_digest(email_hash, stored_hash):
                        self._send_json(
                            404,
                            {"error": "No matching ticket. Check the ID and email."},
                        )
                        return
                    self._send_json(
                        200,
                        {
                            "ticket": ticket_public(row),
                            "chatUrl": (
                                f"chat.html?ticket={urllib.parse.quote(row['id'])}"
                                f"&token={urllib.parse.quote(row['chat_token'])}"
                            ),
                        },
                    )
                    return

                self._send_json(404, {"error": "Not found"})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": str(exc)})
            finally:
                conn.close()

    def handle_api_patch(self, parsed: urllib.parse.ParseResult) -> None:
        path = parsed.path.rstrip("/") or "/"
        try:
            data = self._read_json()
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        match = re.fullmatch(r"/api/admin/technicians/(\d+)", path)
        if not match:
            self._send_json(404, {"error": "Not found"})
            return

        tech_id = int(match.group(1))
        with _db_lock:
            conn = connect()
            try:
                user = self._require_role(conn, "admin")
                if not user:
                    return
                tech = conn.execute(
                    "SELECT * FROM users WHERE id = ? AND role = 'technician'",
                    (tech_id,),
                ).fetchone()
                if not tech:
                    self._send_json(404, {"error": "Technician not found"})
                    return

                if "displayName" in data:
                    name = str(data.get("displayName", "")).strip()
                    if name:
                        conn.execute(
                            "UPDATE users SET display_name = ? WHERE id = ?",
                            (name, tech_id),
                        )
                if "active" in data:
                    active = 1 if data.get("active") else 0
                    conn.execute(
                        "UPDATE users SET active = ? WHERE id = ?", (active, tech_id)
                    )
                    if not active:
                        conn.execute("DELETE FROM sessions WHERE user_id = ?", (tech_id,))
                if data.get("password"):
                    password = str(data["password"])
                    if len(password) < 8:
                        self._send_json(
                            400, {"error": "Password must be at least 8 characters"}
                        )
                        return
                    salt, password_hash = hash_password(password)
                    conn.execute(
                        "UPDATE users SET salt = ?, password_hash = ? WHERE id = ?",
                        (salt, password_hash, tech_id),
                    )
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (tech_id,))

                conn.commit()
                row = conn.execute(
                    "SELECT * FROM users WHERE id = ?", (tech_id,)
                ).fetchone()
                self._send_json(200, {"technician": user_public(row)})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": str(exc)})
            finally:
                conn.close()

    def handle_api_delete(self, parsed: urllib.parse.ParseResult) -> None:
        path = parsed.path.rstrip("/") or "/"
        match = re.fullmatch(r"/api/admin/technicians/(\d+)", path)
        if not match:
            self._send_json(404, {"error": "Not found"})
            return
        tech_id = int(match.group(1))
        with _db_lock:
            conn = connect()
            try:
                user = self._require_role(conn, "admin")
                if not user:
                    return
                tech = conn.execute(
                    "SELECT * FROM users WHERE id = ? AND role = 'technician'",
                    (tech_id,),
                ).fetchone()
                if not tech:
                    self._send_json(404, {"error": "Technician not found"})
                    return
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (tech_id,))
                conn.execute("DELETE FROM users WHERE id = ?", (tech_id,))
                conn.commit()
                self._send_json(200, {"ok": True})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": str(exc)})
            finally:
                conn.close()


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), CitechsHandler)
    print(f"CITECHS server running at http://{HOST}:{PORT}/")
    print(f"Admin login: http://{HOST}:{PORT}/staff-login.html")
    print(f"Default admin user: {DEFAULT_ADMIN_USER}")
    print("Change the admin password from the Admin panel after signing in.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    main()