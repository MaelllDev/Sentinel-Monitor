<div align="center">

# 🖥️ Sentinel Monitor

**Bot de monitoramento de servidores VPS via Telegram — arquitetura master/node em Python + Docker**

[![GitHub](https://img.shields.io/badge/GitHub-MaelllDev%2Fsentinel--monitor-181717?style=flat&logo=github)](https://github.com/MaelllDev/sentinel-monitor)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

</div>

---

## O que é

O **Sentinel Monitor** é um sistema de monitoramento remoto de servidores VPS controlado pelo Telegram. Você gerencia todos os seus servidores a partir de um único bot, sem precisar abrir SSH ou painel de controle.

Funciona com uma arquitetura **master/node**:

```
[VPS Node 1] ──┐
[VPS Node 2] ──┼── WebSocket ──► [Master PC] ──► [Telegram Bot]
[VPS Node N] ──┘
```

- **Master** — roda no seu PC ou servidor central. Hospeda o bot do Telegram e o servidor WebSocket que recebe dados dos nodes.
- **Node** — um agente leve que roda em cada VPS. Coleta métricas do sistema e envia ao master continuamente.

---

## Funcionalidades

- 📊 **Métricas em tempo real** — CPU, RAM, disco, temperatura e rede
- 🐳 **Visibilidade Docker** — lista contêineres e seus estados
- 🔌 **Portas em escuta** — quais serviços estão expostos na VPS
- 🔔 **Alertas automáticos** — notificação no Telegram quando CPU/RAM/disco ultrapassam threshold
- 🏠 **Integração CasaOS** — gerenciamento de apps instalados via CasaOS (opcional)
- ⚡ **Instalação rápida de nodes** — o comando `/integrar` gera o `docker run` completo para copiar e colar na VPS
- 🔐 **Acesso restrito** — bot responde apenas ao seu `chat_id`
- 🔄 **Reconexão automática** — nodes reconectam ao master sem intervenção manual

---

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/install/) instalados
- Token de bot do Telegram — crie um via [@BotFather](https://t.me/BotFather)
- Seu `chat_id` do Telegram — obtenha via [@userinfobot](https://t.me/userinfobot)
- IP público ou domínio do PC master acessível pelas VPS nodes

---

## Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/MaelllDev/sentinel-monitor.git
cd sentinel-monitor
```

### 2. Configure o `.env`

```bash
cp .env.example .env
```

Edite o `.env` com seus valores:

```env
# Token do bot do Telegram (obtido via @BotFather)
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Seu chat_id do Telegram (obtido via @userinfobot)
ALLOWED_CHAT_ID=987654321

# Chave de autenticação entre master e nodes — gere uma chave segura:
# python -c "import secrets; print(secrets.token_hex(32))"
API_KEY=troque-por-uma-chave-aleatoria-segura

# IP público ou domínio do master (usado no comando /integrar)
MASTER_HOST=SEU_IP_PUBLICO

# Porta do servidor WebSocket
WS_PORT=8765
```

> 💡 **Gere uma API key segura:**
> ```bash
> python -c "import secrets; print(secrets.token_hex(32))"
> ```

### 3. Suba o master

```bash
docker compose up -d master
```

O master sobe automaticamente junto com um **node local** que monitora o próprio PC master.

### 4. Verifique

```bash
docker compose logs -f master
```

O bot estará online. Envie `/start` no Telegram para confirmar.

---

## Adicionando nodes (VPS)

### Opção A — Comando gerado pelo bot (recomendado)

No Telegram, envie `/integrar`. O bot responde com o comando `docker run` completo, já com a `API_KEY` e o IP do master preenchidos. Basta copiar e colar na VPS.

### Opção B — Manual

Na VPS, execute:

```bash
docker run -d \
  --name monitor-node \
  --restart unless-stopped \
  -e MASTER_WS_URL=ws://SEU_IP_MASTER:8765 \
  -e API_KEY=SUA_API_KEY \
  -e NODE_NAME=nome-da-vps \
  -e METRICS_INTERVAL=10 \
  -e ALERT_CPU=90 \
  -e ALERT_MEMORY=90 \
  -e ALERT_DISK=90 \
  --pid=host \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/maellldev/sentinel-monitor-node:latest
```

### Opção C — Script de instalação

Para instalação sem Docker (systemd service):

```bash
curl -fsSL https://raw.githubusercontent.com/MaelllDev/sentinel-monitor/main/install-node.sh | bash
```

O script pedirá interativamente o URL do master e a API key.

---

## Variáveis de ambiente

### Master

| Variável | Descrição | Padrão |
|---|---|---|
| `TELEGRAM_TOKEN` | Token do bot do Telegram | obrigatório |
| `ALLOWED_CHAT_ID` | chat_id autorizado a usar o bot | obrigatório |
| `API_KEY` | Chave de autenticação master↔node | obrigatório |
| `MASTER_HOST` | IP ou domínio público do master | obrigatório |
| `WS_PORT` | Porta do servidor WebSocket | `8765` |
| `CASAOS_URL` | URL do CasaOS (deixe vazio para desativar) | — |
| `CASAOS_USER` | Usuário do CasaOS | — |
| `CASAOS_PASSWORD` | Senha do CasaOS | — |

### Node

| Variável | Descrição | Padrão |
|---|---|---|
| `MASTER_WS_URL` | URL WebSocket do master | obrigatório |
| `API_KEY` | Mesma chave configurada no master | obrigatório |
| `NODE_NAME` | Nome amigável desta VPS | obrigatório |
| `METRICS_INTERVAL` | Intervalo de envio de métricas (segundos) | `10` |
| `ALERT_CPU` | Threshold de CPU para alertas (%) | `90` |
| `ALERT_MEMORY` | Threshold de RAM para alertas (%) | `90` |
| `ALERT_DISK` | Threshold de disco para alertas (%) | `90` |

---

## Comandos do bot

| Comando | Descrição |
|---|---|
| `/start` | Mensagem de boas-vindas |
| `/status` | Painel resumido de todos os servidores |
| `/status <nome>` | Detalhes de um servidor específico |
| `/saude` | Diagnóstico e limites configurados |
| `/apps [nome]` | Contêineres Docker e seus estados |
| `/portas [nome]` | Portas TCP em escuta |
| `/cpu [nome]` | Uso de CPU e maiores consumidores |
| `/memoria [nome]` | RAM e maiores consumidores |
| `/disco [nome]` | Uso das partições |
| `/temperatura [nome]` | Temperatura dos sensores e limites |
| `/rede [nome]` | Interfaces de rede e endereços |
| `/servidores` | Lista de nodes conectados |
| `/renomear <atual> <novo>` | Renomeia um servidor |
| `/integrar` | Gera o comando para adicionar nova VPS |
| `/limpar` | Limpa mensagens recentes do bot |
| `/versao` | Versão instalada |

### Comandos CasaOS (se configurado)

| Comando | Descrição |
|---|---|
| `/casastatus` | Status geral do CasaOS |
| `/casaapps` | Apps instalados no CasaOS |

---

## Alertas automáticos

O node monitora CPU, RAM e disco continuamente. Quando o uso ultrapassa o threshold configurado, um alerta é enviado automaticamente no Telegram.

- Thresholds padrão: **90%** para CPU, RAM e disco
- Configure via variáveis `ALERT_CPU`, `ALERT_MEMORY`, `ALERT_DISK` no `.env` do node
- Cooldown de **5 minutos** por métrica para evitar spam

---

## Segurança

- O bot responde **somente** ao `ALLOWED_CHAT_ID` configurado no `.env`
- Nodes se autenticam com `API_KEY` no handshake WebSocket — conexões sem a chave são rejeitadas
- Nunca exponha a porta WebSocket diretamente sem firewall em produção
- A `API_KEY` **não** deve ser commitada no repositório — use o `.env` local

---

## Estrutura do projeto

```
sentinel-monitor/
├── master/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── bot.py          # Bot do Telegram e handlers de todos os comandos
│   ├── ws_server.py    # Servidor WebSocket que recebe dados dos nodes
│   └── casaos.py       # Integração com a API do CasaOS
├── node/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── agent.py        # Agente WebSocket que roda na VPS
│   └── metrics.py      # Coleta de métricas via psutil
├── docker-compose.yml  # Sobe master + node local juntos
├── setup.sh            # Setup interativo do master
├── install-node.sh     # Instalação do node via systemd (sem Docker)
├── uninstall.sh        # Remoção completa do node
├── monitor.service     # Unit file do systemd para o node
├── .env.example        # Template de configuração
├── .gitignore
└── README.md
```

---

## Licença

MIT — veja [LICENSE](LICENSE) para detalhes.
