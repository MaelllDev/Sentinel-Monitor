"""
Agente do node — roda nas VPS monitoradas.
Conecta ao master via WebSocket, envia métricas periodicamente
e responde a comandos remotos.
"""

import asyncio
import json
import logging
import os
import subprocess
import shlex
import sys

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

import metrics

logger = logging.getLogger(__name__)

# ─────────────────────────── configuração ────────────────────────────

MASTER_WS_URL = os.getenv("MASTER_WS_URL", "ws://localhost:8765")
API_KEY = os.getenv("API_KEY", "changeme")
NODE_NAME = os.getenv("NODE_NAME", "vps-node")
NODE_ID = os.getenv("NODE_ID", NODE_NAME)
METRICS_INTERVAL = int(os.getenv("METRICS_INTERVAL", "10"))   # segundos
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))       # segundos

# Thresholds para alertas automáticos (sobrescritos via comando do master)
_thresholds = {
    "cpu": int(os.getenv("ALERT_CPU", "90")),
    "memory": int(os.getenv("ALERT_MEMORY", "90")),
    "disk": int(os.getenv("ALERT_DISK", "90")),
}

# Flag global para saber se o node está conectado
_connected = False


# ─────────────────────────── helpers ────────────────────────────

async def _send(ws, msg: dict):
    await ws.send(json.dumps(msg))


async def _handle_command(ws, request_id: str, command: str):
    """Processa comandos especiais do master ou executa shell."""
    try:
        # Comandos internos
        if command == "__saude__":
            health = metrics._health_check(_thresholds)
            await _send(ws, {
                "type": "cmd_result",
                "request_id": request_id,
                "output": health["text"],
            })
            return

        if command == "__apps__":
            output = metrics.collect_apps()
            await _send(ws, {
                "type": "cmd_result",
                "request_id": request_id,
                "output": output,
            })
            return

        if command == "__portas__":
            output = metrics.collect_ports()
            await _send(ws, {
                "type": "cmd_result",
                "request_id": request_id,
                "output": output,
            })
            return

        if command.startswith("__logs__"):
            # formato: __logs__ <container> [linhas]
            parts = command.split()
            container = parts[1] if len(parts) > 1 else ""
            lines = parts[2] if len(parts) > 2 else "50"
            if not container:
                await _send(ws, {
                    "type": "cmd_result",
                    "request_id": request_id,
                    "error": "Informe o nome do container.",
                })
                return
            result = subprocess.run(
                ["docker", "logs", "--tail", lines, container],
                capture_output=True, text=True, timeout=15,
            )
            output = result.stdout or result.stderr or "(sem saída)"
            await _send(ws, {
                "type": "cmd_result",
                "request_id": request_id,
                "output": output[-3800:],  # últimos chars para caber no Telegram
            })
            return

        if command.startswith("__reiniciar__"):
            # formato: __reiniciar__ <container>
            parts = command.split()
            container = parts[1] if len(parts) > 1 else ""
            if not container:
                await _send(ws, {
                    "type": "cmd_result",
                    "request_id": request_id,
                    "error": "Informe o nome do container.",
                })
                return
            result = subprocess.run(
                ["docker", "restart", container],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout.strip() or result.stderr.strip() or container
            await _send(ws, {
                "type": "cmd_result",
                "request_id": request_id,
                "output": f"Reiniciado: {output}",
            })
            return

        # Comando shell genérico
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr or "(sem saída)"
        await _send(ws, {
            "type": "cmd_result",
            "request_id": request_id,
            "output": output[:4000],  # Telegram tem limite de 4096 chars
        })

    except subprocess.TimeoutExpired:
        await _send(ws, {
            "type": "cmd_result",
            "request_id": request_id,
            "error": "Timeout: o comando demorou mais de 30 segundos.",
        })
    except FileNotFoundError:
        await _send(ws, {
            "type": "cmd_result",
            "request_id": request_id,
            "error": f"Comando não encontrado: {command.split()[0]}",
        })
    except Exception as e:
        await _send(ws, {
            "type": "cmd_result",
            "request_id": request_id,
            "error": str(e),
        })


async def _metrics_loop(ws):
    """Envia métricas periodicamente e verifica thresholds para alertas."""
    last_cpu_alert = 0
    last_mem_alert = 0
    last_disk_alert = 0
    alert_cooldown = 300  # 5 minutos entre alertas do mesmo tipo

    import time

    while True:
        try:
            m = metrics.collect_metrics()
            await _send(ws, {"type": "metrics", "data": m})

            now = time.time()

            # Verifica thresholds e emite alertas
            cpu_pct = m["cpu"]["percent"]
            mem_pct = m["memory"]["percent"]
            disk_pct = m["disk"].get("percent", 0)

            if cpu_pct >= _thresholds["cpu"] and now - last_cpu_alert > alert_cooldown:
                await _send(ws, {
                    "type": "alert",
                    "data": {"metric": "cpu", "value": f"{cpu_pct:.1f}%",
                             "threshold": f"{_thresholds['cpu']}%"},
                })
                last_cpu_alert = now

            if mem_pct >= _thresholds["memory"] and now - last_mem_alert > alert_cooldown:
                await _send(ws, {
                    "type": "alert",
                    "data": {"metric": "memória", "value": f"{mem_pct:.1f}%",
                             "threshold": f"{_thresholds['memory']}%"},
                })
                last_mem_alert = now

            if disk_pct >= _thresholds["disk"] and now - last_disk_alert > alert_cooldown:
                await _send(ws, {
                    "type": "alert",
                    "data": {"metric": "disco", "value": f"{disk_pct:.1f}%",
                             "threshold": f"{_thresholds['disk']}%"},
                })
                last_disk_alert = now

        except Exception as e:
            logger.error(f"Erro ao coletar métricas: {e}")

        await asyncio.sleep(METRICS_INTERVAL)


async def _listen_loop(ws):
    """Recebe mensagens do master."""
    async for raw in ws:
        try:
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "cmd":
                asyncio.create_task(
                    _handle_command(ws, msg["request_id"], msg["command"])
                )

            elif mtype == "rename":
                new_name = msg.get("name", NODE_NAME)
                logger.info(f"Renomeado para: {new_name}")
                # Confirma ao master
                await _send(ws, {"type": "name_update", "name": new_name})

            elif mtype == "set_threshold":
                metric = msg.get("metric")
                value = msg.get("value")
                if metric in _thresholds and isinstance(value, (int, float)):
                    _thresholds[metric] = value
                    logger.info(f"Threshold atualizado: {metric} = {value}%")

        except json.JSONDecodeError:
            logger.warning("Mensagem inválida recebida do master")
        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")


async def _connect():
    """Conecta ao master, autentica e mantém conexão ativa."""
    global _connected

    while True:
        try:
            logger.info(f"Conectando ao master: {MASTER_WS_URL}")
            async with websockets.connect(
                MASTER_WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                # Autenticação
                await _send(ws, {
                    "type": "auth",
                    "api_key": API_KEY,
                    "node_id": NODE_ID,
                    "name": NODE_NAME,
                })

                response = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if response.get("type") != "auth_ok":
                    logger.error(f"Autenticação falhou: {response.get('message')}")
                    sys.exit(1)

                logger.info("✅ Autenticado no master com sucesso")
                _connected = True

                # Roda loops de métricas e escuta em paralelo
                try:
                    await asyncio.gather(
                        _metrics_loop(ws),
                        _listen_loop(ws),
                    )
                except ConnectionClosed as e:
                    logger.warning(f"Conexão encerrada: {e}")
                finally:
                    _connected = False

        except (ConnectionRefusedError, OSError) as e:
            logger.warning(f"Não foi possível conectar: {e}")
        except asyncio.TimeoutError:
            logger.warning("Timeout ao autenticar")
        except WebSocketException as e:
            logger.warning(f"Erro WebSocket: {e}")
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
        finally:
            _connected = False

        logger.info(f"Reconectando em {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(f"Node '{NODE_NAME}' iniciando...")
    asyncio.run(_connect())


if __name__ == "__main__":
    main()
