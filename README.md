# DeFi Daily Flow

Bot gửi bản tin mỗi sáng về Telegram: tiền trong crypto đang chảy vào đâu (phí, stablecoin, TVL theo danh mục/chain/dự án), dữ liệu từ API miễn phí của DeFiLlama, kèm 3 câu nhận định của Claude Haiku. Không giao dịch, không khuyến nghị.

## Chạy trên máy

```
pip install -r requirements.txt
copy .env.example .env      # rồi điền 3 giá trị
python main.py --dry-run    # in ra màn hình, không gửi
python main.py              # gửi Telegram
python analyze.py           # xem bảng số liệu thô
python notify.py            # tìm TELEGRAM_CHAT_ID sau khi nhắn /start cho bot
```

## Chạy tự động (GitHub Actions)

- Lịch: `.github/workflows/daily.yml`, 01:17 UTC (08:17 giờ VN). Chạy tay: tab Actions → daily-report → Run workflow.
- Bí mật: Settings → Secrets and variables → Actions: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Lịch sử SQLite nằm ở branch `data` (một commit, ghi đè mỗi ngày).

## Các file

| File | Việc |
|---|---|
| `fetch.py` | Gọi DeFiLlama, kiểm tra số liệu hợp lệ (lỗi thì dừng) |
| `db.py` | Lưu snapshot mỗi ngày vào SQLite |
| `analyze.py` | Danh mục nóng/nguội, chain hút stablecoin, dự án chưa có token, "nóng bền" |
| `insight.py` | Claude Haiku viết nhận định, chặn số bịa |
| `report.py` | Bản tin Markdown EN/VI + tin Nguồn |
| `notify.py` | Gửi Telegram |
| `main.py` | Ghép tất cả; nguồn lỗi thì gửi báo lỗi thay vì bản tin |
