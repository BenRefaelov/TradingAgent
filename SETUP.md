# Setup Guide — Trading Agent

## Prerequisites
- GitHub account with a repository for this project
- Supabase account (free tier is sufficient)
- Telegram account

---

## Step 1 — Supabase

### 1.1 Create a project
1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a name, password, and region. Wait ~2 minutes for provisioning.

### 1.2 Run the schema
1. In your project dashboard → **SQL Editor** → **New Query**
2. Paste the contents of `supabase/schema.sql`
3. Click **Run** (▶)
4. You should see: `Success. No rows returned.`

The script creates three tables (`watchlist`, `theses`, `scan_log`) and seeds
8 tickers (AAPL, NVDA, MSFT, TSLA, AMZN, BTC, ETH, SOL).

### 1.3 Copy credentials
Go to **Project Settings → API**:
| Secret Name     | Where to find it                        |
|-----------------|-----------------------------------------|
| `SUPABASE_URL`  | **Project URL** (e.g. `https://xyz.supabase.co`) |
| `SUPABASE_KEY`  | **anon / public** key under "Project API Keys" |

---

## Step 2 — Telegram Bot

### 2.1 Create a bot
1. Open Telegram → search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts (name + username)
4. BotFather replies with your **bot token** — copy it.

### 2.2 Get your chat_id
1. Send any message to your new bot (e.g. "hello").
2. Open this URL in a browser (replace `<TOKEN>` with your token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. In the JSON response find `"chat": {"id": 123456789}` — that number is your `TELEGRAM_CHAT_ID`.

---

## Step 3 — Gemini API Key (optional)

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with a Google account → **Get API Key** → **Create API key**
3. Copy the key.

The agent works fully without this key. When set, thesis text is enriched with a short Gemini Flash summary.

---

## Step 4 — GitHub Secrets

Push this repository to GitHub, then:

1. Go to **Settings → Secrets and variables → Actions → New repository secret**
2. Add all six secrets:

| Secret Name       | Value                                                  |
|-------------------|--------------------------------------------------------|
| `SUPABASE_URL`    | From Step 1.3                                          |
| `SUPABASE_KEY`    | From Step 1.3                                          |
| `TELEGRAM_TOKEN`  | From Step 2.1                                          |
| `TELEGRAM_CHAT_ID`| From Step 2.2                                          |
| `GEMINI_API_KEY`  | From Step 3 (or leave empty string if not using)       |
| `WATCHLIST`       | JSON string — see format below                         |

### WATCHLIST format
```json
[
  {"ticker": "AAPL", "type": "stock"},
  {"ticker": "NVDA", "type": "stock"},
  {"ticker": "MSFT", "type": "stock"},
  {"ticker": "TSLA", "type": "stock"},
  {"ticker": "AMZN", "type": "stock"},
  {"ticker": "BTC",  "type": "crypto"},
  {"ticker": "ETH",  "type": "crypto"},
  {"ticker": "SOL",  "type": "crypto"}
]
```
Paste the above (all on one line or multi-line) as the secret value.

> **Note:** If Supabase is configured and reachable, the watchlist is read from
> the `watchlist` table and the `WATCHLIST` env-var is used only as a fallback.

---

## Step 5 — Trigger a manual run

1. Go to **Actions → Trading Agent Scan**
2. Click **Run workflow** → select `crypto_only: false` → **Run workflow**
3. Watch the logs. The first successful run should:
   - Analyse all tickers
   - Insert any BUY/WATCH theses into Supabase
   - Send a scan summary to Telegram

---

## Cron schedule (automatic)

| UTC time | Israel summer | Assets scanned |
|----------|---------------|----------------|
| 13:45    | 16:45         | stocks + crypto |
| 17:00    | 20:00         | stocks + crypto |
| 19:30    | 22:30         | stocks + crypto |
| 03:00    | 06:00         | crypto only (7 days) |

GitHub Actions free tier allows 2,000 minutes/month; this agent uses ~270 min/month.

---

## Local testing

```bash
# Install dependencies
pip install -r requirements.txt

# Test a single stock (no DB or Telegram required)
python test_single.py AAPL stock

# Test crypto
python test_single.py BTC crypto
```

---

## Updating the watchlist

**Via Supabase (recommended):**
```sql
INSERT INTO watchlist (ticker, type) VALUES ('META', 'stock');
-- To disable without deleting:
UPDATE watchlist SET active = false WHERE ticker = 'TSLA';
```

**Via GitHub Secret:**
Edit the `WATCHLIST` secret value directly in the GitHub UI.
