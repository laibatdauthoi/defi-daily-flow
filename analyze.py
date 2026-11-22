"""Turn stored snapshots into the facts the daily report needs.

All comparisons are 7 days vs the previous 7 days, using numbers DeFiLlama
already provides (fees 7d vs 14d-7d, stablecoin supply now vs 7d ago,
TVL change_7d). The DB history is only used for the "nóng bền" streak.
"""
import sqlite3
import sys
from datetime import date

# Not "meta": exchanges, chains' own gas fees, stablecoin issuers' treasury yield
EXCLUDE_CATEGORIES = {"CEX", "Chain", "Stablecoin Issuer", "Unknown"}
# Categories where a missing token is normal (custodians, curators, institutions)
NO_TOKEN_EXCLUDE = EXCLUDE_CATEGORIES | {
    "Bridge", "Canonical Bridge", "Risk Curators", "RWA",
    "Onchain Capital Allocator", "Block Builders",
}

CAT_MIN_FEES_PREV = 2e6     # category must make >= 2M/week to be ranked
CAT_MIN_PROTOCOLS = 5       # ... and have >= 5 protocols with fee data
HOT_PCT, COLD_PCT = 10, -10
TOP_N = 3
STREAK_DAYS = 3             # "nóng bền" = in the hot top-N for >= 3 snapshots in a row
STREAK_MAX_GAP = 2          # a missed day (failed run) does not break a streak

LEADER_MIN_FEES = 50e3
NOTOKEN_MIN_TVL = 20e6
NOTOKEN_MIN_DELTA = 5e6     # TVL added in 7 days, USD
NOTOKEN_MIN_PCT = 15
DOMINANT_SHARE = 0.6        # flag a category whose change is mostly one protocol


def pct(now, before):
    if now is None or not before:
        return None
    return (now / before - 1) * 100


def rows(con, sql, args=()):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, args)]


def ranked_categories(con, day):
    cats = rows(con, "SELECT * FROM category_snap WHERE day = ?", (day,))
    out = []
    for c in cats:
        if (c["category"] in EXCLUDE_CATEGORIES or c["fees_prev_7d"] < CAT_MIN_FEES_PREV
                or c["n_fee_protocols"] < CAT_MIN_PROTOCOLS):
            continue
        c["fees_pct"] = pct(c["fees_7d"], c["fees_prev_7d"])
        c["tvl_pct"] = pct(c["tvl"], c["tvl_7d_ago"])
        out.append(c)
    return sorted(out, key=lambda c: -c["fees_pct"])


def hot_set(con, day):
    return [c["category"] for c in ranked_categories(con, day)[:TOP_N] if c["fees_pct"] >= HOT_PCT]


def hot_streaks(con, day):
    """category -> number of consecutive snapshots (ending at `day`) it was hot."""
    days = [r["day"] for r in rows(con, "SELECT day FROM runs WHERE day <= ? ORDER BY day DESC", (day,))]
    streak, alive, prev = {}, None, None
    for d in days:
        if prev and (date.fromisoformat(prev) - date.fromisoformat(d)).days > STREAK_MAX_GAP:
            break
        hs = set(hot_set(con, d))
        alive = hs if alive is None else alive & hs
        if not alive:
            break
        for c in alive:
            streak[c] = streak.get(c, 0) + 1
        prev = d
    return streak


def category_leaders(con, day, category):
    ps = rows(con, """SELECT name, slug, fees_7d, fees_prev_7d, tvl, tvl_change_7d, symbol
                      FROM protocol_snap WHERE day = ? AND category = ?
                      AND fees_7d >= ? AND fees_prev_7d IS NOT NULL""",
              (day, category, LEADER_MIN_FEES))
    for p in ps:
        p["fees_delta"] = p["fees_7d"] - p["fees_prev_7d"]
        p["fees_pct"] = pct(p["fees_7d"], p["fees_prev_7d"])
    return sorted(ps, key=lambda p: -p["fees_delta"])


def chains_stables(con, day):
    cs = rows(con, "SELECT * FROM chain_snap WHERE day = ? AND stables IS NOT NULL AND stables_7d_ago > 0", (day,))
    for c in cs:
        c["stables_delta"] = c["stables"] - c["stables_7d_ago"]
        c["stables_pct"] = pct(c["stables"], c["stables_7d_ago"])
        c["tvl_pct"] = pct(c["tvl"], c["tvl_7d_ago"])
        c["fees_pct"] = pct(c["fees_7d"], c["fees_prev_7d"])
    cs.sort(key=lambda c: -c["stables_delta"])
    inflow = [c for c in cs if c["stables_delta"] > 0][:TOP_N]
    outflow = [c for c in reversed(cs) if c["stables_delta"] < 0][:TOP_N]
    return inflow, outflow


def no_token_risers(con, day):
    ps = rows(con, f"""SELECT name, slug, category, tvl, tvl_change_7d, fees_7d, fees_prev_7d
        FROM protocol_snap WHERE day = ? AND source = 'protocols'
        AND symbol IS NULL AND gecko_id IS NULL AND parent IS NULL
        AND tvl >= ? AND tvl_change_7d >= ?
        AND category NOT IN ({','.join('?' * len(NO_TOKEN_EXCLUDE))})""",
              (day, NOTOKEN_MIN_TVL, NOTOKEN_MIN_PCT, *sorted(NO_TOKEN_EXCLUDE)))
    out = []
    for p in ps:
        p["tvl_delta"] = p["tvl"] - p["tvl"] / (1 + p["tvl_change_7d"] / 100)
        p["fees_pct"] = pct(p["fees_7d"], p["fees_prev_7d"])
        if p["tvl_delta"] >= NOTOKEN_MIN_DELTA:
            out.append(p)
    return sorted(out, key=lambda p: -p["tvl_delta"])[:5]


def analyze(con, day=None):
    day = day or con.execute("SELECT max(day) FROM runs").fetchone()[0]
    if not day:
        raise ValueError("DB chưa có snapshot nào")
    run = rows(con, "SELECT * FROM runs WHERE day = ?", (day,))[0]
    prices = {p["coin"]: dict(p, pct=pct(p["price"], p["price_7d_ago"]))
              for p in rows(con, "SELECT * FROM prices WHERE day = ?", (day,))}

    all_cats = rows(con, "SELECT * FROM category_snap WHERE day = ?", (day,))
    meta_cats = [c for c in all_cats if c["category"] not in EXCLUDE_CATEGORIES]
    f7, fp = sum(c["fees_7d"] for c in meta_cats), sum(c["fees_prev_7d"] for c in meta_cats)
    chains = rows(con, "SELECT * FROM chain_snap WHERE day = ?", (day,))
    st = sum(c["stables"] or 0 for c in chains)
    st_ago = sum(c["stables_7d_ago"] or 0 for c in chains)

    ranked = ranked_categories(con, day)
    streaks = hot_streaks(con, day)
    hot = [c for c in ranked[:TOP_N] if c["fees_pct"] >= HOT_PCT]
    cold = [c for c in reversed(ranked) if c["fees_pct"] <= COLD_PCT][:TOP_N]
    for c in hot + cold:
        leaders = category_leaders(con, day, c["category"])
        delta = c["fees_7d"] - c["fees_prev_7d"]
        movers = sorted(leaders, key=lambda p: -abs(p["fees_delta"]))
        top = movers[0] if movers else None
        c["dominated_by"] = (top["name"] if top and delta and top["fees_delta"] / delta >= DOMINANT_SHARE
                             else None)
        c["leaders"] = leaders[:TOP_N] if c in hot else []
        c["streak"] = streaks.get(c["category"], 0)
        c["durable"] = c["streak"] >= STREAK_DAYS

    inflow, outflow = chains_stables(con, day)
    return {
        "day": day, "fetched_at": run["fetched_at"],
        "n_days_history": con.execute("SELECT count(*) FROM runs WHERE day <= ?", (day,)).fetchone()[0],
        "prices": prices,
        "market": {"fees_7d": f7, "fees_pct": pct(f7, fp),
                   "stables": st, "stables_delta": st - st_ago, "stables_pct": pct(st, st_ago)},
        "hot": hot, "cold": cold,
        "categories": [{k: c[k] for k in ("category", "fees_7d", "fees_prev_7d", "fees_pct")}
                       for c in ranked],          # every comparable category, for the chart
        "stables_in": inflow, "stables_out": outflow,
        "no_token": no_token_risers(con, day),
    }


# ---------------------------------------------------------------- text dump (check numbers)

def usd(x):
    if x is None:
        return "?"
    a = abs(x)
    s = f"{a/1e9:.2f}B" if a >= 1e9 else f"{a/1e6:.1f}M" if a >= 1e6 else f"{a/1e3:.0f}k"
    return ("-" if x < 0 else "") + "$" + s


def sd(x):
    return "?" if x is None else ("+" if x >= 0 else "") + usd(x)


def sp(x):
    return "?" if x is None else f"{x:+.1f}%"


LABELS = {
    "en": {
        "data": "data", "history": "history", "days": "day(s)",
        "prices": "Prices 7d", "market": "Whole market: 7d fees", "fees": "fees",
        "hot": "HOT CATEGORIES (7d fees vs prior 7d):", "cold": "COOLING CATEGORIES:",
        "durable": "DURABLE HOT", "mostly": "mostly", "fees7d": "7d fees",
        "in": "CHAINS GAINING STABLECOINS:", "out": "CHAINS LOSING STABLECOINS:",
        "notoken": "RISING FAST, NO TOKEN YET:", "none": "(none)",
    },
    "vi": {
        "data": "dữ liệu", "history": "lịch sử", "days": "ngày",
        "prices": "Giá 7d", "market": "Toàn thị trường: phí 7d", "fees": "phí",
        "hot": "DANH MỤC NÓNG (phí 7d so với 7d trước):", "cold": "DANH MỤC NGUỘI:",
        "durable": "NÓNG BỀN", "mostly": "chủ yếu do", "fees7d": "phí 7d",
        "in": "CHAIN HÚT STABLECOIN:", "out": "CHAIN MẤT STABLECOIN:",
        "notoken": "TĂNG MẠNH, CHƯA CÓ TOKEN:", "none": "(không có)",
    },
}


def to_text(r, lang="en"):
    T = LABELS[lang]
    L = [f"DEFI DAILY FLOW {r['day']} ({T['data']} {r['fetched_at']}, {T['history']} {r['n_days_history']} {T['days']})"]
    p = r["prices"]
    L.append(f"{T['prices']}: BTC {sp(p['BTC']['pct'])} | ETH {sp(p['ETH']['pct'])}")
    m = r["market"]
    L.append(f"{T['market']} {usd(m['fees_7d'])} ({sp(m['fees_pct'])}), "
             f"stablecoin {usd(m['stables'])} ({sd(m['stables_delta'])}, {sp(m['stables_pct'])})")

    def dom(c):
        return f" ({T['mostly']} {c['dominated_by']})" if c["dominated_by"] else ""

    def section(title, items, fmt):
        L.append(title)
        L.extend(fmt(x) for x in items) if items else L.append(f"  {T['none']}")

    L.append("")
    L.append(T["hot"])
    if not r["hot"]:
        L.append(f"  {T['none']}")
    for c in r["hot"]:
        tag = f" [{T['durable']} {c['streak']} {T['days']}]" if c["durable"] else f" [{c['streak']} {T['days']}]"
        L.append(f"  {c['category']}: {T['fees']} {usd(c['fees_7d'])} {sp(c['fees_pct'])}, TVL {sp(c['tvl_pct'])}{tag}{dom(c)}")
        for x in c["leaders"]:
            L.append(f"     - {x['name']}: {T['fees']} {usd(x['fees_7d'])} ({sp(x['fees_pct'])}, {sd(x['fees_delta'])})")
    section(T["cold"], r["cold"], lambda c:
            f"  {c['category']}: {T['fees']} {usd(c['fees_7d'])} {sp(c['fees_pct'])}, TVL {sp(c['tvl_pct'])}{dom(c)}")
    L.append("")
    section(T["in"], r["stables_in"], lambda c:
            f"  {c['chain']}: {sd(c['stables_delta'])} ({sp(c['stables_pct'])}), TVL {sp(c['tvl_pct'])}, {T['fees']} {sp(c['fees_pct'])}")
    section(T["out"], r["stables_out"], lambda c:
            f"  {c['chain']}: {sd(c['stables_delta'])} ({sp(c['stables_pct'])}), TVL {sp(c['tvl_pct'])}")
    L.append("")
    section(T["notoken"], r["no_token"], lambda x:
            f"  {x['name']} ({x['category']}): TVL {usd(x['tvl'])} ({sp(x['tvl_change_7d'])}, {sd(x['tvl_delta'])}), {T['fees7d']} {usd(x['fees_7d'])}")
    return "\n".join(L)


def to_bilingual(r):
    """English first, Vietnamese below."""
    return to_text(r, "en") + "\n\n" + "—" * 20 + " 🇻🇳 TIẾNG VIỆT\n\n" + to_text(r, "vi")


if __name__ == "__main__":
    import os
    sys.stdout.reconfigure(encoding="utf-8")
    path = os.environ.get("DEFI_FLOW_DB", os.path.join(os.path.dirname(__file__), "data", "defi_daily_flow.db"))
    print(to_bilingual(analyze(sqlite3.connect(path), sys.argv[1] if len(sys.argv) > 1 else None)))
