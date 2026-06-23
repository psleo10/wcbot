"""
bot.py — WC 2026 Bet Bot (Final)

GROUP commands: /bet /matches /pool /odds /leaderboard /mybets /history
BETTING: button flow — match → team_a | draw | team_b → amount → confirm
ANONYMOUS: bets are private. /odds shows names per pot (not amounts).
REMINDERS: 1hr before, lock at kickoff, 30min in, final result.
HOUSE CUT: 2.5%
"""

import os, re, logging
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from telegram.constants import ParseMode

import db
import scheduler as sched
from facts import get_team_fact, get_h2h, WC_FACTS

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ["BOT_TOKEN"]
ADMIN_IDS     = set(int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip())
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID","0"))
HOUSE_CUT     = float(os.getenv("HOUSE_CUT","0.025"))
AMOUNTS       = [50, 100, 200, 500, 1000]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def is_admin(uid): return uid in ADMIN_IDS

def plabel(m, pot):
    if pot == "team_a": return m["team_a"]
    if pot == "team_b": return m["team_b"]
    return "Draw"

def pemoji(pot):
    if pot in ("team_a","team_a_2plus","team_a_by_1"): return "🔵"
    if pot in ("team_b","team_b_2plus","team_b_by_1"): return "🔴"
    return "⚪"

def ist(s):
    try:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc) + timedelta(hours=5,minutes=30)
        return dt.strftime("%d %b, %I:%M %p IST")
    except:
        return s

def pbar(tot, grand, w=7):
    pct = (tot/grand*100) if grand else 0
    n   = int(pct/(100/w))
    return "█"*n + "░"*(w-n), round(pct,0)

def est(amt, pot_tot, grand):
    np = pot_tot + amt
    ng = grand + amt
    return round((amt/np)*ng*(1-HOUSE_CUT), 0) if np else 0

KNOCKOUT_PREFIXES = ("r32", "r16", "qf", "semi", "3rd", "final", "quarter", "round of")

def is_knockout(match) -> bool:
    label = match["label"].lower()
    return any(p in label for p in KNOCKOUT_PREFIXES)

def safe_send(text, limit=4000):
    """Split text at paragraph boundaries to stay under Telegram limit."""
    if len(text) <= limit:
        return [text]
    parts = []
    while len(text) > limit:
        split = text[:limit].rfind("\n\n")
        if split < 100: split = limit
        parts.append(text[:split].strip())
        text = text[split:].strip()
    if text:
        parts.append(text)
    return parts

# ── Settlement (called from admin + scheduler) ─────────────────────────────────

async def do_settle(app, match, winner_pot: str):
    summary  = db.settle_match(match["mid"], winner_pot, HOUSE_CUT)
    wlabel   = plabel(match, winner_pot)
    emoji    = "🤝" if winner_pot=="draw" else "🏆"

    # Build result card
    wlines = [f"  ✅ [{w['name']}](tg://user?id={w['tid']}): ₹{w['bet']:,.0f} → *₹{w['payout']:,.0f}* (+₹{w['profit']:,.0f}) 🎉"
              for w in summary["winners"]]
    llines = [f"  ❌ [{l['name']}](tg://user?id={l['tid']}): -₹{l['amount']:,.0f}"
              for l in summary["losers"]]

    result = (
        f"{emoji} *{match['label']} — Full Time!*\n\n"
        f"Result: *{wlabel}* wins\n"
        f"Pool: ₹{summary['pool']:,.0f} | House: ₹{summary['house']:,.0f}\n\n"
        f"🏆 *Winners*\n" + ("\n".join(wlines) or "  Nobody bet on this pot!") +
        (f"\n\n😔 *Losers*\n" + "\n".join(llines) if llines else "") +
        f"\n\n📊 /leaderboard — updated standings\n"
        f"👉 /bet to bet on next match"
    )

    # Handle refund case — nobody bet on winning pot
    if summary.get("refunded"):
        result = (
            f"⚠️ *{match['label']} — Refunded!*\n\n"
            f"Result: *{wlabel}*\n"
            f"Nobody bet on the winning pot — all bets have been refunded in full.\n\n"
            f"📊 /leaderboard | 👉 /bet to bet on next match"
        )

    # Post to group
    for chunk in safe_send(result):
        try:
            await app.bot.send_message(GROUP_CHAT_ID, chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Group result failed: {e}")

    # Build leaderboard after settlement
    await _post_leaderboard(app)

    # DM each bettor
    for w in summary["winners"]:
        try:
            await app.bot.send_message(
                w["tid"],
                f"🎉 *You won!* — {match['label']}\n\n"
                f"Picked: {pemoji(winner_pot)} *{wlabel}*\n"
                f"Bet: ₹{w['bet']:,.0f} | Payout: *₹{w['payout']:,.0f}* (+₹{w['profit']:,.0f})\n\n"
                f"📊 /leaderboard | 👉 /bet",
                parse_mode=ParseMode.MARKDOWN
            )
        except: pass
    for l in summary["losers"]:
        try:
            await app.bot.send_message(
                l["tid"],
                f"😔 *Better luck next time* — {match['label']}\n\n"
                f"You lost ₹{l['amount']:,.0f}\n\n"
                f"📊 /leaderboard | 👉 /bet",
                parse_mode=ParseMode.MARKDOWN
            )
        except: pass

async def _post_leaderboard(app):
    rows   = db.leaderboard()
    medals = ["🥇","🥈","🥉"]
    lines  = ["🏆 *Leaderboard — updated*\n"]
    placed = 0
    for i,r in enumerate(rows):
        if r["wagered"] == 0: continue
        px = medals[i] if i<3 else f"{i+1}."
        n  = r["net"]
        ns = f"*+₹{n:,.0f}* 📈" if n>0 else (f"*-₹{abs(n):,.0f}* 📉" if n<0 else "₹0 ➡️")
        lines.append(f"{px} {r['name']}  {ns}")
        placed += 1
    if not placed: return
    lines.append("\n_Net profit/loss, all settled matches_\n👉 /bet to keep going")
    try:
        await app.bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"LB post failed: {e}")

# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.first_name)
    await update.message.reply_text(
        f"👋 *Welcome {u.first_name}!*\n\n"
        f"⚽ This is the WC 2026 Bet Bot\n\n"
        f"*How it works:*\n"
        f"Each match has 3 pots — Team A, Draw, Team B\n"
        f"Put money in the pot you think wins\n"
        f"Winning pot splits the entire pool proportionally\n"
        f"2.5% house cut on total pool\n\n"
        f"*Example:*\n"
        f"Brazil pot: ₹3,000 | You put ₹1,000\n"
        f"Total pool: ₹5,000\n"
        f"Brazil wins → you get (1000÷3000)×4875 = *₹1,625*\n\n"
        f"*Commands:*\n"
        f"👉 /bet — place a bet\n"
        f"📋 /matches — next 5 fixtures\n"
        f"💰 /pool — live pot sizes\n"
        f"📊 /odds — crowd odds + team history\n"
        f"🏆 /leaderboard — standings\n"
        f"📖 /history — WC facts",
        parse_mode=ParseMode.MARKDOWN
    )

# ── Greeting handler ───────────────────────────────────────────────────────────

GREET = {"hi","hello","hey","sup","yo","hola","namaste","hii","heyy","wagwan"}

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u    = update.effective_user
    db.upsert_user(u.id, u.first_name)
    text = (update.message.text or "").strip().lower()

    # Group message — completely silent. Bot never interrupts conversations.
    if update.effective_chat.type != "private":
        return

    # DM only from here
    if any(g in text for g in GREET) or len(text.split()) <= 2:
        import random
        spicy = random.choice([
            f"Aye *{u.first_name}!* You here to chat or to WIN? 😤\n\n👉 /bet — put your money where your mouth is",
            f"*{u.first_name}* showing up with no bet placed yet 👀\nThe pool isn\'t going to fill itself!\n\n👉 /bet now",
            f"Oh look who it is 👋 *{u.first_name}*\nStill deciding which team to back? That\'s called being scared 😂\n\n👉 /bet",
            f"*{u.first_name}* has entered the chat ⚽\nBig talk, small bets. Let\'s change that 💪\n\n👉 /bet to prove yourself",
            f"Hey *{u.first_name}!* The bot doesn\'t sleep, the World Cup doesn\'t wait 🏆\n\n👉 /bet | 📋 /matches | 📊 /odds",
        ])
        await update.message.reply_text(spicy, parse_mode=ParseMode.MARKDOWN)
        return

    # Unknown text in DM
    await update.message.reply_text(
        f"Not sure what you mean *{u.first_name}* 🤔\n\n"
        f"👉 /bet — place a bet\n"
        f"📋 /matches — fixtures\n"
        f"❓ /help — all commands",
        parse_mode=ParseMode.MARKDOWN
    )

# ── /matches ───────────────────────────────────────────────────────────────────

async def cmd_matches(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.upsert_user(update.effective_user.id, update.effective_user.first_name)
    matches = db.open_matches(limit=5)
    if not matches:
        await update.message.reply_text(
            "No open matches right now. Check back soon! 🕐\n\n"
            "📊 /leaderboard | 📖 /history"
        )
        return
    lines = [f"🟢 *Next {len(matches)} matches*\n"]
    for m in matches:
        s = db.pool_summary(m["mid"])
        g = s["grand"]
        pool_str = f"₹{g:,.0f} in pot" if g>0 else "no bets yet"
        lines.append(f"*#{m['mid']}* {m['label']}")
        lines.append(f"  🕐 {ist(m['kickoff'])} | 💰 {pool_str}\n")
    lines.append("👉 /bet to place your bet")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ── BET FLOW ───────────────────────────────────────────────────────────────────
# /bet → match list (5, buttons) → team_a | draw | team_b → amount → confirm

async def cmd_bet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "🔒 *Place your bet privately!*\n\n"
            "Betting is done via DM so your pick stays 100% anonymous.\n\n"
            "👉 *Tap @UFC_wcbot* → then send /bet\n"
            "_Nobody in the group sees what you bet on._",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    db.upsert_user(update.effective_user.id, update.effective_user.first_name)
    await _show_matches(update, ctx, edit=False)

async def _show_matches(update, ctx, edit=False):
    matches = db.open_matches(limit=5)
    if not matches:
        txt = "No open matches right now! 🕐\n\n📋 /matches for upcoming schedule"
        if edit: await update.callback_query.edit_message_text(txt)
        else:    await update.message.reply_text(txt)
        return

    kb = []
    for m in matches:
        s        = db.pool_summary(m["mid"])
        pool_str = f"₹{s['grand']:,.0f}" if s["grand"]>0 else "no bets yet"
        kb.append([InlineKeyboardButton(
            f"⚽ {m['label']}  [{pool_str}]",
            callback_data=f"bm:{m['mid']}"
        )])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

    txt = (
        f"⚽ *Next {len(matches)} matches — tap to bet*\n"
        f"Pool sizes in brackets | 2.5% house cut"
    )
    mu = InlineKeyboardMarkup(kb)
    if edit: await update.callback_query.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=mu)
    else:    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=mu)

# Step 2 — match tapped → pick team

async def cb_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query; await q.answer()
    uid = update.effective_user.id
    mid = int(q.data.split(":")[1])
    m   = db.get_match(mid)

    if not m or m["status"] != "open":
        await q.edit_message_text("❌ Match no longer open.\n\n👉 /bet to see current matches")
        return

    s     = db.pool_summary(mid)
    grand = s["grand"]

    def pot_line(pk):
        tot = s["totals"][pk]; cnt = s["counts"][pk]
        b, pct = pbar(tot, grand)
        odds   = f"{grand/tot:.2f}x" if tot else "—"
        return f"{b} {pct:.0f}% | ₹{tot:,.0f} | {cnt} bets | {odds}"

    existing_bet = db.get_user_bet_on_match(uid, mid)

    # If user already has a bet on this match, only let them edit their existing pot
    if existing_bet:
        ep     = existing_bet
        elabel = db.plabel(m, ep["pot"])
        txt = (
            f"⚽ *{m['label']}*\n"
            f"🕐 {ist(m['kickoff'])}\n\n"
            f"✏️ *You already bet {pemoji(ep['pot'])} {elabel} — ₹{ep['amount']:,.0f}*\n"
            f"You can only edit the amount, not switch outcome.\n\n"
            f"Tap to change your amount:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✏️ Edit — {pemoji(ep['pot'])} {elabel}",
                callback_data=f"bp:{mid}:{ep['pot']}"
            )],
            [
                InlineKeyboardButton("← All matches", callback_data="goback"),
                InlineKeyboardButton("❌ Cancel",      callback_data="cancel"),
            ],
        ])
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    is_ko = not m["label"].startswith("Group")
    draw_label = "⚪ Goes to Pens / AET" if is_ko else "⚪ Draw"

    def pl(pot):
        tot = s["totals"].get(pot,0); cnt = s["counts"].get(pot,0)
        b, pct = pbar(tot, grand)
        odds = f"{grand/tot:.2f}x" if tot else "—"
        return f"{b} {pct:.0f}% | ₹{tot:,.0f} ({cnt}) | {odds}"

    txt = (
        f"⚽ *{m['label']}*\n"
        f"🕐 {ist(m['kickoff'])}\n\n"
        f"*Pool — ₹{grand:,.0f} total* _(anonymous)_\n"
        f"🔵 {m['team_a']} by 2+: {pl('team_a_2plus')}\n"
        f"🔵 {m['team_a']} by 1: {pl('team_a_by_1')}\n"
        f"⚪ {draw_label[2:]}: {pl('draw_pens')}\n"
        f"🔴 {m['team_b']} by 1: {pl('team_b_by_1')}\n"
        f"🔴 {m['team_b']} by 2+: {pl('team_b_2plus')}\n\n"
        f"*Pick your outcome:*"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔵 {m['team_a']} wins by 2+", callback_data=f"bp:{mid}:team_a_2plus")],
        [InlineKeyboardButton(f"🔵 {m['team_a']} wins by 1",  callback_data=f"bp:{mid}:team_a_by_1")],
        [InlineKeyboardButton(draw_label,                       callback_data=f"bp:{mid}:draw_pens")],
        [InlineKeyboardButton(f"🔴 {m['team_b']} wins by 1",  callback_data=f"bp:{mid}:team_b_by_1")],
        [InlineKeyboardButton(f"🔴 {m['team_b']} wins by 2+", callback_data=f"bp:{mid}:team_b_2plus")],
        [
            InlineKeyboardButton("← All matches", callback_data="goback"),
            InlineKeyboardButton("❌ Cancel",      callback_data="cancel"),
        ],
    ])
    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# Step 3 — pick tapped → amount

async def cb_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query; await q.answer()
    uid = update.effective_user.id
    _, mid_s, pot = q.data.split(":")
    mid  = int(mid_s)
    m    = db.get_match(mid)
    pick = db.plabel(m, pot)
    s    = db.pool_summary(mid)
    grand   = s["grand"]
    pot_tot = s["totals"].get(pot, 0.0)

    on_pot = db.get_user_bet_on_match(uid, mid)
    if on_pot and on_pot["pot"] != pot:
        on_pot = None  # different pot, treat as new
    edit_note = (
        f"\nYou already bet ₹{on_pot['amount']:,.0f} here — pick new amount to replace"
        if on_pot else ""
    )

    fact = get_team_fact(pick)
    fact_line = f"\n\n_{fact}_" if fact else ""

    txt = (
        f"{pemoji(pot)} *{pick}* — *{m['label']}*{edit_note}\n\n"
        f"*How much?* _(est. payout if {pick} wins)_\n"
        + "\n".join(
            f"  ₹{a:,} → est. *₹{est(a,pot_tot,grand):,.0f}*"
            for a in AMOUNTS
        )
        + fact_line
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("₹50",   callback_data=f"ba:{mid}:{pot}:50"),
            InlineKeyboardButton("₹100",  callback_data=f"ba:{mid}:{pot}:100"),
            InlineKeyboardButton("₹200",  callback_data=f"ba:{mid}:{pot}:200"),
        ],
        [
            InlineKeyboardButton("₹500",  callback_data=f"ba:{mid}:{pot}:500"),
            InlineKeyboardButton("₹1000", callback_data=f"ba:{mid}:{pot}:1000"),
        ],
        [
            InlineKeyboardButton("← Change pick", callback_data=f"bm:{mid}"),
            InlineKeyboardButton("❌ Cancel",      callback_data="cancel"),
        ],
    ])
    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# Step 4 — amount tapped → confirm

async def cb_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query; await q.answer()
    _, mid_s, pot, amt_s = q.data.split(":")
    mid    = int(mid_s)
    amount = float(amt_s)
    m      = db.get_match(mid)
    pick   = db.plabel(m, pot)
    s      = db.pool_summary(mid)
    pot_tot  = s["totals"][pot]
    grand    = s["grand"]
    new_pot  = pot_tot + amount
    new_grand= grand + amount
    ep       = est(amount, pot_tot, grand)

    txt = (
        f"🎯 *Confirm bet*\n\n"
        f"Match: *{m['label']}*\n"
        f"Pick:  {pemoji(pot)} *{pick}*\n"
        f"Bet:   *₹{amount:,.0f}*\n\n"
        f"If *{pick}* wins:\n"
        f"  Your share: ₹{amount:,.0f} of ₹{new_pot:,.0f}\n"
        f"  Total pool: ₹{new_grand:,.0f}\n"
        f"  Est. payout: *₹{ep:,.0f}*\n"
        f"  Est. profit: *+₹{ep-amount:,.0f}*\n"
        f"  _(2.5% house cut · odds shift as more bets come in)_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Confirm — {pemoji(pot)} {pick} for ₹{amount:,.0f}",
            callback_data=f"bc:{mid}:{pot}:{amount}"
        )],
        [
            InlineKeyboardButton("← Change amount", callback_data=f"bp:{mid}:{pot}"),
            InlineKeyboardButton("❌ Cancel",        callback_data="cancel"),
        ],
    ])
    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# Step 5 — confirmed

async def cb_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query; await q.answer()
    uid    = update.effective_user.id
    _, mid_s, pot, amt_s = q.data.split(":")
    mid    = int(mid_s)
    amount = float(amt_s)
    m      = db.get_match(mid)
    pick   = db.plabel(m, pot)

    logger.info(f"place_bet: uid={uid} mid={mid} pot={pot} amount={amount}")
    ok, msg = db.place_bet(uid, mid, pot, amount)
    logger.info(f"place_bet result: ok={ok} msg={msg}")
    if ok:
        action = "✏️ Updated" if msg=="updated" else "✅ Placed"
        s      = db.pool_summary(mid)
        tot    = s["totals"].get(pot, 0.0)
        g      = s["grand"]
        odds   = f"{g/tot:.2f}x" if tot else "—"
        await q.edit_message_text(
            f"{action}: {pemoji(pot)} *{pick}* — ₹{amount:,.0f}\n"
            f"Match: *{m['label']}*\n\n"
            f"*{pick} pot:* ₹{tot:,.0f} of ₹{g:,.0f} total\n"
            f"Implied odds: *{odds}*\n\n"
            f"🔒 Bets lock at kickoff\n"
            f"👉 /bet for another match\n"
            f"📋 /mybets to see all your bets\n"
            f"💰 /pool {mid} to track this match",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await q.edit_message_text(
            f"❌ {msg}\n\n👉 /bet to try again",
            parse_mode=ParseMode.MARKDOWN
        )

# ── Nav callbacks ──────────────────────────────────────────────────────────────

async def cb_goback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _show_matches(update, ctx, edit=True)

async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "❌ Cancelled.\n\n👉 /bet to start again | /matches to browse"
    )

# ── /pool ──────────────────────────────────────────────────────────────────────

async def cmd_pool(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        matches = db.open_matches(limit=5)
        if not matches:
            await update.message.reply_text("No open matches. 🕐\n\n👉 /bet | 📊 /leaderboard")
            return
        lines = ["💰 *Live pools — next 5 matches*\n"]
        for m in matches:
            s = db.pool_summary(m["mid"])
            g = s["grand"]
            if g == 0:
                lines.append(f"*#{m['mid']}* {m['label']} — no bets yet")
            else:
                ta=s["totals"]["team_a"]; dr=s["totals"]["draw"]; tb=s["totals"]["team_b"]
                lines.append(
                    f"*#{m['mid']}* {m['label']}\n"
                    f"  🔵₹{ta:,.0f} ⚪₹{dr:,.0f} 🔴₹{tb:,.0f} | Total ₹{g:,.0f}"
                )
        lines.append("\n`/pool <id>` for full breakdown\n👉 /bet to place a bet")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    try: mid = int(ctx.args[0])
    except:
        await update.message.reply_text("❌ Use: /pool 5\n\n👉 /bet | 📋 /matches"); return

    s = db.pool_summary(mid)
    if not s:
        await update.message.reply_text(f"❌ Match #{mid} not found.\n\n📋 /matches"); return

    m=s["match"]; g=s["grand"]
    lines = [
        f"💰 *{m['label']}*",
        f"🕐 {ist(m['kickoff'])}",
        f"",
        f"*Total: ₹{g:,.0f}* _(anonymous)_\n",
    ]
    for pk,label,emoji in [("team_a",m["team_a"],"🔵"),("draw","Draw","⚪"),("team_b",m["team_b"],"🔴")]:
        tot=s["totals"][pk]; cnt=s["counts"][pk]
        b,pct=pbar(tot,g)
        odds=f"{g/tot:.2f}x" if tot else "—"
        lines.append(f"{emoji} *{label}*: {b} {pct:.0f}% | ₹{tot:,.0f} | {cnt} bets | {odds}")
    note={"open":"🟢 Bets open","locked":"🔒 Bets locked","settled":f"✅ {plabel(m,m['winner'])} won"}
    lines.append(f"\n{note.get(m['status'],'')}")
    lines.append(f"\n/odds {mid} — names per pot + team history\n👉 /bet to place a bet")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ── /odds ──────────────────────────────────────────────────────────────────────

async def cmd_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        # Auto-show odds for the next upcoming match
        upcoming = db.open_matches(limit=1)
        if not upcoming:
            await update.message.reply_text(
                "No open matches right now.\n\n📋 /matches | 👉 /bet"
            )
            return
        mid = upcoming[0]["mid"]
    else:
        try: mid = int(ctx.args[0])
        except:
            await update.message.reply_text("❌ Number only. e.g. /odds 5\n\n📋 /matches"); return

    m = db.get_match(mid)
    if not m:
        await update.message.reply_text(f"❌ Match #{mid} not found.\n\n📋 /matches"); return

    s = db.pool_summary(mid); g = s["grand"]

    # Part 1 — odds
    msg1_lines = [f"📊 *{m['label']} — Odds*\n"]
    if g == 0:
        msg1_lines.append("No bets yet — be first!\n")
    else:
        msg1_lines.append(f"*Pool: ₹{g:,.0f}*\n")
        for pk,label,emoji in [("team_a",m["team_a"],"🔵"),("draw","Draw","⚪"),("team_b",m["team_b"],"🔴")]:
            tot=s["totals"][pk]; cnt=s["counts"][pk]
            b,pct=pbar(tot,g)
            odds=f"{g/tot:.2f}x" if tot else "—"
            bettors=db.pot_bettors(mid,pk)
            names=", ".join(b["name"] for b in bettors) if bettors else "nobody yet"
            msg1_lines.append(f"{emoji} *{label}*: {b} {pct:.0f}% | {odds}")
            if update.effective_chat.type == "private":
                msg1_lines.append(f"  Backed by: {names}\n")
            else:
                msg1_lines.append(f"  {len(bettors)} bettor(s)\n")
        best=max(s["totals"],key=s["totals"].get)
        msg1_lines.append(f"_Crowd favours *{plabel(m,best)}* right now._")

    await update.message.reply_text("\n".join(msg1_lines), parse_mode=ParseMode.MARKDOWN)

    # Part 2 — team facts + h2h (separate message, safe length)
    fa  = get_team_fact(m["team_a"])
    fb  = get_team_fact(m["team_b"])
    h2h = get_h2h(m["team_a"], m["team_b"])
    msg2_lines = [f"📖 *{m['label']} — History*\n"]
    if fa: msg2_lines.append(fa + "\n")
    if fb: msg2_lines.append(fb + "\n")
    if h2h: msg2_lines.append(f"*Head to Head:*\n{h2h}\n")
    msg2_lines.append("👉 /bet to place your bet")
    await update.message.reply_text("\n".join(msg2_lines), parse_mode=ParseMode.MARKDOWN)

# ── /mybets ────────────────────────────────────────────────────────────────────

async def cmd_mybets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "Your bets are private!\n\nDM @UFC_wcbot and use /mybets",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    u = update.effective_user
    db.upsert_user(u.id, u.first_name)
    bets = db.user_bet_history(u.id)
    if not bets:
        await update.message.reply_text("No bets yet!\n\n👉 /bet to get started ⚽")
        return
    icons = {"pending":"⏳","won":"✅","lost":"❌"}
    lines = [f"📋 *{u.first_name}'s bets*\n"]
    for b in bets:
        m_   = db.get_match(b["mid"])
        pick = plabel(m_, b["pot"]) if m_ else b["pot"]
        icon = icons.get(b["status"],"❓")
        line = f"{icon} *{b['label']}*\n  {pemoji(b['pot'])} {pick} — ₹{b['amount']:,.0f}"
        if b["status"]=="won":
            profit=b["payout"]-b["amount"]
            line+=f"  → ₹{b['payout']:,.0f} (*+₹{profit:,.0f}*) 🎉"
        elif b["status"]=="lost":
            line+=f"  → *-₹{b['amount']:,.0f}* 😔"
        else:
            line+="  → ⏳ Awaiting kickoff"
        lines.append(line+"\n")
    lines.append("👉 /bet to place another | 🏆 /leaderboard")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ── /leaderboard ───────────────────────────────────────────────────────────────

async def cmd_lb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows   = db.leaderboard()
    medals = ["🥇", "🥈", "🥉"]
    out    = ["🏆 *WC 2026 Leaderboard*\n"]
    placed = 0
    for i, r in enumerate(rows):
        if r["wagered"] == 0: continue
        px  = medals[i] if i < 3 else str(i+1) + "."
        n   = r["net"]
        mb  = r["matches_bet"]
        w   = r["wins"]
        wp  = round((w / mb) * 100) if mb > 0 else 0
        pnl = ("*+₹" + "{:,.0f}".format(n) + "* 📈") if n > 0 else (("*-₹" + "{:,.0f}".format(abs(n)) + "* 📉") if n < 0 else "₹0 ➡")
        bar = ("🟩" * int(wp/20)) + ("⬜" * (5 - int(wp/20)))
        out.append(px + " *" + r["name"] + "*")
        out.append("   " + pnl + "  |  " + str(mb) + " match(es)  |  " + bar + " " + str(wp) + "% win")
        out.append("")
        placed += 1
    if not placed:
        await update.message.reply_text("No settled bets yet!\n\n/bet to place a bet")
        return
    out.append("_Net P&L | matches bet | win % -- all settled_")
    out.append("/bet to keep going")
    await update.message.reply_text("\n".join(out), parse_mode=ParseMode.MARKDOWN)

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WC_FACTS + "\n\n📊 /odds <id> for match history\n👉 /bet to place a bet",
        parse_mode=ParseMode.MARKDOWN
    )

# ── /help ──────────────────────────────────────────────────────────────────────


async def cmd_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Last 5 WC 2026 match results with scores from API."""
    db.upsert_user(update.effective_user.id, update.effective_user.first_name)
    import requests as _req
    key = os.getenv("FOOTBALL_API_KEY", "")
    if not key:
        await update.message.reply_text("Results unavailable. Use /matches for upcoming fixtures.")
        return
    try:
        r = _req.get(
            "https://api.football-data.org/v4/competitions/2000/matches",
            headers={"X-Auth-Token": key},
            params={"status": "FINISHED"},
            timeout=10
        )
        if r.status_code != 200:
            await update.message.reply_text("Could not fetch results right now. Try again shortly.")
            return
        all_matches = r.json().get("matches", [])
        if not all_matches:
            await update.message.reply_text("No finished matches yet. Use /matches for upcoming fixtures.")
            return
        last5 = all_matches[-5:]
        lines = ["*Last 5 WC 2026 Results*", ""]
        for m in reversed(last5):
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            gh   = m["score"]["fullTime"]["home"]
            ga   = m["score"]["fullTime"]["away"]
            date = m["utcDate"][5:10].replace("-", "/")
            if gh > ga:
                line = f"*{home}* {gh}-{ga} {away}"
                icon = "🏆"
            elif ga > gh:
                line = f"{home} {gh}-{ga} *{away}*"
                icon = "🏆"
            else:
                line = f"{home} {gh}-{ga} {away}"
                icon = "🤝"
            lines.append(f"{icon} {date}:  {line}")
        lines.append("")
        lines.append("👉 /bet to place bets on upcoming matches")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"Results fetch error: {e}")
        await update.message.reply_text("Could not fetch results. Try again shortly.")


async def cmd_topscorers(update, ctx):
    db.upsert_user(update.effective_user.id, update.effective_user.first_name)
    import requests as req
    key = os.getenv("FOOTBALL_API_KEY","")
    if not key:
        await update.message.reply_text("Football API not configured."); return
    try:
        r = req.get("https://api.football-data.org/v4/competitions/2000/scorers?limit=10",
                    headers={"X-Auth-Token": key}, timeout=10)
        scorers = r.json().get("scorers", [])
        if not scorers:
            await update.message.reply_text("No scorers yet - check back after more matches!"); return
        medals = ["1st", "2nd", "3rd"]
        lines = ["*WC 2026 Golden Boot Race*\n"]
        for i, s in enumerate(scorers[:10]):
            px = medals[i] if i < 3 else str(i+1)+"."
            name = s["player"]["name"]
            team = s["team"]["name"]
            goals = s.get("goals",0) or 0
            assists = s.get("assists",0) or 0
            lines.append(px + " *" + name + "* (" + team + ")")
            lines.append("   " + str(goals) + " goals | " + str(assists) + " assists\n")
        lines.append("👉 /bet  |  /standings  |  /history")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error("Topscorers: " + str(e))
        await update.message.reply_text("Could not fetch top scorers. Try again soon!")


async def cmd_h2h(update, ctx):
    db.upsert_user(update.effective_user.id, update.effective_user.first_name)
    if not ctx.args:
        matches = db.open_matches(limit=1)
        if not matches:
            await update.message.reply_text("Usage: /h2h <match_id>  e.g. /h2h 9"); return
        mid = matches[0]["mid"]
    else:
        try: mid = int(ctx.args[0])
        except:
            await update.message.reply_text("Use: /h2h 9  |  /matches for IDs"); return
    m = db.get_match(mid)
    if not m:
        await update.message.reply_text("Match not found."); return
    import requests as req
    key = os.getenv("FOOTBALL_API_KEY","")
    from facts import get_h2h as fact_h2h, get_team_fact
    lines = ["*" + m["label"] + " - Head to Head*\n"]
    h2h_fact = fact_h2h(m["team_a"], m["team_b"])
    if h2h_fact:
        lines.append("*Historic rivalry:*\n" + h2h_fact + "\n")
    fa = get_team_fact(m["team_a"])
    fb = get_team_fact(m["team_b"])
    if fa: lines.append(fa + "\n")
    if fb: lines.append(fb + "\n")
    if key:
        try:
            r = req.get("https://api.football-data.org/v4/competitions/2000/matches",
                        headers={"X-Auth-Token": key},
                        params={"status": "FINISHED"}, timeout=10)
            finished = r.json().get("matches", [])
            meetings = []
            for fm in finished:
                home = fm["homeTeam"]["name"]
                away = fm["awayTeam"]["name"]
                ta = m["team_a"].lower()
                tb = m["team_b"].lower()
                if (ta in home.lower() or ta in away.lower()) and \
                   (tb in home.lower() or tb in away.lower()):
                    gh = fm["score"]["fullTime"]["home"] or 0
                    ga = fm["score"]["fullTime"]["away"] or 0
                    meetings.append("  WC 2026: " + home + " " + str(gh) + "-" + str(ga) + " " + away)
            if meetings:
                lines.append("*This tournament:*\n" + "\n".join(meetings) + "\n")
        except Exception as e:
            logger.warning("H2H API: " + str(e))
    lines.append("/pool " + str(mid) + "  |  /odds " + str(mid))
    lines.append("👉 /bet to place your bet")
    full = "\n".join(lines)
    if len(full) > 4000:
        split = full[:4000].rfind("\n\n")
        await update.message.reply_text(full[:split], parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(full[split:], parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(full, parse_mode=ParseMode.MARKDOWN)



async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (
        "⚽ *WC 2026 Bet Bot — Commands*\n\n"
        "/bet — place a bet (button flow)\n"
        "/matches — next 5 open fixtures\n"
        "/results — last 5 match scores\n"
        "/pool — live pot sizes overview\n"
        "/pool `<id>` — detailed pool for one match\n"
        "/odds `<id>` — crowd odds + who backed whom + team history\n"
        "/mybets — your bets and results\n"
        "/leaderboard — net profit/loss standings\n"
        "/history — WC records and fun facts\n\n"
        "*Bet flow:*\n"
        "Tap match → 🔵 Team A | ⚪ Draw | 🔴 Team B → ₹50/100/200/500/1000 → confirm\n\n"
        "*Rules:*\n"
        "Winning pot splits entire pool proportionally\n"
        "2.5% house cut | bets lock at kickoff | editable before\n"
        "Bets are anonymous — only names shown in /odds, not amounts\n\n"
        "👉 /bet to start!"
    )
    if is_admin(update.effective_user.id):
        txt += (
            "\n\n*Admin:*\n"
            "/settle `<id> <team_a|team_b|draw>`\n"
            "/halftime `<id>`\n"
            "/lockmatch `<id>`\n"
            "/addmatch `TeamA vs TeamB YYYY-MM-DDTHH:MM`\n"
        )
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

# ── Admin: /settle ─────────────────────────────────────────────────────────────

async def cmd_settle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only."); return
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: /settle <id> <team_a|team_b|draw>"); return
    try: mid = int(ctx.args[0])
    except:
        await update.message.reply_text("❌ Invalid ID."); return
    m = db.get_match(mid)
    if not m:
        await update.message.reply_text("❌ Not found."); return
    if m["status"]=="settled":
        await update.message.reply_text("⚠️ Already settled."); return
    raw = ctx.args[1].strip().lower()
    if raw in ("team_a","team_b","draw"):   wpot=raw
    elif raw in m["team_a"].lower():        wpot="team_a"
    elif raw in m["team_b"].lower():        wpot="team_b"
    else:
        await update.message.reply_text("❌ Use team_a, team_b, or draw."); return
    await do_settle(ctx.application, m, wpot)
    await update.message.reply_text(f"✅ Match #{mid} settled. Results posted.")

# ── Admin: /halftime ───────────────────────────────────────────────────────────

async def cmd_halftime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only."); return
    if not ctx.args:
        await update.message.reply_text("Usage: /halftime <id>"); return
    try: mid=int(ctx.args[0])
    except:
        await update.message.reply_text("❌ Invalid ID."); return
    m=db.get_match(mid)
    if not m:
        await update.message.reply_text("❌ Not found."); return
    s=db.pool_summary(mid); g=s["grand"]
    lines=[f"⏱ *Half Time — {m['label']}*\n",f"Pool: *₹{g:,.0f}*\n"]
    for pk,label,emoji in [("team_a",m["team_a"],"🔵"),("draw","Draw","⚪"),("team_b",m["team_b"],"🔴")]:
        tot=s["totals"][pk]; cnt=s["counts"][pk]
        b,pct=pbar(tot,g); odds=f"{g/tot:.2f}x" if tot else "—"
        lines.append(f"{emoji} *{label}*: {b} {pct:.0f}% | ₹{tot:,.0f} | {cnt} | {odds}")
    lines.append("\n_Bets locked. Full result at full time._\n👉 /bet to bet on next match")
    txt="\n".join(lines)
    try:
        await ctx.bot.send_message(GROUP_CHAT_ID,txt,parse_mode=ParseMode.MARKDOWN)
        db.lock_match(mid)
    except Exception as e: logger.warning(f"HT failed: {e}")
    await update.message.reply_text("✅ Halftime sent to group.")

# ── Admin: /addmatch ───────────────────────────────────────────────────────────

async def cmd_addmatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only."); return
    raw=" ".join(ctx.args)
    try:
        parts=re.split(r"\s+vs\s+",raw,flags=re.IGNORECASE)
        if len(parts)!=2: raise ValueError
        team_a=parts[0].strip()
        rest=parts[1].strip().split()
        ko=rest[-1]; team_b=" ".join(rest[:-1]).strip()
        datetime.fromisoformat(ko)
        mid=db.add_match(f"{team_a} vs {team_b}",team_a,team_b,ko)
        await update.message.reply_text(
            f"✅ Match #{mid}: {team_a} vs {team_b}\n{ist(ko)}",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Format: /addmatch Brazil vs Argentina 2026-06-15T18:00")

# ── Admin: /lockmatch ──────────────────────────────────────────────────────────

async def cmd_lock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only."); return
    if not ctx.args:
        await update.message.reply_text("Usage: /lockmatch <id>"); return
    try:
        m=db.get_match(int(ctx.args[0]))
        if not m: raise ValueError
    except:
        await update.message.reply_text("❌ Not found."); return
    db.lock_match(m["mid"])
    try:
        await ctx.bot.send_message(
            GROUP_CHAT_ID,
            f"🔒 *Bets closed — {m['label']}!*\nKickoff imminent. Good luck! 🍀",
            parse_mode=ParseMode.MARKDOWN
        )
    except: pass
    await update.message.reply_text(f"🔒 Locked: {m['label']}")

# ── Error handler ──────────────────────────────────────────────────────────────

async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {ctx.error}", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        # Only show error in DM — never interrupt group conversations
        if update.effective_chat and update.effective_chat.type == "private":
            await update.effective_message.reply_text(
                "⚠️ Something went wrong. Try again.\n\n👉 /bet to restart"
            )

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    db.init()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("matches",     cmd_matches))
    app.add_handler(CommandHandler("bet",         cmd_bet))
    app.add_handler(CommandHandler("pool",        cmd_pool))
    app.add_handler(CommandHandler("odds",        cmd_odds))
    app.add_handler(CommandHandler("mybets",      cmd_mybets))
    app.add_handler(CommandHandler("leaderboard", cmd_lb))
    app.add_handler(CommandHandler("history",     cmd_history))
    app.add_handler(CommandHandler("results",     cmd_results))
    app.add_handler(CommandHandler("topscorers",  cmd_topscorers))
    app.add_handler(CommandHandler("h2h",         cmd_h2h))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("settle",      cmd_settle))
    app.add_handler(CommandHandler("halftime",    cmd_halftime))
    app.add_handler(CommandHandler("addmatch",    cmd_addmatch))
    app.add_handler(CommandHandler("lockmatch",   cmd_lock))

    app.add_handler(CallbackQueryHandler(cb_goback,  pattern=r"^goback$"))
    app.add_handler(CallbackQueryHandler(cb_match,   pattern=r"^bm:"))
    app.add_handler(CallbackQueryHandler(cb_pick,    pattern=r"^bp:"))
    app.add_handler(CallbackQueryHandler(cb_amount,  pattern=r"^ba:"))
    app.add_handler(CallbackQueryHandler(cb_confirm, pattern=r"^bc:"))
    app.add_handler(CallbackQueryHandler(cb_cancel,  pattern=r"^cancel$"))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text
    ))
    app.add_error_handler(on_error)

    if GROUP_CHAT_ID:
        sched.set_bot(app, GROUP_CHAT_ID, settle_fn=do_settle)
    sched.make_scheduler().start()

    logger.info("WC Bet Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()