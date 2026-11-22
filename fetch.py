"""Fetch DeFiLlama free APIs, build one daily snapshot, validate it.

Any network failure or failed sanity check raises DataError, so the caller
can report the error instead of sending wrong numbers.
"""
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

UA = {"User-Agent": "defi-daily-flow/0.1"}
COINS = {"BTC": "coingecko:bitcoin", "ETH": "coingecko:ethereum"}
CHAIN_HISTORY_TOP_N = 30          # chains whose TVL 7d-ago we look up
KEEP_TVL = 10e6                   # keep protocol row if TVL >= 10M ...
KEEP_FEES_7D = 50e3               # ... or 7-day fees >= 50k
WEEK = 7 * 86400
VN_TZ = timezone(timedelta(hours=7))


class DataError(Exception):
    pass


def get_json(url, tries=3, timeout=90):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
        if i < tries - 1:
            time.sleep(5 * (i + 1))
    raise DataError(f"{url.split('?')[0]} -> {last}")


def num(x):
    return float(x) if isinstance(x, (int, float)) else None


def tvl_7d_ago(tvl, change_7d):
    if tvl is None or change_7d is None or change_7d <= -100:
        return None
    return tvl / (1 + change_7d / 100)


# ---------------------------------------------------------------- sources

def fetch_prices(now):
    ids = ",".join(COINS.values())
    cur = get_json(f"https://coins.llama.fi/prices/current/{ids}")["coins"]
    old = get_json(
        f"https://coins.llama.fi/prices/historical/{int(now - WEEK)}/{ids}?searchWidth=6h"
    )["coins"]
    rows = []
    for sym, cid in COINS.items():
        c, o = cur.get(cid) or {}, old.get(cid) or {}
        rows.append({"coin": sym, "price": num(c.get("price")),
                     "price_7d_ago": num(o.get("price")), "price_ts": c.get("timestamp")})
    return rows


def fetch_fees():
    d = get_json("https://api.llama.fi/overview/fees?excludeTotalDataChart=true"
                 "&excludeTotalDataChartBreakdown=true&dataType=dailyFees")
    return d["protocols"]


def fetch_stables_by_chain():
    """USD-pegged stablecoin supply per chain: now and 7 days ago (one call)."""
    d = get_json("https://stablecoins.llama.fi/stablecoins?includePrices=false")
    agg = defaultdict(lambda: [0.0, 0.0])
    for a in d["peggedAssets"]:
        if a.get("pegType") != "peggedUSD":
            continue
        for ch, v in (a.get("chainCirculating") or {}).items():
            agg[ch][0] += num((v.get("current") or {}).get("peggedUSD")) or 0
            agg[ch][1] += num((v.get("circulatingPrevWeek") or {}).get("peggedUSD")) or 0
    return agg


def fetch_chain_tvl_7d_ago(names, now):
    out, failed = {}, []
    target = now - WEEK
    for n in names:
        try:
            pts = get_json(f"https://api.llama.fi/v2/historicalChainTvl/{requests.utils.quote(n)}")
        except DataError:
            failed.append(n)
            continue
        best = min(pts, key=lambda p: abs(int(p["date"]) - target), default=None)
        if best and abs(int(best["date"]) - target) <= 86400:
            out[n] = num(best["tvl"])
        else:
            failed.append(n)
    return out, failed


# ---------------------------------------------------------------- snapshot

def build_snapshot():
    now = time.time()
    fetched_at = datetime.fromtimestamp(now, timezone.utc)

    protocols = get_json("https://api.llama.fi/protocols")
    fees = fetch_fees()
    chains = get_json("https://api.llama.fi/v2/chains")
    stables = fetch_stables_by_chain()
    prices = fetch_prices(now)

    # --- protocols + fees, joined on DeFiLlama id
    fee_protocols = [f for f in fees if f.get("protocolType") != "chain"]
    fee_chains = {f["name"]: f for f in fees if f.get("protocolType") == "chain"}
    fee_by_id = {str(f.get("defillamaId")): f for f in fee_protocols}

    cat = defaultdict(lambda: {"n_protocols": 0, "tvl": 0.0, "tvl_7d_ago": 0.0,
                               "fees_7d": 0.0, "fees_prev_7d": 0.0, "n_fee_protocols": 0})
    for p in protocols:
        tvl, ago = num(p.get("tvl")), tvl_7d_ago(num(p.get("tvl")), num(p.get("change_7d")))
        c = cat[p.get("category") or "Unknown"]
        c["n_protocols"] += 1
        if ago is not None:          # only protocols with a 7d baseline, so both sides match
            c["tvl"] += tvl
            c["tvl_7d_ago"] += ago
    for f in fee_protocols:
        a, b = num(f.get("total7d")), num(f.get("total14dto7d"))
        if a is None or b is None:   # new / broken adapters would distort the comparison
            continue
        c = cat[f.get("category") or "Unknown"]
        c["fees_7d"] += a
        c["fees_prev_7d"] += b
        c["n_fee_protocols"] += 1
    category_rows = [dict(v, category=k) for k, v in cat.items()]

    protocol_rows, seen = [], set()
    for p in protocols:
        f = fee_by_id.get(str(p.get("id"))) or {}
        tvl, f7 = num(p.get("tvl")), num(f.get("total7d"))
        if (tvl or 0) < KEEP_TVL and (f7 or 0) < KEEP_FEES_7D:
            continue
        seen.add(str(p.get("id")))
        protocol_rows.append({
            "slug": p["slug"], "name": p["name"], "category": p.get("category"),
            "parent": p.get("parentProtocol"), "source": "protocols",
            "symbol": None if p.get("symbol") in (None, "", "-") else p["symbol"],
            "gecko_id": p.get("gecko_id"), "listed_at": p.get("listedAt"),
            "tvl": tvl, "tvl_change_7d": num(p.get("change_7d")),
            "fees_7d": f7, "fees_prev_7d": num(f.get("total14dto7d")),
        })
    for f in fee_protocols:  # fee-only protocols not in /protocols (no TVL tracked)
        if str(f.get("defillamaId")) in seen or (num(f.get("total7d")) or 0) < KEEP_FEES_7D:
            continue
        protocol_rows.append({
            "slug": f.get("slug") or f["name"], "name": f.get("displayName") or f["name"],
            "category": f.get("category"), "parent": f.get("parentProtocol"),
            "source": "fees_only", "symbol": None, "gecko_id": None, "listed_at": None, "tvl": None,
            "tvl_change_7d": None, "fees_7d": num(f.get("total7d")),
            "fees_prev_7d": num(f.get("total14dto7d")),
        })
    # dedupe slugs (PK), keep the first
    uniq = {}
    for r in protocol_rows:
        uniq.setdefault(r["slug"], r)
    protocol_rows = list(uniq.values())

    # --- chains
    chain_tvl = {c["name"]: num(c.get("tvl")) for c in chains}
    top_tvl = sorted(chain_tvl, key=lambda n: -(chain_tvl[n] or 0))[:CHAIN_HISTORY_TOP_N]
    tvl_ago, tvl_failed = fetch_chain_tvl_7d_ago(top_tvl, now)
    names = set(top_tvl) | {n for n, v in stables.items() if v[0] >= 50e6}
    chain_rows = []
    for n in sorted(names):
        s = stables.get(n)
        fc = fee_chains.get(n) or {}
        chain_rows.append({
            "chain": n, "tvl": chain_tvl.get(n), "tvl_7d_ago": tvl_ago.get(n),
            "stables": s[0] if s else None, "stables_7d_ago": s[1] if s else None,
            "fees_7d": num(fc.get("total7d")), "fees_prev_7d": num(fc.get("total14dto7d")),
        })

    snap = {
        "day": fetched_at.astimezone(VN_TZ).strftime("%Y-%m-%d"),  # report date as read in Vietnam
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "n_protocols": len(protocols),
        "n_fee_protocols": len(fee_protocols),
        "prices": prices,
        "category_snap": category_rows,
        "chain_snap": chain_rows,
        "protocol_snap": protocol_rows,
        "_tvl_failed": tvl_failed,
        "_top_tvl": top_tvl,
        "_now": now,
    }
    validate(snap)
    return snap


# ---------------------------------------------------------------- checks

def validate(s):
    errs = []

    def check(cond, msg):
        if not cond:
            errs.append(msg)

    check(s["n_protocols"] >= 5000, f"/protocols chỉ có {s['n_protocols']} giao thức")
    tvl = sum(c["tvl"] for c in s["category_snap"])
    check(tvl >= 50e9, f"Tổng TVL bất thường: {tvl/1e9:.1f}B")

    f7 = sum(c["fees_7d"] for c in s["category_snap"])
    fp = sum(c["fees_prev_7d"] for c in s["category_snap"])
    nf = sum(c["n_fee_protocols"] for c in s["category_snap"])
    check(nf >= 1000, f"Phí: chỉ {nf} giao thức có số liệu 7 ngày")
    check(f7 >= 100e6 and fp >= 100e6, f"Tổng phí 7 ngày bất thường: {f7/1e6:.0f}M / {fp/1e6:.0f}M")
    if fp:
        check(0.5 <= f7 / fp <= 2, f"Tổng phí đổi {f7/fp:.2f}x trong 1 tuần, nghi lỗi dữ liệu")

    st = sum(c["stables"] or 0 for c in s["chain_snap"])
    st_ago = sum(c["stables_7d_ago"] or 0 for c in s["chain_snap"])
    check(st >= 100e9, f"Tổng stablecoin bất thường: {st/1e9:.1f}B")
    if st_ago:
        check(0.9 <= st / st_ago <= 1.1, f"Stablecoin đổi {st/st_ago:.2f}x trong 1 tuần, nghi lỗi")

    ok = len(s["_top_tvl"]) - len(s["_tvl_failed"])
    check(ok >= 0.8 * len(s["_top_tvl"]),
          f"TVL lịch sử chain lỗi {len(s['_tvl_failed'])}/{len(s['_top_tvl'])}: {s['_tvl_failed'][:5]}")

    for p in s["prices"]:
        name = p["coin"]
        if not p["price"] or not p["price_7d_ago"]:
            errs.append(f"Thiếu giá {name}")
            continue
        check(0.5 <= p["price"] / p["price_7d_ago"] <= 2, f"Giá {name} đổi bất thường trong 7 ngày")
        age = s["_now"] - (p["price_ts"] or 0)
        check(age <= 3 * 3600, f"Giá {name} cũ {age/3600:.1f} giờ")

    if errs:
        raise DataError("; ".join(errs))
