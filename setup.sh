#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Sentinel Monitor — Setup unificado
# Uso: bash <(curl -fsSL https://raw.githubusercontent.com/MaelllDev/sentinel-monitor/main/setup.sh)
# ─────────────────────────────────────────────────────────────────────────────

set -e

# Força a leitura interativa pelo terminal, mesmo se o script for executado por pipe/process substitution.
exec < /dev/tty

MASTER_IMAGE="ghcr.io/maellldev/sentinel-monitor-master:latest"
NODE_IMAGE="ghcr.io/maellldev/sentinel-monitor-node:latest"

# ── Cores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${RESET} $*"; }
error()   { echo -e "${RED}[ERRO]${RESET}  $*"; exit 1; }
title()   { echo; echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; echo -e "${BOLD}  $*${RESET}"; echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; echo; }

# Detect if running inside a Docker/LXC container
is_inside_container() {
    # Check for Docker container marker
    if [ -f /.dockerenv ]; then
        return 0
    fi
    # Check cgroup for docker/lxc indicators
    if grep -qi 'docker\|lxc' /proc/1/cgroup 2>/dev/null; then
        return 0
    fi
    return 1
}

ask() {
    local prompt="$1" default="$2"
    [ -n "$default" ] && echo -ne "${BOLD}${prompt}${RESET} [${CYAN}${default}${RESET}]: " \
                      || echo -ne "${BOLD}${prompt}${RESET}: "
    if [ -t 0 ]; then
        read -r REPLY
    else
        read -r REPLY < /dev/tty
    fi
    REPLY="${REPLY%$'\r'}"
    [ -z "$REPLY" ] && REPLY="$default"
}

ask_menu() {
    while true; do
        echo -ne "${BOLD}Escolha uma opção [1-7]${RESET}: "
        read -r REPLY || REPLY=""
        REPLY="${REPLY%$'\r'}"

        if [[ "$REPLY" =~ ^[1-7]$ ]]; then
            return 0
        fi
        warn "Opção inválida. Digite apenas um número de 1 a 7."
    done
}

ask_secret() {
    echo -ne "${BOLD}$1${RESET}: "
    if [ -t 0 ]; then
        read -rs REPLY
    else
        read -rs REPLY < /dev/tty
    fi
    echo
}

confirm() {
    echo -ne "${BOLD}$1${RESET} [${GREEN}s${RESET}/${RED}n${RESET}]: "
    local ans
    if [ -t 0 ]; then
        read -r ans
    else
        read -r ans < /dev/tty
    fi
    [[ "$ans" =~ ^[sSyY] ]]
}

# ── Banner ───────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}"
cat << 'BANNER'
  ███████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗
  ██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║
  ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║
  ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║
  ███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗
  ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
BANNER
echo -e "${RESET}"
echo -e "${BOLD}          Monitor de servidores via Telegram${RESET}"
echo

# ── Verificar Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    warn "Docker não encontrado. Instalando..."
    curl -fsSL https://get.docker.com | sh
    ok "Docker instalado."
fi
ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)"

# ── Verificar se está dentro de container (que impede gerenciamento) ──────────
if is_inside_container; then
    title "Atenção: execução dentro de container"
    echo -e " ${YELLOW}Este script está sendo executado dentro de um container Docker/LXC.${RESET}"
    echo -e " Para instalar/atualizar/remover o Sentinel Monitor, execute este script"
    echo -e " diretamente no ${BOLD}host Docker${RESET} (não dentro de um container)."
    echo
    echo -e " Se você estava dentro do container ${CYAN}monitor-node${RESET} ou"
    echo -e " ${CYAN}monitor-master${RESET}, faça:"
    echo -e "   1. Sair do container: ${CYAN}exit${RESET}"
    echo -e "   2. Rodar o script no host: ${CYAN}bash <(curl -fsSL https://raw.githubusercontent.com/MaelllDev/sentinel-monitor/main/setup.sh)${RESET}"
    exit 1
fi

# ── Menu principal ───────────────────────────────────────────────────────────
title "O que deseja fazer?"
echo "  [1] Instalar MASTER  (bot do Telegram + servidor WebSocket)"
echo "  [2] Instalar NODE    (agente de métricas para esta VPS)"
echo "  [3] Atualizar MASTER"
echo "  [4] Atualizar NODE"
echo "  [5] Remover MASTER"
echo "  [6] Remover NODE"
echo "  [7] Remover Tudo (desinstalar bot e containers)"
echo
ask_menu
ACTION="$REPLY"

# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ─────────────────────────────────────────────────────────────────────────────

pull_image() {
    local image="$1"
    info "Baixando imagem ${image}..."
    docker pull "$image"
    ok "Imagem atualizada."
}

remove_container() {
    local name="$1"
    if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
        info "Parando e removendo container ${name}..."
        docker stop "$name" 2>/dev/null || true
        docker rm   "$name" 2>/dev/null || true
        ok "Container ${name} removido."
    fi
}

show_logs() {
    local name="$1"
    if confirm "Exibir logs agora (10 segundos)?"; then
        echo
        timeout 10 docker logs -f "$name" 2>&1 || true
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# [1] INSTALAR MASTER
# ─────────────────────────────────────────────────────────────────────────────
install_master() {
    if is_inside_container; then
        error "Este script está sendo executado dentro de um container Docker. Para gerenciar containers, execute este script no host Docker."
    fi
    title "Instalação do MASTER"

    # ── Coleta de configurações ──────────────────────────────────────────────
    echo -e " Você precisa de:"
    echo -e " • Token do bot → crie via ${CYAN}@BotFather${RESET} no Telegram"
    echo -e " • Chat ID      → obtenha via ${CYAN}@userinfobot${RESET} no Telegram"
    echo

    ask_secret "Token do Telegram (@BotFather)"
    TELEGRAM_TOKEN="$REPLY"
    while [ -z "$TELEGRAM_TOKEN" ]; do
        warn "Token não pode ser vazio."
        ask_secret "Token do Telegram"
        TELEGRAM_TOKEN="$REPLY"
    done

    ask "Seu Chat ID do Telegram" ""
    ALLOWED_CHAT_ID="$REPLY"
    while ! [[ "$ALLOWED_CHAT_ID" =~ ^-?[0-9]+$ ]]; do
        warn "Chat ID deve ser numérico."
        ask "Seu Chat ID" ""
        ALLOWED_CHAT_ID="$REPLY"
    done

    # Detecta IP local sem interromper a instalação se a ferramenta não existir.
    DETECTED_IP=""
    if command -v hostname &>/dev/null; then
        DETECTED_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    fi
    if [ -z "$DETECTED_IP" ] && command -v ip &>/dev/null; then
        DETECTED_IP=$(ip -4 addr show 2>/dev/null \
            | awk '/inet / && $2 !~ /^127\./ {sub(/\/.*/, "", $2); print $2; exit}' || true)
    fi
    ask "IP público ou local deste servidor (usado pelos nodes)" "${DETECTED_IP:-}"
    MASTER_HOST="$REPLY"
    while [ -z "$MASTER_HOST" ]; do
        warn "IP não pode ser vazio."
        ask "IP deste servidor" ""
        MASTER_HOST="$REPLY"
    done

    ask "Porta WebSocket" "8765"
    WS_PORT="$REPLY"

    # Gera API Key
    if command -v python3 &>/dev/null; then
        AUTO_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    else
        AUTO_KEY=$(tr -dc 'a-f0-9' < /dev/urandom | head -c 64)
    fi
    ask "API Key (Enter para usar a gerada automaticamente)" "$AUTO_KEY"
    API_KEY="$REPLY"

    ask "Nome deste servidor no monitor" "$(hostname 2>/dev/null || echo master-local)"
    NODE_NAME="$REPLY"

    ask "Intervalo de métricas (segundos)" "10"
    METRICS_INTERVAL="$REPLY"

    ask "Alerta CPU (%)" "90"
    ALERT_CPU="$REPLY"

    ask "Alerta Memória (%)" "90"
    ALERT_MEMORY="$REPLY"

    ask "Alerta Disco (%)" "90"
    ALERT_DISK="$REPLY"

    # CasaOS
    CASAOS_URL=""; CASAOS_USER=""; CASAOS_PASSWORD=""
    echo
    if confirm "Configurar integração com CasaOS? (opcional)"; then
        ask "URL do CasaOS" "http://${MASTER_HOST}:80"
        CASAOS_URL="$REPLY"
        ask "Usuário do CasaOS" "admin"
        CASAOS_USER="$REPLY"
        ask_secret "Senha do CasaOS"
        CASAOS_PASSWORD="$REPLY"
    fi

    # ── Baixa e sobe o master ────────────────────────────────────────────────
    pull_image "$MASTER_IMAGE"
    pull_image "$NODE_IMAGE"

    remove_container "monitor-master"
    remove_container "monitor-node-local"

    # Cria rede se não existir
    docker network inspect monitor-net &>/dev/null || docker network create monitor-net

    info "Subindo master..."
    docker run -d \
        --name monitor-master \
        --restart unless-stopped \
        --network monitor-net \
        -p "${WS_PORT}:8765" \
        -e TELEGRAM_TOKEN="$TELEGRAM_TOKEN" \
        -e ALLOWED_CHAT_ID="$ALLOWED_CHAT_ID" \
        -e API_KEY="$API_KEY" \
        -e WS_PORT=8765 \
        -e MASTER_HOST="$MASTER_HOST" \
        -e CASAOS_URL="$CASAOS_URL" \
        -e CASAOS_USER="$CASAOS_USER" \
        -e CASAOS_PASSWORD="$CASAOS_PASSWORD" \
        "$MASTER_IMAGE"

    info "Subindo node local..."
    docker run -d \
        --name monitor-node-local \
        --restart unless-stopped \
        --network monitor-net \
        --pid=host \
        -v /proc:/host/proc:ro \
        -v /sys:/host/sys:ro \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -e MASTER_WS_URL="ws://monitor-master:8765" \
        -e API_KEY="$API_KEY" \
        -e NODE_NAME="$NODE_NAME" \
        -e METRICS_INTERVAL="$METRICS_INTERVAL" \
        -e ALERT_CPU="$ALERT_CPU" \
        -e ALERT_MEMORY="$ALERT_MEMORY" \
        -e ALERT_DISK="$ALERT_DISK" \
        "$NODE_IMAGE"

    ok "Master e node local rodando!"
    echo
    echo -e " ${BOLD}API Key (guarde para adicionar nodes):${RESET}"
    echo -e " ${CYAN}${API_KEY}${RESET}"
    echo
    echo -e " Logs:   ${CYAN}docker logs -f monitor-master${RESET}"
    echo -e " Envie ${CYAN}/start${RESET} no Telegram para confirmar."
    echo

    show_logs "monitor-master"
}

# ─────────────────────────────────────────────────────────────────────────────
# [2] INSTALAR NODE
# ─────────────────────────────────────────────────────────────────────────────
install_node() {
    if is_inside_container; then
        error "Este script está sendo executado dentro de um container Docker. Para gerenciar containers, execute este script no host Docker."
    fi
    title "Instalação do NODE"

    ask "Nome desta VPS" "$(hostname 2>/dev/null || echo minha-vps)"
    NODE_NAME="$REPLY"

    ask "IP ou domínio do master" ""
    MASTER_IP="$REPLY"
    while [ -z "$MASTER_IP" ]; do
        warn "IP do master não pode ser vazio."
        ask "IP ou domínio do master" ""
        MASTER_IP="$REPLY"
    done

    ask "Porta WebSocket do master" "8765"
    MASTER_PORT="$REPLY"
    MASTER_WS_URL="ws://${MASTER_IP}:${MASTER_PORT}"

    ask_secret "API Key (mesma do master)"
    API_KEY="$REPLY"
    while [ -z "$API_KEY" ]; do
        warn "API Key não pode ser vazia."
        ask_secret "API Key"
        API_KEY="$REPLY"
    done

    ask "Intervalo de métricas (segundos)" "10"
    METRICS_INTERVAL="$REPLY"

    ask "Alerta CPU (%)" "90"
    ALERT_CPU="$REPLY"

    ask "Alerta Memória (%)" "90"
    ALERT_MEMORY="$REPLY"

    ask "Alerta Disco (%)" "90"
    ALERT_DISK="$REPLY"

    pull_image "$NODE_IMAGE"
    remove_container "monitor-node"

    info "Subindo node '${NODE_NAME}'..."
    docker run -d \
        --name monitor-node \
        --restart unless-stopped \
        --pid=host \
        -v /proc:/host/proc:ro \
        -v /sys:/host/sys:ro \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -e MASTER_WS_URL="$MASTER_WS_URL" \
        -e API_KEY="$API_KEY" \
        -e NODE_NAME="$NODE_NAME" \
        -e METRICS_INTERVAL="$METRICS_INTERVAL" \
        -e ALERT_CPU="$ALERT_CPU" \
        -e ALERT_MEMORY="$ALERT_MEMORY" \
        -e ALERT_DISK="$ALERT_DISK" \
        "$NODE_IMAGE"

    ok "Node '${NODE_NAME}' rodando!"
    echo
    echo -e " Master:  ${CYAN}${MASTER_WS_URL}${RESET}"
    echo -e " Logs:    ${CYAN}docker logs -f monitor-node${RESET}"
    echo

    show_logs "monitor-node"
}

# ─────────────────────────────────────────────────────────────────────────────
# [3] ATUALIZAR MASTER
# ─────────────────────────────────────────────────────────────────────────────
update_master() {
    if is_inside_container; then
        error "Este script está sendo executado dentro de um container Docker. Para gerenciar containers, execute este script no host Docker."
    fi
    title "Atualização do MASTER"

    # Salva envs do container atual antes de remover
    if ! docker inspect monitor-master &>/dev/null; then
        error "Container monitor-master não encontrado. Instale primeiro (opção 1)."
    fi

    info "Salvando configuração atual..."
    ENV_JSON=$(docker inspect monitor-master --format '{{json .Config.Env}}')

    get_env() {
        echo "$ENV_JSON" | tr ',' '\n' | grep "^\"${1}=" | head -1 | sed 's/.*=//;s/"$//'
    }

    TELEGRAM_TOKEN=$(get_env TELEGRAM_TOKEN)
    ALLOWED_CHAT_ID=$(get_env ALLOWED_CHAT_ID)
    API_KEY=$(get_env API_KEY)
    WS_PORT=$(get_env WS_PORT)
    MASTER_HOST=$(get_env MASTER_HOST)
    CASAOS_URL=$(get_env CASAOS_URL)
    CASAOS_USER=$(get_env CASAOS_USER)
    CASAOS_PASSWORD=$(get_env CASAOS_PASSWORD)

    # Salva envs do node local também
    NODE_ENV_JSON=""
    if docker inspect monitor-node-local &>/dev/null; then
        NODE_ENV_JSON=$(docker inspect monitor-node-local --format '{{json .Config.Env}}')
        get_node_env() {
            echo "$NODE_ENV_JSON" | tr ',' '\n' | grep "^\"${1}=" | head -1 | sed 's/.*=//;s/"$//'
        }
        NODE_NAME=$(get_node_env NODE_NAME)
        METRICS_INTERVAL=$(get_node_env METRICS_INTERVAL)
        ALERT_CPU=$(get_node_env ALERT_CPU)
        ALERT_MEMORY=$(get_node_env ALERT_MEMORY)
        ALERT_DISK=$(get_node_env ALERT_DISK)
    fi

    pull_image "$MASTER_IMAGE"
    pull_image "$NODE_IMAGE"

    remove_container "monitor-master"
    remove_container "monitor-node-local"

    docker network inspect monitor-net &>/dev/null || docker network create monitor-net

    info "Subindo master atualizado..."
    docker run -d \
        --name monitor-master \
        --restart unless-stopped \
        --network monitor-net \
        -p "${WS_PORT:-8765}:8765" \
        -e TELEGRAM_TOKEN="$TELEGRAM_TOKEN" \
        -e ALLOWED_CHAT_ID="$ALLOWED_CHAT_ID" \
        -e API_KEY="$API_KEY" \
        -e WS_PORT="${WS_PORT:-8765}" \
        -e MASTER_HOST="$MASTER_HOST" \
        -e CASAOS_URL="$CASAOS_URL" \
        -e CASAOS_USER="$CASAOS_USER" \
        -e CASAOS_PASSWORD="$CASAOS_PASSWORD" \
        "$MASTER_IMAGE"

    if [ -n "$NODE_ENV_JSON" ]; then
        info "Subindo node local atualizado..."
        docker run -d \
            --name monitor-node-local \
            --restart unless-stopped \
            --network monitor-net \
            --pid=host \
            -v /proc:/host/proc:ro \
            -v /sys:/host/sys:ro \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -e MASTER_WS_URL="ws://monitor-master:8765" \
            -e API_KEY="$API_KEY" \
            -e NODE_NAME="${NODE_NAME:-master-local}" \
            -e METRICS_INTERVAL="${METRICS_INTERVAL:-10}" \
            -e ALERT_CPU="${ALERT_CPU:-90}" \
            -e ALERT_MEMORY="${ALERT_MEMORY:-90}" \
            -e ALERT_DISK="${ALERT_DISK:-90}" \
            "$NODE_IMAGE"
    fi

    ok "Master atualizado e rodando!"
    show_logs "monitor-master"
}

# ─────────────────────────────────────────────────────────────────────────────
# [4] ATUALIZAR NODE
# ─────────────────────────────────────────────────────────────────────────────
update_node() {
    if is_inside_container; then
        error "Este script está sendo executado dentro de um container Docker. Para gerenciar containers, execute este script no host Docker."
    fi
    title "Atualização do NODE"

    # Detecta nome do container (monitor-node ou monitor-node-local)
    NODE_CONTAINER=""
    for name in monitor-node monitor-node-local; do
        if docker inspect "$name" &>/dev/null; then
            NODE_CONTAINER="$name"
            break
        fi
    done

    if [ -z "$NODE_CONTAINER" ]; then
        error "Nenhum container de node encontrado. Instale primeiro (opção 2)."
    fi

    info "Container encontrado: ${NODE_CONTAINER}"
    info "Salvando configuração atual..."
    ENV_JSON=$(docker inspect "$NODE_CONTAINER" --format '{{json .Config.Env}}')

    get_env() {
        echo "$ENV_JSON" | tr ',' '\n' | grep "^\"${1}=" | head -1 | sed 's/.*=//;s/"$//'
    }

    MASTER_WS_URL=$(get_env MASTER_WS_URL)
    API_KEY=$(get_env API_KEY)
    NODE_NAME=$(get_env NODE_NAME)
    METRICS_INTERVAL=$(get_env METRICS_INTERVAL)
    ALERT_CPU=$(get_env ALERT_CPU)
    ALERT_MEMORY=$(get_env ALERT_MEMORY)
    ALERT_DISK=$(get_env ALERT_DISK)

    # Detecta se estava numa rede customizada
    NETWORK=$(docker inspect "$NODE_CONTAINER" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -1)

    pull_image "$NODE_IMAGE"
    remove_container "$NODE_CONTAINER"

    info "Subindo node '${NODE_NAME}' atualizado..."
    NETWORK_ARG=""
    [ -n "$NETWORK" ] && [ "$NETWORK" != "bridge" ] && NETWORK_ARG="--network $NETWORK"

    docker run -d \
        --name "$NODE_CONTAINER" \
        --restart unless-stopped \
        $NETWORK_ARG \
        --pid=host \
        -v /proc:/host/proc:ro \
        -v /sys:/host/sys:ro \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -e MASTER_WS_URL="$MASTER_WS_URL" \
        -e API_KEY="$API_KEY" \
        -e NODE_NAME="$NODE_NAME" \
        -e METRICS_INTERVAL="${METRICS_INTERVAL:-10}" \
        -e ALERT_CPU="${ALERT_CPU:-90}" \
        -e ALERT_MEMORY="${ALERT_MEMORY:-90}" \
        -e ALERT_DISK="${ALERT_DISK:-90}" \
        "$NODE_IMAGE"

    ok "Node '${NODE_NAME}' atualizado e rodando!"
    show_logs "$NODE_CONTAINER"
}

# ─────────────────────────────────────────────────────────────────────────────
# [5] REMOVER MASTER
# ─────────────────────────────────────────────────────────────────────────────
remove_master() {
    if is_inside_container; then
        error "Este script está sendo executado dentro de um container Docker. Para gerenciar containers, execute este script no host Docker."
    fi
    title "Remover MASTER"
    confirm "Tem certeza? Isso vai parar e remover o bot e o node local." || { info "Cancelado."; exit 0; }
    remove_container "monitor-master"
    remove_container "monitor-node-local"
    docker network rm monitor-net 2>/dev/null || true
    ok "Master removido."
}

# ─────────────────────────────────────────────────────────────────────────────
# [7] REMOVER TUDO (desinstalar bot e containers)
# ─────────────────────────────────────────────────────────────────────────────
remove_all() {
    if is_inside_container; then
        error "Este script está sendo executado dentro de um container Docker. Para gerenciar containers, execute este script no host Docker."
    fi
    title "Remover TUDO (desinstalar)"
    confirm "Tem certeza? Isso vai parar, remover todos os containers e limpar o setup (excluindo .env e arquivos do bot)." || { info "Cancelado."; exit 0; }
    remove_container "monitor-master"
    remove_container "monitor-node-local"
    remove_container "monitor-node"
    docker network rm monitor-net 2>/dev/null || true
    rm -f .env .env.example .gitignore
    ok "Setup Sentinel Monitor desinstalado completamente."
}

# ─────────────────────────────────────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────────────────────────────────────
case "$ACTION" in
    1) install_master ;;
    2) install_node   ;;
    3) update_master  ;;
    4) update_node    ;;
    5) remove_master  ;;
    6) remove_node    ;;
    7) remove_all     ;;
    *) error "Opção inválida: ${ACTION}" ;;
esac