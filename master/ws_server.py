"""
Servidor WebSocket do master.
Recebe conexões dos nodes, autentica via API key e mantém estado em memória.
"""

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)

# Estado global dos nodes conectados
# { node_id: { "ws": ws, "name": str, "metrics": dict, "last_seen": datetime } }
connected_nodes: dict = {}

# Histórico de métricas por node: { node_id: deque de {"ts": datetime, "cpu": float, "mem": float, "disk": float} }
HISTORY_SIZE = 30  # últimas 30 amostras (~5 min com intervalo de 10s)
metrics_history: dict[str, deque] = {}

# Contagem de reconexões por node_id
reconnect_count: dict[str, int] = {}

# Callbacks registrados pelo bot para receber eventos
_event_callbacks: list = []

API_KEY = os.getenv("API_KEY", "changeme")


def register_event_callback(callback):
    """Registra um callback que será chamado quando um evento chegar de um node."""
    _event_callbacks.append(callback)


async def _notify_callbacks(event: dict):
    for cb in _event_callbacks:
        try:
            await cb(event)
        except Exception as e:
            logger.error(f"Erro no callback de evento: {e}")


async def _handle_node(websocket: WebSocketServerProtocol):
    node_id = None
    try:
        # Primeira mensagem deve ser autenticação
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        msg = json.loads(raw)

        if msg.get("type") != "auth" or msg.get("api_key") != API_KEY:
            await websocket.send(json.dumps({"type": "auth_error", "message": "API key inválida"}))
            await websocket.close()
            return

        node_id = msg.get("node_id", str(id(websocket)))
        node_name = msg.get("name", node_id)

        connected_nodes[node_id] = {
            "ws": websocket,
            "name": node_name,
            "metrics": {},
            "last_seen": datetime.now(),
        }

        await websocket.send(json.dumps({"type": "auth_ok", "message": "Autenticado com sucesso"}))
        logger.info(f"Node conectado: {node_name} ({node_id})")

        # Conta reconexões (a primeira conexão conta como 0 quedas anteriores)
        reconnect_count[node_id] = reconnect_count.get(node_id, -1) + 1

        await _notify_callbacks({
            "type": "node_connected",
            "node_id": node_id,
            "name": node_name,
            "reconnects": reconnect_count[node_id],
        })

        async for raw_msg in websocket:
            try:
                data = json.loads(raw_msg)
                connected_nodes[node_id]["last_seen"] = datetime.now()

                if data.get("type") == "metrics":
                    connected_nodes[node_id]["metrics"] = data.get("data", {})
                    # Alimenta buffer de histórico
                    m = data.get("data", {})
                    if node_id not in metrics_history:
                        metrics_history[node_id] = deque(maxlen=HISTORY_SIZE)
                    metrics_history[node_id].append({
                        "ts": datetime.now(),
                        "cpu": m.get("cpu", {}).get("percent", 0),
                        "mem": m.get("memory", {}).get("percent", 0),
                        "disk": m.get("disk", {}).get("percent", 0),
                    })

                elif data.get("type") == "alert":
                    await _notify_callbacks({
                        "type": "alert",
                        "node_id": node_id,
                        "name": node_name,
                        "data": data.get("data", {}),
                    })

                elif data.get("type") == "cmd_result":
                    await _notify_callbacks({
                        "type": "cmd_result",
                        "node_id": node_id,
                        "name": node_name,
                        "request_id": data.get("request_id"),
                        "output": data.get("output", ""),
                        "error": data.get("error", ""),
                    })

                elif data.get("type") == "name_update":
                    new_name = data.get("name", node_name)
                    connected_nodes[node_id]["name"] = new_name
                    node_name = new_name

            except json.JSONDecodeError:
                logger.warning(f"Mensagem inválida de {node_id}")

    except asyncio.TimeoutError:
        logger.warning("Timeout na autenticação do node")
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"Erro no handler do node {node_id}: {e}")
    finally:
        if node_id and node_id in connected_nodes:
            name = connected_nodes[node_id]["name"]
            del connected_nodes[node_id]
            logger.info(f"Node desconectado: {name} ({node_id})")
            await _notify_callbacks({"type": "node_disconnected", "node_id": node_id, "name": name})


async def send_command(node_id: str, command: str, request_id: str) -> bool:
    """Envia um comando para um node específico. Retorna True se enviado."""
    node = connected_nodes.get(node_id)
    if not node:
        return False
    try:
        await node["ws"].send(json.dumps({
            "type": "cmd",
            "request_id": request_id,
            "command": command,
        }))
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar comando para {node_id}: {e}")
        return False


async def remove_node(node_id: str) -> bool:
    """Fecha a conexão com o node e remove do estado. Retorna True se removido."""
    node = connected_nodes.get(node_id)
    if not node:
        return False
    try:
        await node["ws"].close()
    except Exception:
        pass
    # O finally do _handle_node limpa connected_nodes e notifica callbacks,
    # mas se a limpeza não ocorreu ainda, garantimos aqui.
    if node_id in connected_nodes:
        name = connected_nodes[node_id]["name"]
        del connected_nodes[node_id]
        await _notify_callbacks({"type": "node_disconnected", "node_id": node_id, "name": name})
    return True


async def rename_node(node_id: str, new_name: str) -> bool:
    """Envia instrução de renomear para o node."""
    node = connected_nodes.get(node_id)
    if not node:
        # Node offline, apenas atualiza localmente se existir
        return False
    connected_nodes[node_id]["name"] = new_name
    try:
        await node["ws"].send(json.dumps({"type": "rename", "name": new_name}))
        return True
    except Exception as e:
        logger.error(f"Erro ao renomear node {node_id}: {e}")
        return False


def get_history(node_id: str) -> list:
    """Retorna o histórico de métricas de um node (lista de dicts)."""
    h = metrics_history.get(node_id)
    if not h:
        return []
    return list(h)


def get_nodes() -> dict:
    """Retorna cópia do estado atual dos nodes."""
    return {
        nid: {
            "name": info["name"],
            "metrics": info["metrics"],
            "last_seen": info["last_seen"].isoformat(),
        }
        for nid, info in connected_nodes.items()
    }


def get_node_by_name(name: str) -> tuple[str, dict] | None:
    """Busca node pelo nome (case-insensitive). Retorna (node_id, info) ou None."""
    name_lower = name.lower()
    for nid, info in connected_nodes.items():
        if info["name"].lower() == name_lower:
            return nid, info
    return None


async def start_server(host: str = "0.0.0.0", port: int = 8765):
    logger.info(f"Servidor WebSocket iniciando em {host}:{port}")
    async with websockets.serve(_handle_node, host, port):
        await asyncio.Future()  # roda para sempre
