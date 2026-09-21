<div align="center">

# 🖥️ Sentinel Monitor

**Bot de monitoramento de servidores VPS via Telegram — arquitetura master/node em Python + Docker**

[![GitHub](https://img.shields.io/badge/GitHub-MaelllDev%2Fsentinel--monitor-181717?style=flat&logo=github)](https://github.com/MaelllDev/sentinel-monitor)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)](https://docs.docker.com/get-docker/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

</div>

---

## O que é

O **Sentinel Monitor** é um sistema de monitoramento remoto de servidores VPS controlado pelo Telegram. Você gerencia todos os seus servidores a partir de um único bot, sem precisar abrir SSH ou painel de controle.

Funciona com uma arquitetura **master/node**:

```
[VPS Node 1] ──┐
[VPS Node 2] ──┼── WebSocket ──► [Master] ──► [Telegram Bot]
[VPS Node N] ──┘
```

- **Master** — roda no seu PC ou servidor central. Hospeda o bot do Telegram e o servidor WebSocket que recebe dados dos nodes.
- **Node** — um agente leve que roda em cada VPS. Coleta métricas do sistema e envia ao master continuamente.

---

## Instalação

Tudo é feito com um único comando — sem clonar o repositório, sem buildar imagens.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/MaelllDev/sentinel-monitor/main/setup.sh)
```

O script apresenta um menu interativo:

```
  [1] Instalar MASTER  (bot do Telegram + servidor WebSocket)
  [2] Instalar NODE    (agente de métricas para esta VPS)
  [3] Atualizar MASTER
  [4] Atualizar NODE
  [5] Remover MASTER
  [6] Remover NODE
  [7] Remover TUDO (desinstalação completa)
```

### Instalar o Master

Execute o script no servidor que vai rodar o bot. Você vai precisar de:

- Token do bot do Telegram — crie via [@BotFather](https://t.me/BotFather)
- Seu `chat_id` do Telegram — obtenha via [@userinfobot](https://t.me/userinfobot)
- IP público ou local deste servidor (para os nodes se conectarem)

O script configura tudo interativamente, baixa as imagens do registry e sobe o master junto com um node local que monitora o próprio servidor.

### Instalar um Node (VPS)

Execute o script em cada VPS que quiser monitorar. Você vai precisar da API Key gerada durante a instalação do master.

Ou use `/integrar` no Telegram — o bot gera o `docker run` completo com tudo preenchido.

### Atualizar

Para atualizar master ou node para a versão mais recente, execute o script novamente e escolha a opção 3 ou 4. As configurações existentes são preservadas automaticamente.

---

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) instalado (o script instala automaticamente se não encontrar)
- Token de bot do Telegram — crie via [@BotFather](https://t.me/BotFather)
- Seu `chat_id` do Telegram — obtenha via [@userinfobot](https://t.me/userinfobot)

---

## Imagens Docker

As imagens são publicadas automaticamente no GitHub Container Registry a cada push na `main`:

| Imagem | Descrição |
|---|---|
| `ghcr.io/maellldev/sentinel-monitor-master:latest` | Bot do Telegram + servidor WebSocket |
| `ghcr.io/maellldev/sentinel-monitor-node:latest` | Agente de métricas para VPS |

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
- Configure via variáveis `ALERT_CPU`, `ALERT_MEMORY`, `ALERT_DISK`
- Cooldown de **5 minutos** por métrica para evitar spam

---

## Segurança

- O bot responde **somente** ao `ALLOWED_CHAT_ID` configurado
- Nodes se autenticam com `API_KEY` no handshake WebSocket — conexões sem a chave são rejeitadas
- Nunca exponha a porta WebSocket diretamente sem firewall em produção

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
├── .github/
│   └── workflows/
│       └── docker-publish.yml  # CI: build e push automático no ghcr.io
├── docker-compose.yml  # Sobe master + node local (uso avançado)
├── setup.sh            # Setup interativo unificado
├── .env.example        # Template de configuração
└── README.md
```

---

## Licença

MIT — veja [LICENSE](LICENSE) para detalhes.
