__all__ = ("ClientCore",)

import threading
from typing import TYPE_CHECKING, Any
import warnings

from ..errors import ClientClosedError, UnclosedClientError
from ..headers import HeaderSource
from ..messages import CLIENT_CLOSED, UNCLOSED_CLIENT
from ..request import Request
from ..timeouts import Timeouts
from ..transport_stats import TransportStats
from ..types import QueryParams, RequestData
from ..url import URL
from .config import ClientConfig
from .raw import create_raw_client
from .request_builder.builder import RequestBuilder
from .request_builder.merge import RequestMergeContract
from .request_builder.models import RequestBuildOptions
from .stats import stats_from_raw


if TYPE_CHECKING:
    from foghttp import _foghttp


class ClientCore:
    def __init__(self, *, config: ClientConfig) -> None:
        self._config = config
        self._closed = False
        self._client_lock = threading.Lock()
        self._client: _foghttp.RawClient | None = None
        self._request_builder = RequestBuilder(
            merge_contract=RequestMergeContract(defaults=config.request_defaults),
        )

    def __del__(self) -> None:
        if getattr(self, "_closed", True) is False:
            warnings.warn(UNCLOSED_CLIENT, UnclosedClientError, stacklevel=2)

    def build_request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
    ) -> Request:
        return self._request_builder.build(
            RequestBuildOptions(
                method=method,
                url=url,
                headers=headers,
                params=params,
                content=content,
                data=data,
                json=json,
            ),
        )

    def stats(self) -> TransportStats:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            raw_stats = None if raw_client is None else raw_client.stats()
        if raw_stats is None:
            return TransportStats()
        return stats_from_raw(raw=raw_stats)

    def dump_transport_state(self) -> dict[str, int]:
        stats = self.stats()
        return {
            "active_requests": stats.active_requests,
            "pending_requests": stats.pending_requests,
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError(CLIENT_CLOSED)

    def _raw_client(self) -> "_foghttp.RawClient":
        self._ensure_open()
        raw_client = self._client
        if raw_client is not None:
            return raw_client
        with self._client_lock:
            self._ensure_open()
            return self._raw_client_locked()

    def _raw_client_locked(self) -> "_foghttp.RawClient":
        raw_client = self._client
        if raw_client is None:
            raw_client = self._create_raw_client()
            self._client = raw_client
        return raw_client

    def _create_raw_client(self) -> "_foghttp.RawClient":
        return create_raw_client(
            limits=self._config.limits,
            timeouts=self._config.timeouts,
            follow_redirects=self._config.follow_redirects,
            max_redirects=self._config.max_redirects,
            runtime_workers=self._config.runtime_workers,
            trust_env=self._config.trust_env,
            tls=self._config.tls,
        )

    def _request_timeouts(self, timeout: Timeouts | None) -> Timeouts:
        return timeout or self._config.timeouts
