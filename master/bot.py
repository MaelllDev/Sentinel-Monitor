"""
Bot do Telegram — master do sistema de monitoramento.
Comandos: /status, /saude, /apps, /portas, /cpu, /memoria,
          /disco, /temperatura, /rede, /servidores, /renomear,
          /integrar, /limpar, /versao
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

import ws_server
import casaos

logger = logging.getLogger(__name__)

VERSION = "1.0.0"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "0"))
MASTER_HOST = os.getenv("MASTER_HOST", "localhost")
MASTER_PORT = int(os.getenv("WS_PORT", "8765"))

# Pendências de resposta de comandos remotos: request_id -> asyncio.Future
_pending: dict[str, asyncio.Future] = {}


# ─────────────────────────── helpers ────────────────────────────

def _auth(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


def _esc(text: str) -> str:
    """Escapa caracteres especiais do MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _fmt_bytes(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _bar(percent: float, width: int = 10) -> str:
    filled = int(percent / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _ago(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        delta = datetime.now() - dt
        s = int(delta.total_seconds())
        if s < 60:
            return f"{s}s atrás"
        elif s < 3600:
            return f"{s // 60}m atrás"
        else:
            return f"{s // 3600}h atrás"
    except Exception:
        return "?"


async def _send(update: Update, text: str):
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def _resolve_node(update: Update, name_arg: str | None) -> tuple[str, dict] | None:
    """
    Resolve um node pelo nome passado como argumento.
    Se não passado e só há um node, usa ele.
    Caso contrário, pede que especifique.
    """
    nodes = ws_server.get_nodes()
    if not nodes:
        await _send(update, "❌ Nenhum servidor conectado no momento.")
        return None

    if name_arg:
        result = ws_server.get_node_by_name(name_arg)
        if not result:
            await _send(update, f"❌ Servidor <b>{name_arg}</b> não encontrado.")
            return None
        return result

    if len(nodes) == 1:
        nid = list(nodes.keys())[0]
        return nid, ws_server.connected_nodes[nid]

    nomes = ", ".join(f"<b>{v['name']}</b>" for v in nodes.values())
    await _send(update, f"⚠️ Especifique o servidor: {nomes}")
    return None


async def _run_remote(node_id: str, command: str, timeout: int = 15) -> str:
    """Envia comando remoto e aguarda resposta."""
    request_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    _pending[request_id] = future

    sent = await ws_server.send_command(node_id, command, request_id)
    if not sent:
        del _pending[request_id]
        return "❌ Não foi possível enviar o comando."

    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        del _pending[request_id]
        return "⏱️ Timeout aguardando resposta do servidor."


def _metrics_status_text(name: str, m: dict) -> str:
    cpu = m.get("cpu", {})
    mem = m.get("memory", {})
    disk = m.get("disk", {})
    uptime = m.get("uptime", "N/A")
    sysinfo = m.get("system", {})

    cpu_pct = cpu.get("percent", 0)
    mem_pct = mem.get("percent", 0)
    disk_pct = disk.get("percent", 0)

    lines = [
        f"🖥️ <b>{name}</b>",
        f"",
        f"⏱ Uptime: <code>{uptime}</code>",
    ]

    if sysinfo:
        if sysinfo.get("os"):
            lines.append(f"🐧 OS:     <code>{sysinfo['os']}</code>")
        if sysinfo.get("kernel"):
            lines.append(f"🔧 Kernel: <code>{sysinfo['kernel']}</code>")
        if sysinfo.get("local_ip") and sysinfo["local_ip"] != "N/A":
            lines.append(f"🌐 IP:     <code>{sysinfo['local_ip']}</code>")

    lines += [
        f"",
        f"🔲 CPU:    {_bar(cpu_pct)} {cpu_pct:.1f}%",
        f"🧠 RAM:    {_bar(mem_pct)} {mem_pct:.1f}%",
        f"           {_fmt_bytes(mem.get('used', 0))} / {_fmt_bytes(mem.get('total', 0))}",
        f"💾 Disco:  {_bar(disk_pct)} {disk_pct:.1f}%",
        f"           {_fmt_bytes(disk.get('used', 0))} / {_fmt_bytes(disk.get('total', 0))}",
    ]

    load = m.get("load_avg")
    if load:
        lines.append(f"📊 Load:   {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")

    return "\n".join(lines)


# ─────────────────────────── event callback ────────────────────────────

async def _on_ws_event(event: dict):
    """Callback chamado pelo ws_server para eventos dos nodes."""
    bot: Bot = _bot_instance

    if event["type"] == "node_connected":
        reconnects = event.get("reconnects", 0)
        if reconnects == 0:
            msg = f"✅ Servidor <b>{event['name']}</b> conectado."
        else:
            msg = f"✅ Servidor <b>{event['name']}</b> reconectado. (queda #{reconnects})"
        await bot.send_message(ALLOWED_CHAT_ID, msg, parse_mode=ParseMode.HTML)

    elif event["type"] == "node_disconnected":
        await bot.send_message(
            ALLOWED_CHAT_ID,
            f"⚠️ Servidor <b>{event['name']}</b> desconectado!",
            parse_mode=ParseMode.HTML,
        )

    elif event["type"] == "alert":
        data = event.get("data", {})
        metric = data.get("metric", "?")
        value = data.get("value", "?")
        threshold = data.get("threshold", "?")
        await bot.send_message(
            ALLOWED_CHAT_ID,
            f"🚨 <b>ALERTA — {event['name']}</b>\n"
            f"Métrica: <code>{metric}</code>\n"
            f"Valor: <code>{value}</code> (limite: <code>{threshold}</code>)",
            parse_mode=ParseMode.HTML,
        )

    elif event["type"] == "cmd_result":
        rid = event.get("request_id")
        future = _pending.pop(rid, None)
        if future and not future.done():
            output = event.get("output", "")
            error = event.get("error", "")
            future.set_result(output or error or "(sem saída)")


_bot_instance: Bot = None


# ─────────────────────────── comandos ────────────────────────────

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    nodes = ws_server.get_nodes()

    if not nodes:
        await _send(update, "❌ Nenhum servidor conectado.")
        return

    if args:
        result = await _resolve_node(update, args[0])
        if not result:
            return
        nid, info = result
        m = info["metrics"]
        if not m:
            await _send(update, f"⏳ Aguardando métricas de <b>{info['name']}</b>...")
            return
        await _send(update, _metrics_status_text(info["name"], m))
        return

    # Painel resumido de todos
    lines = ["📊 <b>STATUS DOS SERVIDORES</b>\n"]
    for nid, info in nodes.items():
        m = info["metrics"]
        if not m:
            lines.append(f"• <b>{info['name']}</b> — aguardando dados...")
            continue
        cpu = m.get("cpu", {}).get("percent", 0)
        mem = m.get("memory", {}).get("percent", 0)
        disk = m.get("disk", {}).get("percent", 0)

        def icon(v):
            return "🟢" if v < 70 else "🟡" if v < 90 else "🔴"

        lines.append(
            f"{icon(cpu)} <b>{info['name']}</b>\n"
            f"   CPU {cpu:.0f}% | RAM {mem:.0f}% | Disco {disk:.0f}%"
        )

    await _send(update, "\n".join(lines))


async def cmd_saude(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    out = await _run_remote(nid, "__saude__")
    await _send(update, f"🏥 <b>Saúde — {info['name']}</b>\n\n<pre>{out}</pre>")


async def cmd_apps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    out = await _run_remote(nid, "__apps__")
    await _send(update, f"🐳 <b>Contêineres — {info['name']}</b>\n\n<pre>{out}</pre>")


async def cmd_portas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    out = await _run_remote(nid, "__portas__")
    await _send(update, f"🔌 <b>Portas TCP — {info['name']}</b>\n\n<pre>{out}</pre>")


async def cmd_cpu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result
    m = info["metrics"]

    if not m:
        await _send(update, "⏳ Aguardando métricas...")
        return

    cpu = m.get("cpu", {})
    load = m.get("load_avg", [0, 0, 0])
    top = m.get("top_cpu", [])

    lines = [
        f"🔲 <b>CPU — {info['name']}</b>",
        f"",
        f"Uso geral:  {_bar(cpu.get('percent', 0))} {cpu.get('percent', 0):.1f}%",
        f"Núcleos:    {cpu.get('count', '?')}",
        f"Load avg:   {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}",
        f"",
        f"<b>Top processos:</b>",
    ]
    for p in top[:5]:
        lines.append(f"  {p.get('cpu', 0):5.1f}%  {p.get('name', '?')[:30]}")

    await _send(update, "\n".join(lines))


async def cmd_memoria(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result
    m = info["metrics"]

    if not m:
        await _send(update, "⏳ Aguardando métricas...")
        return

    mem = m.get("memory", {})
    top = m.get("top_mem", [])

    lines = [
        f"🧠 <b>Memória — {info['name']}</b>",
        f"",
        f"Uso:     {_bar(mem.get('percent', 0))} {mem.get('percent', 0):.1f}%",
        f"Usada:   {_fmt_bytes(mem.get('used', 0))}",
        f"Livre:   {_fmt_bytes(mem.get('available', 0))}",
        f"Total:   {_fmt_bytes(mem.get('total', 0))}",
        f"",
        f"<b>Top processos:</b>",
    ]
    for p in top[:5]:
        lines.append(f"  {_fmt_bytes(p.get('mem', 0)):>10}  {p.get('name', '?')[:30]}")

    await _send(update, "\n".join(lines))


async def cmd_disco(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result
    m = info["metrics"]

    if not m:
        await _send(update, "⏳ Aguardando métricas...")
        return

    partitions = m.get("partitions", [])
    lines = [f"💾 <b>Disco — {info['name']}</b>\n"]

    for p in partitions:
        pct = p.get("percent", 0)
        lines.append(
            f"<b>{p.get('mountpoint', '?')}</b>\n"
            f"  {_bar(pct, 8)} {pct:.1f}%\n"
            f"  {_fmt_bytes(p.get('used', 0))} / {_fmt_bytes(p.get('total', 0))}\n"
        )

    await _send(update, "\n".join(lines))


async def cmd_temperatura(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result
    m = info["metrics"]

    temps = m.get("temperatures", {}) if m else {}

    if not temps:
        await _send(update,
            f"🌡️ <b>Temperatura — {info['name']}</b>\n\n"
            "⚠️ Dados de temperatura não disponíveis neste servidor."
        )
        return

    lines = [f"🌡️ <b>Temperatura — {info['name']}</b>\n"]
    for sensor, readings in temps.items():
        for r in readings:
            current = r.get("current", 0)
            high = r.get("high", "N/A")
            icon = "🟢" if current < 70 else "🟡" if current < 85 else "🔴"
            lines.append(f"{icon} {sensor} — {current}°C (limite: {high}°C)")

    await _send(update, "\n".join(lines))


async def cmd_rede(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result
    m = info["metrics"]

    if not m:
        await _send(update, "⏳ Aguardando métricas...")
        return

    interfaces = m.get("network", {}).get("interfaces", [])
    net_io = m.get("network", {}).get("io", {})

    lines = [f"🌐 <b>Rede — {info['name']}</b>\n"]
    for iface in interfaces:
        addrs = ", ".join(iface.get("addresses", []))
        lines.append(f"<b>{iface['name']}</b>: <code>{addrs}</code>")

    if net_io:
        lines.append(f"\n📥 Recebido:  {_fmt_bytes(net_io.get('bytes_recv', 0))}")
        lines.append(f"📤 Enviado:   {_fmt_bytes(net_io.get('bytes_sent', 0))}")

    await _send(update, "\n".join(lines))


async def cmd_servidores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    nodes = ws_server.get_nodes()
    if not nodes:
        await _send(update, "📭 Nenhum servidor conectado.")
        return

    lines = [f"🖥️ <b>Servidores conectados ({len(nodes)})</b>\n"]
    for nid, info in nodes.items():
        last = _ago(info["last_seen"])
        lines.append(f"• <b>{info['name']}</b> — visto {last}")

    await _send(update, "\n".join(lines))


async def cmd_renomear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    if len(ctx.args) < 2:
        await _send(update, "Uso: /renomear <nome-atual> <novo-nome>")
        return

    nome_atual, novo_nome = ctx.args[0], ctx.args[1]
    result = ws_server.get_node_by_name(nome_atual)
    if not result:
        await _send(update, f"❌ Servidor <b>{nome_atual}</b> não encontrado.")
        return

    nid, _ = result
    ok = await ws_server.rename_node(nid, novo_nome)
    if ok:
        await _send(update, f"✅ Servidor renomeado: <b>{nome_atual}</b> → <b>{novo_nome}</b>")
    else:
        await _send(update, f"❌ Erro ao renomear servidor.")


async def cmd_remover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    if not ctx.args:
        await _send(update, "Uso: /remover <nome-do-servidor>")
        return

    nome = ctx.args[0]
    result = ws_server.get_node_by_name(nome)
    if not result:
        await _send(update, f"❌ Servidor <b>{nome}</b> não encontrado.")
        return

    nid, info = result

    # Pede confirmação explícita
    if len(ctx.args) < 2 or ctx.args[1].lower() != "confirmar":
        await _send(update,
            f"⚠️ Isso vai desconectar e remover <b>{info['name']}</b> do sistema.\n\n"
            f"Envie <code>/remover {info['name']} confirmar</code> para confirmar."
        )
        return

    ok = await ws_server.remove_node(nid)
    if ok:
        await _send(update, f"🗑️ Servidor <b>{info['name']}</b> removido do sistema.")
    else:
        await _send(update, f"❌ Erro ao remover servidor <b>{info['name']}</b>.")


async def cmd_exec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    # Uso: /exec <nome-do-servidor> <comando>
    # O nome é o primeiro argumento; o resto é o comando.
    if len(ctx.args) < 2:
        await _send(update, "Uso: /exec <nome-do-servidor> <comando>\nExemplo: /exec minha-vps df -h")
        return

    nome = ctx.args[0]
    comando = " ".join(ctx.args[1:])

    result = ws_server.get_node_by_name(nome)
    if not result:
        await _send(update, f"❌ Servidor <b>{nome}</b> não encontrado.")
        return

    nid, info = result

    await _send(update, f"⚙️ Executando em <b>{info['name']}</b>: <code>{comando}</code>")
    out = await _run_remote(nid, comando, timeout=30)
    await _send(update, f"<b>{info['name']}</b> $ <code>{comando}</code>\n\n<pre>{out}</pre>")


async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    # Uso: /logs <nome> <container> [linhas]
    if len(ctx.args) < 2:
        await _send(update, "Uso: /logs <servidor> <container> [linhas]\nExemplo: /logs minha-vps nginx 100")
        return

    nome = ctx.args[0]
    container = ctx.args[1]
    linhas = ctx.args[2] if len(ctx.args) > 2 else "50"

    result = await _resolve_node(update, nome)
    if not result:
        return
    nid, info = result

    await _send(update, f"📋 Buscando logs de <b>{container}</b> em <b>{info['name']}</b>...")
    out = await _run_remote(nid, f"__logs__ {container} {linhas}", timeout=20)
    await _send(update, f"📋 <b>{info['name']}</b> — <code>{container}</code>\n\n<pre>{out}</pre>")


async def cmd_reiniciar_container(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    # Uso: /reiniciar <nome> <container>
    if len(ctx.args) < 2:
        await _send(update, "Uso: /reiniciar <servidor> <container>\nExemplo: /reiniciar minha-vps nginx")
        return

    nome = ctx.args[0]
    container = ctx.args[1]

    result = await _resolve_node(update, nome)
    if not result:
        return
    nid, info = result

    await _send(update, f"🔄 Reiniciando container <b>{container}</b> em <b>{info['name']}</b>...")
    out = await _run_remote(nid, f"__reiniciar__ {container}", timeout=65)
    await _send(update, f"✅ <b>{info['name']}</b>: {out}")


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    import time
    t0 = time.monotonic()
    out = await _run_remote(nid, "echo pong", timeout=10)
    rtt = (time.monotonic() - t0) * 1000

    if "pong" in out:
        await _send(update, f"🏓 <b>{info['name']}</b> — RTT: <code>{rtt:.0f} ms</code>")
    else:
        await _send(update, f"⚠️ Resposta inesperada de <b>{info['name']}</b>: <code>{out}</code>")


def _sparkline(values: list[float]) -> str:
    """Gera mini gráfico de barras ASCII a partir de uma lista de percentuais."""
    blocks = " ▁▂▃▄▅▆▇█"
    if not values:
        return ""
    mn, mx = min(values), max(values)
    span = mx - mn or 1
    result = ""
    for v in values:
        idx = int((v - mn) / span * (len(blocks) - 1))
        result += blocks[idx]
    return result


async def cmd_historico(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    history = ws_server.get_history(nid)
    if not history:
        await _send(update, f"⏳ Ainda sem histórico para <b>{info['name']}</b>. Aguarde algumas medições.")
        return

    cpu_vals = [h["cpu"] for h in history]
    mem_vals = [h["mem"] for h in history]
    disk_vals = [h["disk"] for h in history]

    n = len(history)
    span_min = n * int(os.getenv("METRICS_INTERVAL", "10")) // 60 or 1

    lines = [
        f"📈 <b>Histórico — {info['name']}</b>",
        f"<i>Últimas {n} amostras (~{span_min} min)</i>",
        f"",
        f"🔲 CPU",
        f"  <code>{_sparkline(cpu_vals)}</code>",
        f"  mín {min(cpu_vals):.0f}%  méd {sum(cpu_vals)/n:.0f}%  máx {max(cpu_vals):.0f}%",
        f"",
        f"🧠 RAM",
        f"  <code>{_sparkline(mem_vals)}</code>",
        f"  mín {min(mem_vals):.0f}%  méd {sum(mem_vals)/n:.0f}%  máx {max(mem_vals):.0f}%",
        f"",
        f"💾 Disco",
        f"  <code>{_sparkline(disk_vals)}</code>",
        f"  mín {min(disk_vals):.0f}%  méd {sum(disk_vals)/n:.0f}%  máx {max(disk_vals):.0f}%",
    ]
    await _send(update, "\n".join(lines))


async def cmd_alertas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    # Uso: /alertas [nome] ou /alertas <nome> <metrica> <valor>
    # Ex:  /alertas minha-vps cpu 80
    args = ctx.args

    # Alteração de threshold
    if len(args) == 3:
        nome, metrica, valor_str = args
        metrica = metrica.lower()
        if metrica not in ("cpu", "memory", "disk"):
            await _send(update, "❌ Métrica inválida. Use: <code>cpu</code>, <code>memory</code> ou <code>disk</code>.")
            return
        try:
            valor = int(valor_str)
            if not 1 <= valor <= 100:
                raise ValueError
        except ValueError:
            await _send(update, "❌ Valor deve ser um inteiro entre 1 e 100.")
            return

        result = await _resolve_node(update, nome)
        if not result:
            return
        nid, info = result

        sent = await ws_server.send_command(nid, f"__set_threshold__ {metrica} {valor}", request_id=str(uuid.uuid4()))
        # set_threshold é processado pelo listen_loop do agent, não retorna cmd_result
        # Então enviamos via tipo set_threshold diretamente
        node = ws_server.connected_nodes.get(nid)
        if node:
            import json as _json
            try:
                await node["ws"].send(_json.dumps({
                    "type": "set_threshold",
                    "metric": metrica,
                    "value": valor,
                }))
                await _send(update,
                    f"✅ Threshold de <b>{metrica}</b> em <b>{info['name']}</b> "
                    f"atualizado para <b>{valor}%</b>."
                )
            except Exception as e:
                await _send(update, f"❌ Erro ao enviar: {e}")
        return

    # Listagem de thresholds — mostra o que está configurado nos nodes via métricas
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    m = info.get("metrics") or ws_server.connected_nodes.get(nid, {}).get("metrics", {})
    thresholds = m.get("thresholds", {}) if m else {}

    if thresholds:
        lines = [f"🔔 <b>Alertas — {info['name']}</b>\n"]
        labels = {"cpu": "CPU", "memory": "RAM", "disk": "Disco"}
        for k, label in labels.items():
            v = thresholds.get(k, "?")
            lines.append(f"  {label}: <code>{v}%</code>")
        lines.append(f"\nPara alterar: <code>/alertas {info['name']} cpu 80</code>")
        await _send(update, "\n".join(lines))
    else:
        # Thresholds não vêm nas métricas por padrão — informa os padrões e como alterar
        await _send(update,
            f"🔔 <b>Alertas — {info['name']}</b>\n\n"
            f"Thresholds padrão: CPU 90% | RAM 90% | Disco 90%\n\n"
            f"Para alterar:\n"
            f"<code>/alertas {info['name']} cpu 80</code>\n"
            f"<code>/alertas {info['name']} memory 85</code>\n"
            f"<code>/alertas {info['name']} disk 95</code>"
        )


# ─────────────────────────── /uptime ────────────────────────────

async def cmd_uptime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    nodes = ws_server.get_nodes()
    if not nodes:
        await _send(update, "❌ Nenhum servidor conectado.")
        return

    lines = ["⏱ <b>Uptime dos servidores</b>\n"]
    for nid, info in nodes.items():
        m = info.get("metrics") or {}
        uptime = m.get("uptime", "N/A")
        last   = _ago(info["last_seen"])
        sysinfo = m.get("system", {})
        ip = sysinfo.get("local_ip", "")
        ip_str = f" — <code>{ip}</code>" if ip and ip != "N/A" else ""
        lines.append(f"🖥️ <b>{info['name']}</b>{ip_str}\n   ⏱ {uptime}  (visto {last})")

    await _send(update, "\n".join(lines))


# ─────────────────────────── CasaOS ────────────────────────────

def _casa_not_configured(update):
    return _send(update,
        "❌ Integração CasaOS não configurada.\n"
        "Defina <code>CASAOS_URL</code>, <code>CASAOS_USER</code> e <code>CASAOS_PASSWORD</code> no <code>.env</code>."
    )


async def cmd_casa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    if not casaos.is_configured():
        await _casa_not_configured(update)
        return

    apps = await casaos.list_apps()
    if not apps:
        await _send(update, "📭 Nenhum app encontrado no CasaOS (ou sem conexão).")
        return

    lines = [f"🏠 <b>CasaOS — {len(apps)} apps</b>\n"]
    for a in sorted(apps, key=lambda x: x["title"].lower()):
        status = a.get("status", "unknown")
        icon   = "🟢" if status == "running" else "🔴" if status == "stopped" else "🟡"
        update_badge = " 🆙" if a.get("update") else ""
        lines.append(f"{icon} <b>{a['title']}</b> — <code>{a['id']}</code>{update_badge}")

    lines.append("\n<i>Use /casa_iniciar, /casa_parar, /casa_logs, /casa_atualizar &lt;id&gt;</i>")
    await _send(update, "\n".join(lines))


async def cmd_casa_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    if not casaos.is_configured():
        await _casa_not_configured(update)
        return
    if not ctx.args:
        await _send(update, "Uso: /casa_iniciar <id-do-app>\nVeja os IDs com /casa")
        return

    app_id = ctx.args[0]
    await _send(update, f"▶️ Iniciando <b>{app_id}</b>...")
    ok, msg = await casaos.set_app_status(app_id, "start")
    if ok:
        await _send(update, f"✅ <b>{app_id}</b> iniciado com sucesso.")
    else:
        await _send(update, f"❌ Erro ao iniciar <b>{app_id}</b>: <code>{msg}</code>")


async def cmd_casa_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    if not casaos.is_configured():
        await _casa_not_configured(update)
        return
    if not ctx.args:
        await _send(update, "Uso: /casa_parar <id-do-app>\nVeja os IDs com /casa")
        return

    app_id = ctx.args[0]
    await _send(update, f"⏹ Parando <b>{app_id}</b>...")
    ok, msg = await casaos.set_app_status(app_id, "stop")
    if ok:
        await _send(update, f"✅ <b>{app_id}</b> parado com sucesso.")
    else:
        await _send(update, f"❌ Erro ao parar <b>{app_id}</b>: <code>{msg}</code>")


async def cmd_casa_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    if not casaos.is_configured():
        await _casa_not_configured(update)
        return
    if not ctx.args:
        await _send(update, "Uso: /casa_logs <id-do-app> [linhas]\nExemplo: /casa_logs nextcloud 50")
        return

    app_id = ctx.args[0]
    lines  = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 50

    await _send(update, f"📋 Buscando logs de <b>{app_id}</b>...")
    output = await casaos.get_app_logs(app_id, lines)
    # Telegram limita mensagem a 4096 chars
    output = output[-3800:] if len(output) > 3800 else output
    await _send(update, f"📋 <b>Logs — {app_id}</b>\n\n<pre>{output}</pre>")


async def cmd_casa_atualizar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    if not casaos.is_configured():
        await _casa_not_configured(update)
        return
    if not ctx.args:
        await _send(update, "Uso: /casa_atualizar <id-do-app>\nVeja os IDs com /casa")
        return

    app_id = ctx.args[0]
    await _send(update, f"🔄 Iniciando atualização de <b>{app_id}</b>...")
    ok, msg = await casaos.update_app(app_id)
    if ok:
        await _send(update, f"✅ Atualização de <b>{app_id}</b> iniciada. Acompanhe no painel CasaOS.")
    else:
        await _send(update, f"❌ Erro ao atualizar <b>{app_id}</b>: <code>{msg}</code>")


async def cmd_integrar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    api_key = os.getenv("API_KEY", "changeme")
    text = (
        f"📦 <b>Como adicionar um novo servidor</b>\n\n"
        f"1. Instale o Docker na VPS\n"
        f"2. Crie o arquivo <code>.env</code> com:\n\n"
        f"<pre>"
        f"MASTER_WS_URL=ws://{MASTER_HOST}:{MASTER_PORT}\n"
        f"API_KEY={api_key}\n"
        f"NODE_NAME=meu-servidor\n"
        f"</pre>\n"
        f"3. Execute:\n\n"
        f"<pre>"
        f"docker run -d --restart unless-stopped \\\n"
        f"  --env-file .env \\\n"
        f"  --name monitor-node \\\n"
        f"  --pid=host \\\n"
        f"  -v /proc:/host/proc:ro \\\n"
        f"  -v /sys:/host/sys:ro \\\n"
        f"  -v /var/run/docker.sock:/var/run/docker.sock \\\n"
        f"  monitor-node:latest\n"
        f"</pre>"
    )
    await _send(update, text)


async def cmd_limpar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    deleted = 0

    for i in range(msg_id, max(msg_id - 50, 0), -1):
        try:
            await ctx.bot.delete_message(chat_id=chat_id, message_id=i)
            deleted += 1
        except Exception:
            pass

    try:
        m = await ctx.bot.send_message(
            chat_id, f"🧹 {deleted} mensagens removidas.", parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(3)
        await m.delete()
    except Exception:
        pass


async def cmd_versao(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    await _send(update, f"🤖 <b>Sentinel Monitor</b> v{VERSION}")


async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    await _send(update, f"🔄 Reiniciando <b>{info['name']}</b>...")
    out = await _run_remote(nid, "reboot", timeout=10)
    # Se chegou resposta, algo deu errado (reboot não retorna)
    await _send(update, f"⚠️ Resposta inesperada: <pre>{out}</pre>")


async def cmd_shutdown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return

    args = ctx.args
    result = await _resolve_node(update, args[0] if args else None)
    if not result:
        return
    nid, info = result

    # Pede confirmação antes de desligar
    await _send(update,
        f"⚠️ <b>Atenção!</b> Você está prestes a desligar <b>{info['name']}</b>.\n\n"
        f"Envie <code>/shutdown {info['name']} confirmar</code> para confirmar."
    )

    # Verifica confirmação
    if len(args) < 2 or args[1].lower() != "confirmar":
        return

    await _send(update, f"🔴 Desligando <b>{info['name']}</b>...")
    out = await _run_remote(nid, "poweroff", timeout=10)
    await _send(update, f"⚠️ Resposta inesperada: <pre>{out}</pre>")


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _auth(update):
        return
    await _send(update,
        f"🖥️ <b>Sentinel Monitor v{VERSION}</b>\n\n"
        f"<b>📊 Monitoramento</b>\n"
        f"/status — painel resumido de todos os servidores\n"
        f"/status &lt;nome&gt; — detalhes de um servidor\n"
        f"/uptime — uptime de todos os servidores\n"
        f"/saude — diagnóstico e limites\n"
        f"/historico — gráfico ASCII de CPU/RAM/Disco\n"
        f"/ping — latência até o servidor\n"
        f"/cpu — uso e top processos\n"
        f"/memoria — RAM e top processos\n"
        f"/disco — uso das partições\n"
        f"/temperatura — temperaturas\n"
        f"/rede — interfaces e endereços\n"
        f"\n"
        f"<b>🐳 Docker</b>\n"
        f"/apps — contêineres e estado\n"
        f"/portas — portas TCP em escuta\n"
        f"/logs &lt;srv&gt; &lt;container&gt; — logs de container\n"
        f"/reiniciar &lt;srv&gt; &lt;container&gt; — reinicia container\n"
        f"\n"
        f"<b>🏠 CasaOS</b>\n"
        f"/casa — painel de apps instalados\n"
        f"/casa_iniciar &lt;id&gt; — inicia um app\n"
        f"/casa_parar &lt;id&gt; — para um app\n"
        f"/casa_logs &lt;id&gt; — logs de um app\n"
        f"/casa_atualizar &lt;id&gt; — atualiza um app\n"
        f"\n"
        f"<b>⚙️ Controle</b>\n"
        f"/exec &lt;srv&gt; &lt;cmd&gt; — executa comando shell\n"
        f"/alertas — ver/alterar thresholds\n"
        f"/restart — reinicia o sistema\n"
        f"/shutdown — desliga o servidor\n"
        f"/remover — remove servidor do sistema\n"
        f"\n"
        f"<b>🔧 Gestão</b>\n"
        f"/servidores — servidores conectados\n"
        f"/renomear &lt;atual&gt; &lt;novo&gt; — renomeia servidor\n"
        f"/integrar — como adicionar novo servidor\n"
        f"/limpar — limpa mensagens recentes\n"
        f"/versao — versão instalada"
    )


# ─────────────────────────── main ────────────────────────────

async def main():
    global _bot_instance

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    _bot_instance = app.bot

    # Registra callback de eventos do WebSocket
    ws_server.register_event_callback(_on_ws_event)

    # Registra handlers de comandos
    handlers = [
        ("start", cmd_start),
        ("status", cmd_status),
        ("saude", cmd_saude),
        ("apps", cmd_apps),
        ("portas", cmd_portas),
        ("cpu", cmd_cpu),
        ("memoria", cmd_memoria),
        ("disco", cmd_disco),
        ("temperatura", cmd_temperatura),
        ("rede", cmd_rede),
        ("servidores", cmd_servidores),
        ("renomear", cmd_renomear),
        ("integrar", cmd_integrar),
        ("limpar", cmd_limpar),
        ("versao", cmd_versao),
        ("restart", cmd_restart),
        ("shutdown", cmd_shutdown),
        ("remover", cmd_remover),
        ("exec", cmd_exec),
        ("logs", cmd_logs),
        ("reiniciar", cmd_reiniciar_container),
        ("ping", cmd_ping),
        ("historico", cmd_historico),
        ("alertas", cmd_alertas),
        ("uptime", cmd_uptime),
        ("casa", cmd_casa),
        ("casa_iniciar", cmd_casa_iniciar),
        ("casa_parar", cmd_casa_parar),
        ("casa_logs", cmd_casa_logs),
        ("casa_atualizar", cmd_casa_atualizar),
    ]
    for name, handler in handlers:
        app.add_handler(CommandHandler(name, handler))

    # Inicia servidor WebSocket em paralelo
    ws_port = int(os.getenv("WS_PORT", "8765"))
    ws_task = asyncio.create_task(ws_server.start_server("0.0.0.0", ws_port))

    logger.info("Bot iniciando...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info(f"Bot online. Aguardando mensagens de {ALLOWED_CHAT_ID}...")

    try:
        await ws_task
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
