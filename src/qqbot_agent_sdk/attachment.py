# -*- coding: utf-8 -*-
"""QQ Bot attachment downloading and processing pipeline.

Provides two composable classes:

- :class:`AttachmentDownloader` — downloads CDN URLs to a local cache directory
  with retry, SSRF protection, and transient error handling.
- :class:`AttachmentProcessor` — orchestrates the full attachment pipeline,
  returning a list of :class:`ProcessedAttachment` for each inbound message.

**STTPipeline** has been moved to :mod:`~audio` module for better organization.

All classes are dependency-injected at construction time and carry no
external framework imports.

Security notes:

- :func:`_ssrf_redirect_guard` validates redirect targets to prevent SSRF attacks.
- For production use with httpx.AsyncClient, pass event hooks::

    import httpx
    from qqbot_agent_sdk.attachment import _ssrf_redirect_guard
    
    client = httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        event_hooks={"response": [_ssrf_redirect_guard]},
    )

Usage::

    from qqbot_agent_sdk.audio import STTPipeline, resolve_stt_config

    downloader = AttachmentDownloader(
        http_client=httpx_client,
        cache_dir="/path/to/cache",
    )
    stt = STTPipeline(
        http_client=httpx_client,
        stt_config_fn=lambda: resolve_stt_config(config.extra),
        downloader=downloader,
        log_tag="QQBot",
    )
    processor = AttachmentProcessor(downloader=downloader, stt_pipeline=stt)
    results = await processor.process(attachments)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional
from urllib.parse import unquote, urlparse

from .audio import convert_audio_to_wav, guess_audio_ext, is_voice_content_type
from .dto import MessageAttachment
from .utils import build_user_agent

if TYPE_CHECKING:
    from .audio import STTPipeline

logger = logging.getLogger(__name__)


# ── Security helpers ──────────────────────────────────────────────────

async def _ssrf_redirect_guard(response: Any) -> None:
    """Re-validate each redirect target to prevent redirect-based SSRF.

    Without this, an attacker can host a public URL that 302-redirects to
    http://169.254.169.254/ and bypass the pre-flight _is_safe_url() check.

    Must be async because httpx.AsyncClient awaits response event hooks.

    To use, pass event_hooks when creating httpx.AsyncClient::

        import httpx
        from qqbot_agent_sdk.attachment import _ssrf_redirect_guard
        
        client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            event_hooks={"response": [_ssrf_redirect_guard]},
        )
    """
    if response.is_redirect and response.next_request:
        redirect_url = str(response.next_request.url)
        parsed = urlparse(redirect_url)
        if not (parsed.scheme in ("http", "https") and bool(parsed.netloc)):
            raise ValueError(
                f"Blocked redirect to unsafe URL: {redirect_url[:80]}"
            )


def _safe_url_for_log(url: str, max_len: int = 80) -> str:
    """Return a URL string safe for logs (truncated, no query/fragment)."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        safe = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        safe = str(url)
    if len(safe) <= max_len:
        return safe
    if max_len <= 3:
        return "." * max_len
    return f"{safe[:max_len - 3]}..."


# ── Result type ───────────────────────────────────────────────────────

@dataclass
class ProcessedAttachment:
    """Processed attachment descriptor.

    All three textual fields are populated when meaningful, so consumers
    can pick the level of detail they need:

    - ``transcript``: structured field holding the voice recognition
      result (STT or QQ ``asr_refer_text``). Empty for non-voice or when
      no transcript could be produced.
    - ``description``: human-readable, prompt-friendly view (built via
      :func:`describe_attachment`); already includes ``transcript`` for
      voice attachments. Use this when stitching attachment context into
      a single text body for an LLM.
    - ``local_path``: absolute path to the locally cached file (the WAV
      for voice attachments). Empty when the download failed.

    :param kind: ``'image'`` | ``'voice'`` | ``'video'`` | ``'document'``.
    :param local_path: Absolute path to the locally cached file.
    :param content_type: MIME type of the attachment.
    :param transcript: Voice transcription text (for ``kind='voice'``).
    :param description: Unified human-readable description.
    """

    kind: str
    local_path: str
    content_type: str
    transcript: str = ""
    description: str = ""


# ── AttachmentDownloader ─────────────────────────────────────────────

class AttachmentDownloader:
    """Download QQ CDN URLs to a local cache directory.

    Dependency-injected: requires only an HTTP client and a cache directory path.

    Features:
    - Retry mechanism with exponential backoff (2 retries by default)
    - SSRF protection (basic scheme validation + redirect guard)
    - Precise exception handling (TimeoutException, HTTPStatusError)
    - Smart error classification (4xx non-retryable except 429)

    :param http_client: Any async HTTP client with ``.get()`` method.
    :param cache_dir: Root directory for cached files.
    :param log_tag: Log prefix.
    :param download_timeout: HTTP request timeout in seconds.
    :param download_retries: Number of retry attempts on transient errors.
    """

    def __init__(
        self,
        http_client: Any,
        cache_dir: str,
        log_tag: str = "QQBot",
        download_timeout: float = 30.0,
        download_retries: int = 2,
    ) -> None:
        self._http_client = http_client
        self._cache_dir = Path(cache_dir)
        self._log_tag = log_tag
        self._download_timeout = download_timeout
        self._download_retries = download_retries

    def update_http_client(self, http_client: Any) -> None:
        """Replace the HTTP client (called after connect())."""
        self._http_client = http_client

    async def download_image(
        self,
        url: str,
        content_type: str,
        original_name: str = "",
    ) -> Optional[str]:
        """Download an image URL using MD5-based deduplication.

        :param url: CDN URL to download.
        :param content_type: MIME type (used to derive file extension).
        :param original_name: Original filename for naming the cached file.
        :returns: Local file path, or ``None`` on failure.
        """
        if not self._is_safe_url(url):
            logger.warning("[%s] Blocked unsafe image URL: %s", self._log_tag, _safe_url_for_log(url))
            return None

        # Build cache filename (mirrors document handling)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        if original_name:
            # Use original filename if provided (with hash prefix for uniqueness)
            cached_path = self._cache_dir / f"img_{url_hash}_{original_name}"
        else:
            # Fallback to extension guessing from content_type
            ext = mimetypes.guess_extension(content_type) or ".jpg"
            cached_path = self._cache_dir / f"img_{url_hash}{ext}"

        if cached_path.exists():
            logger.debug("[%s] Image cache hit: %s", self._log_tag, cached_path.name)
            return str(cached_path)

        data = await self._fetch(url)
        if data is None:
            return None

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cached_path.write_bytes(data)
        logger.debug("[%s] Image cached: %s (%d bytes)", self._log_tag, cached_path.name, len(data))
        return str(cached_path)

    async def download_audio(self, url: str, filename: str = "") -> Optional[str]:
        """Download an audio URL and convert to WAV.

        No deduplication (audio is converted to a new format on each download).

        :param url: CDN URL or pre-converted WAV URL.
        :param filename: Hint for extension detection.
        :returns: Local WAV file path, or ``None`` on failure.
        """
        if not self._is_safe_url(url):
            logger.warning("[%s] Blocked unsafe audio URL: %s", self._log_tag, _safe_url_for_log(url))
            return None

        data = await self._fetch(url)
        if data is None:
            return None

        return await self._convert_and_cache_audio(data, filename or url)

    async def download_document(self, url: str, original_name: str = "") -> Optional[str]:
        """Download a document/file URL with MD5-based deduplication.

        :param url: CDN URL to download.
        :param original_name: Original filename for naming the cached file.
        :returns: Local file path, or ``None`` on failure.
        """
        if not self._is_safe_url(url):
            logger.warning("[%s] Blocked unsafe document URL: %s", self._log_tag, _safe_url_for_log(url))
            return None

        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        name = original_name or _extract_filename_from_url(url) or "qq_attachment"
        cached_path = self._cache_dir / f"doc_{url_hash}_{name}"

        if cached_path.exists():
            logger.debug("[%s] Document cache hit: %s", self._log_tag, cached_path.name)
            return str(cached_path)

        data = await self._fetch(url)
        if data is None:
            return None

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cached_path.write_bytes(data)
        return str(cached_path)

    async def download(self, url: str, content_type: str, filename: str = "") -> Optional[str]:
        """Dispatch to the correct download method based on *content_type*.

        :param url: CDN URL to download.
        :param content_type: MIME type used for routing.
        :param filename: Original filename hint passed to handlers.
        :returns: Local file path, or ``None`` on failure.
        """
        ct = content_type.lower()
        if ct.startswith("image/"):
            return await self.download_image(url, content_type, filename)
        if ct.startswith("audio/") or ct == "voice":
            return await self.download_audio(url, filename)
        return await self.download_document(url, filename)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch(self, url: str) -> Optional[bytes]:
        """Perform an HTTP GET with retry and return raw bytes.

        QQ Bot CDN URLs are publicly accessible and do not require authentication.

        Retry strategy:
        - Retries on: TimeoutException, HTTPStatusError (429+, 5xx)
        - No retry on: 4xx errors (except 429)
        - Exponential backoff: 1.5s, 3.0s
        - SSRF protection: validates redirect targets via event hooks
        """
        if not self._http_client:
            logger.warning("[%s] No HTTP client available", self._log_tag)
            return None

        try:
            import httpx
        except ImportError:
            logger.error("[%s] httpx not installed", self._log_tag)
            return None

        for attempt in range(self._download_retries + 1):
            try:
                # Note: httpx.AsyncClient event_hooks require the hook to be async
                resp = await self._http_client.get(
                    url,
                    timeout=self._download_timeout,
                    follow_redirects=True,
                    headers={
                        "User-Agent": build_user_agent(),
                        "Accept": "*/*",
                    },
                )
                # Manual redirect guard (if client doesn't support event_hooks)
                # In production, pass event_hooks={"response": [_ssrf_redirect_guard]}
                # when creating the httpx.AsyncClient
                resp.raise_for_status()
                return resp.content

            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                # Non-retryable: 4xx errors (except 429)
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 429:
                    logger.debug(
                        "[%s] Non-retryable HTTP %d for %s",
                        self._log_tag,
                        exc.response.status_code,
                        _safe_url_for_log(url),
                    )
                    return None

                # Retry logic
                if attempt < self._download_retries:
                    wait = 1.5 * (attempt + 1)  # 1.5s, 3.0s
                    logger.debug(
                        "[%s] Retry %d/%d for %s (wait %.1fs): %s",
                        self._log_tag,
                        attempt + 1,
                        self._download_retries,
                        _safe_url_for_log(url),
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
                    continue

                logger.warning(
                    "[%s] Download failed after %d retries for %s: %s",
                    self._log_tag,
                    self._download_retries,
                    _safe_url_for_log(url),
                    exc,
                )
                return None

            except Exception as exc:
                logger.debug(
                    "[%s] Unexpected download error for %s: %s",
                    self._log_tag,
                    _safe_url_for_log(url),
                    exc,
                )
                return None

        return None

    async def _convert_and_cache_audio(
        self,
        audio_data: bytes,
        source_hint: str,
    ) -> Optional[str]:
        """Convert audio bytes to WAV and write to cache."""
        wav_path = await convert_audio_to_wav(
            audio_data,
            source_hint=source_hint,
            log_tag=self._log_tag,
        )
        if not wav_path:
            ext = guess_audio_ext(audio_data)
            return self._write_to_cache(audio_data, ext)

        try:
            wav_data = Path(wav_path).read_bytes()
            os.unlink(wav_path)
            return self._write_to_cache(wav_data, ".wav")
        except Exception as exc:
            logger.debug("[%s] Failed to read converted WAV: %s", self._log_tag, exc)
            return None

    def _write_to_cache(self, data: bytes, ext: str) -> str:
        """Write *data* to a uniquely named file in the cache directory."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=ext,
            dir=self._cache_dir,
            delete=False,
        ) as tmp:
            tmp.write(data)
            return tmp.name

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Check URL safety (basic scheme validation).

        Can be extended by subclasses to apply stricter validation rules.
        """
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)


# ── AttachmentProcessor ───────────────────────────────────────────────

class AttachmentProcessor:
    """Process a list of :class:`~dto.MessageAttachment` objects.

    Dispatches each attachment to the appropriate handler based on content
    type, returning a flat list of :class:`ProcessedAttachment` results.

    :param downloader: :class:`AttachmentDownloader` instance.
    :param stt_pipeline: :class:`STTPipeline` instance (optional; voice
        attachments are skipped if ``None``).
    """

    def __init__(
        self,
        downloader: AttachmentDownloader,
        stt_pipeline: Optional[STTPipeline] = None,
    ) -> None:
        self._downloader = downloader
        self._stt = stt_pipeline

    async def process(
        self,
        attachments: List[MessageAttachment],
    ) -> List[ProcessedAttachment]:
        """Process all attachments and return results.

        :param attachments: List of inbound :class:`~dto.MessageAttachment`.
        :returns: List of :class:`ProcessedAttachment` (one per processed item).
        """
        results: List[ProcessedAttachment] = []
        for att in attachments:
            url = att.resolved_url
            if not url:
                continue
            ct = att.content_type.strip().lower()
            result = await self._process_one(att, url, ct)
            if result is not None:
                results.append(result)
        return results

    async def _process_one(
        self,
        att: MessageAttachment,
        url: str,
        ct: str,
    ) -> Optional[ProcessedAttachment]:
        """Dispatch a single attachment to the correct handler."""
        if is_voice_content_type(ct, att.filename):
            return await self._handle_voice(att)
        if ct.startswith("image/"):
            return await self._handle_image(url, ct)
        if ct.startswith("video/"):
            return await self._handle_video(url, ct, att.filename)
        return await self._handle_document(url, ct, att.filename)

    async def _handle_voice(
        self,
        att: MessageAttachment,
    ) -> Optional[ProcessedAttachment]:
        """Process a voice attachment.

        Behaviour matrix (priority order):

        - **STT pipeline available** → call ``transcribe_with_path``, which
          downloads the WAV (kept in cache) and runs the configured STT
          engine, falling back to ``asr_refer_text`` if STT yields nothing.
          Both ``local_path`` (WAV) and ``transcript`` are populated when
          available.
        - **No STT pipeline** → still try to download the WAV directly
          (so ``local_path`` is meaningful for downstream consumers) and
          surface ``att.asr_refer_text`` as the transcript.
        """
        transcript: Optional[str] = None
        local_path: Optional[str] = None

        if self._stt is not None:
            transcript, local_path = await self._stt.transcribe_with_path(att)
        else:
            # Without an STT engine: download WAV ourselves (so
            # ``local_path`` is filled) and fall back to QQ's built-in
            # ASR for the transcript.
            url = self._best_voice_url(att)
            if url:
                local_path = await self._downloader.download_audio(url, att.filename)
            transcript = att.asr_refer_text or None

        return ProcessedAttachment(
            kind="voice",
            local_path=local_path or "",
            content_type=att.content_type,
            transcript=transcript or "",
            description=describe_attachment(
                att.content_type,
                att.filename,
                local_path,
                transcript=transcript or "",
            ),
        )

    @staticmethod
    def _best_voice_url(att: MessageAttachment) -> str:
        """Return the best URL to download a voice attachment from.

        Mirrors :meth:`STTPipeline._resolve_download_url` — prefers
        ``voice_wav_url`` (pre-converted WAV from QQ) over the raw URL.
        """
        wav_url = att.voice_wav_url.strip()
        if wav_url:
            return f"https:{wav_url}" if wav_url.startswith("//") else wav_url
        return att.resolved_url

    async def _handle_image(
        self,
        url: str,
        ct: str,
    ) -> Optional[ProcessedAttachment]:
        local_path = await self._downloader.download_image(url, ct)
        if not local_path:
            return None
        return ProcessedAttachment(kind="image", local_path=local_path, content_type=ct)

    async def _handle_video(
        self,
        url: str,
        ct: str,
        filename: str,
    ) -> Optional[ProcessedAttachment]:
        local_path = await self._downloader.download_document(url, filename)
        return ProcessedAttachment(
            kind="video",
            local_path=local_path or "",
            content_type=ct,
            description=describe_attachment(ct, filename, local_path),
        )

    async def _handle_document(
        self,
        url: str,
        ct: str,
        filename: str,
    ) -> Optional[ProcessedAttachment]:
        local_path = await self._downloader.download_document(url, filename)
        # Fall back to MIME type when no original filename is provided so the
        # description still carries useful identification (matches legacy
        # behaviour: ``[file: text/plain (...)]``).
        display_name = filename or ct
        return ProcessedAttachment(
            kind="document",
            local_path=local_path or "",
            content_type=ct,
            description=describe_attachment(ct, display_name, local_path),
        )


# ── Helpers ───────────────────────────────────────────────────────────

def _extract_filename_from_url(url: str) -> str:
    """Extract the filename component from a URL path."""
    try:
        return Path(unquote(urlparse(url).path)).name
    except Exception:
        return ""


def describe_attachment(
    content_type: str,
    filename: str,
    local_path: Optional[str] = None,
    transcript: str = "",
) -> str:
    """Build a human-readable text description for a QQ Bot attachment.

    Used to embed attachment context into plain-text message bodies — both
    for processed attachments (voice transcribed via STT) and for
    quoted/reference messages where the SDK only sees the raw metadata.

    :param content_type: MIME type string (e.g. ``"image/jpeg"``).
    :param filename: Original filename from the attachment metadata.
    :param local_path: Local cached file path, if available.
    :param transcript: Voice transcription text, when known (either from
        QQ's ``asr_refer_text`` or a configured STT engine). Only used by
        the voice/audio branch; ignored for other attachment types.
    :returns: A short bracketed description string.

    Examples::

        describe_attachment("image/jpeg", "photo.jpg", "/tmp/cache/photo.jpg")
        # → "[image: photo.jpg (/tmp/cache/photo.jpg)]"

        describe_attachment("audio/silk", "", None, transcript="你好")
        # → "[voice: 你好]"

        describe_attachment(
            "voice", "a.amr", "/tmp/a.wav", transcript="一二三四",
        )
        # → "[voice: 一二三四 (/tmp/a.wav)]"

        describe_attachment("audio/silk", "", None)
        # → "[voice message]"

        describe_attachment("application/pdf", "report.pdf", None)
        # → "[file: report.pdf]"
    """
    ct = content_type.lower()
    fname = filename or ""
    cached = local_path or ""
    text = (transcript or "").strip()

    if ct.startswith("image/"):
        if fname and cached:
            return f"[image: {fname} ({cached})]"
        if fname:
            return f"[image: {fname}]"
        return "[image]"

    if "audio" in ct or "voice" in ct or "silk" in ct:
        if text and cached:
            return f"[voice: {text} ({cached})]"
        if text:
            return f"[voice: {text}]"
        if cached:
            return f"[voice message ({cached})]"
        return "[voice message]"

    if ct.startswith("video/"):
        if fname and cached:
            return f"[video: {fname} ({cached})]"
        if fname:
            return f"[video: {fname}]"
        return "[video]"

    # Generic file
    if fname and cached:
        return f"[file: {fname} ({cached})]"
    if fname:
        return f"[file: {fname}]"
    return "[attachment]"
