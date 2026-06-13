"""
facts.py — Football knowledge base
Short facts safe for Telegram (no markdown issues).
"""

TEAM_FACTS = {
    "brazil":       "🇧🇷 Brazil — 5× World Champions (1958,62,70,94,2002). Pelé won 3. Ronaldo scored 8 WC goals. Most WC appearances of any nation.",
    "argentina":    "🇦🇷 Argentina — 3× champions (1978,86,2022). Maradona's Hand of God + Goal of the Century both in 1986 vs England. Messi finally won in Qatar 2022.",
    "france":       "🇫🇷 France — 2× champions (1998,2018). Mbappé scored a hat-trick in 2022 final and still lost. Zidane headbutted Materazzi in 2006 final.",
    "germany":      "🇩🇪 Germany — 4× champions (1954,74,90,2014). The 7-1 vs Brazil in 2014 semi is the greatest upset ever. Klose holds all-time record: 16 goals.",
    "england":      "🏴󠁧󠁢󠁥󠁮󠁧󠁿 England — 1966 only title, at home. Geoff Hurst's hat-trick in the final is still the only one in WC history. Still waiting since.",
    "spain":        "🇪🇸 Spain — 2010 champions. Tiki-taka era with Xavi and Iniesta was football perfection. Iniesta scored the winner in extra time of the final.",
    "portugal":     "🇵🇹 Portugal — Never won. Eusébio (9 goals, 1966) was the golden era. Ronaldo has scored in 5 World Cups. Still chasing that title.",
    "netherlands":  "🇳🇱 Netherlands — 3 finals (1974,78,2010), never won. Total Football with Johan Cruyff changed the game. Robben missed crucial chance in 2010.",
    "italy":        "🇮🇹 Italy — 4× champions (1934,38,82,2006). Baggio's missed penalty in 1994 is one of football's saddest moments. Cannavaro lifted it in 2006.",
    "uruguay":      "🇺🇾 Uruguay — First ever champions in 1930. 3.5M people, 2 titles. Suárez handball vs Ghana in 2010 QF remains the most controversial moment ever.",
    "usa":          "🇺🇸 USA — Hosting 2026 alongside Canada and Mexico. Biggest WC ever: 48 teams. Pulisic leads this generation.",
    "mexico":       "🇲🇽 Mexico — 7 straight R16 exits. Hugo Sánchez was the 80s legend. Hosting 2026. Desperate to finally go further.",
    "japan":        "🇯🇵 Japan — Beat Germany AND Spain in Qatar 2022 group stage. First Asian team in QF (2002). Left the dressing room spotless after every match.",
    "south korea":  "🇰🇷 South Korea — 4th place in 2002 on home soil. Son Heung-min is their star. Park Ji-sung was first Asian to win the Premier League.",
    "morocco":      "🇲🇦 Morocco — 4th place in Qatar 2022, first African nation in WC semis. Bounou saved 2 penalties in the QF shootout. Whole Arab world cheered.",
    "senegal":      "🇸🇳 Senegal — QF in 2002. AFCON winners 2022 with Mané. Beat Poland 2-1 in 2018 group stage. Always dangerous.",
    "australia":    "🇦🇺 Australia — QF in 2006 with Kewell. Leckie's solo run vs Denmark in 2022 R16 was stunning. Strong Asian football tradition.",
    "croatia":      "🇭🇷 Croatia — Runners up 2018. Modric won Golden Ball. 3rd place in 2022. Tiny country with world class talent every generation.",
    "draw":         "⚪ Draw — In WC group stage ~24% of matches are draws. In knockouts a draw means 30 mins extra time then penalties. High risk, high reward pot.",
}

HEAD_TO_HEAD = {
    ("brazil","argentina"):   "🔥 El Clásico of South America. All-time: Brazil leads 36-26 (17 draws). Last WC meeting: 2007 Copa América, Brazil won 3-0.",
    ("france","germany"):     "⚔️ European giants. France leads 12-7 (3 draws) in competitive games. France knocked out Germany in Euro 2020 group stage.",
    ("england","germany"):    "Historic rivalry. Germany leads overall. England won 4-2 in 1966 WC final. Germany knocked England out in 2010 R16 (4-1).",
    ("brazil","france"):      "France beat Brazil 3-0 in 1998 QF on home soil — one of the biggest upsets. Ronaldo mysteriously ill before the match.",
    ("argentina","france"):   "2022 WC Final — one of the greatest ever. 3-3 AET. Argentina won on penalties. Mbappé hat-trick wasn't enough.",
    ("spain","germany"):      "Spain beat Germany 1-0 in 2010 WC semi. Puyol header. Spain went on to win the whole thing.",
    ("brazil","germany"):     "Germany 7-1 Brazil in 2014 semi. At home. The Mineirazo. Brazil's biggest ever humiliation.",
    ("italy","france"):       "2006 WC Final. Italy beat France on penalties. Zidane headbutt on Materazzi. Italy's last WC title.",
}

WC_FACTS = """🌍 WC 2026 — Fast Facts

🏆 Most titles: Brazil 5 | Germany & Italy 4 | Argentina 3
⚽ Top scorer all time: Miroslav Klose — 16 goals (4 WCs)
👶 Youngest scorer: Pelé — 17 years old, 1958 final
💥 Biggest result: Germany 7-1 Brazil, 2014 semi-final
🎯 Best individual: Maradona 1986 — 5 goals, 5 assists
😭 Saddest moment: Baggio's penalty miss, 1994 final
🤝 Fair play: Japan 2022 left dressing room spotless
🇦🇷 Last winner: Argentina beat France on pens, Qatar 2022
🏟 WC 2026: 48 teams, USA + Canada + Mexico, June 11 - July 19"""


def get_team_fact(name: str) -> str:
    name = name.lower()
    for key, val in TEAM_FACTS.items():
        if key in name or name in key:
            return val
    return ""

def get_h2h(team_a: str, team_b: str) -> str:
    a = team_a.lower(); b = team_b.lower()
    for (t1,t2), fact in HEAD_TO_HEAD.items():
        if (t1 in a or a in t1) and (t2 in b or b in t2):
            return fact
        if (t1 in b or b in t1) and (t2 in a or a in t2):
            return fact
    return ""
