"""
Coleta de métricas do sistema usando psutil.
Retorna dict estruturado para envio ao master.
"""

import logging
import os
import platform
import socket
import subprocess
import shutil
from datetime import timedelta

import psutil

logger = logging.getLogger(__name__)


def _uptime() -> str:
    try:
        boot = psutil.boot_time()
        delta = timedelta(seconds=int(psutil.time.time() - boot))
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        minutes = rem // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)
    except Exception:
        return "N/A"


def _cpu() -> dict:
    return {
        "percent": psutil.cpu_percent(interval=0.5),
        "count": psutil.cpu_count(logical=True),
        "count_physical": psutil.cpu_count(logical=False),
    }


def _top_cpu(n: int = 5) -> list:
    try:
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent"]):
            try:
                procs.append({"name": p.info["name"], "cpu": p.info["cpu_percent"] or 0})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return sorted(procs, key=lambda x: x["cpu"], reverse=True)[:n]
    except Exception:
        return []


def _memory() -> dict:
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "used": mem.used,
        "available": mem.available,
        "percent": mem.percent,
    }


def _top_mem(n: int = 5) -> list:
    try:
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                mi = p.info["memory_info"]
                if mi:
                    procs.append({"name": p.info["name"], "mem": mi.rss})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return sorted(procs, key=lambda x: x["mem"], reverse=True)[:n]
    except Exception:
        return []


def _disk_partitions() -> list:
    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            })
        except (PermissionError, OSError):
            pass
    return partitions


def _disk_main() -> dict:
    """Disco da partição raiz para o painel resumido."""
    try:
        usage = psutil.disk_usage("/")
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
        }
    except Exception:
        return {}


def _temperatures() -> dict:
    try:
        if not hasattr(psutil, "sensors_temperatures"):
            return {}
        temps = psutil.sensors_temperatures()
        if not temps:
            return {}
        result = {}
        for sensor, readings in temps.items():
            result[sensor] = [
                {
                    "label": r.label or sensor,
                    "current": r.current,
                    "high": r.high,
                    "critical": r.critical,
                }
                for r in readings
            ]
        return result
    except Exception:
        return {}


def _network() -> dict:
    interfaces = []
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, addr_list in addrs.items():
            if name == "lo":
                continue
            addresses = [
                a.address for a in addr_list
                if a.family.name in ("AF_INET", "AF_INET6") and not a.address.startswith("127.")
            ]
            is_up = stats.get(name, None)
            interfaces.append({
                "name": name,
                "addresses": addresses,
                "is_up": is_up.isup if is_up else False,
            })
    except Exception as e:
        logger.warning(f"Erro ao coletar interfaces: {e}")

    io = {}
    try:
        net_io = psutil.net_io_counters()
        io = {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
        }
    except Exception:
        pass

    return {"interfaces": interfaces, "io": io}


def _load_avg() -> list:
    try:
        return list(os.getloadavg())
    except (AttributeError, OSError):
        return [0.0, 0.0, 0.0]


def _system_info() -> dict:
    """Retorna informações estáticas do sistema: kernel, OS, hostname, IP local."""
    info = {}
    try:
        info["hostname"] = socket.gethostname()
    except Exception:
        info["hostname"] = "N/A"
    try:
        info["os"] = f"{platform.system()} {platform.release()}"
    except Exception:
        info["os"] = "N/A"
    try:
        info["kernel"] = platform.uname().release
    except Exception:
        info["kernel"] = "N/A"
    try:
        info["arch"] = platform.machine()
    except Exception:
        info["arch"] = "N/A"
    # IP local (primeiro endereço não-loopback)
    try:
        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            if iface == "lo":
                continue
            for a in addr_list:
                if a.family.name == "AF_INET" and not a.address.startswith("127."):
                    info["local_ip"] = a.address
                    break
            if "local_ip" in info:
                break
        if "local_ip" not in info:
            info["local_ip"] = "N/A"
    except Exception:
        info["local_ip"] = "N/A"
    return info


def _docker_containers() -> list:
    """Lista contêineres Docker.

    Tenta primeiro via Docker API REST no Unix socket (/var/run/docker.sock),
    que funciona mesmo sem o binário 'docker' instalado e não sofre com
    problemas de permissão de grupo. Cai para o binário 'docker' como fallback.
    """
    # ── Tentativa 1: Docker API via Unix socket ──────────────────────────────
    DOCKER_SOCKET = "/var/run/docker.sock"
    if os.path.exists(DOCKER_SOCKET):
        try:
            import http.client

            conn = http.client.HTTPConnection("localhost")
            # Monkey-patch para usar o Unix socket
            import socket as _socket

            class _UnixHTTPConnection(http.client.HTTPConnection):
                def connect(self):
                    self.sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                    self.sock.settimeout(10)
                    self.sock.connect(DOCKER_SOCKET)

            conn = _UnixHTTPConnection("localhost")
            conn.request("GET", "/containers/json?all=1")
            resp = conn.getresponse()
            if resp.status == 200:
                import json as _json
                data = _json.loads(resp.read().decode())
                containers = []
                for c in data:
                    # Nome: remove a barra inicial que a API retorna
                    names = c.get("Names", [""])
                    name = names[0].lstrip("/") if names else ""
                    state = c.get("State", "")
                    status = c.get("Status", state)
                    image = c.get("Image", "")
                    # Monta string de portas no mesmo formato do `docker ps`
                    ports_raw = c.get("Ports", [])
                    port_parts = []
                    for p in ports_raw:
                        if p.get("PublicPort"):
                            port_parts.append(
                                f"{p.get('IP', '')}:{p['PublicPort']}->{p['PrivatePort']}/{p.get('Type', 'tcp')}"
                            )
                        else:
                            port_parts.append(f"{p['PrivatePort']}/{p.get('Type', 'tcp')}")
                    ports = ", ".join(port_parts)
                    containers.append({
                        "name": name,
                        "status": status,
                        "image": image,
                        "ports": ports,
                    })
                conn.close()
                return containers
            conn.close()
        except Exception as e:
            logger.warning(f"Docker API via socket falhou: {e}")

    # ── Tentativa 2: binário docker ──────────────────────────────────────────
    if not shutil.which("docker"):
        logger.warning("Binário 'docker' não encontrado e socket indisponível")
        return []
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format",
             "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"docker ps retornou erro: {result.stderr.strip()}")
            return []
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            containers.append({
                "name": parts[0] if len(parts) > 0 else "",
                "status": parts[1] if len(parts) > 1 else "",
                "image": parts[2] if len(parts) > 2 else "",
                "ports": parts[3] if len(parts) > 3 else "",
            })
        return containers
    except Exception as e:
        logger.warning(f"Erro ao listar Docker via CLI: {e}")
        return []


def _open_ports() -> list:
    """Lista portas TCP em escuta."""
    ports = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == "LISTEN":
                ports.append({
                    "port": conn.laddr.port,
                    "ip": conn.laddr.ip,
                    "pid": conn.pid,
                })
        ports.sort(key=lambda x: x["port"])
    except (psutil.AccessDenied, Exception) as e:
        logger.warning(f"Erro ao listar portas: {e}")
    return ports


def _health_check(thresholds: dict) -> dict:
    """Diagnóstico de saúde comparando métricas com thresholds."""
    issues = []
    warnings = []

    cpu_pct = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    cpu_thresh = thresholds.get("cpu", 90)
    mem_thresh = thresholds.get("memory", 90)
    disk_thresh = thresholds.get("disk", 90)

    if cpu_pct >= cpu_thresh:
        issues.append(f"CPU crítica: {cpu_pct:.1f}% (limite {cpu_thresh}%)")
    elif cpu_pct >= cpu_thresh * 0.8:
        warnings.append(f"CPU alta: {cpu_pct:.1f}%")

    if mem.percent >= mem_thresh:
        issues.append(f"RAM crítica: {mem.percent:.1f}% (limite {mem_thresh}%)")
    elif mem.percent >= mem_thresh * 0.8:
        warnings.append(f"RAM alta: {mem.percent:.1f}%")

    if disk.percent >= disk_thresh:
        issues.append(f"Disco crítico: {disk.percent:.1f}% (limite {disk_thresh}%)")
    elif disk.percent >= disk_thresh * 0.8:
        warnings.append(f"Disco alto: {disk.percent:.1f}%")

    status = "🔴 CRÍTICO" if issues else ("🟡 ATENÇÃO" if warnings else "🟢 SAUDÁVEL")

    lines = [f"Status: {status}", ""]
    if issues:
        lines.append("❌ Problemas:")
        lines.extend(f"  • {i}" for i in issues)
        lines.append("")
    if warnings:
        lines.append("⚠️ Avisos:")
        lines.extend(f"  • {w}" for w in warnings)
        lines.append("")

    lines.append(f"Limites configurados:")
    lines.append(f"  CPU:   {cpu_thresh}%")
    lines.append(f"  RAM:   {mem_thresh}%")
    lines.append(f"  Disco: {disk_thresh}%")

    return {"text": "\n".join(lines), "status": status}


def collect_metrics() -> dict:
    """Coleta completa de todas as métricas."""
    return {
        "uptime": _uptime(),
        "cpu": _cpu(),
        "top_cpu": _top_cpu(),
        "memory": _memory(),
        "top_mem": _top_mem(),
        "disk": _disk_main(),
        "partitions": _disk_partitions(),
        "temperatures": _temperatures(),
        "network": _network(),
        "load_avg": _load_avg(),
        "system": _system_info(),
    }


def collect_apps() -> str:
    """Texto formatado de contêineres Docker."""
    DOCKER_SOCKET = "/var/run/docker.sock"
    containers = _docker_containers()
    if not containers:
        if not os.path.exists(DOCKER_SOCKET):
            return (
                "❌ Socket do Docker não encontrado.\n"
                "Monte o socket ao iniciar o node:\n"
                "  -v /var/run/docker.sock:/var/run/docker.sock"
            )
        return "Docker disponível mas nenhum contêiner encontrado."

    lines = [f"{'NOME':<25} {'STATUS':<20} {'IMAGEM':<30} {'PORTAS'}"]
    lines.append("─" * 90)
    for c in containers:
        icon = "🟢" if "Up" in c["status"] else "🔴"
        lines.append(
            f"{icon} {c['name']:<23} {c['status']:<20} {c['image']:<30} {c['ports']}"
        )
    return "\n".join(lines)


def collect_ports() -> str:
    """Texto formatado de portas TCP abertas."""
    ports = _open_ports()
    if not ports:
        return "Nenhuma porta em escuta encontrada."

    lines = [f"{'PORTA':<8} {'IP':<20} {'PID'}"]
    lines.append("─" * 40)
    for p in ports:
        lines.append(f"{p['port']:<8} {p['ip']:<20} {p['pid'] or '-'}")
    return "\n".join(lines)
