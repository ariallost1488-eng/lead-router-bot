import logging
import aiohttp
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

_shared_session: Optional[aiohttp.ClientSession] = None

async def get_http_session() -> aiohttp.ClientSession:
    """Возвращает общий пул HTTP-соединений"""
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        connector = aiohttp.TCPConnector(limit=25, ttl_dns_cache=300)
        _shared_session = aiohttp.ClientSession(connector=connector)
    return _shared_session

async def close_http_session() -> None:
    """Закрывает общий HTTP-сеанс"""
    global _shared_session
    if _shared_session and not _shared_session.closed:
        await _shared_session.close()
        _shared_session = None

class DialogiAIClient:
    def __init__(self, api_key: str, base_url: str = "https://api.dialogiai.ru", session: Optional[aiohttp.ClientSession] = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/json"
        }
        self._custom_session = session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._custom_session and not self._custom_session.closed:
            return self._custom_session
        return await get_http_session()

    async def get_me(self) -> Optional[Dict[str, Any]]:
        """Проверка ключа и получение информации о клиенте"""
        url = f"{self.base_url}/v1/me"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"get_me status={resp.status}: {await resp.text()}")
        except Exception as e:
            logger.error(f"Error calling get_me: {e}")
        return None

    async def get_profiles(self) -> List[Dict[str, Any]]:
        """Получение списка активных профилей площадок"""
        url = f"{self.base_url}/v1/profiles"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("profiles", [])
                logger.warning(f"get_profiles status={resp.status}: {await resp.text()}")
        except Exception as e:
            logger.error(f"Error calling get_profiles: {e}")
        return []

    async def get_leads_for_profile(self, profile_id: str, limit: int = 50, created_since: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получение списка лидов профиля"""
        url = f"{self.base_url}/v1/profiles/{profile_id}/leads"
        params = {"limit": limit}
        if created_since:
            params["created_since"] = created_since

        try:
            session = await self._get_session()
            async with session.get(url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("leads", [])
                logger.warning(f"get_leads status={resp.status} for profile {profile_id}: {await resp.text()}")
        except Exception as e:
            logger.error(f"Error calling get_leads_for_profile {profile_id}: {e}")
        return []

    async def get_lead_details(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Получение полной детализации лида, включая чат и объект"""
        url = f"{self.base_url}/v1/leads/{lead_id}"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"get_lead_details status={resp.status} for lead {lead_id}: {await resp.text()}")
        except Exception as e:
            logger.error(f"Error calling get_lead_details {lead_id}: {e}")
        return None
