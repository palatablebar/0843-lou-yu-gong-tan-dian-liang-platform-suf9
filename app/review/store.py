import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY,
              request_key TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL,
              profile TEXT NOT NULL,
              status TEXT NOT NULL,
              revision INTEGER NOT NULL,
              payload TEXT NOT NULL,
              comment TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS issuances(
              id TEXT PRIMARY KEY,
              idempotency_key TEXT UNIQUE NOT NULL,
              run_id TEXT NOT NULL,
              building_id TEXT NOT NULL,
              posting_no TEXT NOT NULL,
              status TEXT NOT NULL,
              amount_wh INTEGER NOT NULL DEFAULT 0,
              payload TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              UNIQUE(run_id, building_id)
            );
            CREATE TABLE IF NOT EXISTS kv(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            ''')

    def find_by_request(self, request_key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE request_key=?", (request_key,)).fetchone()
        return dict(row) if row else None

    def create(self, request_key, profile, payload):
        existing = self.find_by_request(request_key)
        if existing:
            return existing
        run_id = uuid.uuid4().hex[:12]
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,request_key,created_at,profile,status,revision,payload) VALUES(?,?,?,?,?,?,?)",
                       (run_id, request_key, datetime.now(timezone.utc).isoformat(), profile, "DRAFT", 0,
                        json.dumps(payload, ensure_ascii=False)))
        return self.get(run_id)

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def review(self, run_id, decision, comment, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None, "missing"
            if row["revision"] != expected_revision:
                return None, "stale"
            db.execute("UPDATE runs SET status=?, revision=revision+1, comment=? WHERE id=?",
                       (decision, comment, run_id))
        return self.get(run_id), None

    # ---------- 楼栋签发 / 出账（幂等） ----------

    def find_issuance(self, run_id, building_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM issuances WHERE run_id=? AND building_id=?",
                (run_id, str(building_id))).fetchone()
        return dict(row) if row else None

    def find_issuance_by_key(self, idempotency_key):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM issuances WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return dict(row) if row else None

    def list_issuances(self, run_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM issuances WHERE run_id=? ORDER BY created_at, id",
                (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def create_issuance(self, run_id, building_id, idempotency_key, posting_no,
                        status, amount_wh, payload):
        """插入签发记录；命中幂等键或 (run, building) 唯一约束时返回旧记录。

        返回 ``(row, created)``。重试不会重复出账。
        """
        building_id = str(building_id)
        existing = self.find_issuance_by_key(idempotency_key)
        if existing:
            return existing, False
        existing = self.find_issuance(run_id, building_id)
        if existing:
            return existing, False
        issuance_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # 事务内再查一次，挡住并发重试。
                row = db.execute(
                    "SELECT * FROM issuances WHERE idempotency_key=? OR (run_id=? AND building_id=?)",
                    (idempotency_key, run_id, building_id)).fetchone()
                if row is not None:
                    return dict(row), False
                db.execute(
                    "INSERT INTO issuances(id,idempotency_key,run_id,building_id,posting_no,"
                    "status,amount_wh,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (issuance_id, idempotency_key, run_id, building_id, posting_no, status,
                     int(amount_wh or 0), json.dumps(payload, ensure_ascii=False), now))
                row = db.execute("SELECT * FROM issuances WHERE id=?", (issuance_id,)).fetchone()
            return dict(row), True
        except sqlite3.IntegrityError:
            existing = self.find_issuance(run_id, building_id) or self.find_issuance_by_key(idempotency_key)
            return existing, False

    # ---------- 简单 KV（合同上限按月录入的持久化） ----------

    def kv_get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def kv_set(self, key, value):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), now))
        return value
