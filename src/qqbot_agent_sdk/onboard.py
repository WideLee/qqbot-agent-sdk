# -*- coding: utf-8 -*-
"""QQBot scan-to-configure (QR code onboard) module.

Calls the ``q.qq.com`` ``create_bind_task`` / ``poll_bind_result`` APIs to
generate a QR-code URL and poll for scan completion.  On success the caller
receives the bot's *app_id*, *client_secret* (decrypted locally), and the
scanner's *user_openid*.

Reference: https://bot.q.qq.com/wiki/develop/api-v2/
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional
from urllib.parse import quote

from .constants import (
    ONBOARD_API_TIMEOUT,
    ONBOARD_CREATE_PATH,
    ONBOARD_POLL_INTERVAL,
    ONBOARD_POLL_PATH,
    PORTAL_HOST,
)
from .utils import get_api_headers

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Crypto utilities (internal)
# ---------------------------------------------------------------------------

def _generate_bind_key() -> str:
    """Generate a 256-bit random AES key encoded as base64.

    The key is passed to ``_create_bind_task`` so the server can encrypt
    the bot credentials before returning them. Only this client holds
    the key, ensuring the secret never travels in plaintext.

    :returns: Base64-encoded 32-byte random key.
    """
    return base64.b64encode(os.urandom(32)).decode()


def _decrypt_secret(encrypted_base64: str, key_base64: str) -> str:
    """Decrypt a base64-encoded AES-256-GCM ciphertext.

    Ciphertext layout (after base64-decoding)::

        IV (12 bytes) | ciphertext (N bytes) | AuthTag (16 bytes)

    :param encrypted_base64: The ``bot_encrypt_secret`` value from poll result.
    :param key_base64: The base64 AES key from :func:`_generate_bind_key`.
    :returns: Decrypted *client_secret* as a UTF-8 string.
    :raises ValueError: If decryption fails (wrong key or tampered data).
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = base64.b64decode(key_base64)
    raw = base64.b64decode(encrypted_base64)

    # AESGCM expects ciphertext + tag concatenated after the IV
    iv = raw[:12]
    ciphertext_with_tag = raw[12:]

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OnboardError(Exception):
    """Base exception for onboard module errors."""


class OnboardAPIError(OnboardError):
    """Raised when the onboard API returns a non-zero retcode.
    
    :param retcode: Error code from API response.
    :param message: Error message from API response.
    """
    
    def __init__(self, retcode: int, message: str) -> None:
        self.retcode = retcode
        self.message = message
        super().__init__(f"Onboard API error [{retcode}]: {message}")


class OnboardExpiredError(OnboardError):
    """Raised when the QR code / bind task has expired."""


# ---------------------------------------------------------------------------
# Bind status and result types
# ---------------------------------------------------------------------------

class BindStatus(IntEnum):
    """Status codes returned by ``poll_bind_result``."""

    NONE = 0
    PENDING = 1
    COMPLETED = 2
    EXPIRED = 3


@dataclass
class _BindTaskResult:
    """Internal result from creating a bind task."""
    
    task_id: str
    aes_key: str


@dataclass
class _BindPollResult:
    """Internal result from polling a bind task."""
    
    status: BindStatus
    bot_appid: str
    bot_encrypt_secret: str
    user_openid: str
    
    def is_completed(self) -> bool:
        return self.status == BindStatus.COMPLETED
    
    def is_pending(self) -> bool:
        return self.status == BindStatus.PENDING
    
    def is_expired(self) -> bool:
        return self.status == BindStatus.EXPIRED


@dataclass
class OnboardResult:
    """Complete onboard result with decrypted credentials.
    
    :param app_id: Bot application ID.
    :param client_secret: Decrypted client secret (ready to use).
    :param user_openid: OpenID of the user who scanned the QR code.
    """
    
    app_id: str
    client_secret: str
    user_openid: str


# ---------------------------------------------------------------------------
# Internal API (not exported)
# ---------------------------------------------------------------------------

async def _create_bind_task(
    timeout: float = ONBOARD_API_TIMEOUT,
) -> _BindTaskResult:
    """Create a bind task and return typed result with task_id and AES key.

    The AES key is generated locally and sent to the server so it can
    encrypt the bot credentials before returning them.

    :param timeout: HTTP request timeout in seconds.
    :returns: :class:`_BindTaskResult` with task_id and aes_key.
    :raises OnboardAPIError: If the API returns a non-zero ``retcode``.
    :raises RuntimeError: If the response is missing required fields.
    """
    import httpx

    url = f"https://{PORTAL_HOST}{ONBOARD_CREATE_PATH}"
    key = _generate_bind_key()

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(url, json={"key": key}, headers=get_api_headers())
        resp.raise_for_status()
        data = resp.json()

    retcode = data.get("retcode", -1)
    if retcode != 0:
        raise OnboardAPIError(retcode, data.get("msg", "create_bind_task failed"))

    task_id = data.get("data", {}).get("task_id")
    if not task_id:
        raise RuntimeError("create_bind_task: missing task_id in response")

    logger.debug("create_bind_task ok: task_id=%s", task_id)
    return _BindTaskResult(task_id=task_id, aes_key=key)


async def _poll_bind_result(
    task_id: str,
    timeout: float = ONBOARD_API_TIMEOUT,
) -> _BindPollResult:
    """Poll the bind result for *task_id*.

    :param task_id: Task ID from :func:`_create_bind_task`.
    :param timeout: HTTP request timeout in seconds.
    :returns: :class:`_BindPollResult` with status and encrypted credentials.
    :raises OnboardAPIError: If the API returns a non-zero ``retcode``.
    """
    import httpx

    url = f"https://{PORTAL_HOST}{ONBOARD_POLL_PATH}"

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(
            url,
            json={"task_id": task_id},
            headers=get_api_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    retcode = data.get("retcode", -1)
    if retcode != 0:
        raise OnboardAPIError(retcode, data.get("msg", "poll_bind_result failed"))

    d = data.get("data", {})
    return _BindPollResult(
        status=BindStatus(d.get("status", 0)),
        bot_appid=str(d.get("bot_appid", "")),
        bot_encrypt_secret=d.get("bot_encrypt_secret", ""),
        user_openid=d.get("user_openid", ""),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_connect_url(task_id: str, source: Optional[str] = None) -> str:
    """Build the QR-code target URL for *task_id*.

    :param task_id: Task ID from bind task.
    :param source: Optional source identifier (default from SDK config).
    :returns: Full HTTPS URL to embed in a QR code.
    """
    from .constants import sdk_config
    
    # 如果提供了 source，覆盖配置中的 source
    if source is not None:
        original_source = sdk_config.source
        sdk_config.source = source
        template = sdk_config.qr_url_template()
        sdk_config.source = original_source
    else:
        template = sdk_config.qr_url_template()
    
    return template.format(task_id=quote(task_id))


async def start_onboard(
    on_qr_ready: Optional[Callable[[str], None]] = None,
    poll_interval: float = ONBOARD_POLL_INTERVAL,
    poll_timeout: float = 300.0,
    source: Optional[str] = None,
) -> OnboardResult:
    """Start the complete onboard flow: create task, poll for completion, decrypt credentials.
    
    This is the recommended high-level API for onboarding. It handles:
    - Task creation
    - QR code URL generation
    - Polling until completion or timeout
    - Credential decryption
    
    Usage::
    
        def show_qr(url: str):
            print(f"Please scan: {url}")
            # Or generate QR code image and display
        
        result = await start_onboard(on_qr_ready=show_qr)
        print(f"Bot ID: {result.app_id}")
        print(f"Secret: {result.client_secret}")
        print(f"User: {result.user_openid}")
    
    :param on_qr_ready: Optional callback to receive QR code URL when ready.
        The callback receives the URL string and should display it to the user.
    :param poll_interval: Seconds to wait between poll attempts (default 2s).
    :param poll_timeout: Maximum seconds to wait for completion (default 300s / 5 minutes).
    :param source: Optional source identifier for QR code URL.
    :returns: :class:`OnboardResult` with decrypted credentials.
    :raises OnboardAPIError: If API returns an error.
    :raises TimeoutError: If polling exceeds poll_timeout without completion.
    :raises OnboardExpiredError: If the QR code / bind task expires before completion.
    """
    # Step 1: Create bind task
    task = await _create_bind_task()
    logger.info("Onboard task created: task_id=%s", task.task_id)
    
    # Step 2: Build QR code URL
    qr_url = build_connect_url(task.task_id, source=source)
    
    # Step 3: Notify caller with QR code URL
    if on_qr_ready:
        try:
            on_qr_ready(qr_url)
        except Exception as e:
            logger.warning("on_qr_ready callback failed: %s", e)
    
    # Step 4: Poll for completion
    start_time = time.time()
    attempt = 0
    
    while True:
        attempt += 1
        elapsed = time.time() - start_time
        
        # Check timeout
        if elapsed >= poll_timeout:
            raise TimeoutError(
                f"Onboard polling timeout after {elapsed:.1f}s "
                f"({attempt} attempts)"
            )
        
        # Poll result
        try:
            result = await _poll_bind_result(task.task_id)
        except OnboardAPIError as e:
            logger.error("Poll failed (attempt %d): [%d] %s", attempt, e.retcode, e.message)
            raise
        
        # Check status
        if result.is_completed():
            logger.info(
                "Onboard completed after %.1fs (%d attempts): bot_appid=%s user_openid=%s",
                elapsed, attempt, result.bot_appid, result.user_openid,
            )
            # Decrypt credentials internally
            client_secret = _decrypt_secret(result.bot_encrypt_secret, task.aes_key)
            return OnboardResult(
                app_id=result.bot_appid,
                client_secret=client_secret,
                user_openid=result.user_openid,
            )
        
        if result.is_expired():
            raise OnboardExpiredError(
                f"Onboard task expired after {elapsed:.1f}s ({attempt} attempts)"
            )
        
        # Still pending, wait and retry
        logger.debug(
            "Onboard pending (attempt %d, elapsed %.1fs), retry in %.1fs",
            attempt, elapsed, poll_interval,
        )
        await asyncio.sleep(poll_interval)
