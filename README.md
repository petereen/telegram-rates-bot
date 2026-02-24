# Telegram Exchange Rates Bot

A production-ready Telegram bot that fetches financial exchange rates from multiple sources and lets users build a personalised watchlist. Built with **python-telegram-bot v20+**, **Supabase**, and a modular Factory-pattern provider architecture.

## Project Structure

```
telegram-rates-bot/
├── main.py                  # Entry point
├── config.py                # Env-var loader
├── schema.sql               # Supabase table DDL
├── requirements.txt
├── bot.service              # systemd unit file
├── .env.example
├── db/
│   └── supabase_client.py   # Supabase CRUD + cache
├── providers/
│   ├── base.py              # BaseProvider ABC + Factory
│   ├── cbr.py               # Central Bank of Russia XML
│   ├── xe.py                # XE Currency Data API
│   ├── binance.py           # Binance Spot + P2P
│   ├── profinance.py        # Profinance.ru scraper
│   ├── boc.py               # Bank of China scraper
│   └── grx.py               # Garantex REST API
└── bot/
    ├── keyboards.py         # Inline keyboard builders
    └── handlers.py          # Command + callback handlers
```

## Supabase Setup

Open the Supabase SQL Editor for your project and run every statement in `schema.sql`. This creates three tables: `users`, `user_subscriptions`, and `cached_rates`. The cache table stores JSON rate data with a composite primary key of `(provider, symbol)` so that upserts naturally replace stale entries. The default cache TTL is 300 seconds (5 minutes) and is controlled by the `CACHE_TTL` environment variable.

## VPS Deployment

The deployment target is a fresh Ubuntu 22.04+ VPS. Begin by connecting via SSH and updating the system packages. Run `sudo apt update && sudo apt upgrade -y` followed by `sudo apt install -y python3 python3-venv python3-pip git`. This ensures the system has a modern Python 3 interpreter and Git available.

Create a dedicated non-root user to run the bot process. Execute `sudo useradd -r -m -s /bin/bash botuser`. This user has no login password, which is the recommended practice for service accounts because it prevents any interactive login over SSH, reducing the attack surface of the server.

Clone the repository into the deployment directory. Run `sudo mkdir -p /opt/telegram-rates-bot && sudo chown botuser:botuser /opt/telegram-rates-bot` and then switch to that user with `sudo -u botuser bash`. As botuser, clone the repo: `git clone https://github.com/YOUR_USER/telegram-rates-bot.git /opt/telegram-rates-bot`. If the repo is private, configure an SSH deploy key or a personal access token for HTTPS cloning beforehand.

Create a Python virtual environment inside the project directory. Run `cd /opt/telegram-rates-bot && python3 -m venv venv && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt`. The virtual environment isolates dependencies from the system Python, preventing version conflicts with other applications on the same server.

Copy the example environment file and fill in real credentials. Run `cp .env.example .env && nano .env`. You must provide values for `TELEGRAM_BOT_TOKEN` (obtained from @BotFather on Telegram), `SUPABASE_URL` and `SUPABASE_KEY` (from the Supabase project dashboard under Settings > API), and optionally `XE_ACCOUNT_ID` plus `XE_API_KEY` if you have an XE API subscription. Save the file and exit the editor. Ensure the file permissions are restrictive: `chmod 600 .env` so only botuser can read the secrets.

Install the systemd service file. Switch back to a privileged user (`exit` from the botuser shell) and run `sudo cp /opt/telegram-rates-bot/bot.service /etc/systemd/system/telegram-rates-bot.service`. Then reload the systemd daemon with `sudo systemctl daemon-reload`. Enable the service so it starts automatically on boot: `sudo systemctl enable telegram-rates-bot`. Finally, start it: `sudo systemctl start telegram-rates-bot`.

Verify the bot is running correctly by checking the journal logs: `sudo journalctl -u telegram-rates-bot -f`. You should see log lines from the bot indicating it has connected to Telegram and is polling for updates. If any error appears (e.g., invalid token or unreachable Supabase URL), edit the `.env` file, then run `sudo systemctl restart telegram-rates-bot` and check the logs again.

To deploy updates after pushing new code to GitHub, SSH into the VPS, switch to botuser, pull the latest code, and restart the service. The sequence is: `sudo -u botuser bash -c 'cd /opt/telegram-rates-bot && git pull origin main'` followed by `sudo systemctl restart telegram-rates-bot`. If you added new Python dependencies, activate the venv and run `pip install -r requirements.txt` before restarting.

## Bot Commands

| Command   | Description                              |
|-----------|------------------------------------------|
| `/start`  | Register and show help                   |
| `/add`    | Open provider menu to add pairs          |
| `/remove` | Open provider menu to remove pairs       |
| `/list`   | Display current watchlist                |
| `/rates`  | Fetch and display rates for all pairs    |
| `/clear`  | Remove all pairs from the watchlist      |
| `/help`   | Show help message                        |
