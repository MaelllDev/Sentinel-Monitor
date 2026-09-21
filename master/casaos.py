"""
Cliente HTTP para a API do CasaOS.
Documentação: GET/PUT /v2/app_management/compose/{id}/status
              GET     /v2/app_management/compose
              GET     /v2/app_management/compose/{id}/logs
              PATCH   /v2/app_management/compose/{id}   (update)

Autenticação:
  - Usa CASAOS_USER + CASAOS_PASSWORD para fazer login e obter os tokens.
  - O access_token é renovado automaticamente via refresh_token antes de expirar.
  - Se o refresh_token expirar, faz login novamente com usuário e senha.
  - Variáveis no .env:
      CASAOS_URL       URL base do CasaOS (ex: http://192.168.1.100:80)
      CASAOS_USER      Usuário do CasaOS
      CASAOS_PASSWORD  Senha do CasaOS
"""

import asyncio
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)

CASAOS_URL      = os.getenv("CASAOS_URL", "").rstrip("/")
CASAOS_USER     = os.getenv("CASAOS_USER", "")
CASAOS_PASSWORD = os.getenv("CASAOS_PASSWORD", "")

_BASE = f"{CASAOS_URL}/v2/app_management"

# ── Estado interno dos tokens ────────────────────────────────────────────────
_access_token:   str   = ""
_refresh_token:  str   = ""
_expires_at:     float = 0.0          # unix timestamp do access_token
_token_lock:     asyncio.Lock | None  = None


def _get_lock() -> asyncio.Lock:
    global _token_lock
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    return _token_lock


# ── Login / renovação ────────────────────────────────────────────────────────

async def _login() -> bool:
    """Faz login com usuário e senha, armazena os tokens. Retorna True se OK."""
    global _access_token, _refresh_token, _expires_at

    if not CASAOS_URL or not CASAOS_USER or not CASAOS_PASSWORD:
        logger.warning("CasaOS: CASAOS_URL, CASAOS_USER ou CASAOS_PASSWORD não configurados.")
        return False

    url = f"{CASAOS_URL}/v1/users/login"
    payload = {"username": CASAOS_USER, "password": CASAOS_PASSWORD}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"CasaOS login falhou: HTTP {resp.status} — {text[:200]}")
                    return False
                data = await resp.json()
                token_data = data.get("data", {}).get("token", {})
                _access_token  = token_data.get("access_token", "")
                _refresh_token = token_data.get("refresh_token", "")
                _expires_at    = float(token_data.get("expires_at", 0))
                if _access_token:
                    logger.info("CasaOS: login realizado com sucesso.")
                    return True
                logger.error("CasaOS: login OK mas access_token vazio.")
                return False
    except Exception as e:
        logger.error(f"CasaOS _login error: {e}")
        return False


async def _refresh() -> bool:
    """Renova o access_token usando o refresh_token. Retorna True se OK."""
    global _access_token, _refresh_token, _expires_at

    if not _refresh_token:
        return False

    url = f"{CASAOS_URL}/v1/users/refresh"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={"Authorization": _refresh_token},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"CasaOS refresh falhou: HTTP {resp.status}. Tentando login completo.")
                    return False
                data = await resp.json()
                token_data = data.get("data", {}).get("token", {})
                new_access  = token_data.get("access_token", "")
                new_refresh = token_data.get("refresh_token", "")
                new_exp     = float(token_data.get("expires_at", 0))
                if new_access:
                    _access_token  = new_access
                    _refresh_token = new_refresh or _refresh_token
                    _expires_at    = new_exp
                    logger.info("CasaOS: access_token renovado via refresh_token.")
                    return True
                return False
    except Exception as e:
        logger.warning(f"CasaOS _refresh error: {e}. Tentando login completo.")
        return False


async def _ensure_token() -> bool:
    """
    Garante que existe um access_token válido.
    Ordem: verifica expiração → tenta refresh → fallback para login completo.
    Retorna True se token disponível.
    """
    global _access_token, _expires_at

    async with _get_lock():
        # Renova 60 segundos antes de expirar para evitar race conditions
        needs_refresh = (not _access_token) or (time.time() >= _expires_at - 60)

        if not needs_refresh:
            return True

        # Tenta renovar via refresh_token primeiro (mais rápido, sem senha)
        if _refresh_token and await _refresh():
            return True

        # Fallback: login completo com usuário e senha
        return await _login()


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": _access_token,
    }


# ── API calls ────────────────────────────────────────────────────────────────

async def list_apps() -> list[dict]:
    """
    Retorna lista de apps instalados no CasaOS.
    Cada item: { "id": str, "status": str, "title": str, "icon": str, "update": bool }
    """
    if not await _ensure_token():
        return []

    url = f"{_BASE}/compose"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    # Token rejeitado — força novo login e tenta uma vez mais
                    logger.warning("CasaOS list_apps: 401, forçando novo login.")
                    if await _login():
                        return await list_apps()
                    return []
                if resp.status != 200:
                    logger.warning(f"CasaOS list_apps: HTTP {resp.status}")
                    return []
                data = await resp.json()
                apps_raw = data.get("data", {})
                result = []
                for app_id, info in apps_raw.items():
                    store_info = info.get("store_info") or {}
                    title_map  = store_info.get("title") or {}
                    title = title_map.get("en_us") or title_map.get("en_US") or app_id
                    result.append({
                        "id":     app_id,
                        "status": info.get("status", "unknown"),
                        "title":  title,
                        "icon":   store_info.get("icon", ""),
                        "update": info.get("update_available", False),
                    })
                return result
    except Exception as e:
        logger.error(f"CasaOS list_apps error: {e}")
        return []


async def set_app_status(app_id: str, action: str) -> tuple[bool, str]:
    """
    Inicia ou para um app. action: 'start' | 'stop' | 'restart'
    Retorna (sucesso, mensagem).
    """
    if not await _ensure_token():
        return False, "Não foi possível autenticar no CasaOS."

    url = f"{_BASE}/compose/{app_id}/status"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url,
                json=action,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    if await _login():
                        return await set_app_status(app_id, action)
                    return False, "Falha de autenticação no CasaOS."
                text = await resp.text()
                if resp.status == 200:
                    return True, "OK"
                return False, f"HTTP {resp.status}: {text[:200]}"
    except Exception as e:
        logger.error(f"CasaOS set_app_status error: {e}")
        return False, str(e)


async def get_app_logs(app_id: str, lines: int = 100) -> str:
    """Retorna os últimos N logs de um app CasaOS."""
    if not await _ensure_token():
        return "❌ Não foi possível autenticar no CasaOS."

    url = f"{_BASE}/compose/{app_id}/logs"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params={"lines": lines},
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    if await _login():
                        return await get_app_logs(app_id, lines)
                    return "❌ Falha de autenticação no CasaOS."
                if resp.status != 200:
                    return f"❌ HTTP {resp.status}"
                data = await resp.json()
                return data.get("data", "(sem logs)")
    except Exception as e:
        logger.error(f"CasaOS get_app_logs error: {e}")
        return f"❌ Erro: {e}"


async def update_app(app_id: str) -> tuple[bool, str]:
    """
    Atualiza um app CasaOS para a versão mais recente.
    PATCH /v2/app_management/compose/{id}
    """
    if not await _ensure_token():
        return False, "Não foi possível autenticar no CasaOS."

    url = f"{_BASE}/compose/{app_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                url,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 401:
                    if await _login():
                        return await update_app(app_id)
                    return False, "Falha de autenticação no CasaOS."
                text = await resp.text()
                if resp.status == 200:
                    return True, "Atualização iniciada com sucesso."
                return False, f"HTTP {resp.status}: {text[:200]}"
    except Exception as e:
        logger.error(f"CasaOS update_app error: {e}")
        return False, str(e)


def is_configured() -> bool:
    """Retorna True se a integração CasaOS está ativada."""
    return bool(CASAOS_URL and CASAOS_USER and CASAOS_PASSWORD)
