"""Daily report, one self-contained version per language.

No ** or _ markers. English keeps # headings and uses [+] bullets;
Vietnamese has no # and uses - bullets. Each is sent inside a Telegram code block for a one-tap Copy.
"""
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import quote

from analyze import sd, sp, usd

SITE = "https://defillama.com"
TG_LIMIT = 4096

T = {
    "en": {
        "subtitle": "Where money is flowing in crypto",
        "prices": "Prices 7d", "market": "Market 7d", "fees": "fees", "stables": "stablecoins",
        "hot": "🔥 Hot categories", "hot_note": "7d fees vs prior 7d",
        "cold": "🧊 Cooling categories",
        "flows": "💵 Stablecoin flows by chain", "in": "Inflow", "out": "Outflow",
        "notoken": "🌱 Rising fast, no token yet",
        "insight": "🧠 Takeaways", "insight_note": "AI, based only on the numbers above",
        "no_insight": "AI commentary skipped today",
        "durable": "durable hot", "days": "days", "mostly": "mostly", "none": "none",
        "sources": "📚 Sources", "fetched": "Data fetched", "vn": "Vietnam time",
        "cats": "Categories", "chains": "Chains", "protocols": "Protocols",
        "disclaimer": "Data only, not investment advice.",
    },
    "vi": {
        "subtitle": "Tiền đang chảy vào đâu trong crypto",
        "prices": "Giá 7 ngày", "market": "Thị trường 7 ngày", "fees": "phí", "stables": "stablecoin",
        "hot": "🔥 Danh mục nóng", "hot_note": "phí 7 ngày so với 7 ngày trước",
        "cold": "🧊 Danh mục nguội",
        "flows": "💵 Dòng stablecoin theo chain", "in": "Vào", "out": "Ra",
        "notoken": "🌱 Tăng mạnh, chưa có token",
        "insight": "🧠 Nhận định", "insight_note": "AI, chỉ dựa trên các con số ở trên",
        "no_insight": "Hôm nay bỏ qua nhận định AI",
        "durable": "nóng bền", "days": "ngày", "mostly": "chủ yếu do", "none": "không có",
        "sources": "📚 Nguồn", "fetched": "Dữ liệu lấy lúc", "vn": "giờ VN",
        "cats": "Danh mục", "chains": "Chain", "protocols": "Dự án",
        "disclaimer": "Chỉ là dữ liệu, không phải khuyến nghị đầu tư.",
    },
}


def cat_url(c):
    return f"{SITE}/protocols/{quote(c.lower().replace(' ', '-'))}"


def chain_url(c):
    return f"{SITE}/stablecoins/{quote(c)}"


def proto_url(slug):
    return f"{SITE}/protocol/{quote(slug)}"


def links(r):
    cats, chains, protos = {}, {}, {}
    for c in r["hot"] + r["cold"]:
        cats[c["category"]] = cat_url(c["category"])
        for x in c["leaders"]:
            protos[x["name"]] = proto_url(x["slug"])
    for c in r["stables_in"] + r["stables_out"]:
        chains[c["chain"]] = chain_url(c["chain"])
    for x in r["no_token"]:
        protos[x["name"]] = proto_url(x["slug"])
    return cats, chains, protos


# Per-language text style: (title prefix, section prefix, bullet, sub-bullet).
# No ** or _ anywhere, so the text pastes as-is.
STYLE = {"en": ("# ", "## ", "[+] ", "    [+] "),
         "vi": ("", "", "- ", "  - ")}


def plain(r, lang, insight=None, insight_note=None):
    """One language's report as plain text in that language's STYLE."""
    t, p, m = T[lang], r["prices"], r["market"]
    h1, h2, b, sb = STYLE[lang]
    L = [f"{h1}📡 DeFi Daily Flow · {_date(r, lang)}", t["subtitle"], ""]
    L.append(f"{t['prices']}: BTC {sp(p['BTC']['pct'])} · ETH {sp(p['ETH']['pct'])}")
    L.append(f"{t['market']}: {t['fees']} {usd(m['fees_7d'])} ({sp(m['fees_pct'])}) · "
             f"{t['stables']} {usd(m['stables'])} ({sd(m['stables_delta'])})")

    def dom(c):
        return f" ({t['mostly']} {c['dominated_by']})" if c["dominated_by"] else ""

    def tvl(c):
        return f", TVL {sp(c['tvl_pct'])}" if c["tvl_pct"] is not None else ""

    L += ["", h2 + t["hot"], f"({t['hot_note']})"]
    if not r["hot"]:
        L.append(t["none"])
    for c in r["hot"]:
        tag = f" · 🏆 {t['durable']} {c['streak']} {t['days']}" if c["durable"] else ""
        L.append(f"{b}{c['category']}: {t['fees']} {usd(c['fees_7d'])} {sp(c['fees_pct'])}"
                 f"{tvl(c)}{tag}{dom(c)}")
        L += [f"{sb}{x['name']}: {sp(x['fees_pct'])} ({sd(x['fees_delta'])})" for x in c["leaders"]]

    L += ["", h2 + t["cold"]]
    L += [f"{b}{c['category']}: {t['fees']} {sp(c['fees_pct'])}{tvl(c)}{dom(c)}"
          for c in r["cold"]] or [t["none"]]

    L += ["", h2 + t["flows"]]
    L += [f"{b}{t['in']}: {c['chain']} {sd(c['stables_delta'])} ({sp(c['stables_pct'])})" for c in r["stables_in"]]
    L += [f"{b}{t['out']}: {c['chain']} {sd(c['stables_delta'])} ({sp(c['stables_pct'])})" for c in r["stables_out"]]

    L += ["", h2 + t["notoken"]]
    L += [f"{b}{x['name']} ({x['category']}): TVL {usd(x['tvl'])} {sp(x['tvl_change_7d'])} "
          f"({sd(x['tvl_delta'])})" for x in r["no_token"]] or [t["none"]]

    L += ["", h2 + t["insight"], f"({t['insight_note']})"]
    if insight:
        L += [f"{i}. {s}" for i, s in enumerate(getattr(insight, lang), 1)]
    else:
        L.append(f"{t['no_insight']}: {(insight_note or '')[:150]}")

    fetched, vn = _times(r)
    when = (f"{fetched.strftime('%Y-%m-%d %H:%M')} UTC" if lang == "en"
            else f"{vn.strftime('%Y-%m-%d %H:%M')} {t['vn']}")
    L += ["", f"{t['fetched']} {when} · DeFiLlama", t["disclaimer"]]
    return "\n".join(L)


def _times(r):
    fetched = datetime.fromisoformat(r["fetched_at"])
    return fetched, fetched.astimezone(timezone(timedelta(hours=7)))


def _date(r, lang):
    """English version dated in UTC, Vietnamese version in Vietnam time."""
    fetched, vn = _times(r)
    return (fetched if lang == "en" else vn).strftime("%Y-%m-%d")


def sources_message(r):
    """Plain Telegram HTML (outside code blocks) so every link is clickable."""
    fetched, vn = _times(r)
    cats, chains, protos = links(r)
    L = ["📚 <b>Sources · Nguồn</b>",
         f"Data fetched · Dữ liệu lấy lúc: {fetched.strftime('%Y-%m-%d %H:%M')} UTC "
         f"({vn.strftime('%H:%M')} giờ VN) · DeFiLlama API", ""]
    for label, d in (("Categories · Danh mục", cats), ("Chains (stablecoins)", chains),
                     ("Protocols · Dự án", protos)):
        if d:
            L.append(f"<b>{label}</b>")
            L.append(" · ".join(f'<a href="{escape(u)}">{escape(n)}</a>' for n, u in d.items()))
            L.append("")
    return "\n".join(L).rstrip()


def _code_blocks(text, lang="text", limit=TG_LIMIT - 200):
    """Wrap text in Telegram <pre> blocks (one-tap Copy); split on lines if too long."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(escape(cur)) + len(escape(line)) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    chunks.append(cur)
    return [f'<pre><code class="language-{lang}">{escape(c)}</code></pre>' for c in chunks]


def build_messages(r, insight=None, insight_note=None):
    """EN block, VI block (both copyable), then clickable Sources."""
    out = []
    for lang, flag in (("en", "🇬🇧 English"), ("vi", "🇻🇳 Tiếng Việt")):
        blocks = _code_blocks(plain(r, lang, insight, insight_note))
        blocks[0] = f"<b>{flag}</b> · DeFi Daily Flow {_date(r, lang)}\n" + blocks[0]
        out += blocks
    return out + [sources_message(r)]


def error_message(err, data_error=True):
    if data_error:
        head = ("⚠️ <b>DEFI DAILY FLOW</b>: no report today - data source error (not sending possibly wrong numbers).\n"
                "Hôm nay không gửi bản tin vì nguồn dữ liệu lỗi (tránh gửi số sai).")
    else:
        head = ("⚠️ <b>DEFI DAILY FLOW</b>: no report today - the bot crashed.\n"
                "Hôm nay không gửi bản tin vì bot bị lỗi chương trình.")
    return f"{head}\n\n<code>{escape(str(err))[:3000]}</code>"
