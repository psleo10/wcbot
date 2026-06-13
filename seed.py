"""
seed.py — Load WC 2026 group stage fixtures
Run once: python3 seed.py
"""
from datetime import datetime, timezone
import db

db.init()

with db.get_conn() as c:
    c.execute("DELETE FROM bets")
    c.execute("DELETE FROM matches")
    try:
        c.execute("DELETE FROM sqlite_sequence WHERE name='matches'")
        c.execute("DELETE FROM sqlite_sequence WHERE name='bets'")
    except: pass
print("Cleared old data.")

MATCHES = [
    ("Group A: Mexico vs South Africa",     "Mexico",       "South Africa",  "2026-06-11T19:00"),
    ("Group A: South Korea vs Czechia",      "South Korea",  "Czechia",       "2026-06-12T02:00"),
    ("Group B: Canada vs Bosnia",            "Canada",       "Bosnia",        "2026-06-12T19:00"),
    ("Group D: USA vs Paraguay",             "USA",          "Paraguay",      "2026-06-13T01:00"),
    ("Group B: Qatar vs Switzerland",        "Qatar",        "Switzerland",   "2026-06-13T19:00"),
    ("Group C: Brazil vs Morocco",           "Brazil",       "Morocco",       "2026-06-13T22:00"),
    ("Group C: Haiti vs Scotland",           "Haiti",        "Scotland",      "2026-06-14T01:00"),
    ("Group D: Australia vs Turkiye",        "Australia",    "Turkiye",       "2026-06-14T04:00"),
    ("Group E: Germany vs Curacao",          "Germany",      "Curacao",       "2026-06-14T17:00"),
    ("Group F: Netherlands vs Japan",        "Netherlands",  "Japan",         "2026-06-14T20:00"),
    ("Group E: Ivory Coast vs Ecuador",      "Ivory Coast",  "Ecuador",       "2026-06-14T23:00"),
    ("Group F: Sweden vs Tunisia",           "Sweden",       "Tunisia",       "2026-06-15T02:00"),
    ("Group H: Spain vs Cape Verde",         "Spain",        "Cape Verde",    "2026-06-15T16:00"),
    ("Group G: Belgium vs Egypt",            "Belgium",      "Egypt",         "2026-06-15T19:00"),
    ("Group H: Saudi Arabia vs Uruguay",     "Saudi Arabia", "Uruguay",       "2026-06-15T22:00"),
    ("Group G: Iran vs New Zealand",         "Iran",         "New Zealand",   "2026-06-16T01:00"),
    ("Group I: France vs Senegal",           "France",       "Senegal",       "2026-06-16T19:00"),
    ("Group I: Iraq vs Norway",              "Iraq",         "Norway",        "2026-06-16T22:00"),
    ("Group J: Argentina vs Algeria",        "Argentina",    "Algeria",       "2026-06-17T01:00"),
    ("Group J: Austria vs Jordan",           "Austria",      "Jordan",        "2026-06-17T04:00"),
    ("Group K: Portugal vs DR Congo",        "Portugal",     "DR Congo",      "2026-06-17T17:00"),
    ("Group L: England vs Croatia",          "England",      "Croatia",       "2026-06-17T20:00"),
    ("Group L: Ghana vs Panama",             "Ghana",        "Panama",        "2026-06-17T23:00"),
    ("Group K: Uzbekistan vs Colombia",      "Uzbekistan",   "Colombia",      "2026-06-18T02:00"),
    ("Group A: Czechia vs South Africa",     "Czechia",      "South Africa",  "2026-06-18T16:00"),
    ("Group B: Switzerland vs Bosnia",       "Switzerland",  "Bosnia",        "2026-06-18T19:00"),
    ("Group B: Canada vs Qatar",             "Canada",       "Qatar",         "2026-06-18T22:00"),
    ("Group A: Mexico vs South Korea",       "Mexico",       "South Korea",   "2026-06-19T01:00"),
    ("Group D: USA vs Australia",            "USA",          "Australia",     "2026-06-19T19:00"),
    ("Group C: Scotland vs Morocco",         "Scotland",     "Morocco",       "2026-06-19T22:00"),
    ("Group C: Brazil vs Haiti",             "Brazil",       "Haiti",         "2026-06-20T00:30"),
    ("Group D: Turkiye vs Paraguay",         "Turkiye",      "Paraguay",      "2026-06-20T03:00"),
    ("Group F: Netherlands vs Sweden",       "Netherlands",  "Sweden",        "2026-06-20T17:00"),
    ("Group E: Germany vs Ivory Coast",      "Germany",      "Ivory Coast",   "2026-06-20T20:00"),
    ("Group E: Ecuador vs Curacao",          "Ecuador",      "Curacao",       "2026-06-21T03:00"),
    ("Group F: Tunisia vs Japan",            "Tunisia",      "Japan",         "2026-06-21T04:00"),
    ("Group H: Spain vs Saudi Arabia",       "Spain",        "Saudi Arabia",  "2026-06-21T16:00"),
    ("Group G: Belgium vs Iran",             "Belgium",      "Iran",          "2026-06-21T19:00"),
    ("Group H: Uruguay vs Cape Verde",       "Uruguay",      "Cape Verde",    "2026-06-21T22:00"),
    ("Group G: New Zealand vs Egypt",        "New Zealand",  "Egypt",         "2026-06-22T01:00"),
    ("Group J: Argentina vs Austria",        "Argentina",    "Austria",       "2026-06-22T17:00"),
    ("Group I: France vs Iraq",              "France",       "Iraq",          "2026-06-22T21:00"),
    ("Group I: Norway vs Senegal",           "Norway",       "Senegal",       "2026-06-23T00:00"),
    ("Group J: Jordan vs Algeria",           "Jordan",       "Algeria",       "2026-06-23T03:00"),
    ("Group K: Portugal vs Uzbekistan",      "Portugal",     "Uzbekistan",    "2026-06-23T17:00"),
    ("Group L: England vs Ghana",            "England",      "Ghana",         "2026-06-23T20:00"),
    ("Group L: Panama vs Croatia",           "Panama",       "Croatia",       "2026-06-23T23:00"),
    ("Group K: Colombia vs DR Congo",        "Colombia",     "DR Congo",      "2026-06-24T02:00"),
    ("Group B: Switzerland vs Canada",       "Switzerland",  "Canada",        "2026-06-24T19:00"),
    ("Group B: Bosnia vs Qatar",             "Bosnia",       "Qatar",         "2026-06-24T19:00"),
    ("Group C: Scotland vs Brazil",          "Scotland",     "Brazil",        "2026-06-24T22:00"),
    ("Group C: Morocco vs Haiti",            "Morocco",      "Haiti",         "2026-06-24T22:00"),
    ("Group A: Czechia vs Mexico",           "Czechia",      "Mexico",        "2026-06-25T01:00"),
    ("Group A: South Africa vs South Korea", "South Africa", "South Korea",   "2026-06-25T01:00"),
    ("Group E: Ecuador vs Germany",          "Ecuador",      "Germany",       "2026-06-25T20:00"),
    ("Group E: Curacao vs Ivory Coast",      "Curacao",      "Ivory Coast",   "2026-06-25T20:00"),
    ("Group F: Japan vs Sweden",             "Japan",        "Sweden",        "2026-06-25T23:00"),
    ("Group F: Tunisia vs Netherlands",      "Tunisia",      "Netherlands",   "2026-06-25T23:00"),
    ("Group D: Turkiye vs USA",              "Turkiye",      "USA",           "2026-06-26T02:00"),
    ("Group D: Paraguay vs Australia",       "Paraguay",     "Australia",     "2026-06-26T02:00"),
    ("Group I: Norway vs France",            "Norway",       "France",        "2026-06-26T19:00"),
    ("Group I: Senegal vs Iraq",             "Senegal",      "Iraq",          "2026-06-26T19:00"),
    ("Group H: Cape Verde vs Saudi Arabia",  "Cape Verde",   "Saudi Arabia",  "2026-06-27T00:00"),
    ("Group H: Uruguay vs Spain",            "Uruguay",      "Spain",         "2026-06-27T00:00"),
    ("Group G: Egypt vs Belgium",            "Egypt",        "Belgium",       "2026-06-27T19:00"),
    ("Group G: New Zealand vs Iran",         "New Zealand",  "Iran",          "2026-06-27T19:00"),
    ("Group J: Algeria vs Austria",          "Algeria",      "Austria",       "2026-06-27T23:00"),
    ("Group J: Jordan vs Argentina",         "Jordan",       "Argentina",     "2026-06-27T23:00"),
    ("Group K: DR Congo vs Portugal",        "DR Congo",     "Portugal",      "2026-06-28T02:00"),
    ("Group K: Colombia vs Uzbekistan",      "Colombia",     "Uzbekistan",    "2026-06-28T02:00"),
    ("Group L: Croatia vs England",          "Croatia",      "England",       "2026-06-28T02:00"),
    ("Group L: Panama vs Ghana",             "Panama",       "Ghana",         "2026-06-28T02:00"),
    # Knockouts
    ("R32 Match 1",  "TBD","TBD","2026-06-28T19:00"),
    ("R32 Match 2",  "TBD","TBD","2026-06-28T23:00"),
    ("R32 Match 3",  "TBD","TBD","2026-06-29T19:00"),
    ("R32 Match 4",  "TBD","TBD","2026-06-29T23:00"),
    ("R32 Match 5",  "TBD","TBD","2026-06-30T19:00"),
    ("R32 Match 6",  "TBD","TBD","2026-06-30T23:00"),
    ("R32 Match 7",  "TBD","TBD","2026-07-01T19:00"),
    ("R32 Match 8",  "TBD","TBD","2026-07-01T23:00"),
    ("R32 Match 9",  "TBD","TBD","2026-07-02T19:00"),
    ("R32 Match 10", "TBD","TBD","2026-07-02T23:00"),
    ("R32 Match 11", "TBD","TBD","2026-07-03T19:00"),
    ("R32 Match 12", "TBD","TBD","2026-07-03T23:00"),
    ("R16 Match 1",  "TBD","TBD","2026-07-04T19:00"),
    ("R16 Match 2",  "TBD","TBD","2026-07-04T23:00"),
    ("R16 Match 3",  "TBD","TBD","2026-07-05T19:00"),
    ("R16 Match 4",  "TBD","TBD","2026-07-05T23:00"),
    ("R16 Match 5",  "TBD","TBD","2026-07-06T19:00"),
    ("R16 Match 6",  "TBD","TBD","2026-07-06T23:00"),
    ("R16 Match 7",  "TBD","TBD","2026-07-07T19:00"),
    ("R16 Match 8",  "TBD","TBD","2026-07-07T23:00"),
    ("QF 1", "TBD","TBD","2026-07-09T19:00"),
    ("QF 2", "TBD","TBD","2026-07-09T23:00"),
    ("QF 3", "TBD","TBD","2026-07-10T19:00"),
    ("QF 4", "TBD","TBD","2026-07-11T23:00"),
    ("Semi Final 1", "TBD","TBD","2026-07-14T23:00"),
    ("Semi Final 2", "TBD","TBD","2026-07-15T23:00"),
    ("3rd Place",    "TBD","TBD","2026-07-18T23:00"),
    ("World Cup Final 2026","TBD","TBD","2026-07-19T19:00"),
]

now    = datetime.now(timezone.utc)
added  = 0
locked = 0
for label,ta,tb,ko in MATCHES:
    mid = db.add_match(label,ta,tb,ko)
    dt  = datetime.fromisoformat(ko).replace(tzinfo=timezone.utc)
    if dt <= now:
        db.lock_match(mid)
        locked += 1
    else:
        added += 1
    print(f"  {'🔒' if dt<=now else '✅'} #{mid}: {label} ({ko} UTC)")

print(f"\n🎉 {added+locked} matches loaded ({locked} auto-locked, {added} open)")
print("Run: python3 bot.py")
