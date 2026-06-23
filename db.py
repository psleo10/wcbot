"""
db.py — WC 2026 Betting Bot
5-pot pari-mutuel system:
  team_a_2plus | team_a_by_1 | draw_pens | team_b_by_1 | team_b_2plus
2.5% house cut. Anonymous pots.
"""
import sqlite3, os
from contextlib import contextmanager
from typing import Optional

DB = os.getenv("DATABASE_PATH", "wc_bet.db")

POTS = ["team_a_2plus", "team_a_by_1", "draw_pens", "team_b_by_1", "team_b_2plus"]

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
                pot     TEXT NOT NULL,
                amount  REAL NOT NULL,
                payout  REAL DEFAULT NULL,
                status  TEXT NOT NULL DEFAULT 'pending',
                at      TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(uid, mid)
            );
        """)
    print("DB ready.")

def plabel(m, pot):
    """Human readable pot label."""
    ta = m["team_a"]; tb = m["team_b"]
    is_ko = not m["label"].startswith("Group")
    labels = {
        "team_a_2plus": f"🔵 {ta} wins by 2+",
        "team_a_by_1":  f"🔵 {ta} wins by 1",
        "draw_pens":    "⚪ Goes to Pens / AET" if is_ko else "⚪ Draw",
        "team_b_by_1":  f"🔴 {tb} wins by 1",
        "team_b_2plus": f"🔴 {tb} wins by 2+",
    }
    return labels.get(pot, pot)

def pot_emoji(pot):
    if "team_a" in pot: return "🔵"
    if "team_b" in pot: return "🔴"
    return "⚪"

# ── Users ──────────────────────────────────────────────────────────────────────
def upsert_user(tid, name):
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO users (tid,name) VALUES (?,?)", (tid,name))
    return get_user(tid)

def get_user(tid) -> Optional[sqlite3.Row]:
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

def get_match(mid) -> Optional[sqlite3.Row]:
    with get_conn() as c:
        return c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()

def locked_matches():
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM matches WHERE status IN ('locked','open')"
        ).fetchall()

def lock_match(mid):
    with get_conn() as c:
        c.execute("UPDATE matches SET status='locked' WHERE mid=?", (mid,))

# ── Bets ───────────────────────────────────────────────────────────────────────
def get_user_bet_on_match(uid, mid):
    """One bet per user per match."""
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM bets WHERE uid=? AND mid=? AND status='pending'",
            (uid, mid)
        ).fetchone()

def place_bet(uid, mid, pot, amount) -> tuple:
    print(f"DEBUG POT: {pot}")
    if pot not in POTS:
        return False, "Invalid pot."
    if amount < 50:
        return False, "Minimum bet is ₹50."
    with get_conn() as c:
        m = c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()
        if not m:
            return False, "Match not found."
        if m["status"] != "open":
            return False, "Bets are closed for this match."
        existing = c.execute(
            "SELECT * FROM bets WHERE uid=? AND mid=?", (uid, mid)
        ).fetchone()
        if existing:
            if existing["pot"] != pot:
                return False, f"You already bet on *{plabel(m, existing['pot'])}*. You cannot switch — only edit the amount."
            c.execute(
                "UPDATE bets SET amount=?,at=datetime('now') WHERE uid=? AND mid=?",
                (amount, uid, mid)
            )
            return True, "updated"
        c.execute(
            "INSERT INTO bets (uid,mid,pot,amount) VALUES (?,?,?,?)",
            (uid, mid, pot, amount)
        )
    return True, "placed"

def pool_summary(mid) -> dict:
    """Anonymous totals + counts per pot."""
    with get_conn() as c:
        m = c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()
        if not m: return {}
        rows = c.execute(
            "SELECT pot, SUM(amount) as total, COUNT(*) as cnt "
            "FROM bets WHERE mid=? AND status='pending' GROUP BY pot",
            (mid,)
        ).fetchall()
    totals = {p: 0.0 for p in POTS}
    counts = {p: 0   for p in POTS}
    for r in rows:
        totals[r["pot"]] = r["total"]
        counts[r["pot"]] = r["cnt"]
    return {"match": m, "totals": totals, "counts": counts, "grand": sum(totals.values())}

def pot_bettors(mid, pot):
    """Names only for /odds view."""
    with get_conn() as c:
        return c.execute(
            "SELECT u.name FROM bets b JOIN users u ON b.uid=u.tid "
            "WHERE b.mid=? AND b.pot=? AND b.status='pending'",
            (mid, pot)
        ).fetchall()

def settle_match(mid, winner_pot, house_cut=0.025) -> dict:
    out = {"winners":[], "losers":[], "pool":0.0, "house":0.0, "refunded":False}
    with get_conn() as c:
        m = c.execute("SELECT * FROM matches WHERE mid=?", (mid,)).fetchone()
        if not m or m["status"] == "settled": return out
        bets = c.execute(
            "SELECT b.*,u.name,u.tid FROM bets b JOIN users u ON b.uid=u.tid "
            "WHERE b.mid=? AND b.status='pending'", (mid,)
        ).fetchall()
        pool      = sum(b["amount"] for b in bets)
        win_total = sum(b["amount"] for b in bets if b["pot"] == winner_pot)
        out["pool"] = pool

        if win_total == 0:
            # Nobody bet winning pot — full refund
            out["refunded"] = True
            out["house"] = 0.0
            for b in bets:
                c.execute("UPDATE bets SET status='won',payout=? WHERE bid=?",
                          (b["amount"], b["bid"]))
                out["winners"].append({
                    "name":b["name"],"tid":b["tid"],
                    "bet":b["amount"],"payout":b["amount"],"profit":0.0
                })
        else:
            house    = round(pool * house_cut, 2)
            net_pool = pool - house
            out["house"] = house
            for b in bets:
                if b["pot"] == winner_pot:
                    payout = round((b["amount"]/win_total)*net_pool, 2)
                    c.execute("UPDATE bets SET status='won',payout=? WHERE bid=?",
                              (payout, b["bid"]))
                    out["winners"].append({
                        "name":b["name"],"tid":b["tid"],
                        "bet":b["amount"],"payout":payout,
                        "profit":round(payout-b["amount"],2)
                    })
                else:
                    c.execute("UPDATE bets SET status='lost',payout=0 WHERE bid=?",
                              (b["bid"],))
                    out["losers"].append({
                        "name":b["name"],"tid":b["tid"],"amount":b["amount"]
                    })
        c.execute("UPDATE matches SET status='settled',winner=? WHERE mid=?",
                  (winner_pot, mid))
    return out

def user_bet_history(uid, limit=15):
    with get_conn() as c:
        return c.execute(
            "SELECT b.*,m.label,m.team_a,m.team_b,m.status as mstatus,m.winner "
            "FROM bets b JOIN matches m ON b.mid=m.mid "
            "WHERE b.uid=? ORDER BY b.at DESC LIMIT ?",
            (uid, limit)
        ).fetchall()

def leaderboard():
    with get_conn() as c:
        return c.execute("""
            SELECT u.name,
              COALESCE(SUM(b.amount),0) as wagered,
              COALESCE(SUM(
                CASE WHEN b.status='won'  THEN b.payout-b.amount
                     WHEN b.status='lost' THEN -b.amount
                     ELSE 0 END),0) as net
            FROM users u
            LEFT JOIN bets b ON u.tid=b.uid
            GROUP BY u.tid ORDER BY net DESC
        """).fetchall()
