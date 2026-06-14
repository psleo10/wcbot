"""
db.py — WC 2026 Bet Bot database
Pari-mutuel pool: team_a | draw | team_b
2.5% house cut. Bets stored anonymously by pot.
"""
import sqlite3, os
from contextlib import contextmanager
from typing import Optional

DB = os.getenv("DATABASE_PATH", "wc_bet.db")

@contextmanager
def get_conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init():
    with get_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                tid   INTEGER PRIMARY KEY,
                name  TEXT NOT NULL,
                at    TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS matches (
                mid      INTEGER PRIMARY KEY AUTOINCREMENT,
                label    TEXT NOT NULL,
                team_a   TEXT NOT NULL,
                team_b   TEXT NOT NULL,
                kickoff  TEXT NOT NULL,
                status   TEXT NOT NULL DEFAULT 'open',
                winner   TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS bets (
                bid     INTEGER PRIMARY KEY AUTOINCREMENT,
                uid     INTEGER NOT NULL,
                mid     INTEGER NOT NULL,
                pot     TEXT NOT NULL CHECK(pot IN ('team_a','draw','team_b')),
                amount  REAL NOT NULL,
                payout  REAL DEFAULT NULL,
                status  TEXT NOT NULL DEFAULT 'pending',
                at      TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(uid, mid, pot)
            );
        """)
    print("✅ DB ready.")

# ── Users ──────────────────────────────────────────────────────────────────────
def upsert_user(tid: int, name: str):
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO users (tid,name) VALUES (?,?)", (tid, name))
    return get_user(tid)

def get_user(tid: int) -> Optional[sqlite3.Row]:
    with get_conn() as c:
        return c.execute("SELECT * FROM users WHERE tid=?", (tid,)).fetchone()

# ── Matches ────────────────────────────────────────────────────────────────────
def add_match(label, team_a, team_b, kickoff) -> int:
    with get_conn() as c:
        return c.execute(
            "INSERT INTO matches (label,team_a,team_b,kickoff) VALUES (?,?,?,?)",
            (label, team_a, team_b, kickoff)
        ).lastrowid

def open_matches(limit=5):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE status='open' ORDER BY kickoff LIMIT ?",
            (limit,)
        ).fetchall()

def get_match(mid: int) -> Optional[sqlite3.Row]:
    with get_conn() as c:
        return c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()

def locked_matches():
    with get_conn() as c:
        return c.execute("SELECT * FROM matches WHERE status='locked'").fetchall()

def lock_match(mid: int):
    with get_conn() as c:
        c.execute("UPDATE matches SET status='locked' WHERE mid=?", (mid,))

# ── Bets ───────────────────────────────────────────────────────────────────────
def get_user_bets_on_match(uid: int, mid: int):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM bets WHERE uid=? AND mid=? AND status='pending'",
            (uid, mid)
        ).fetchall()

def place_bet(uid: int, mid: int, pot: str, amount: float) -> tuple:
    if pot not in ("team_a","draw","team_b"):
        return False, "Invalid selection."
    if amount < 50:
        return False, "Minimum bet is ₹50."
    with get_conn() as c:
        m = c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()
        if not m:
            return False, "Match not found."
        if m["status"] != "open":
            return False, "Bets are closed for this match."
        existing = c.execute(
            "SELECT * FROM bets WHERE uid=? AND mid=? AND pot=?", (uid,mid,pot)
        ).fetchone()
        if existing:
            c.execute(
                "UPDATE bets SET amount=?,at=datetime('now') WHERE uid=? AND mid=? AND pot=?",
                (amount,uid,mid,pot)
            )
            return True, "updated"
        c.execute(
            "INSERT INTO bets (uid,mid,pot,amount) VALUES (?,?,?,?)",
            (uid,mid,pot,amount)
        )
    return True, "placed"

def pool_summary(mid: int) -> dict:
    """Returns anonymous totals + counts per pot. No names."""
    with get_conn() as c:
        m = c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()
        if not m: return {}
        rows = c.execute(
            "SELECT pot, SUM(amount) as total, COUNT(*) as cnt "
            "FROM bets WHERE mid=? AND status='pending' GROUP BY pot",
            (mid,)
        ).fetchall()
    totals = {"team_a":0.0,"draw":0.0,"team_b":0.0}
    counts = {"team_a":0,  "draw":0,  "team_b":0}
    for r in rows:
        totals[r["pot"]] = r["total"]
        counts[r["pot"]] = r["cnt"]
    return {"match":m, "totals":totals, "counts":counts, "grand":sum(totals.values())}

def pot_bettors(mid: int, pot: str) -> list:
    """Names only (no amounts) for public odds view."""
    with get_conn() as c:
        return c.execute(
            "SELECT u.name FROM bets b JOIN users u ON b.uid=u.tid "
            "WHERE b.mid=? AND b.pot=? AND b.status='pending'",
            (mid, pot)
        ).fetchall()

def settle_match(mid: int, winner_pot: str, house_cut: float = 0.025) -> dict:
    out = {"winners":[], "losers":[], "pool":0.0, "house":0.0}
    with get_conn() as c:
        m = c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()
        if not m or m["status"] == "settled": return out
        bets = c.execute(
            "SELECT b.*,u.name,u.tid FROM bets b JOIN users u ON b.uid=u.tid "
            "WHERE b.mid=? AND b.status='pending'", (mid,)
        ).fetchall()
        pool      = sum(b["amount"] for b in bets)
        win_total = sum(b["amount"] for b in bets if b["pot"]==winner_pot)
        out["pool"] = pool

        # Edge case: nobody bet on the winning pot — full refund, no house cut
        if win_total == 0:
            out["house"]    = 0.0
            out["refunded"] = True
            for b in bets:
                c.execute("UPDATE bets SET status='won',payout=? WHERE bid=?",
                          (b["amount"], b["bid"]))
                out["winners"].append({
                    "name":b["name"],"tid":b["tid"],
                    "bet":b["amount"],"payout":b["amount"],"profit":0.0
                })
            c.execute("UPDATE matches SET status='settled',winner=? WHERE mid=?", (winner_pot,mid))
            return out

        house     = round(pool * house_cut, 2)
        net_pool  = pool - house
        out["house"]    = house
        out["refunded"] = False
        for b in bets:
            if b["pot"] == winner_pot:
                payout = round((b["amount"]/win_total)*net_pool, 2)
                c.execute("UPDATE bets SET status='won',payout=? WHERE bid=?", (payout,b["bid"]))
                out["winners"].append({
                    "name":b["name"],"tid":b["tid"],
                    "bet":b["amount"],"payout":payout,
                    "profit":round(payout-b["amount"],2)
                })
            else:
                c.execute("UPDATE bets SET status='lost',payout=0 WHERE bid=?", (b["bid"],))
                out["losers"].append({"name":b["name"],"tid":b["tid"],"amount":b["amount"]})
        c.execute("UPDATE matches SET status='settled',winner=? WHERE mid=?", (winner_pot,mid))
    return out

def user_bet_history(uid: int, limit: int = 15):
    with get_conn() as c:
        return c.execute(
            "SELECT b.*,m.label,m.team_a,m.team_b,m.status as mstatus,m.winner "
            "FROM bets b JOIN matches m ON b.mid=m.mid "
            "WHERE b.uid=? ORDER BY b.at DESC LIMIT ?",
            (uid,limit)
        ).fetchall()

def leaderboard():
    with get_conn() as c:
        return c.execute("""
            SELECT u.name,
              COALESCE(SUM(b.amount),0) as wagered,
              COALESCE(SUM(
                CASE WHEN b.status='won'  THEN b.payout-b.amount
                     WHEN b.status='lost' THEN -b.amount
                     ELSE 0 END),0) as net,
              COUNT(CASE WHEN b.status IN ('won','lost') THEN 1 END) as matches_bet,
              COUNT(CASE WHEN b.status='won' THEN 1 END) as wins
            FROM users u
            LEFT JOIN bets b ON u.tid=b.uid
            GROUP BY u.tid ORDER BY net DESC
        """).fetchall()
