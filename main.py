"""DeFi Daily Flow: fetch -> validate -> store -> analyze -> Haiku -> Telegram.

  python main.py              full run, sends to Telegram
  python main.py --dry-run    full run, prints messages instead of sending
  python main.py --no-fetch   reuse the latest stored snapshot (testing)
"""
import os
import sqlite3
import sys
import traceback

import db
import notify
from analyze import analyze, to_text
from fetch import DataError, build_snapshot
from insight import write_insight
from report import build_messages, error_message

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DEFI_FLOW_DB", os.path.join(HERE, "data", "defi_daily_flow.db"))


def deliver(messages, dry_run):
    for m in messages:
        if dry_run:
            print(m, "\n" + "=" * 60)
        else:
            notify.send(m)


def run(dry_run, no_fetch):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = db.connect(DB_PATH)
    if not no_fetch:
        snap = build_snapshot()          # raises DataError on any bad source
        db.save_snapshot(con, snap)
        print(f"Đã lưu snapshot {snap['day']} ({len(snap['protocol_snap'])} dự án)", file=sys.stderr)
    con.row_factory = sqlite3.Row
    r = analyze(con)
    ins, note = write_insight(to_text(r, "en"))
    print(f"Haiku: {note}", file=sys.stderr)
    deliver(build_messages(r, ins, note), dry_run)


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows console defaults to cp1252
        stream.reconfigure(encoding="utf-8")
    notify.load_dotenv(os.path.join(HERE, ".env"))
    dry_run, no_fetch = "--dry-run" in sys.argv, "--no-fetch" in sys.argv
    try:
        run(dry_run, no_fetch)
        return 0
    except DataError as err:
        msg, data_error = f"Nguồn dữ liệu lỗi: {err}", True
    except Exception as err:  # bug or Telegram failure: still try to alert
        traceback.print_exc()
        msg, data_error = f"Lỗi chương trình: {type(err).__name__}: {err}", False
    print(msg, file=sys.stderr)
    try:
        deliver([error_message(msg, data_error)], dry_run)
    except Exception as err2:
        print(f"Không gửi được báo lỗi qua Telegram: {err2}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
