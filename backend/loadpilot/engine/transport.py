from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import aiohttp

from ..config import RequestSpec


@dataclass(frozen=True, slots=True)
class Response:
    status: int | None
    bytes_in: int = 0
    error: str | None = None
    error_detail: str | None = None


class Transport(Protocol):
    async def send(self, request: RequestSpec) -> Response: ...

    async def aclose(self) -> None: ...


class AiohttpTransport:
    """Default transport.

    aiohttp is used instead of httpx because httpx's connection pool degrades
    badly under high concurrency (about 270 vs 14,000 RPS at 50 connections in
    our benchmark), which would make the load generator the bottleneck.
    """

    def __init__(self, *, verify: bool = True, max_connections: int = 1000) -> None:
        self._verify = verify
        self._max_connections = max_connections
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        # Created lazily so it binds to the running event loop.
        if self._session is None:
            connector = aiohttp.TCPConnector(
                limit=self._max_connections, ssl=self._verify, ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                connector=connector, cookie_jar=aiohttp.DummyCookieJar()
            )
        return self._session

    async def send(self, request: RequestSpec) -> Response:
        session = self._get_session()
        try:
            async with session.request(
                request.method,
                request.url,
                headers=request.headers,
                params=request.params or None,
                json=request.json_body,
                data=request.body,
                timeout=aiohttp.ClientTimeout(total=request.timeout),
                allow_redirects=request.follow_redirects,
            ) as resp:
                body = await resp.read()
                return Response(status=resp.status, bytes_in=len(body))
        except TimeoutError as e:
            return _error("timeout", e)
        except aiohttp.ClientConnectorError as e:
            return _error("connect_error", e)
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError) as e:
            return _error("protocol_error", e)
        except aiohttp.ClientError as e:
            return _error(f"http_error:{type(e).__name__}", e)

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


def _error(kind: str, exc: BaseException) -> Response:
    return Response(status=None, error=kind, error_detail=str(exc) or type(exc).__name__)
