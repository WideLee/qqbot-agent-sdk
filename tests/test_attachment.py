# -*- coding: utf-8 -*-
"""Unit tests for attachment_processor module.

Tests cover:
- AttachmentDownloader: retry, timeout, SSRF, caching, naming
- AttachmentProcessor: dispatching, image/voice/video/document handling
- Security helpers: _ssrf_redirect_guard, _safe_url_for_log
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from qqbot_agent_sdk.attachment import (
    AttachmentDownloader,
    AttachmentProcessor,
    _safe_url_for_log,
    _ssrf_redirect_guard,
)
from qqbot_agent_sdk.dto import MessageAttachment


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def temp_cache_dir():
    """Temporary cache directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def downloader(mock_http_client, temp_cache_dir):
    """AttachmentDownloader instance with mocked client."""
    return AttachmentDownloader(
        http_client=mock_http_client,
        cache_dir=temp_cache_dir,
        download_timeout=5.0,
        download_retries=2,
    )


@pytest.fixture
def processor(downloader):
    """AttachmentProcessor instance without STT."""
    return AttachmentProcessor(downloader=downloader, stt_pipeline=None)


# ── Security Helpers Tests ────────────────────────────────────────────

def test_safe_url_for_log_removes_query():
    """Test URL sanitization removes query parameters."""
    url = "https://cdn.qq.com/file.jpg?token=secret123&key=abc"
    result = _safe_url_for_log(url)
    assert result == "https://cdn.qq.com/file.jpg"
    assert "secret123" not in result
    assert "key=abc" not in result


def test_safe_url_for_log_truncates_long_urls():
    """Test URL truncation for long paths."""
    long_path = "/a" * 100
    url = f"https://cdn.qq.com{long_path}"
    result = _safe_url_for_log(url, max_len=50)
    assert len(result) == 50
    assert result.endswith("...")


def test_safe_url_for_log_empty_url():
    """Test empty URL handling."""
    assert _safe_url_for_log("") == ""
    assert _safe_url_for_log(None) == ""


@pytest.mark.asyncio
async def test_ssrf_redirect_guard_blocks_non_http_redirect():
    """Test SSRF guard blocks redirects to non-http schemes."""
    mock_response = Mock()
    mock_response.is_redirect = True
    mock_next_request = Mock()
    # The guard blocks when scheme not in (http, https) or netloc is empty
    mock_next_request.url = "file:///etc/passwd"
    mock_response.next_request = mock_next_request

    with pytest.raises(ValueError, match="Blocked redirect"):
        await _ssrf_redirect_guard(mock_response)


@pytest.mark.asyncio
async def test_ssrf_redirect_guard_allows_safe_redirect():
    """Test SSRF guard allows redirects to public URLs."""
    mock_response = Mock()
    mock_response.is_redirect = True
    mock_next_request = Mock()
    mock_next_request.url = "https://cdn.qq.com/file.jpg"
    mock_response.next_request = mock_next_request

    # Should not raise
    await _ssrf_redirect_guard(mock_response)


@pytest.mark.asyncio
async def test_ssrf_redirect_guard_ignores_non_redirect():
    """Test SSRF guard ignores non-redirect responses."""
    mock_response = Mock()
    mock_response.is_redirect = False

    # Should not raise
    await _ssrf_redirect_guard(mock_response)


# ── AttachmentDownloader Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_download_image_with_original_name(downloader, mock_http_client, temp_cache_dir):
    """Test image download with original filename."""
    url = "https://cdn.qq.com/avatar.jpg"
    original_name = "user_avatar.jpg"
    content_type = "image/jpeg"
    image_data = b"fake_image_data"

    # Mock HTTP response
    mock_response = Mock()
    mock_response.content = image_data
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    # Download
    result = await downloader.download_image(url, content_type, original_name)

    # Verify
    assert result is not None
    assert Path(result).exists()
    assert original_name in Path(result).name
    assert Path(result).read_bytes() == image_data
    mock_http_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_download_image_without_original_name(downloader, mock_http_client, temp_cache_dir):
    """Test image download without original filename (fallback to extension)."""
    url = "https://cdn.qq.com/12345"
    content_type = "image/png"
    image_data = b"fake_png_data"

    mock_response = Mock()
    mock_response.content = image_data
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    result = await downloader.download_image(url, content_type)

    assert result is not None
    assert result.endswith(".png")
    assert Path(result).read_bytes() == image_data


@pytest.mark.asyncio
async def test_download_image_cache_hit(downloader, mock_http_client, temp_cache_dir):
    """Test image download uses cache on second call."""
    url = "https://cdn.qq.com/cached.jpg"
    content_type = "image/jpeg"
    image_data = b"cached_data"

    # First download
    mock_response = Mock()
    mock_response.content = image_data
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    result1 = await downloader.download_image(url, content_type)
    assert mock_http_client.get.call_count == 1

    # Second download (should hit cache)
    result2 = await downloader.download_image(url, content_type)
    assert result1 == result2
    assert mock_http_client.get.call_count == 1  # No new HTTP call


@pytest.mark.asyncio
async def test_download_retry_on_timeout(downloader, mock_http_client):
    """Test download retries on timeout."""
    import httpx

    url = "https://cdn.qq.com/file.jpg"

    # First two calls timeout, third succeeds
    mock_http_client.get = AsyncMock(
        side_effect=[
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            Mock(content=b"data", raise_for_status=Mock()),
        ]
    )

    result = await downloader.download_image(url, "image/jpeg")

    assert result is not None
    assert mock_http_client.get.call_count == 3


@pytest.mark.asyncio
async def test_download_retry_on_429(downloader, mock_http_client):
    """Test download retries on 429 rate limit."""
    import httpx

    url = "https://cdn.qq.com/file.jpg"

    # 429 error, then success
    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    mock_http_client.get = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError("429", request=Mock(), response=mock_response_429),
            Mock(content=b"data", raise_for_status=Mock()),
        ]
    )

    result = await downloader.download_image(url, "image/jpeg")

    assert result is not None
    assert mock_http_client.get.call_count == 2


@pytest.mark.asyncio
async def test_download_no_retry_on_404(downloader, mock_http_client):
    """Test download does NOT retry on 404."""
    import httpx

    url = "https://cdn.qq.com/notfound.jpg"

    mock_response_404 = Mock()
    mock_response_404.status_code = 404
    mock_http_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("404", request=Mock(), response=mock_response_404)
    )

    result = await downloader.download_image(url, "image/jpeg")

    assert result is None
    assert mock_http_client.get.call_count == 1  # No retry


@pytest.mark.asyncio
async def test_download_blocks_unsafe_url(downloader):
    """Test download blocks unsafe URLs."""
    unsafe_urls = [
        "file:///etc/passwd",
        "javascript:alert('xss')",
        "/just/a/path",
        "ftp://example.com/file",
    ]

    for url in unsafe_urls:
        result = await downloader.download_image(url, "image/jpeg")
        assert result is None


@pytest.mark.asyncio
async def test_download_document_with_original_name(downloader, mock_http_client, temp_cache_dir):
    """Test document download with original filename."""
    url = "https://cdn.qq.com/doc123"
    original_name = "report.pdf"
    doc_data = b"fake_pdf_data"

    mock_response = Mock()
    mock_response.content = doc_data
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    result = await downloader.download_document(url, original_name)

    assert result is not None
    assert original_name in Path(result).name
    assert Path(result).read_bytes() == doc_data


# ── AttachmentProcessor Tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_processor_handles_image(processor, mock_http_client):
    """Test processor handles image attachments."""
    attachment = MessageAttachment(
        url="https://cdn.qq.com/photo.jpg",
        content_type="image/jpeg",
        filename="photo.jpg",
    )

    mock_response = Mock()
    mock_response.content = b"image_data"
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    results = await processor.process([attachment])

    assert len(results) == 1
    assert results[0].kind == "image"
    assert results[0].local_path
    assert Path(results[0].local_path).exists()


@pytest.mark.asyncio
async def test_processor_handles_video(processor, mock_http_client):
    """Test processor handles video attachments."""
    attachment = MessageAttachment(
        url="https://cdn.qq.com/video.mp4",
        content_type="video/mp4",
        filename="video.mp4",
    )

    mock_response = Mock()
    mock_response.content = b"video_data"
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    results = await processor.process([attachment])

    assert len(results) == 1
    assert results[0].kind == "video"
    assert "video.mp4" in results[0].description


@pytest.mark.asyncio
async def test_processor_handles_document(processor, mock_http_client):
    """Test processor handles document attachments."""
    attachment = MessageAttachment(
        url="https://cdn.qq.com/file.txt",
        content_type="text/plain",
        filename="notes.txt",
    )

    mock_response = Mock()
    mock_response.content = b"file content"
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    results = await processor.process([attachment])

    assert len(results) == 1
    assert results[0].kind == "document"
    assert "notes.txt" in results[0].description


@pytest.mark.asyncio
async def test_processor_skips_voice_without_stt(processor):
    """Test processor skips voice attachments when STT is None."""
    attachment = MessageAttachment(
        url="https://cdn.qq.com/voice.silk",
        content_type="audio/silk",
        filename="voice.silk",
    )

    results = await processor.process([attachment])

    assert len(results) == 0  # Voice skipped


@pytest.mark.asyncio
async def test_processor_handles_multiple_attachments(processor, mock_http_client):
    """Test processor handles multiple attachments in one batch."""
    attachments = [
        MessageAttachment(
            url="https://cdn.qq.com/photo1.jpg",
            content_type="image/jpeg",
            filename="photo1.jpg",
        ),
        MessageAttachment(
            url="https://cdn.qq.com/photo2.png",
            content_type="image/png",
            filename="photo2.png",
        ),
    ]

    mock_response = Mock()
    mock_response.content = b"data"
    mock_response.raise_for_status = Mock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    results = await processor.process(attachments)

    assert len(results) == 2
    assert all(r.kind == "image" for r in results)


@pytest.mark.asyncio
async def test_processor_skips_empty_url(processor):
    """Test processor skips attachments with empty URL."""
    attachment = MessageAttachment(
        url="",
        content_type="image/jpeg",
        filename="photo.jpg",
    )

    results = await processor.process([attachment])

    assert len(results) == 0


# ── Integration Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_pipeline_with_retry(temp_cache_dir):
    """Test full download pipeline with retry recovery."""
    import httpx

    mock_http_client = AsyncMock()

    # First call fails, second succeeds
    mock_http_client.get = AsyncMock(
        side_effect=[
            httpx.TimeoutException("timeout"),
            Mock(content=b"recovered_data", raise_for_status=Mock()),
        ]
    )

    downloader = AttachmentDownloader(
        http_client=mock_http_client,
        cache_dir=temp_cache_dir,
        download_retries=2,
    )

    processor = AttachmentProcessor(downloader=downloader)

    attachment = MessageAttachment(
        url="https://cdn.qq.com/image.jpg",
        content_type="image/jpeg",
        filename="image.jpg",
    )

    results = await processor.process([attachment])

    assert len(results) == 1
    assert results[0].kind == "image"
    assert Path(results[0].local_path).read_bytes() == b"recovered_data"
    assert mock_http_client.get.call_count == 2  # Retry happened
