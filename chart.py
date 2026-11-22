"""One shareable chart per day: 7-day fee change by category.

1200x675 (16:9) so X shows it uncropped. Gold = heating up, blue = cooling,
gray = flat; every bar carries its own % label, so color is never the only cue.
"""
import os

import matplotlib

matplotlib.use("Agg")                      # no display on GitHub Actions
import matplotlib.pyplot as plt            # noqa: E402

from analyze import COLD_PCT, HOT_PCT, sp, usd   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "assets", "logo.png")

SURFACE = "#14181F"
INK, INK_2, INK_3 = "#F0EFEC", "#AEB4BD", "#6E7682"
HOT, COLD, FLAT = "#BF7E1C", "#4C8FD6", "#5C6470"   # hot/cold validated for CVD on SURFACE
ROWS_EACH_SIDE = 6


def pick_rows(categories):
    """Top movers both ways, ordered from biggest gain to biggest drop."""
    cats = sorted(categories, key=lambda c: -c["fees_pct"])
    if len(cats) > 2 * ROWS_EACH_SIDE:
        cats = cats[:ROWS_EACH_SIDE] + cats[-ROWS_EACH_SIDE:]
    return cats


def color(pct):
    return HOT if pct >= HOT_PCT else COLD if pct <= COLD_PCT else FLAT


def render(r, path):
    rows = pick_rows(r["categories"])
    if not rows:
        return None
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK})
    fig = plt.figure(figsize=(12, 6.75), dpi=100, facecolor=SURFACE)

    # header
    fig.text(0.04, 0.915, "Where DeFi fees are moving", fontsize=27, weight="bold", color=INK)
    fig.text(0.04, 0.862, f"7-day fees vs the prior 7 days, by category  ·  {r['day']}",
             fontsize=14, color=INK_2)
    p, m = r["prices"], r["market"]
    fig.text(0.96, 0.925, f"BTC {sp(p['BTC']['pct'])}   ETH {sp(p['ETH']['pct'])}",
             fontsize=14, color=INK, ha="right", weight="bold")
    fig.text(0.96, 0.872, f"All DeFi fees {usd(m['fees_7d'])} ({sp(m['fees_pct'])})",
             fontsize=13, color=INK_2, ha="right")

    # legend chips (identity is also in every % label)
    x = 0.04
    for label, c in ((f"Heating  ≥ +{HOT_PCT:g}%", HOT), (f"Cooling  ≤ {COLD_PCT:g}%", COLD), ("Flat", FLAT)):
        fig.patches.append(plt.Rectangle((x, 0.797), 0.012, 0.022, color=c, transform=fig.transFigure))
        fig.text(x + 0.018, 0.799, label, fontsize=12, color=INK_2)
        x += 0.17 if label != "Flat" else 0

    # bars
    ax = fig.add_axes([0.36, 0.12, 0.56, 0.64], facecolor=SURFACE)
    ys = list(range(len(rows)))[::-1]
    vals = [c["fees_pct"] for c in rows]
    ax.barh(ys, vals, height=0.66, color=[color(v) for v in vals], zorder=2)
    lo, hi = min(vals + [0]), max(vals + [0])
    span = (hi - lo) or 1
    ax.set_xlim(lo - 0.16 * span, hi + 0.16 * span)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.axvline(0, color=INK_3, lw=1.2, zorder=1)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])

    for y, c, v in zip(ys, rows, vals):
        off = 0.012 * span
        ax.text(v + off if v >= 0 else v - off, y, sp(v), va="center",
                ha="left" if v >= 0 else "right", fontsize=13, weight="bold", color=INK)
        ax.text(-0.20, y, c["category"], transform=ax.get_yaxis_transform(),
                ha="right", va="center", fontsize=14, color=INK)
        ax.text(-0.02, y, f"{usd(c['fees_7d'])}/wk", transform=ax.get_yaxis_transform(),
                ha="right", va="center", fontsize=12, color=INK_3)

    # footer + logo
    fig.text(0.04, 0.045, "DeFi Daily Flow  ·  data: DeFiLlama  ·  data only, not investment advice",
             fontsize=11, color=INK_3)
    if os.path.exists(LOGO):
        lax = fig.add_axes([0.905, 0.015, 0.075, 0.075 * 12 / 6.75])
        lax.imshow(plt.imread(LOGO))
        lax.axis("off")

    fig.savefig(path, dpi=100, facecolor=SURFACE)
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sqlite3
    import sys

    import db
    from analyze import analyze

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    db_path = os.environ.get("DEFI_FLOW_DB", os.path.join(HERE, "data", "defi_daily_flow.db"))
    con = db.connect(db_path)
    con.row_factory = sqlite3.Row
    print(render(analyze(con), os.path.join(os.path.dirname(db_path), "chart.png")))
