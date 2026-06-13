"""
scheduler.py — Background jobs
- Lock bets 1 min before kickoff
- 1hr before reminder to group
- 30min after kickoff: "match started" nudge
- Poll API for results (optional)
"""
import os, logging, requests
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import db

logger = logging.getLogger(__name__)

FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY","")
HOUSE_CUT        = float(os.getenv("HOUSE_CUT","0.025"))

_app      = None
_group_id = None

def set_bot(app, group_id: int):
    global _app, _group_id
    _app      = app
    _group_id = group_id

def _now():
    return datetime.now(timezone.utc)

def _ko(m):
    try:
        return datetime.fromisoformat(m["kickoff"]).replace(tzinfo=timezone.utc)
    except:
        return None

def _ist(s):
    try:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc) + timedelta(hours=5,minutes=30)
        return dt.strftime("%d %b, %I:%M %p IST")
    except:
        return s

# track what we've already notified to avoid repeats
_notified_1hr   = set()
_notified_30min = set()
_notified_lock  = set()

async def job_tick():
    """Runs every 30s. Handles locking + reminders."""
    now = _now()
    for m in db.open_matches(limit=20):
        ko  = _ko(m)
        if not ko: continue
        mid = m["mid"]
        diff = (ko - now).total_seconds()

        # 1 hour reminder
        if 3550 < diff < 3650 and mid not in _notified_1hr:
            _notified_1hr.add(mid)
            s = db.pool_summary(mid)
            g = s["grand"]
            await _send(
                f"⏰ *1 hour to kickoff!*\n\n"
                f"⚽ *{m['label']}*\n"
                f"🕐 {_ist(m['kickoff'])}\n\n"
                f"💰 Pool so far: ₹{g:,.0f}\n"
                f"Bets lock in 60 mins — place yours now!\n\n"
                f"👉 /bet to place a bet"
            )

        # Lock 1 min before kickoff
        if diff <= 60 and mid not in _notified_lock:
            _notified_lock.add(mid)
            db.lock_match(mid)
            s = db.pool_summary(mid)
            g = s["grand"]
            ta = s["totals"]["team_a"]; dr = s["totals"]["draw"]; tb = s["totals"]["team_b"]
            await _send(
                f"🔒 *Bets locked! — {m['label']}*\n\n"
                f"Final pool: *₹{g:,.0f}*\n"
                f"🔵 {m['team_a']}: ₹{ta:,.0f}\n"
                f"⚪ Draw: ₹{dr:,.0f}\n"
                f"🔴 {m['team_b']}: ₹{tb:,.0f}\n\n"
                f"Good luck everyone! 🍀"
            )



async def job_poll():
    """Poll football API for results. Runs every 60s."""
    if not FOOTBALL_API_KEY: return
    for m in db.locked_matches():
        try:
            winner = _fetch_result(m)
            if winner is None: continue
            from bot import do_settle
            await do_settle(_app, m, winner)
        except Exception as e:
            logger.error(f"Poll settle error {m['mid']}: {e}")

def _fetch_result(m):
    """
    Tries football-data.org first (free, no credit card).
    API key from env: FOOTBALL_API_KEY
    WC 2026 competition id = 2000
    """
    if not FOOTBALL_API_KEY:
        return None
    try:
        # football-data.org — free tier covers WC
        r = requests.get(
            "https://api.football-data.org/v4/competitions/2000/matches",
            headers={"X-Auth-Token": FOOTBALL_API_KEY},
            params={"status": "FINISHED", "matchday": _guess_matchday(m)},
            timeout=10
        )
        if r.status_code != 200:
            logger.warning(f"football-data.org returned {r.status_code}")
            return None

        for match in r.json().get("matches", []):
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]
            status = match["status"]
            ta = m["team_a"].lower(); tb = m["team_b"].lower()

            if not ((ta in home.lower() or ta in away.lower()) and
                    (tb in home.lower() or tb in away.lower())):
                continue

            if status != "FINISHED":
                return None  # still playing

            gh = match["score"]["fullTime"]["home"] or 0
            ga = match["score"]["fullTime"]["away"] or 0

            if gh > ga:
                return "team_a" if m["team_a"].lower() in home.lower() else "team_b"
            elif ga > gh:
                return "team_b" if m["team_b"].lower() in away.lower() else "team_a"
            else:
                return "draw"

    except Exception as e:
        logger.warning(f"API fetch error: {e}")
    return None


def _guess_matchday(m):
    """Rough matchday estimate from kickoff date for API filtering."""
    try:
        from datetime import datetime, timezone
        ko = datetime.fromisoformat(m["kickoff"]).replace(tzinfo=timezone.utc)
        start = datetime(2026, 6, 11, tzinfo=timezone.utc)
        day = (ko - start).days + 1
        return max(1, min(day, 52))
    except:
        return 1

async def _send(text: str):
    if _app and _group_id:
        try:
            await _app.bot.send_message(_group_id, text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Scheduler send failed: {e}")

def make_scheduler() -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone="UTC")
    s.add_job(job_tick, IntervalTrigger(seconds=30), id="tick", replace_existing=True)
    s.add_job(job_poll, IntervalTrigger(seconds=60), id="poll", replace_existing=True)
    return s
