#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Sentinel Monitor — Setup interativo do MASTER
# Uso: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── Cores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ──────────────────────────────────────────────────────────────────
info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${RESET} $*"; }
error()   { echo -e "${RED}[ERRO]${RESET}  $*"; exit 1; }

# Executa um comando com privilégio de root, independente do sistema.
# Funciona com: sudo, doas, ou direto se já for root.
asroot() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo &>/dev/null; then
        sudo "$@"
    elif command -v doas &>/dev/null; then
        doas "$@"
    else
        error "Nenhum método de elevação de privilégio encontrado (sudo/doas).\nExecute este script como root: su -c 'bash setup.sh'"
    fi
}

ask() {
    # ask "Pergunta" "valor_default" → imprime prompt, lê e devolve em $REPLY
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
    # confirm "Pergunta" → retorna 0 para sim, 1 para não
    echo -ne "${BOLD}$1${RESET} [${GREEN}s${RESET}/${RED}n${RESET}]: "
    read -r ans
    [[ "$ans" =~ ^[sSyY] ]]
}

# ── Banner ───────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}"
echo "  ███████╗██╗      ██████╗ ██╗    ██╗"
echo "  ██╔════╝██║     ██╔═══██╗██║    ██║"
echo "  █████╗  ██║     ██║   ██║██║ █╗ ██║"
echo "  ██╔══╝  ██║     ██║   ██║██║███╗██║"
echo "  ██║     ███████╗╚██████╔╝╚███╔███╔╝"
echo "  ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝"
echo -e "${RESET}"
echo -e "${BOLD}       Sentinel Monitor — Setup Master${RESET}"
echo -e "       ─────────────────────────────────"
echo

# ── Verificar dependências ───────────────────────────────────────────────────
info "Verificando dependências..."

if ! command -v docker &>/dev/null; then
    error "Docker não encontrado. Instale em https://docs.docker.com/get-docker/"
fi
success "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1) encontrado"

if ! docker compose version &>/dev/null 2>&1 && ! docker-compose --version &>/dev/null 2>&1; then
    error "Docker Compose não encontrado. Instale junto com o Docker."
fi
success "Docker Compose encontrado"

# Detecta o comando correto de compose
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

echo

# ── .env já existe? ──────────────────────────────────────────────────────────
if [ -f ".env" ]; then
    warn "Arquivo .env já existe."
    if ! confirm "Deseja reconfigurar e sobrescrever?"; then
        info "Mantendo .env existente."
        ENV_EXISTS=true
    fi
fi

# ── Coleta de configurações ──────────────────────────────────────────────────
if [ "${ENV_EXISTS}" != "true" ]; then

    # ── Bot do Telegram ──────────────────────────────────────────────────────
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}  Configurações do Bot${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo
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

    ask "Seu Chat ID do Telegram (@userinfobot)" ""
    ALLOWED_CHAT_ID="$REPLY"
    while ! [[ "$ALLOWED_CHAT_ID" =~ ^-?[0-9]+$ ]]; do
        warn "Chat ID deve ser numérico (ex: 123456789 ou -100123456789)."
        ask "Seu Chat ID" ""
        ALLOWED_CHAT_ID="$REPLY"
    done

    # ── Rede ─────────────────────────────────────────────────────────────────
    echo
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}  Configurações de Rede (rede local)${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo

    # Detecta IPs locais (exclui loopback 127.x e endereços IPv6)
    LOCAL_IPS=()
    while IFS= read -r ip; do
        [[ "$ip" == 127.* ]] && continue
        [[ "$ip" == *:* ]]   && continue   # pula IPv6
        LOCAL_IPS+=("$ip")
    done < <(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' || \
             ip -4 addr show 2>/dev/null | grep -oP '(?<=inet )\d+\.\d+\.\d+\.\d+' | grep -v '^127\.')

    if [ ${#LOCAL_IPS[@]} -eq 0 ]; then
        warn "Nenhum IP local detectado. Verifique sua interface de rede."
        DETECTED_IP=""
    elif [ ${#LOCAL_IPS[@]} -eq 1 ]; then
        DETECTED_IP="${LOCAL_IPS[0]}"
        info "IP local detectado: ${CYAN}${DETECTED_IP}${RESET}"
    else
        info "Múltiplos IPs locais encontrados:"
        for i in "${!LOCAL_IPS[@]}"; do
            echo -e "   ${CYAN}[$((i+1))]${RESET} ${LOCAL_IPS[$i]}"
        done
        echo -ne "${BOLD}Escolha o número do IP a usar${RESET} [${CYAN}1${RESET}]: "
        read -r ip_choice
        ip_choice="${ip_choice:-1}"
        if [[ "$ip_choice" =~ ^[0-9]+$ ]] && [ "$ip_choice" -ge 1 ] && [ "$ip_choice" -le "${#LOCAL_IPS[@]}" ]; then
            DETECTED_IP="${LOCAL_IPS[$((ip_choice-1))]}"
        else
            DETECTED_IP="${LOCAL_IPS[0]}"
        fi
        info "Usando: ${CYAN}${DETECTED_IP}${RESET}"
    fi

    ask "IP local deste PC master (nodes usarão este endereço)" "${DETECTED_IP:-192.168.1.1}"
    MASTER_HOST="$REPLY"

    ask "Porta WebSocket (nodes se conectam nesta porta)" "8765"
    WS_PORT="$REPLY"
    while ! [[ "$WS_PORT" =~ ^[0-9]+$ ]] || [ "$WS_PORT" -lt 1 ] || [ "$WS_PORT" -gt 65535 ]; do
        warn "Porta inválida. Use um número entre 1 e 65535."
        ask "Porta WebSocket" "8765"
        WS_PORT="$REPLY"
    done

    # ── API Key ───────────────────────────────────────────────────────────────
    echo
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}  API Key${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo

    # Gera chave automática se Python disponível
    if command -v python3 &>/dev/null; then
        AUTO_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        info "Chave gerada automaticamente."
        ask "API Key (deixe em branco para usar a gerada)" "$AUTO_KEY"
        API_KEY="$REPLY"
    else
        warn "Python3 não encontrado. Insira uma API Key manualmente."
        ask_secret "API Key (mínimo 16 caracteres)"
        API_KEY="$REPLY"
        while [ ${#API_KEY} -lt 16 ]; do
            warn "Chave muito curta. Use no mínimo 16 caracteres."
            ask_secret "API Key"
            API_KEY="$REPLY"
        done
    fi

    # ── Node local (padrões) ─────────────────────────────────────────────────
    echo
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}  Configurações dos Nodes (padrões)${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo
    echo -e " ${CYAN}Este PC também será monitorado como um node local.${RESET}"
    echo

    HOSTNAME_DEFAULT=$(hostname 2>/dev/null || echo "master-local")
    ask "Nome deste PC no monitor" "$HOSTNAME_DEFAULT"
    NODE_NAME="$REPLY"

    ask "Intervalo de envio de métricas (segundos)" "10"
    METRICS_INTERVAL="$REPLY"

    ask "Threshold de alerta CPU (%)" "90"
    ALERT_CPU="$REPLY"

    ask "Threshold de alerta Memória (%)" "90"
    ALERT_MEMORY="$REPLY"

    ask "Threshold de alerta Disco (%)" "90"
    ALERT_DISK="$REPLY"

    # ── CasaOS (opcional) ────────────────────────────────────────────────────
    echo
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}  Integração CasaOS (opcional)${RESET}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo
    echo -e " O CasaOS permite gerenciar apps via os comandos:"
    echo -e " ${CYAN}/casa  /casa_iniciar  /casa_parar  /casa_logs  /casa_atualizar${RESET}"
    echo -e " Deixe em branco para desativar."
    echo

    CASAOS_URL=""
    CASAOS_USER=""
    CASAOS_PASSWORD=""

    if confirm "Configurar integração com CasaOS?"; then
        ask "URL base do CasaOS (ex: http://192.168.1.100:80)" "http://${MASTER_HOST}:80"
        CASAOS_URL="$REPLY"

        ask "Usuário do CasaOS" "admin"
        CASAOS_USER="$REPLY"
        while [ -z "$CASAOS_USER" ]; do
            warn "Usuário não pode ser vazio."
            ask "Usuário do CasaOS" "admin"
            CASAOS_USER="$REPLY"
        done

        ask_secret "Senha do CasaOS"
        CASAOS_PASSWORD="$REPLY"
        while [ -z "$CASAOS_PASSWORD" ]; do
            warn "Senha não pode ser vazia."
            ask_secret "Senha do CasaOS"
            CASAOS_PASSWORD="$REPLY"
        done

        success "CasaOS configurado: ${CYAN}${CASAOS_URL}${RESET} (usuário: ${CYAN}${CASAOS_USER}${RESET})"
    else
        info "Integração CasaOS desativada. Configure depois editando o .env."
    fi

    # ── Grava o .env ─────────────────────────────────────────────────────────
    echo
    info "Gravando .env..."

    cat > .env <<EOF
# Gerado pelo setup.sh em $(date '+%Y-%m-%d %H:%M:%S')

# ── MASTER ──────────────────────────────────────────────
TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
ALLOWED_CHAT_ID=${ALLOWED_CHAT_ID}
API_KEY=${API_KEY}
MASTER_HOST=${MASTER_HOST}
WS_PORT=${WS_PORT}

# ── NODE (padrões usados no docker-compose) ──────────────
MASTER_WS_URL=ws://${MASTER_HOST}:${WS_PORT}
NODE_NAME=${NODE_NAME}
METRICS_INTERVAL=${METRICS_INTERVAL}

# ── ALERTAS ──────────────────────────────────────────────
ALERT_CPU=${ALERT_CPU}
ALERT_MEMORY=${ALERT_MEMORY}
ALERT_DISK=${ALERT_DISK}

# ── CASAOS (opcional) ────────────────────────────────────
# Deixe em branco para desativar os comandos /casa*
CASAOS_URL=${CASAOS_URL}
CASAOS_USER=${CASAOS_USER}
CASAOS_PASSWORD=${CASAOS_PASSWORD}
EOF

    success ".env criado com sucesso!"
fi

# ── Resumo ───────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Resumo da configuração${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
# Lê .env para exibir resumo (sem mostrar valores secretos completos)
source .env 2>/dev/null || true
echo -e " Token:       ${CYAN}${TELEGRAM_TOKEN:0:10}...${RESET}"
echo -e " Chat ID:     ${CYAN}${ALLOWED_CHAT_ID}${RESET}"
echo -e " Master IP:   ${CYAN}${MASTER_HOST}:${WS_PORT}${RESET}"
echo -e " API Key:     ${CYAN}${API_KEY:0:8}...${RESET}"
echo -e " Node local:  ${CYAN}${NODE_NAME:-master-local}${RESET}"
if [ -n "$CASAOS_URL" ]; then
    echo -e " CasaOS URL:  ${CYAN}${CASAOS_URL}${RESET}"
    echo -e " CasaOS User: ${CYAN}${CASAOS_USER}${RESET}"
else
    echo -e " CasaOS:      ${YELLOW}não configurado${RESET}"
fi
echo

# ── Configura sudo sem senha para reboot/poweroff ────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Permissões sudo (reboot/shutdown remoto)${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
echo -e " Os comandos ${CYAN}/restart${RESET} e ${CYAN}/shutdown${RESET} do bot precisam"
echo -e " executar ${CYAN}sudo reboot${RESET} e ${CYAN}sudo poweroff${RESET} sem senha."
echo

if confirm "Configurar sudo automático para reboot/poweroff?"; then
    CURRENT_USER="${SUDO_USER:-$(whoami)}"
    SUDOERS_FILE="/etc/sudoers.d/monitor-reboot"

    REBOOT_BIN=$(which reboot 2>/dev/null || echo "/sbin/reboot")
    POWEROFF_BIN=$(which poweroff 2>/dev/null || echo "/sbin/poweroff")
    SHUTDOWN_BIN=$(which shutdown 2>/dev/null || echo "/sbin/shutdown")

    asroot tee "$SUDOERS_FILE" > /dev/null <<EOF
# Sentinel Monitor — permite reboot/poweroff sem senha
# Gerado automaticamente pelo setup.sh
${CURRENT_USER} ALL=(ALL) NOPASSWD: ${REBOOT_BIN}
${CURRENT_USER} ALL=(ALL) NOPASSWD: ${POWEROFF_BIN}
${CURRENT_USER} ALL=(ALL) NOPASSWD: ${SHUTDOWN_BIN}
EOF

    if asroot visudo -cf "$SUDOERS_FILE" &>/dev/null; then
        asroot chmod 440 "$SUDOERS_FILE"
        success "Sudo configurado para o usuário '${CURRENT_USER}'."
        echo -e " Arquivo: ${CYAN}${SUDOERS_FILE}${RESET}"
    else
        asroot rm -f "$SUDOERS_FILE"
        warn "Erro ao validar sudoers. Configure manualmente:"
        echo -e "    ${CYAN}echo '${CURRENT_USER} ALL=(ALL) NOPASSWD: ${REBOOT_BIN}, ${POWEROFF_BIN}' | tee ${SUDOERS_FILE}${RESET}"
    fi
else
    warn "Sudo não configurado. Os comandos /restart e /shutdown precisarão de senha."
fi

# ── Build e subida do container ──────────────────────────────────────────────
echo
if confirm "Deseja fazer o build e subir o master agora?"; then
    echo
    info "Fazendo build das imagens..."
    $COMPOSE build master node-local

    echo
    info "Subindo master + node local..."
    $COMPOSE up -d master node-local

    echo
    success "Master e node local rodando!"
    echo
    info "Acompanhe os logs com:"
    echo -e "    ${CYAN}${COMPOSE} logs -f master node-local${RESET}"
    echo
    echo -e " Envie ${CYAN}/start${RESET} no Telegram para verificar."

    echo
    if confirm "Exibir logs agora (10 segundos)?"; then
        echo
        timeout 10 $COMPOSE logs -f master node-local || true
    fi
else
    echo
    info "Para subir depois, execute:"
    echo -e "    ${CYAN}${COMPOSE} up -d master node-local${RESET}"
fi

# ── Autostart no boot via systemd ────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Autostart no boot${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo

if confirm "Habilitar início automático com o sistema (systemd)?"; then
    INSTALL_DIR="$(pwd)"
    SERVICE_FILE="/etc/systemd/system/monitor.service"

    sed "s|%INSTALL_DIR%|${INSTALL_DIR}|g" monitor.service > /tmp/monitor.service

    DOCKER_COMPOSE_BIN=$(which docker 2>/dev/null || echo "/usr/bin/docker")
    sed -i "s|/usr/bin/docker compose|${DOCKER_COMPOSE_BIN} compose|g" /tmp/monitor.service

    asroot cp /tmp/monitor.service "$SERVICE_FILE"
    rm -f /tmp/monitor.service

    asroot systemctl daemon-reload
    asroot systemctl enable monitor.service

    success "Serviço systemd instalado e habilitado!"
    echo -e " O monitor vai iniciar automaticamente com o sistema."
    echo
    info "Comandos úteis do serviço:"
    echo -e "  Status:   ${CYAN}sudo systemctl status monitor${RESET}"
    echo -e "  Parar:    ${CYAN}sudo systemctl stop monitor${RESET}"
    echo -e "  Iniciar:  ${CYAN}sudo systemctl start monitor${RESET}"
    echo -e "  Logs:     ${CYAN}sudo journalctl -u monitor -f${RESET}"
else
    info "Autostart não configurado. Para habilitar depois:"
    echo -e "    ${CYAN}sudo bash setup.sh${RESET}  (e responda 's' para autostart)"
fi

# ── Instruções para os nodes ─────────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Próximos passos — adicionar VPS${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
echo -e " Em cada VPS que quiser monitorar, execute:"
echo
echo -e "    ${CYAN}bash install-node.sh${RESET}"
echo
echo -e " O script vai pedir o IP do master e a API Key."
echo -e " Ou use ${CYAN}/integrar${RESET} no Telegram — o bot gera o"
echo -e " comando completo automaticamente."
echo
success "Setup concluído!"
