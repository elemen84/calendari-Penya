from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class OfficialHttpError(RuntimeError):
    pass


class OfficialHttpClient:
    """Small HTTP client with bounded retries for official public endpoints."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        retries: int = 3,
        backoff_seconds: float = 1.0,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "PenyaCalendarBot/1.0 (+https://github.com/)",
        }

    def _request(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> requests.Response:
        request_headers = {**self.headers, **(headers or {})}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=request_headers,
                    params=params,
                    timeout=self.timeout,
                )
                if response.status_code not in {408, 425, 429} and response.status_code < 500:
                    response.raise_for_status()
                    return response
                last_error = OfficialHttpError(f"HTTP {response.status_code} from {url}")
            except (requests.RequestException, OfficialHttpError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            delay = self.backoff_seconds * (2**attempt)
            LOGGER.warning(
                "Retrying official HTTP request",
                extra={"url": url, "attempt": attempt + 1, "delay_seconds": delay},
            )
            time.sleep(delay)
        raise OfficialHttpError(f"Request failed after retries: {url}") from last_error

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        response = self._request(url, headers=headers, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise OfficialHttpError(f"Invalid JSON response from {url}") from exc

    def get_text(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        response = self._request(url, headers=headers, params=params)
        return response.text

