# Evil Vps V1 Bot — LXC Edition

Made by **EVILSAAD**
Repo: https://github.com/evilsaad0-hash/vps-deploy-bot-v1.git

Fully automated Discord bot for managing LXC/LXD-based VPS containers — creation, resizing, suspension, port forwarding, multi-node support, and admin controls, all from Discord.

## Requirements

- A fresh Ubuntu or Debian server (root access)
- A Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Your Discord User ID (main admin)
- `git` installed (`sudo apt install git -y` if missing)

## Installation (from GitHub)

Clone the repo and run the installer as root:

```bash
git clone https://github.com/evilsaad0-hash/vps-deploy-bot-v1.git
cd vps-deploy-bot-v1
chmod +x install.sh
sudo ./install.sh
```

Then follow the prompts:
1. Choose your OS (Ubuntu / Debian) when prompted.
2. Enter your **Discord Bot Token** and **Main Admin Discord ID** when asked.

> If you're not using GitHub, just place `bot.py` and `install.sh` in the same folder on your server and run `sudo ./install.sh` directly.

The script will:
- Install and initialize LXD/LXC
- Install Python 3, pip, and required packages (`discord.py`, `requests`)
- Copy `bot.py` to `/root/bot.py`
- Create and enable a `bot.service` systemd unit so the bot runs 24/7 and restarts on failure or reboot

## Managing the Bot

| Action | Command |
|---|---|
| Check status | `systemctl status bot` |
| View live logs | `journalctl -u bot -f` |
| Restart | `sudo systemctl restart bot` |
| Stop | `sudo systemctl stop bot` |
| Disable autostart | `sudo systemctl disable bot` |

## Configuration

Environment variables are set directly in `/etc/systemd/system/bot.service`. After editing that file, apply changes with:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bot
```

Key variables:

| Variable | Description | Default |
|---|---|---|
| `DISCORD_TOKEN` | Your bot's token | — (required) |
| `MAIN_ADMIN_ID` | Your Discord user ID. Supports **multiple IDs**, comma-separated (e.g. `id1,id2,id3`) | — (required) |
| `BOT_NAME` | Display name used in embeds | `Svm-v9` |
| `PREFIX` | Command prefix | `!` |
| `VPS_USER_ROLE_ID` | Role ID granted to VPS owners | — |
| `DEFAULT_STORAGE_POOL` | LXD storage pool name | `default` |

## Admin Management

- `!admin-add @user` / `!admin-remove @user` — manage regular admins by mention (main admin only). Requires the user to be in the server.
- `!add-admin <user_id>` / `!rm-admin <user_id>` — manage **main admins** by raw Discord ID (main admin only). Works even if the user isn't in the server yet. At least one main admin is always kept.
- `!admin-list` — shows all main admins and regular admins.

Multiple main admins are stored in the database (seeded from `MAIN_ADMIN_ID`), so changes made with `!add-admin`/`!rm-admin` persist across restarts.

## Notes

- The bot runs as **root** because it directly manages LXC containers via `lxc`/`lxd` — keep the bot token and server access secured.
- `vps.db` (SQLite) is created automatically in `/root` on first run and stores nodes, VPS records, admins, and settings.
- Run `!help` in Discord after the bot is online to see the full command list.
