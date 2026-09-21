<div align="center">

# 🖥️ Sentinel Monitor

**Telegram-based VPS server monitoring bot — Python + Docker master/node architecture**

[![GitHub](https://img.shields.io/badge/GitHub-MaelllDev%2Fsentinel--monitor-181717?style=flat&logo=github)](https://github.com/MaelllDev/sentinel-monitor)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)](https://docs.docker.com/get-docker/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

</div>

---

## What it is

**Sentinel Monitor** is a remote VPS server monitoring system controlled via Telegram. You manage all your servers from a single bot — no SSH or web panel needed.

It uses a **master/node** architecture:

```
[VPS Node 1] ──┐
[VPS Node 2] ──┼── WebSocket ──► [Master] ──► [Telegram Bot]
[VPS Node N] ──┘
```

- **Master** — runs on your central server/PC. Hosts the Telegram bot and WebSocket server that receives data from nodes.
- **Node** — a lightweight agent running on each VPS. Collects system metrics and sends them to the master continuously.

---

## Installation

Everything is done with a single command — no cloning, no building.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/MaelllDev/sentinel-monitor/main/setup.sh)
```

The script presents an interactive menu:

```
  [1] Install MASTER  (Telegram bot + WebSocket server)
  [2] Install NODE    (metrics agent for this VPS)
  [3] Update MASTER
  [4] Update NODE
  [5] Remove MASTER
  [6] Remove NODE
  [7] Remove ALL (complete uninstall)
  [8] Configure ENV for an existing container
```

### Install the Master

Run the script on the server that will host the bot. You'll need:

- Telegram bot token — create via [@BotFather](https://t.me/BotFather)
- Your Telegram `chat_id` — get it via [@userinfobot](https://t.me/userinfobot)
- Public or local IP of this server (for nodes to connect)

The script configures everything interactively, pulls images from the registry, and starts the master along with a local node that monitors the host itself.

If CasaOS integration is enabled during setup, the master and local node are installed through the CasaOS App. They will appear under Apps, where the Compose configuration and environment variables can be viewed and edited.

### Install a Node (VPS)

Run the script on each VPS you want to monitor. You'll need the API key generated during master installation.

Or use `/integrar` in Telegram — the bot generates the complete `docker run` command pre-filled.

### Update

To update master or node to the latest version, run the script again and choose option 3 or 4. Existing settings are preserved automatically.

For an installation that was previously shown under “Aplicativo legado”, run option 3 after configuring the CasaOS URL and credentials. The setup removes the manually created containers and registers them as a CasaOS App.

### Configure the environment

To change the environment variables of an existing master or node without reinstalling it, run the script and choose option 8. Press Enter to keep the current value; secrets are requested without displaying them.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed (script installs automatically if missing)
- Telegram bot token — create via [@BotFather](https://t.me/BotFather)
- Your Telegram `chat_id` — get it via [@userinfobot](https://t.me/userinfobot)

---

## Docker Images

Images are published automatically to GitHub Container Registry on each push to `main`:

| Image | Description |
|---|---|
| `ghcr.io/maellldev/sentinel-monitor-master:latest` | Telegram bot + WebSocket server |
| `ghcr.io/maellldev/sentinel-monitor-node:latest` | Metrics agent for VPS |

---

## Features

- 📊 **Real-time metrics** — CPU, RAM, disk, temperature, network
- 🐳 **Docker visibility** — lists containers and their states
- 🔌 **Listening ports** — which services are exposed on the VPS
- 🔔 **Automatic alerts** — Telegram notification when CPU/RAM/disk exceeds threshold
- 🏠 **CasaOS integration** — manage installed apps via CasaOS (optional)
- ⚡ **Quick node setup** — `/integrar` generates the complete `docker run` command
- 🔐 **Access control** — bot only responds to the configured `chat_id`
- 🔄 **Auto-reconnect** — nodes reconnect to master without manual intervention

---

## Environment variables

### Master

| Variable | Description | Default |
|---|---|---|
| `TELEGRAM_TOKEN` | Telegram bot token | required |
| `ALLOWED_CHAT_ID` | chat_id authorized to use the bot | required |
| `API_KEY` | Authentication key master↔node | required |
| `MASTER_HOST` | Public IP or domain of the master | required |
| `WS_PORT` | WebSocket server port | `8765` |
| `CASAOS_URL` | CasaOS URL (leave empty to disable) | — |
| `CASAOS_USER` | CasaOS username | — |
| `CASAOS_PASSWORD` | CasaOS password | — |

### Node

| Variable | Description | Default |
|---|---|---|
| `MASTER_WS_URL` | Master WebSocket URL | required |
| `API_KEY` | Same key configured on the master | required |
| `NODE_NAME` | Friendly name for this VPS | required |
| `METRICS_INTERVAL` | Metrics send interval (seconds) | `10` |
| `ALERT_CPU` | CPU threshold for alerts (%) | `90` |
| `ALERT_MEMORY` | RAM threshold for alerts (%) | `90` |
| `ALERT_DISK` | Disk threshold for alerts (%) | `90` |

---

## Bot commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/status` | Summary panel of all servers |
| `/status <name>` | Details of a specific server |
| `/saude` | Diagnostics and configured limits |
| `/apps [name]` | Docker containers and their states |
| `/portas [name]` | TCP listening ports |
| `/cpu [name]` | CPU usage and top consumers |
| `/memoria [name]` | RAM and top consumers |
| `/disco [name]` | Partition usage |
| `/temperatura [name]` | Sensor temperatures and limits |
| `/rede [name]` | Network interfaces and addresses |
| `/servidores` | List of connected nodes |
| `/renomear <old> <new>` | Rename a server |
| `/integrar` | Generates the command to add a new VPS |
| `/limpar` | Clears recent bot messages |
| `/versao` | Installed version |

### CasaOS commands (if configured)

| Command | Description |
|---|---|
| `/casastatus` | CasaOS overall status |
| `/casaapps` | Apps installed in CasaOS |

---

## Automatic alerts

The node monitors CPU, RAM, and disk continuously. When usage exceeds the configured threshold, an alert is sent automatically via Telegram.

- Default thresholds: **90%** for CPU, RAM, and disk
- Configure via `ALERT_CPU`, `ALERT_MEMORY`, `ALERT_DISK`
- **5-minute cooldown** per metric to prevent spam

---

## Security

- The bot only responds to the configured `ALLOWED_CHAT_ID`
- Nodes authenticate with `API_KEY` during WebSocket handshake — connections without the key are rejected
- Never expose the WebSocket port directly without a firewall in production

---

## Project structure

```
sentinel-monitor/
├── master/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── bot.py          # Telegram bot and command handlers
│   ├── ws_server.py    # WebSocket server receiving data from nodes
│   └── casaos.py       # CasaOS API integration
├── node/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── agent.py        # WebSocket agent running on the VPS
│   └── metrics.py      # Metrics collection via psutil
├── .github/
│   └── workflows/
│       └── docker-publish.yml  # CI: automatic build & push to ghcr.io
├── docker-compose.yml  # Bring up master + local node (advanced usage)
├── setup.sh            # Unified interactive setup
├── .env.example        # Configuration template
└── README.md
```

---

## License

MIT — see [LICENSE](LICENSE) for details.

## Support

If you find this project useful, consider supporting its development:

| Platform | Link |
|---|---|
| GitHub | [MaelllDev](https://github.com/MaelllDev) |
| Discord | [Discord](https://discord.com/invite/xykJqCUeNt) |
| YouTube | [ManoshzDev](https://www.youtube.com/@ManoshzDev) |
| Instagram | [MaelllDev](https://www.instagram.com/omaelldev/) |
| Support | [Pix](https://pixgg.com/maelldev) |