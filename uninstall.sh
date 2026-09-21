#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Sentinel Monitor — Desinstalação
# Remove containers, imagens Docker e limpa arquivos de configuração.
# Uso: bash uninstall.sh
# ─────────────────────────────────────────────────────────────────────────────

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
skipped() { echo -e "       ${YELLOW}(não encontrado, pulando)${RESET}"; }

# Executa com privilégio de root: direto se root, sudo, ou doas.
asroot() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo &>/dev/null; then
        sudo "$@"
    elif command -v doas &>/dev/null; then
        doas "$@"
    else
        warn "Sem sudo/doas — tentando executar diretamente: $*"
        "$@"
    fi
}

confirm() {
    echo -ne "${BOLD}$1${RESET} [${GREEN}s${RESET}/${RED}n${RESET}]: "
    read -r ans
    [[ "$ans" =~ ^[sSyY] ]]
}

# ── Banner ───────────────────────────────────────────────────────────────────
clear
echo -e "${RED}"
echo "  ██╗   ██╗███╗   ██╗██╗███╗   ██╗███████╗████████╗ █████╗ ██╗     ██╗"
echo "  ██║   ██║████╗  ██║██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██║     ██║"
echo "  ██║   ██║██╔██╗ ██║██║██╔██╗ ██║███████╗   ██║   ███████║██║     ██║"
echo "  ██║   ██║██║╚██╗██║██║██║╚██╗██║╚════██║   ██║   ██╔══██║██║     ██║"
echo "  ╚██████╔╝██║ ╚████║██║██║ ╚████║███████║   ██║   ██║  ██║███████╗███████╗"
echo "   ╚═════╝ ╚═╝  ╚═══╝╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝"
echo -e "${RESET}"
echo -e "${BOLD}        Sentinel Monitor — Desinstalação${RESET}"
echo -e "        ──────────────────────────────────"
echo

warn "Este script vai remover o monitor do ar."
echo -e " Serão removidos:"
echo -e "   • Container  ${CYAN}monitor-master${RESET}"
echo -e "   • Container  ${CYAN}monitor-node-local${RESET} (node do próprio PC)"
echo -e "   • Container  ${CYAN}monitor-node${RESET} (se existir)"
echo -e "   • Imagem     ${CYAN}telegram-server-monitor-master${RESET}"
echo -e "   • Imagem     ${CYAN}telegram-server-monitor-node-local${RESET}"
echo -e "   • Imagem     ${CYAN}monitor-node${RESET}"
echo -e "   • Rede       ${CYAN}monitor-net${RESET}"
echo -e "   • Arquivo    ${CYAN}.env${RESET} (opcional)"
echo -e "   • Serviço    ${CYAN}monitor.service${RESET} (systemd, se existir)"
echo -e "   • Sudoers    ${CYAN}/etc/sudoers.d/monitor-reboot${RESET} (se existir)"
echo
echo -e " ${YELLOW}Isso NÃO remove o código-fonte.${RESET}"
echo

if ! confirm "Confirma a desinstalação?"; then
    echo
    info "Operação cancelada."
    exit 0
fi

echo

# Detecta o comando correto de compose
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
elif docker-compose --version &>/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    COMPOSE=""
fi

# ── Para e remove via docker compose (se disponível) ─────────────────────────
if [ -n "$COMPOSE" ] && [ -f "docker-compose.yml" ]; then
    info "Parando serviços via docker compose..."
    $COMPOSE down --remove-orphans 2>/dev/null && success "Compose: serviços parados." || true
    echo
fi

# ── Remove containers individualmente ────────────────────────────────────────
CONTAINERS=(
    "monitor-master"
    "monitor-node-local"
    "monitor-node"
)

info "Removendo containers..."
for cname in "${CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
        docker stop "$cname" 2>/dev/null || true
        docker rm   "$cname" 2>/dev/null || true
        success "Container ${cname} removido."
    else
        echo -ne "  Container ${CYAN}${cname}${RESET}"
        skipped
    fi
done
echo

# ── Remove imagens ────────────────────────────────────────────────────────────
info "Removendo imagens Docker..."

IMAGES=(
    "telegram-server-monitor-master"
    "telegram-server-monitor-node-local"
    "telegram-server-monitor_master"
    "telegram-server-monitor_node-local"
    "monitor-node"
    "monitor-master"
)

for img in "${IMAGES[@]}"; do
    if docker image inspect "$img" &>/dev/null 2>&1; then
        docker rmi "$img" 2>/dev/null && success "Imagem ${img} removida." || \
            warn "Não foi possível remover ${img} (pode estar em uso)."
    else
        echo -ne "  Imagem ${CYAN}${img}${RESET}"
        skipped
    fi
done
echo

# ── Remove redes Docker ───────────────────────────────────────────────────────
info "Removendo redes Docker..."
NETWORKS=(
    "telegram-server-monitor_monitor-net"
    "monitor-net"
)
for net in "${NETWORKS[@]}"; do
    if docker network inspect "$net" &>/dev/null 2>&1; then
        docker network rm "$net" 2>/dev/null && success "Rede ${net} removida." || \
            warn "Não foi possível remover rede ${net}."
    else
        echo -ne "  Rede ${CYAN}${net}${RESET}"
        skipped
    fi
done
echo

# ── Remove serviço systemd ────────────────────────────────────────────────────
info "Removendo serviço systemd..."
SERVICE_FILE="/etc/systemd/system/monitor.service"

if [ -f "$SERVICE_FILE" ]; then
    asroot systemctl stop    monitor.service 2>/dev/null || true
    asroot systemctl disable monitor.service 2>/dev/null || true
    asroot rm -f "$SERVICE_FILE"
    asroot systemctl daemon-reload
    success "Serviço systemd monitor.service removido."
else
    echo -ne "  Serviço ${CYAN}monitor.service${RESET}"
    skipped
fi
echo

# ── Remove arquivo sudoers ────────────────────────────────────────────────────
info "Removendo configuração de sudo..."
SUDOERS_FILE="/etc/sudoers.d/monitor-reboot"
if [ -f "$SUDOERS_FILE" ]; then
    asroot rm -f "$SUDOERS_FILE"
    success "Arquivo ${SUDOERS_FILE} removido."
else
    echo -ne "  Arquivo ${CYAN}monitor-reboot${RESET}"
    skipped
fi
echo

# ── Remove .env ───────────────────────────────────────────────────────────────
if [ -f ".env" ]; then
    # Verifica se há CasaOS configurado para informar
    CASAOS_URL_CONF=""
    CASAOS_URL_CONF=$(grep -E '^CASAOS_URL=' .env 2>/dev/null | cut -d'=' -f2 || true)

    if [ -n "$CASAOS_URL_CONF" ]; then
        echo -e " ${CYAN}[INFO]${RESET} CasaOS configurado em: ${CYAN}${CASAOS_URL_CONF}${RESET}"
        echo -e "        A remoção do .env irá apagar usuário e senha do CasaOS."
        echo
    fi

    if confirm "Remover o arquivo .env (contém token, API key e credenciais CasaOS)?"; then
        rm -f .env
        success ".env removido."
    else
        info ".env mantido."
    fi
    echo
fi

# ── Resumo final ──────────────────────────────────────────────────────────────
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
success "Desinstalação concluída."
echo
echo -e " O código-fonte permanece em:"
echo -e "   ${CYAN}$(pwd)${RESET}"
echo
echo -e " Para reinstalar, execute:"
echo -e "   ${CYAN}bash setup.sh${RESET}"
echo
