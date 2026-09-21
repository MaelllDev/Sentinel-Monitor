#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Sentinel Monitor — Instalação do NODE na VPS
# Uso: bash install-node.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── Cores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${RESET} $*"; }
error()   { echo -e "${RED}[ERRO]${RESET}  $*"; exit 1; }

# Executa com privilégio de root: direto se root, sudo, ou doas.
asroot() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo &>/dev/null; then
        sudo "$@"
    elif command -v doas &>/dev/null; then
        doas "$@"
    else
        error "Nenhum método de elevação encontrado (sudo/doas).\nExecute como root: su -c 'bash install-node.sh'"
    fi
}

ask() {
    local prompt="$1"
    local default="$2"
    if [ -n "$default" ]; then
        echo -ne "${BOLD}${prompt}${RESET} [${CYAN}${default}${RESET}]: "
    else
        echo -ne "${BOLD}${prompt}${RESET}: "
    fi
    read -r REPLY
    if [ -z "$REPLY" ] && [ -n "$default" ]; then
        REPLY="$default"
    fi
}

ask_secret() {
    local prompt="$1"
    echo -ne "${BOLD}${prompt}${RESET}: "
    read -rs REPLY
    echo
}

confirm() {
    echo -ne "${BOLD}$1${RESET} [${GREEN}s${RESET}/${RED}n${RESET}]: "
    read -r ans
    [[ "$ans" =~ ^[sSyY] ]]
}

# ── Banner ───────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}"
echo "  ███╗   ██╗ ██████╗ ██████╗ ███████╗"
echo "  ████╗  ██║██╔═══██╗██╔══██╗██╔════╝"
echo "  ██╔██╗ ██║██║   ██║██║  ██║█████╗  "
echo "  ██║╚██╗██║██║   ██║██║  ██║██╔══╝  "
echo "  ██║ ╚████║╚██████╔╝██████╔╝███████╗"
echo "  ╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚══════╝"
echo -e "${RESET}"
echo -e "${BOLD}     Sentinel Monitor — Setup Node${RESET}"
echo -e "     ───────────────────────────────"
echo

# ── Verificar Docker ─────────────────────────────────────────────────────────
info "Verificando Docker..."
if ! command -v docker &>/dev/null; then
    warn "Docker não encontrado. Tentando instalar automaticamente..."
    echo
    if confirm "Instalar Docker agora? (requer privilégio de root)"; then
        curl -fsSL https://get.docker.com | asroot sh
        asroot usermod -aG docker "$USER" || true
        success "Docker instalado!"
        warn "Se necessário, faça logout e login novamente para usar Docker sem sudo."
    else
        error "Docker é necessário. Instale em https://docs.docker.com/get-docker/"
    fi
fi
success "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1) encontrado"
echo

# ── Configurações ─────────────────────────────────────────────────────────────
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Configurações do Node${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo

# Nome do servidor
HOSTNAME_DEFAULT=$(hostname 2>/dev/null || echo "minha-vps")
ask "Nome desta VPS" "$HOSTNAME_DEFAULT"
NODE_NAME="$REPLY"

# URL do master
ask "IP ou domínio do master (PC com o bot)" ""
MASTER_IP="$REPLY"
while [ -z "$MASTER_IP" ]; do
    warn "IP do master não pode ser vazio."
    ask "IP ou domínio do master" ""
    MASTER_IP="$REPLY"
done

ask "Porta WebSocket do master" "8765"
MASTER_PORT="$REPLY"

MASTER_WS_URL="ws://${MASTER_IP}:${MASTER_PORT}"
info "URL do master: ${CYAN}${MASTER_WS_URL}${RESET}"
echo

# API Key
ask_secret "API Key (mesma configurada no master)"
API_KEY="$REPLY"
while [ -z "$API_KEY" ]; do
    warn "API Key não pode ser vazia."
    ask_secret "API Key"
    API_KEY="$REPLY"
done

echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Configurações de monitoramento${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo

ask "Intervalo de métricas (segundos)" "10"
METRICS_INTERVAL="$REPLY"

ask "Alerta CPU (%)" "90"
ALERT_CPU="$REPLY"

ask "Alerta Memória (%)" "90"
ALERT_MEMORY="$REPLY"

ask "Alerta Disco (%)" "90"
ALERT_DISK="$REPLY"

# ── Cria .env do node ────────────────────────────────────────────────────────
echo
info "Criando .env..."

cat > .env <<EOF
# Gerado pelo install-node.sh em $(date '+%Y-%m-%d %H:%M:%S')
MASTER_WS_URL=${MASTER_WS_URL}
API_KEY=${API_KEY}
NODE_NAME=${NODE_NAME}
METRICS_INTERVAL=${METRICS_INTERVAL}
ALERT_CPU=${ALERT_CPU}
ALERT_MEMORY=${ALERT_MEMORY}
ALERT_DISK=${ALERT_DISK}
EOF

success ".env criado!"

# ── Configura sudo sem senha para reboot/poweroff ────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Permissões sudo (reboot/shutdown remoto)${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
echo -e " Necessário para os comandos ${CYAN}/restart${RESET} e ${CYAN}/shutdown${RESET}"
echo -e " funcionarem sem pedir senha ao bot."
echo

if confirm "Configurar sudo automático para reboot/poweroff nesta VPS?"; then
    CURRENT_USER="${SUDO_USER:-$(whoami)}"
    SUDOERS_FILE="/etc/sudoers.d/monitor-reboot"

    REBOOT_BIN=$(which reboot   2>/dev/null || echo "/sbin/reboot")
    POWEROFF_BIN=$(which poweroff 2>/dev/null || echo "/sbin/poweroff")
    SHUTDOWN_BIN=$(which shutdown 2>/dev/null || echo "/sbin/shutdown")

    asroot tee "$SUDOERS_FILE" > /dev/null <<EOF
# Sentinel Monitor — permite reboot/poweroff sem senha
# Gerado automaticamente pelo install-node.sh
${CURRENT_USER} ALL=(ALL) NOPASSWD: ${REBOOT_BIN}
${CURRENT_USER} ALL=(ALL) NOPASSWD: ${POWEROFF_BIN}
${CURRENT_USER} ALL=(ALL) NOPASSWD: ${SHUTDOWN_BIN}
EOF

    if asroot visudo -cf "$SUDOERS_FILE" &>/dev/null; then
        asroot chmod 440 "$SUDOERS_FILE"
        success "Sudo configurado para '${CURRENT_USER}'."
    else
        asroot rm -f "$SUDOERS_FILE"
        warn "Falha ao validar sudoers. Configure manualmente:"
        echo -e "    ${CYAN}echo '${CURRENT_USER} ALL=(ALL) NOPASSWD: ${REBOOT_BIN}, ${POWEROFF_BIN}' | tee ${SUDOERS_FILE}${RESET}"
    fi
else
    warn "Sudo não configurado. /restart e /shutdown precisarão de senha nesta VPS."
fi

# ── Build da imagem ───────────────────────────────────────────────────────────
echo
info "Verificando se a pasta node/ existe..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/node/Dockerfile" ]; then
    error "Pasta node/ não encontrada. Execute este script na raiz do projeto."
fi

info "Fazendo build da imagem monitor-node..."
docker build -t monitor-node "$SCRIPT_DIR/node/"
success "Imagem criada!"

# ── Remove container antigo se existir ───────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^monitor-node$"; then
    warn "Container monitor-node já existe. Removendo versão antiga..."
    docker stop monitor-node 2>/dev/null || true
    docker rm monitor-node 2>/dev/null || true
fi

# ── Sobe o container ─────────────────────────────────────────────────────────
info "Subindo container do node..."

docker run -d \
    --name monitor-node \
    --restart unless-stopped \
    --env-file .env \
    --pid=host \
    -v /proc:/host/proc:ro \
    -v /sys:/host/sys:ro \
    -v /var/run/docker.sock:/var/run/docker.sock \
    monitor-node

success "Node '${NODE_NAME}' rodando!"

# ── Status final ─────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Resumo${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e " Nome:    ${CYAN}${NODE_NAME}${RESET}"
echo -e " Master:  ${CYAN}${MASTER_WS_URL}${RESET}"
echo -e " Status:  $(docker inspect -f '{{.State.Status}}' monitor-node 2>/dev/null | tr '[:lower:]' '[:upper:]')"
echo

info "Comandos úteis:"
echo -e "  Ver logs:     ${CYAN}docker logs -f monitor-node${RESET}"
echo -e "  Parar:        ${CYAN}docker stop monitor-node${RESET}"
echo -e "  Reiniciar:    ${CYAN}docker restart monitor-node${RESET}"
echo -e "  Remover:      ${CYAN}docker rm -f monitor-node${RESET}"
echo

if confirm "Exibir logs agora (10 segundos)?"; then
    echo
    timeout 10 docker logs -f monitor-node || true
fi

echo
success "Instalação do node concluída!"
echo -e " Verifique o Telegram — o bot deve notificar a conexão de ${CYAN}${NODE_NAME}${RESET}."
echo
