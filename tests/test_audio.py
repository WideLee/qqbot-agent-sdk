# -*- coding: utf-8 -*-
"""Unit tests for audio module.

Tests cover:
- Audio format detection (is_voice_content_type, guess_audio_ext)
- Audio conversion pipeline (convert_audio_to_wav)
- STT configuration (resolve_stt_config, STTConfig)
- STT API calls (call_stt)
- STTPipeline (full transcription workflow)
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from qqbot_agent_sdk.audio import (
    STTConfig,
    STTPipeline,
    call_stt,
    convert_audio_to_wav,
    guess_audio_ext,
    is_voice_content_type,
    resolve_stt_config,
)


# ── Voice Detection Tests ─────────────────────────────────────────────

def test_is_voice_content_type_audio_mime():
    """Test voice detection by audio MIME type."""
    assert is_voice_content_type("audio/silk", "") is True
    assert is_voice_content_type("audio/mpeg", "") is True
    assert is_voice_content_type("audio/wav", "") is True
    assert is_voice_content_type("voice", "") is True


def test_is_voice_content_type_by_extension():
    """Test voice detection by filename extension."""
    assert is_voice_content_type("", "voice.silk") is True
    assert is_voice_content_type("", "audio.mp3") is True
    assert is_voice_content_type("", "recording.wav") is True
    assert is_voice_content_type("", "message.amr") is True


def test_is_voice_content_type_non_voice():
    """Test non-voice content is not detected as voice."""
    assert is_voice_content_type("image/jpeg", "photo.jpg") is False
    assert is_voice_content_type("text/plain", "notes.txt") is False
    assert is_voice_content_type("video/mp4", "video.mp4") is False


def test_guess_audio_ext_silk():
    """Test SILK audio detection."""
    assert guess_audio_ext(b"#!SILK_V3") == ".silk"
    assert guess_audio_ext(b"#!SILK") == ".silk"
    assert guess_audio_ext(b"\x02!") == ".silk"


def test_guess_audio_ext_wav():
    """Test WAV audio detection."""
    assert guess_audio_ext(b"RIFF") == ".wav"


def test_guess_audio_ext_mp3():
    """Test MP3 audio detection."""
    assert guess_audio_ext(b"\xff\xfb") == ".mp3"
    assert guess_audio_ext(b"\xff\xf3") == ".mp3"


def test_guess_audio_ext_ogg():
    """Test OGG audio detection."""
    assert guess_audio_ext(b"\x4f\x67\x67\x53") == ".ogg"


def test_guess_audio_ext_default():
    """Test default fallback to AMR."""
    assert guess_audio_ext(b"unknown_format") == ".amr"


# ── Audio Conversion Tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_convert_audio_to_wav_wav_input_no_self_overwrite():
    """Test that .wav input does not self-overwrite via wav_path collision.

    Before the fix, wav_path == src_path when ext is '.wav', causing
    the source file to be overwritten and then deleted in the finally block.
    After the fix, wav_path uses '.conv.wav' suffix to avoid collision.
    """
    # Create a minimal WAV file (RIFF header magic bytes)
    wav_data = b"RIFF" + b"\x00" * 100

    # Mock the converters to simulate a "pass-through" scenario
    with patch("qqbot_agent_sdk.audio.convert_silk_to_wav", return_value=None), \
         patch("qqbot_agent_sdk.audio.convert_ffmpeg_to_wav") as mock_ffmpeg:
        # ffmpeg "succeeds" by creating the output file
        async def fake_ffmpeg(src_path, wav_path, log_tag="QQBot"):
            # Verify the paths are different
            assert src_path != wav_path, (
                f"wav_path should differ from src_path, got: {src_path}"
            )
            assert wav_path.endswith(".conv.wav")
            # Write a fake WAV output
            Path(wav_path).write_bytes(b"RIFF" + b"\x00" * 50)
            return wav_path

        mock_ffmpeg.side_effect = fake_ffmpeg

        result = await convert_audio_to_wav(wav_data, source_hint="voice.wav")

        assert result is not None
        assert result.endswith(".conv.wav")
        # Clean up
        if Path(result).exists():
            os.unlink(result)


# ── STT Configuration Tests ───────────────────────────────────────────

def test_sttconfig_dataclass():
    """Test STTConfig dataclass."""
    config = STTConfig(
        base_url="https://api.openai.com/v1",
        api_key="sk-test123",
        model="whisper-1",
    )
    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_key == "sk-test123"
    assert config.model == "whisper-1"


def test_sttconfig_default_model():
    """Test STTConfig default model."""
    config = STTConfig(
        base_url="https://api.openai.com/v1",
        api_key="sk-test123",
    )
    assert config.model == "whisper-1"


def test_resolve_stt_config_from_dict():
    """Test STT config resolution from config dict."""
    extra = {
        "stt": {
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "test_key",
            "model": "custom-model",
        }
    }

    config = resolve_stt_config(extra)

    assert config is not None
    assert config.base_url == "https://api.example.com/v1"
    assert config.api_key == "test_key"
    assert config.model == "custom-model"


def test_resolve_stt_config_from_provider():
    """Test STT config resolution from provider name."""
    extra = {
        "stt": {
            "provider": "glm",
            "apiKey": "glm_key",
        }
    }

    config = resolve_stt_config(extra)

    assert config is not None
    assert config.base_url == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert config.api_key == "glm_key"
    assert config.model == "glm-asr"


def test_resolve_stt_config_disabled():
    """Test STT config returns None when disabled."""
    extra = {"stt": {"enabled": False}}

    config = resolve_stt_config(extra)

    assert config is None


def test_resolve_stt_config_from_env():
    """Test STT config resolution from environment variables."""
    with patch.dict(os.environ, {
        "QQ_STT_API_KEY": "env_key",
        "QQ_STT_BASE_URL": "https://env.api.com",
        "QQ_STT_MODEL": "env-model",
    }):
        config = resolve_stt_config({})

        assert config is not None
        assert config.base_url == "https://env.api.com"
        assert config.api_key == "env_key"
        assert config.model == "env-model"


def test_resolve_stt_config_no_config():
    """Test STT config returns None when not configured."""
    with patch.dict(os.environ, {}, clear=True):
        config = resolve_stt_config({})
        assert config is None


# ── STT API Call Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_stt_openai_format():
    """Test STT API call with OpenAI response format."""
    mock_http_client = AsyncMock()

    # Mock OpenAI Whisper response
    mock_response = Mock()
    mock_response.json = Mock(return_value={"text": "Hello world"})
    mock_response.raise_for_status = Mock()
    mock_http_client.post = AsyncMock(return_value=mock_response)

    stt_config = STTConfig(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="whisper-1",
    )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"fake_wav_data")
        tmp_path = tmp.name

    try:
        result = await call_stt(mock_http_client, tmp_path, stt_config)

        assert result == "Hello world"
        mock_http_client.post.assert_called_once()
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_call_stt_glm_format():
    """Test STT API call with GLM/Zhipu response format."""
    mock_http_client = AsyncMock()

    # Mock GLM response
    mock_response = Mock()
    mock_response.json = Mock(return_value={
        "choices": [
            {"message": {"content": "你好世界"}}
        ]
    })
    mock_response.raise_for_status = Mock()
    mock_http_client.post = AsyncMock(return_value=mock_response)

    stt_config = STTConfig(
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        api_key="glm_key",
        model="glm-asr",
    )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"fake_wav_data")
        tmp_path = tmp.name

    try:
        result = await call_stt(mock_http_client, tmp_path, stt_config)

        assert result == "你好世界"
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_call_stt_api_error():
    """Test STT API call handles errors gracefully."""
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(side_effect=Exception("API error"))

    stt_config = STTConfig(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="whisper-1",
    )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"fake_wav_data")
        tmp_path = tmp.name

    try:
        result = await call_stt(mock_http_client, tmp_path, stt_config)

        assert result is None
    finally:
        os.unlink(tmp_path)


# ── STTPipeline Tests ─────────────────────────────────────────────────

@pytest.fixture
def mock_downloader():
    """Mock AttachmentDownloader."""
    downloader = Mock()
    downloader.download_audio = AsyncMock()
    return downloader


@pytest.fixture
def mock_attachment():
    """Mock MessageAttachment."""
    att = Mock()
    att.asr_refer_text = ""
    att.voice_wav_url = ""
    att.resolved_url = "https://cdn.qq.com/voice.silk"
    att.filename = "voice.silk"
    return att


@pytest.mark.asyncio
async def test_stt_pipeline_uses_builtin_asr(mock_downloader):
    """Test STTPipeline uses QQ's built-in ASR when available."""
    mock_http_client = AsyncMock()

    def stt_config_fn():
        return STTConfig(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="whisper-1",
        )

    pipeline = STTPipeline(
        http_client=mock_http_client,
        stt_config_fn=stt_config_fn,
        downloader=mock_downloader,
    )

    # Attachment with built-in ASR
    att = Mock()
    att.asr_refer_text = "你好世界"
    att.voice_wav_url = ""
    att.resolved_url = "https://cdn.qq.com/voice.silk"
    att.filename = "voice.silk"

    result = await pipeline.transcribe(att)

    assert result == "你好世界"
    # Should not download or call STT API
    mock_downloader.download_audio.assert_not_called()
    mock_http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_stt_pipeline_prefers_wav_url(mock_downloader, mock_attachment):
    """Test STTPipeline prefers voice_wav_url over raw URL."""
    mock_http_client = AsyncMock()

    def stt_config_fn():
        return STTConfig(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

    # Mock download and STT
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"wav_data")
        tmp_path = tmp.name

    try:
        mock_downloader.download_audio = AsyncMock(return_value=tmp_path)

        pipeline = STTPipeline(
            http_client=mock_http_client,
            stt_config_fn=stt_config_fn,
            downloader=mock_downloader,
        )

        # Set voice_wav_url
        mock_attachment.voice_wav_url = "//cdn.qq.com/voice.wav"

        # Mock http_client.post to return STT API response
        mock_stt_response = Mock()
        mock_stt_response.json = Mock(return_value={"text": "transcript"})
        mock_stt_response.raise_for_status = Mock()
        mock_http_client.post = AsyncMock(return_value=mock_stt_response)

        result = await pipeline.transcribe(mock_attachment)

        assert result == "transcript"
        # Should download from WAV URL (with https: prefix)
        mock_downloader.download_audio.assert_called_once()
        call_args = mock_downloader.download_audio.call_args
        assert call_args[0][0].startswith("https:")
    finally:
        if Path(tmp_path).exists():
            os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_stt_pipeline_no_config(mock_downloader, mock_attachment):
    """Test STTPipeline returns None when STT not configured."""
    mock_http_client = AsyncMock()

    def stt_config_fn():
        return None

    # Mock download
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"wav_data")
        tmp_path = tmp.name

    try:
        mock_downloader.download_audio = AsyncMock(return_value=tmp_path)

        pipeline = STTPipeline(
            http_client=mock_http_client,
            stt_config_fn=stt_config_fn,
            downloader=mock_downloader,
        )

        result = await pipeline.transcribe(mock_attachment)

        assert result is None
    finally:
        if Path(tmp_path).exists():
            os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_stt_pipeline_download_failure(mock_downloader, mock_attachment):
    """Test STTPipeline handles download failure."""
    mock_http_client = AsyncMock()

    def stt_config_fn():
        return STTConfig(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

    # Download fails
    mock_downloader.download_audio = AsyncMock(return_value=None)

    pipeline = STTPipeline(
        http_client=mock_http_client,
        stt_config_fn=stt_config_fn,
        downloader=mock_downloader,
    )

    result = await pipeline.transcribe(mock_attachment)

    assert result is None


@pytest.mark.asyncio
async def test_stt_pipeline_no_url(mock_downloader):
    """Test STTPipeline handles attachment with no URL."""
    mock_http_client = AsyncMock()

    def stt_config_fn():
        return STTConfig(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

    pipeline = STTPipeline(
        http_client=mock_http_client,
        stt_config_fn=stt_config_fn,
        downloader=mock_downloader,
    )

    # Attachment with no URL
    att = Mock()
    att.asr_refer_text = ""
    att.voice_wav_url = ""
    att.resolved_url = ""

    result = await pipeline.transcribe(att)

    assert result is None


# ── Integration Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_stt_pipeline():
    """Test complete STT pipeline from download to transcription."""
    mock_http_client = AsyncMock()
    mock_downloader = Mock()

    # Mock download returns WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"RIFF" + b"\x00" * 40)  # Minimal WAV header
        tmp_path = tmp.name

    try:
        mock_downloader.download_audio = AsyncMock(return_value=tmp_path)

        def config_fn():
            return STTConfig(
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                model="whisper-1",
            )

        pipeline = STTPipeline(
            http_client=mock_http_client,
            stt_config_fn=config_fn,
            downloader=mock_downloader,
        )

        att = Mock()
        att.asr_refer_text = ""
        att.voice_wav_url = ""
        att.resolved_url = "https://cdn.qq.com/voice.silk"
        att.filename = "voice.silk"

        # Mock http_client.post to return STT API response
        mock_stt_response = Mock()
        mock_stt_response.json = Mock(return_value={"text": "完整测试"})
        mock_stt_response.raise_for_status = Mock()
        mock_http_client.post = AsyncMock(return_value=mock_stt_response)

        result = await pipeline.transcribe(att)

        assert result == "完整测试"
        mock_downloader.download_audio.assert_called_once()
    finally:
        # Pipeline should clean up temp file
        pass  # File already cleaned by pipeline
