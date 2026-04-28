# -*- coding: utf-8 -*-
"""Unit tests for media_loader module.

Tests cover:
- MediaLoader: URL loading, local file loading, edge cases
- MediaUploader: URL upload, local upload dispatch, error handling
- ChunkedUploader: prepare/part/complete flow, retry, error codes
- Exception classes: UploadDailyLimitExceededError, UploadFileTooLargeError
- Helper functions: _format_size, _compute_file_hashes, _read_file_chunk
"""

import base64
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from qqbot_agent_sdk.constants import MEDIA_TYPE_FILE, MEDIA_TYPE_IMAGE
from qqbot_agent_sdk.dto import (
    CompleteUploadResponse,
    RichMediaMessage,
    UploadPart,
    UploadPrepareResponse,
)
from qqbot_agent_sdk.media_loader import (
    ChunkedUploader,
    MediaLoader,
    MediaUploader,
    UploadDailyLimitExceededError,
    UploadFileTooLargeError,
    _compute_file_hashes,
    _format_size,
    _read_file_chunk,
)


# ══════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════


class TestFormatSize:
    """Tests for _format_size()."""

    def test_bytes(self):
        assert _format_size(0) == "0.0 B"
        assert _format_size(512) == "512.0 B"

    def test_kilobytes(self):
        assert _format_size(1024) == "1.0 KB"
        assert _format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert _format_size(1024 * 1024) == "1.0 MB"
        assert _format_size(int(12.3 * 1024 * 1024)) == "12.3 MB"

    def test_gigabytes(self):
        assert _format_size(1024 ** 3) == "1.0 GB"

    def test_terabytes(self):
        assert _format_size(1024 ** 4) == "1.0 TB"


class TestReadFileChunk:
    """Tests for _read_file_chunk()."""

    def test_read_full_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"hello world")
            f.flush()
            result = _read_file_chunk(f.name, 0, 11)
            assert result == b"hello world"
            Path(f.name).unlink()

    def test_read_middle_chunk(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"abcdefghijklmnop")
            f.flush()
            result = _read_file_chunk(f.name, 4, 5)
            assert result == b"efghi"
            Path(f.name).unlink()

    def test_read_from_offset(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"0123456789")
            f.flush()
            result = _read_file_chunk(f.name, 7, 3)
            assert result == b"789"
            Path(f.name).unlink()

    def test_read_short_read_raises(self):
        """Short read (truncated file) should raise IOError."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"short")
            f.flush()
            with pytest.raises(IOError, match="Short read"):
                _read_file_chunk(f.name, 0, 100)  # Ask for 100 bytes from 5-byte file
            Path(f.name).unlink()


class TestComputeFileHashes:
    """Tests for _compute_file_hashes()."""

    def test_small_file_md5_equals_md5_10m(self):
        """For files smaller than 10MB, md5 == md5_10m."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            data = b"test data for hashing"
            f.write(data)
            f.flush()

            result = _compute_file_hashes(f.name, len(data))

            assert result["md5"] == hashlib.md5(data).hexdigest()
            assert result["sha1"] == hashlib.sha1(data).hexdigest()
            # Small file: md5_10m should equal full md5
            assert result["md5_10m"] == result["md5"]
            Path(f.name).unlink()

    def test_hash_values_correct(self):
        """Verify hash values match expected."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            data = b"a" * 1000
            f.write(data)
            f.flush()

            result = _compute_file_hashes(f.name, len(data))

            assert result["md5"] == hashlib.md5(data).hexdigest()
            assert result["sha1"] == hashlib.sha1(data).hexdigest()
            Path(f.name).unlink()

    def test_empty_file(self):
        """Empty file should still produce valid hashes."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.flush()

            result = _compute_file_hashes(f.name, 0)

            assert result["md5"] == hashlib.md5(b"").hexdigest()
            assert result["sha1"] == hashlib.sha1(b"").hexdigest()
            assert result["md5_10m"] == result["md5"]
            Path(f.name).unlink()


# ══════════════════════════════════════════════════════════════════════
# Exception classes
# ══════════════════════════════════════════════════════════════════════


class TestUploadDailyLimitExceededError:
    """Tests for UploadDailyLimitExceededError."""

    def test_default_message(self):
        err = UploadDailyLimitExceededError("test.png", 1024)
        assert "test.png" in str(err)
        assert err.file_name == "test.png"
        assert err.file_size == 1024

    def test_custom_message(self):
        err = UploadDailyLimitExceededError("test.png", 1024, "custom msg")
        assert str(err) == "custom msg"

    def test_file_size_human(self):
        err = UploadDailyLimitExceededError("big.zip", 1024 * 1024 * 5)
        assert err.file_size_human == "5.0 MB"

    def test_is_exception(self):
        err = UploadDailyLimitExceededError("f.txt", 100)
        assert isinstance(err, Exception)


class TestUploadFileTooLargeError:
    """Tests for UploadFileTooLargeError."""

    def test_default_message(self):
        err = UploadFileTooLargeError("big.zip", 100 * 1024 * 1024)
        assert "big.zip" in str(err)
        assert "100.0 MB" in str(err)

    def test_with_limit(self):
        err = UploadFileTooLargeError("big.zip", 100 * 1024 * 1024, 50 * 1024 * 1024)
        assert "50.0 MB" in str(err)
        assert err.limit_human == "50.0 MB"

    def test_without_limit(self):
        err = UploadFileTooLargeError("big.zip", 100 * 1024 * 1024)
        assert err.limit_human == "unknown"

    def test_file_size_human(self):
        err = UploadFileTooLargeError("f.bin", 2048)
        assert err.file_size_human == "2.0 KB"


# ══════════════════════════════════════════════════════════════════════
# MediaLoader
# ══════════════════════════════════════════════════════════════════════


class TestMediaLoaderIsUrl:
    """Tests for MediaLoader.is_url()."""

    def test_http_url(self):
        assert MediaLoader.is_url("http://example.com/img.jpg") is True

    def test_https_url(self):
        assert MediaLoader.is_url("https://cdn.qq.com/file.png") is True

    def test_local_path(self):
        assert MediaLoader.is_url("/tmp/file.png") is False

    def test_relative_path(self):
        assert MediaLoader.is_url("./file.png") is False

    def test_empty_string(self):
        assert MediaLoader.is_url("") is False

    def test_ftp_url(self):
        assert MediaLoader.is_url("ftp://example.com/file") is False


class TestMediaLoaderLoadUrl:
    """Tests for MediaLoader.load() with URL sources."""

    def test_load_http_url(self):
        result = MediaLoader.load("https://cdn.qq.com/photo.jpg")
        assert result.data_or_url == "https://cdn.qq.com/photo.jpg"
        assert result.content_type == "image/jpeg"
        assert result.filename == "photo.jpg"

    def test_load_url_with_override_name(self):
        result = MediaLoader.load("https://cdn.qq.com/abc123", file_name="custom.png")
        assert result.filename == "custom.png"
        assert result.data_or_url == "https://cdn.qq.com/abc123"

    def test_load_url_unknown_content_type(self):
        result = MediaLoader.load("https://cdn.qq.com/unknown_file")
        assert result.content_type == "application/octet-stream"

    def test_load_url_with_query_params(self):
        url = "https://cdn.qq.com/photo.png?token=abc&expire=123"
        result = MediaLoader.load(url)
        assert result.data_or_url == url
        # mimetypes.guess_type 对含 query 的 URL 可能无法识别扩展名
        assert result.content_type in ("image/png", "application/octet-stream")

    def test_load_url_fallback_filename(self):
        """URL with no path should fallback to 'media'."""
        result = MediaLoader.load("https://cdn.qq.com/")
        assert result.filename == "media"


class TestMediaLoaderLoadLocal:
    """Tests for MediaLoader.load() with local file sources."""

    def test_load_local_file(self):
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".txt", mode="wb",
        ) as f:
            f.write(b"hello world")
            f.flush()

            result = MediaLoader.load(f.name)

            assert result.content_type == "text/plain"
            assert result.filename == Path(f.name).name
            # data_or_url 应该是 base64 编码
            decoded = base64.b64decode(result.data_or_url)
            assert decoded == b"hello world"
            Path(f.name).unlink()

    def test_load_local_with_override_name(self):
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".png", mode="wb",
        ) as f:
            f.write(b"\x89PNG")
            f.flush()

            result = MediaLoader.load(f.name, file_name="renamed.png")

            assert result.filename == "renamed.png"
            Path(f.name).unlink()

    def test_load_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            MediaLoader.load("/tmp/nonexistent_file_12345.txt")

    def test_load_empty_source_raises(self):
        with pytest.raises(ValueError, match="required"):
            MediaLoader.load("")

    def test_load_whitespace_source_raises(self):
        with pytest.raises(ValueError, match="required"):
            MediaLoader.load("   ")

    def test_load_placeholder_source_raises(self):
        with pytest.raises(ValueError, match="placeholder"):
            MediaLoader.load("<path>")


# ══════════════════════════════════════════════════════════════════════
# MediaUploader
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_api():
    """Mock QQApiClient."""
    api = AsyncMock()
    api.upload_c2c_file = AsyncMock()
    api.upload_group_file = AsyncMock()
    api.upload_c2c_prepare = AsyncMock()
    api.upload_group_prepare = AsyncMock()
    api.upload_c2c_part_finish = AsyncMock()
    api.upload_group_part_finish = AsyncMock()
    api.complete_c2c_upload = AsyncMock()
    api.complete_group_upload = AsyncMock()
    return api


@pytest.fixture
def mock_http():
    """Mock httpx.AsyncClient."""
    return AsyncMock()


@pytest.fixture
def uploader(mock_api, mock_http):
    """MediaUploader instance."""
    return MediaUploader(mock_api, mock_http, log_tag="TEST")


class TestMediaUploaderUpload:
    """Tests for MediaUploader.upload()."""

    @pytest.mark.asyncio
    async def test_unsupported_chat_type_raises(self, uploader):
        with pytest.raises(ValueError, match="Unsupported chat_type"):
            await uploader.upload("guild", "id", "https://example.com/img.jpg", MEDIA_TYPE_IMAGE)

    @pytest.mark.asyncio
    async def test_url_upload_c2c(self, uploader, mock_api):
        """URL source should call upload_c2c_file."""
        mock_api.upload_c2c_file.return_value = {"file_info": "token_c2c_123"}

        result = await uploader.upload(
            "c2c", "user_123", "https://cdn.qq.com/image.jpg", MEDIA_TYPE_IMAGE,
        )

        assert result == "token_c2c_123"
        mock_api.upload_c2c_file.assert_called_once()
        call_args = mock_api.upload_c2c_file.call_args
        assert call_args[0][0] == "user_123"
        msg = call_args[0][1]
        assert isinstance(msg, RichMediaMessage)
        assert msg.url == "https://cdn.qq.com/image.jpg"

    @pytest.mark.asyncio
    async def test_url_upload_group(self, uploader, mock_api):
        """URL source should call upload_group_file for group."""
        mock_api.upload_group_file.return_value = {"file_info": "token_grp_456"}

        result = await uploader.upload(
            "group", "group_456", "https://cdn.qq.com/file.zip", MEDIA_TYPE_FILE,
        )

        assert result == "token_grp_456"
        mock_api.upload_group_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_url_upload_no_file_info_raises(self, uploader, mock_api):
        """URL upload with no file_info in response should raise."""
        mock_api.upload_c2c_file.return_value = {"status": "ok"}

        with pytest.raises(RuntimeError, match="no file_info"):
            await uploader.upload(
                "c2c", "user_123", "https://cdn.qq.com/img.jpg", MEDIA_TYPE_IMAGE,
            )

    @pytest.mark.asyncio
    async def test_url_upload_retry_on_transient_error(self, uploader, mock_api):
        """URL upload should retry on non-fatal errors."""
        mock_api.upload_c2c_file.side_effect = [
            RuntimeError("server error 500"),
            {"file_info": "token_retry"},
        ]

        result = await uploader.upload(
            "c2c", "user_123", "https://cdn.qq.com/img.jpg", MEDIA_TYPE_IMAGE,
        )

        assert result == "token_retry"
        assert mock_api.upload_c2c_file.call_count == 2

    @pytest.mark.asyncio
    async def test_url_upload_no_retry_on_fatal_error(self, uploader, mock_api):
        """URL upload should NOT retry on fatal errors (400, 401, etc.)."""
        mock_api.upload_c2c_file.side_effect = RuntimeError("400 Bad Request")

        with pytest.raises(RuntimeError, match="400"):
            await uploader.upload(
                "c2c", "user_123", "https://cdn.qq.com/img.jpg", MEDIA_TYPE_IMAGE,
            )

        assert mock_api.upload_c2c_file.call_count == 1

    @pytest.mark.asyncio
    async def test_local_upload_dispatches_to_chunked(self, uploader, mock_api, mock_http):
        """Local file source should use chunked upload flow."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"test content")
            f.flush()

            # Mock the chunked upload flow
            mock_api.upload_c2c_prepare.return_value = UploadPrepareResponse(
                upload_id="up_123",
                block_size=1024 * 1024,
                parts=[UploadPart(index=1, presigned_url="https://cos.qq.com/part1")],
            )

            mock_put_resp = Mock()
            mock_put_resp.status_code = 200
            mock_put_resp.headers = {"ETag": "abc"}
            mock_put_resp.raise_for_status = Mock()
            mock_http.put = AsyncMock(return_value=mock_put_resp)

            mock_api.upload_c2c_part_finish = AsyncMock()
            mock_api.complete_c2c_upload.return_value = CompleteUploadResponse(
                file_info="chunked_token_123",
            )

            result = await uploader.upload(
                "c2c", "user_123", f.name, MEDIA_TYPE_FILE,
            )

            assert result == "chunked_token_123"
            mock_api.upload_c2c_prepare.assert_called_once()
            mock_api.complete_c2c_upload.assert_called_once()
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_local_upload_no_file_info_raises(self, uploader, mock_api, mock_http):
        """Chunked upload with empty file_info should raise."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"data")
            f.flush()

            mock_api.upload_c2c_prepare.return_value = UploadPrepareResponse(
                upload_id="up_x",
                block_size=1024,
                parts=[UploadPart(index=1, presigned_url="https://cos.qq.com/p")],
            )

            mock_put_resp = Mock()
            mock_put_resp.status_code = 200
            mock_put_resp.headers = {}
            mock_put_resp.raise_for_status = Mock()
            mock_http.put = AsyncMock(return_value=mock_put_resp)
            mock_api.upload_c2c_part_finish = AsyncMock()
            mock_api.complete_c2c_upload.return_value = CompleteUploadResponse(
                file_info="",
            )

            with pytest.raises(RuntimeError, match="no file_info"):
                await uploader.upload("c2c", "user_123", f.name, MEDIA_TYPE_FILE)

            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_url_upload_file_type_file_includes_name(self, uploader, mock_api):
        """MEDIA_TYPE_FILE uploads should include file_name in RichMediaMessage."""
        mock_api.upload_c2c_file.return_value = {"file_info": "token"}

        await uploader.upload(
            "c2c", "user_123", "https://cdn.qq.com/report.pdf", MEDIA_TYPE_FILE,
        )

        msg = mock_api.upload_c2c_file.call_args[0][1]
        assert msg.file_name == "report.pdf"

    @pytest.mark.asyncio
    async def test_url_upload_image_no_file_name(self, uploader, mock_api):
        """Non-file type uploads should NOT include file_name."""
        mock_api.upload_c2c_file.return_value = {"file_info": "token"}

        await uploader.upload(
            "c2c", "user_123", "https://cdn.qq.com/photo.jpg", MEDIA_TYPE_IMAGE,
        )

        msg = mock_api.upload_c2c_file.call_args[0][1]
        assert msg.file_name == ""


# ══════════════════════════════════════════════════════════════════════
# ChunkedUploader
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def chunked_uploader(mock_api, mock_http):
    """ChunkedUploader instance."""
    return ChunkedUploader(mock_api, mock_http, log_tag="TEST")


class TestChunkedUploaderPrepare:
    """Tests for ChunkedUploader._prepare()."""

    @pytest.mark.asyncio
    async def test_prepare_c2c(self, chunked_uploader, mock_api):
        """Should call upload_c2c_prepare for c2c."""
        expected = UploadPrepareResponse(
            upload_id="up_c2c",
            block_size=1024,
            parts=[],
        )
        mock_api.upload_c2c_prepare.return_value = expected

        result = await chunked_uploader._prepare(
            "c2c", "user_1", MEDIA_TYPE_IMAGE, "img.png", 100,
            {"md5": "a", "sha1": "b", "md5_10m": "a"},
        )

        assert result.upload_id == "up_c2c"
        mock_api.upload_c2c_prepare.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_group(self, chunked_uploader, mock_api):
        """Should call upload_group_prepare for group."""
        expected = UploadPrepareResponse(
            upload_id="up_grp",
            block_size=1024,
            parts=[],
        )
        mock_api.upload_group_prepare.return_value = expected

        result = await chunked_uploader._prepare(
            "group", "grp_1", MEDIA_TYPE_FILE, "f.zip", 500,
            {"md5": "x", "sha1": "y", "md5_10m": "x"},
        )

        assert result.upload_id == "up_grp"
        mock_api.upload_group_prepare.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_unsupported_type_raises(self, chunked_uploader):
        """Should raise ValueError for unsupported chat_type."""
        with pytest.raises(ValueError, match="Unsupported chat_type"):
            await chunked_uploader._prepare(
                "guild", "ch_1", MEDIA_TYPE_IMAGE, "img.png", 100,
                {"md5": "a", "sha1": "b", "md5_10m": "a"},
            )

    @pytest.mark.asyncio
    async def test_prepare_daily_limit_error(self, chunked_uploader, mock_api):
        """Should raise UploadDailyLimitExceededError on biz_code 40093002."""
        mock_api.upload_c2c_prepare.side_effect = RuntimeError(
            "biz_code 40093002: daily limit exceeded"
        )

        with pytest.raises(UploadDailyLimitExceededError) as exc_info:
            await chunked_uploader._prepare(
                "c2c", "user_1", MEDIA_TYPE_IMAGE, "img.png", 1024,
                {"md5": "a", "sha1": "b", "md5_10m": "a"},
            )

        assert exc_info.value.file_name == "img.png"
        assert exc_info.value.file_size == 1024

    @pytest.mark.asyncio
    async def test_prepare_other_runtime_error_reraises(self, chunked_uploader, mock_api):
        """Non-daily-limit RuntimeError should be re-raised as-is."""
        mock_api.upload_c2c_prepare.side_effect = RuntimeError("some other error")

        with pytest.raises(RuntimeError, match="some other error"):
            await chunked_uploader._prepare(
                "c2c", "user_1", MEDIA_TYPE_IMAGE, "img.png", 100,
                {"md5": "a", "sha1": "b", "md5_10m": "a"},
            )


class TestChunkedUploaderComplete:
    """Tests for ChunkedUploader._complete()."""

    @pytest.mark.asyncio
    async def test_complete_c2c(self, chunked_uploader, mock_api):
        expected = CompleteUploadResponse(file_info="final_token")
        mock_api.complete_c2c_upload.return_value = expected

        result = await chunked_uploader._complete("c2c", "user_1", "up_123")

        assert result.file_info == "final_token"
        mock_api.complete_c2c_upload.assert_called_once_with("user_1", "up_123")

    @pytest.mark.asyncio
    async def test_complete_group(self, chunked_uploader, mock_api):
        expected = CompleteUploadResponse(file_info="grp_token")
        mock_api.complete_group_upload.return_value = expected

        result = await chunked_uploader._complete("group", "grp_1", "up_456")

        assert result.file_info == "grp_token"
        mock_api.complete_group_upload.assert_called_once_with("grp_1", "up_456")

    @pytest.mark.asyncio
    async def test_complete_retry_on_failure(self, chunked_uploader, mock_api):
        """complete_upload should retry on transient failure."""
        mock_api.complete_c2c_upload.side_effect = [
            RuntimeError("transient"),
            CompleteUploadResponse(file_info="recovered_token"),
        ]

        result = await chunked_uploader._complete("c2c", "user_1", "up_789")

        assert result.file_info == "recovered_token"
        assert mock_api.complete_c2c_upload.call_count == 2

    @pytest.mark.asyncio
    async def test_complete_exhausted_retries_raises(self, chunked_uploader, mock_api):
        """complete_upload should raise after exhausting retries."""
        mock_api.complete_c2c_upload.side_effect = RuntimeError("persistent error")

        with pytest.raises(RuntimeError, match="complete_upload failed"):
            await chunked_uploader._complete("c2c", "user_1", "up_fail")

        # 1 initial + 2 retries = 3
        assert mock_api.complete_c2c_upload.call_count == 3


class TestChunkedUploaderPartFinish:
    """Tests for ChunkedUploader._part_finish_with_retry()."""

    @pytest.mark.asyncio
    async def test_part_finish_c2c_success(self, chunked_uploader, mock_api):
        mock_api.upload_c2c_part_finish = AsyncMock()

        await chunked_uploader._part_finish_with_retry(
            "c2c", "user_1", "up_123", 1, 1024, "abc123", 10.0,
        )

        mock_api.upload_c2c_part_finish.assert_called_once_with(
            "user_1", "up_123", 1, 1024, "abc123",
        )

    @pytest.mark.asyncio
    async def test_part_finish_group_success(self, chunked_uploader, mock_api):
        mock_api.upload_group_part_finish = AsyncMock()

        await chunked_uploader._part_finish_with_retry(
            "group", "grp_1", "up_456", 2, 2048, "def456", 10.0,
        )

        mock_api.upload_group_part_finish.assert_called_once_with(
            "grp_1", "up_456", 2, 2048, "def456",
        )

    @pytest.mark.asyncio
    async def test_part_finish_non_retryable_error_raises(self, chunked_uploader, mock_api):
        """Non-40093001 errors should be re-raised immediately."""
        mock_api.upload_c2c_part_finish.side_effect = RuntimeError("500 server error")

        with pytest.raises(RuntimeError, match="500 server error"):
            await chunked_uploader._part_finish_with_retry(
                "c2c", "user_1", "up_123", 1, 1024, "abc", 10.0,
            )

        assert mock_api.upload_c2c_part_finish.call_count == 1


class TestChunkedUploaderPutPresigned:
    """Tests for ChunkedUploader._put_to_presigned_url()."""

    @pytest.mark.asyncio
    async def test_put_success(self, chunked_uploader, mock_http):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"ETag": "etag_abc"}
        mock_resp.raise_for_status = Mock()
        mock_http.put = AsyncMock(return_value=mock_resp)

        await chunked_uploader._put_to_presigned_url(
            "https://cos.qq.com/part1", b"data", 1, 1,
        )

        mock_http.put.assert_called_once()
        call_kwargs = mock_http.put.call_args
        assert call_kwargs[1]["content"] == b"data"

    @pytest.mark.asyncio
    async def test_put_retry_on_failure(self, chunked_uploader, mock_http):
        """PUT should retry on transient failure."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.raise_for_status = Mock()

        mock_http.put = AsyncMock(side_effect=[
            Exception("network error"),
            mock_resp,
        ])

        await chunked_uploader._put_to_presigned_url(
            "https://cos.qq.com/part1", b"data", 1, 1,
        )

        assert mock_http.put.call_count == 2

    @pytest.mark.asyncio
    async def test_put_exhausted_retries_raises(self, chunked_uploader, mock_http):
        """PUT should raise after all retries fail."""
        mock_http.put = AsyncMock(side_effect=Exception("persistent failure"))

        with pytest.raises(RuntimeError, match="upload failed after"):
            await chunked_uploader._put_to_presigned_url(
                "https://cos.qq.com/part1", b"data", 1, 3,
            )

        # 1 initial + 2 retries = 3
        assert mock_http.put.call_count == 3


class TestChunkedUploaderFullFlow:
    """Integration tests for ChunkedUploader.upload() full flow."""

    @pytest.mark.asyncio
    async def test_single_part_upload(self, mock_api, mock_http):
        """Full single-part upload flow (small file)."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"small file content")
            f.flush()

            mock_api.upload_c2c_prepare.return_value = UploadPrepareResponse(
                upload_id="up_single",
                block_size=1024 * 1024,
                parts=[UploadPart(index=1, presigned_url="https://cos.qq.com/p1")],
            )

            mock_put_resp = Mock()
            mock_put_resp.status_code = 200
            mock_put_resp.headers = {"ETag": "etag1"}
            mock_put_resp.raise_for_status = Mock()
            mock_http.put = AsyncMock(return_value=mock_put_resp)

            mock_api.upload_c2c_part_finish = AsyncMock()
            mock_api.complete_c2c_upload.return_value = CompleteUploadResponse(
                file_info="final_single",
            )

            chunked = ChunkedUploader(mock_api, mock_http, log_tag="TEST")
            result = await chunked.upload(
                chat_type="c2c",
                target_id="user_1",
                file_path=f.name,
                file_type=MEDIA_TYPE_FILE,
                file_name="test.txt",
            )

            assert result.file_info == "final_single"
            mock_api.upload_c2c_prepare.assert_called_once()
            mock_http.put.assert_called_once()
            mock_api.upload_c2c_part_finish.assert_called_once()
            mock_api.complete_c2c_upload.assert_called_once_with("user_1", "up_single")
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_multi_part_upload(self, mock_api, mock_http):
        """Full multi-part upload flow."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin", mode="wb") as f:
            f.write(b"x" * 2000)
            f.flush()

            mock_api.upload_group_prepare.return_value = UploadPrepareResponse(
                upload_id="up_multi",
                block_size=1000,
                parts=[
                    UploadPart(index=1, presigned_url="https://cos.qq.com/p1"),
                    UploadPart(index=2, presigned_url="https://cos.qq.com/p2"),
                ],
            )

            mock_put_resp = Mock()
            mock_put_resp.status_code = 200
            mock_put_resp.headers = {}
            mock_put_resp.raise_for_status = Mock()
            mock_http.put = AsyncMock(return_value=mock_put_resp)

            mock_api.upload_group_part_finish = AsyncMock()
            mock_api.complete_group_upload.return_value = CompleteUploadResponse(
                file_info="final_multi",
            )

            chunked = ChunkedUploader(mock_api, mock_http, log_tag="TEST")
            result = await chunked.upload(
                chat_type="group",
                target_id="grp_1",
                file_path=f.name,
                file_type=MEDIA_TYPE_FILE,
                file_name="big.bin",
            )

            assert result.file_info == "final_multi"
            assert mock_http.put.call_count == 2
            assert mock_api.upload_group_part_finish.call_count == 2
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_progress_callback(self, mock_api, mock_http):
        """Progress callback should be invoked for each part."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"data")
            f.flush()

            mock_api.upload_c2c_prepare.return_value = UploadPrepareResponse(
                upload_id="up_prog",
                block_size=1024 * 1024,
                parts=[UploadPart(index=1, presigned_url="https://cos.qq.com/p1")],
            )

            mock_put_resp = Mock()
            mock_put_resp.status_code = 200
            mock_put_resp.headers = {}
            mock_put_resp.raise_for_status = Mock()
            mock_http.put = AsyncMock(return_value=mock_put_resp)

            mock_api.upload_c2c_part_finish = AsyncMock()
            mock_api.complete_c2c_upload.return_value = CompleteUploadResponse(
                file_info="token",
            )

            progress_calls = []
            chunked = ChunkedUploader(
                mock_api, mock_http, log_tag="TEST",
                on_progress=lambda p: progress_calls.append(p),
            )
            await chunked.upload("c2c", "user_1", f.name, MEDIA_TYPE_FILE, "f.txt")

            assert len(progress_calls) == 1
            assert progress_calls[0]["completed_parts"] == 1
            assert progress_calls[0]["total_parts"] == 1
            Path(f.name).unlink()
