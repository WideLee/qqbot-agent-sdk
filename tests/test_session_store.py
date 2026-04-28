# -*- coding: utf-8 -*-
"""Tests for session_store module.

Tests cover:
- PersistedSession dataclass properties
- WSSessionStore CRUD operations
- File I/O edge cases
- Timestamp expiry logic
"""

import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qqbot_agent_sdk.session_store import (
    PersistedSession,
    WSSessionStore,
)


# ── PersistedSession Tests ────────────────────────────────────────────────


class TestPersistedSession:
    """Test PersistedSession dataclass and properties."""

    def test_init_defaults(self):
        """Test default values when creating empty session."""
        session = PersistedSession()
        assert session.session_id == ""
        assert session.seq is None
        assert session.intents == 0
        assert session.last_active == ""
        assert session.bot_username == ""

    def test_init_with_values(self):
        """Test creating session with all fields."""
        session = PersistedSession(
            session_id="sess_123",
            seq=42,
            intents=1073807360,
            last_active="2026-04-27T10:00:00+00:00",
            bot_username="TestBot",
        )
        assert session.session_id == "sess_123"
        assert session.seq == 42
        assert session.intents == 1073807360
        assert session.last_active == "2026-04-27T10:00:00+00:00"
        assert session.bot_username == "TestBot"

    def test_is_resumable_true(self):
        """Test is_resumable returns True when session_id and seq are set."""
        session = PersistedSession(session_id="sess_123", seq=42)
        assert session.is_resumable is True

    def test_is_resumable_false_no_session_id(self):
        """Test is_resumable returns False when session_id is empty."""
        session = PersistedSession(session_id="", seq=42)
        assert session.is_resumable is False

    def test_is_resumable_false_no_seq(self):
        """Test is_resumable returns False when seq is None."""
        session = PersistedSession(session_id="sess_123", seq=None)
        assert session.is_resumable is False

    def test_is_resumable_false_seq_zero(self):
        """Test is_resumable returns True when seq is 0 (valid seq)."""
        session = PersistedSession(session_id="sess_123", seq=0)
        assert session.is_resumable is True

    def test_age_seconds_no_timestamp(self):
        """Test age_seconds returns inf when last_active is empty."""
        session = PersistedSession(last_active="")
        assert session.age_seconds == float("inf")

    def test_age_seconds_recent(self):
        """Test age_seconds returns small value for recent timestamp."""
        now = datetime.now(tz=timezone.utc)
        recent = (now - timedelta(seconds=10)).isoformat()
        session = PersistedSession(last_active=recent)
        age = session.age_seconds
        # Should be around 10 seconds, allow some tolerance
        assert 9 < age < 12

    def test_age_seconds_old(self):
        """Test age_seconds returns large value for old timestamp."""
        old = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        session = PersistedSession(last_active=old)
        assert session.age_seconds > 7000  # > 2 hours in seconds

    def test_age_seconds_naive_timestamp(self):
        """Test age_seconds handles naive datetime (no timezone)."""
        naive = datetime.now().isoformat()  # No tz info
        session = PersistedSession(last_active=naive)
        # Should still work by adding UTC timezone
        assert session.age_seconds < 5

    def test_age_seconds_invalid_timestamp(self):
        """Test age_seconds returns inf for invalid timestamp."""
        session = PersistedSession(last_active="not-a-timestamp")
        assert session.age_seconds == float("inf")

    def test_is_fresh_recent(self):
        """Test is_fresh returns True for recent session."""
        recent = (datetime.now(tz=timezone.utc) - timedelta(seconds=10)).isoformat()
        session = PersistedSession(last_active=recent)
        assert session.is_fresh() is True

    def test_is_fresh_old(self):
        """Test is_fresh returns False for old session (> 1 hour)."""
        old = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        session = PersistedSession(last_active=old)
        assert session.is_fresh() is False

    def test_is_fresh_custom_max_age(self):
        """Test is_fresh with custom max_age parameter."""
        recent = (datetime.now(tz=timezone.utc) - timedelta(seconds=100)).isoformat()
        session = PersistedSession(last_active=recent)
        assert session.is_fresh(max_age=50) is False  # Too old for 50s limit
        assert session.is_fresh(max_age=200) is True  # Fresh enough for 200s limit

    def test_is_fresh_no_timestamp(self):
        """Test is_fresh returns False when last_active is empty."""
        session = PersistedSession(last_active="")
        assert session.is_fresh() is False


# ── WSSessionStore Tests ──────────────────────────────────────────────────


class TestWSSessionStore:
    """Test WSSessionStore file I/O and CRUD operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def store(self, temp_dir):
        """Create a WSSessionStore instance in temp directory."""
        return WSSessionStore(base_dir=temp_dir)

    def test_init_creates_store(self, temp_dir):
        """Test store initialization with non-existent file."""
        store = WSSessionStore(base_dir=temp_dir)
        assert store._data == {}
        assert not store._path.exists()  # Not created until first save

    def test_init_custom_filename(self, temp_dir):
        """Test store initialization with custom filename."""
        store = WSSessionStore(base_dir=temp_dir, filename="custom.json")
        assert store._path.name == "custom.json"

    def test_init_loads_existing_file(self, temp_dir):
        """Test store loads existing JSON file on init."""
        json_path = Path(temp_dir) / "ws_sessions.json"
        json_path.write_text(
            json.dumps({
                "app_123": {
                    "session_id": "sess_abc",
                    "seq": 10,
                    "intents": 123,
                    "last_active": "2026-04-27T10:00:00+00:00",
                    "bot_username": "Bot",
                }
            }),
            encoding="utf-8",
        )
        store = WSSessionStore(base_dir=temp_dir)
        assert "app_123" in store._data
        assert store._data["app_123"]["session_id"] == "sess_abc"

    def test_init_handles_corrupt_json(self, temp_dir):
        """Test store handles corrupted JSON file gracefully."""
        json_path = Path(temp_dir) / "ws_sessions.json"
        json_path.write_text("{ not valid json", encoding="utf-8")
        store = WSSessionStore(base_dir=temp_dir)
        assert store._data == {}  # Should fallback to empty dict

    def test_init_handles_non_dict_json(self, temp_dir):
        """Test store handles JSON that is not a dict."""
        json_path = Path(temp_dir) / "ws_sessions.json"
        json_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        store = WSSessionStore(base_dir=temp_dir)
        assert store._data == {}

    def test_get_existing_session(self, store):
        """Test get() returns PersistedSession for existing app_id."""
        store._data["app_123"] = {
            "session_id": "sess_abc",
            "seq": 42,
            "intents": 1073807360,
            "last_active": "2026-04-27T10:00:00+00:00",
            "bot_username": "TestBot",
        }
        session = store.get("app_123")
        assert isinstance(session, PersistedSession)
        assert session.session_id == "sess_abc"
        assert session.seq == 42
        assert session.intents == 1073807360
        assert session.bot_username == "TestBot"

    def test_get_nonexistent_session(self, store):
        """Test get() returns empty PersistedSession for unknown app_id."""
        session = store.get("unknown_app")
        assert isinstance(session, PersistedSession)
        assert session.session_id == ""
        assert session.seq is None

    def test_get_invalid_data(self, store):
        """Test get() handles invalid stored data."""
        store._data["app_123"] = "not a dict"
        session = store.get("app_123")
        assert session.session_id == ""

    def test_get_missing_fields(self, store):
        """Test get() handles missing fields with defaults."""
        store._data["app_123"] = {"session_id": "sess_abc"}  # Missing other fields
        session = store.get("app_123")
        assert session.session_id == "sess_abc"
        assert session.seq is None
        assert session.intents == 0
        assert session.last_active == ""
        assert session.bot_username == ""

    def test_get_seq_string_converted_to_int(self, store):
        """Test get() converts string seq to int (e.g. from JSON deserialization)."""
        store._data["app_str_seq"] = {
            "session_id": "sess_str",
            "seq": "42",
            "intents": 0,
            "last_active": "",
            "bot_username": "",
        }
        session = store.get("app_str_seq")
        assert session.seq == 42
        assert isinstance(session.seq, int)

    def test_get_seq_none_stays_none(self, store):
        """Test get() preserves None seq."""
        store._data["app_none_seq"] = {
            "session_id": "sess_none",
            "seq": None,
            "intents": 0,
            "last_active": "",
            "bot_username": "",
        }
        session = store.get("app_none_seq")
        assert session.seq is None

    def test_save_with_session_object(self, store):
        """Test save() with PersistedSession object."""
        session = PersistedSession(
            session_id="sess_xyz",
            seq=100,
            intents=999,
            last_active="2026-04-27T12:00:00+00:00",
            bot_username="MyBot",
        )
        store.save("app_456", session)
        
        # Verify in-memory data
        assert "app_456" in store._data
        assert store._data["app_456"]["session_id"] == "sess_xyz"
        assert store._data["app_456"]["seq"] == 100
        assert store._data["app_456"]["intents"] == 999
        assert store._data["app_456"]["bot_username"] == "MyBot"
        
        # Verify file was written
        assert store._path.exists()

    def test_save_with_session_object_no_last_active(self, store):
        """Test save() with PersistedSession that has no last_active."""
        session = PersistedSession(
            session_id="sess_new",
            seq=5,
        )
        store.save("app_789", session)
        
        # Should auto-generate last_active timestamp
        assert "app_789" in store._data
        last_active = store._data["app_789"]["last_active"]
        assert last_active != ""
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(last_active)

    def test_save_with_individual_params(self, store):
        """Test save() with individual parameters (legacy API)."""
        store.save(
            app_id="app_legacy",
            session="sess_old_style",
            seq=25,
            intents=456,
            bot_username="LegacyBot",
        )
        
        assert "app_legacy" in store._data
        assert store._data["app_legacy"]["session_id"] == "sess_old_style"
        assert store._data["app_legacy"]["seq"] == 25
        assert store._data["app_legacy"]["intents"] == 456
        assert store._data["app_legacy"]["bot_username"] == "LegacyBot"
        # Should auto-generate last_active
        assert store._data["app_legacy"]["last_active"] != ""

    def test_save_overwrites_existing(self, store):
        """Test save() overwrites existing session data."""
        store._data["app_overwrite"] = {
            "session_id": "old_sess",
            "seq": 1,
            "intents": 0,
            "last_active": "2026-01-01T00:00:00+00:00",
            "bot_username": "OldBot",
        }
        
        new_session = PersistedSession(
            session_id="new_sess",
            seq=999,
            intents=888,
            last_active="2026-04-27T12:00:00+00:00",
            bot_username="NewBot",
        )
        store.save("app_overwrite", new_session)
        
        assert store._data["app_overwrite"]["session_id"] == "new_sess"
        assert store._data["app_overwrite"]["seq"] == 999

    def test_save_persists_to_disk(self, store):
        """Test save() writes data to disk."""
        session = PersistedSession(session_id="sess_disk", seq=50)
        store.save("app_disk", session)
        
        # Read file directly
        content = store._path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert "app_disk" in data
        assert data["app_disk"]["session_id"] == "sess_disk"

    def test_save_creates_parent_dirs(self, temp_dir):
        """Test save() creates parent directories if needed."""
        nested_dir = Path(temp_dir) / "nested" / "deep"
        store = WSSessionStore(base_dir=str(nested_dir))
        
        session = PersistedSession(session_id="sess_nested", seq=1)
        store.save("app_nested", session)
        
        assert nested_dir.exists()
        assert store._path.exists()

    def test_clear_existing_session(self, store):
        """Test clear() removes session data."""
        store._data["app_clear"] = {
            "session_id": "sess_clear",
            "seq": 10,
            "intents": 0,
            "last_active": "2026-04-27T10:00:00+00:00",
            "bot_username": "ClearBot",
        }
        
        store.clear("app_clear")
        
        assert "app_clear" not in store._data
        # Verify file was updated
        if store._path.exists():
            content = store._path.read_text(encoding="utf-8")
            data = json.loads(content)
            assert "app_clear" not in data

    def test_clear_nonexistent_session(self, store):
        """Test clear() handles nonexistent session gracefully."""
        # Should not raise error
        store.clear("nonexistent_app")
        assert "nonexistent_app" not in store._data

    def test_touch_updates_timestamp(self, store):
        """Test touch() updates last_active timestamp."""
        store._data["app_touch"] = {
            "session_id": "sess_touch",
            "seq": 10,
            "intents": 0,
            "last_active": "2026-01-01T00:00:00+00:00",
            "bot_username": "TouchBot",
        }
        
        old_timestamp = store._data["app_touch"]["last_active"]
        time.sleep(0.01)  # Small delay to ensure timestamp changes
        
        store.touch("app_touch")
        
        new_timestamp = store._data["app_touch"]["last_active"]
        assert new_timestamp != old_timestamp
        assert new_timestamp > old_timestamp
        
        # Other fields should remain unchanged
        assert store._data["app_touch"]["session_id"] == "sess_touch"
        assert store._data["app_touch"]["seq"] == 10

    def test_touch_nonexistent_session(self, store):
        """Test touch() handles nonexistent session gracefully."""
        # Should not raise error or create entry
        store.touch("nonexistent_app")
        assert "nonexistent_app" not in store._data

    def test_multiple_apps(self, store):
        """Test store handles multiple app_ids independently."""
        session1 = PersistedSession(session_id="sess_1", seq=10)
        session2 = PersistedSession(session_id="sess_2", seq=20)
        session3 = PersistedSession(session_id="sess_3", seq=30)
        
        store.save("app_1", session1)
        store.save("app_2", session2)
        store.save("app_3", session3)
        
        assert len(store._data) == 3
        assert store.get("app_1").seq == 10
        assert store.get("app_2").seq == 20
        assert store.get("app_3").seq == 30
        
        # Clear one should not affect others
        store.clear("app_2")
        assert len(store._data) == 2
        assert store.get("app_1").seq == 10
        assert store.get("app_3").seq == 30

    def test_roundtrip_persistence(self, temp_dir):
        """Test full save and reload cycle."""
        # Save data with first store instance
        store1 = WSSessionStore(base_dir=temp_dir)
        session = PersistedSession(
            session_id="sess_roundtrip",
            seq=99,
            intents=12345,
            last_active="2026-04-27T15:00:00+00:00",
            bot_username="RoundtripBot",
        )
        store1.save("app_roundtrip", session)
        
        # Load with new store instance
        store2 = WSSessionStore(base_dir=temp_dir)
        loaded = store2.get("app_roundtrip")
        
        assert loaded.session_id == "sess_roundtrip"
        assert loaded.seq == 99
        assert loaded.intents == 12345
        assert loaded.last_active == "2026-04-27T15:00:00+00:00"
        assert loaded.bot_username == "RoundtripBot"

    def test_atomic_write_with_temp_file(self, store):
        """Test _save() uses temp file and atomic replace."""
        session = PersistedSession(session_id="sess_atomic", seq=1)
        store.save("app_atomic", session)
        
        # Temp file should not exist after save
        tmp_path = store._path.with_suffix(".tmp")
        assert not tmp_path.exists()
        
        # Main file should exist
        assert store._path.exists()

    def test_unicode_handling(self, store):
        """Test store handles Unicode characters correctly."""
        session = PersistedSession(
            session_id="sess_unicode",
            seq=1,
            bot_username="测试机器人🤖",  # Chinese + emoji
        )
        store.save("app_unicode", session)
        
        # Reload and verify
        loaded = store.get("app_unicode")
        assert loaded.bot_username == "测试机器人🤖"

    def test_concurrent_access_simulation(self, temp_dir):
        """Test multiple store instances accessing same file."""
        store1 = WSSessionStore(base_dir=temp_dir)
        WSSessionStore(base_dir=temp_dir)  # second instance for concurrency test
        
        # Store1 saves data
        store1.save("app_concurrent", PersistedSession(session_id="sess_1", seq=10))
        
        # Store2 reloads and should see store1's data
        store2_reload = WSSessionStore(base_dir=temp_dir)
        loaded = store2_reload.get("app_concurrent")
        assert loaded.session_id == "sess_1"
        assert loaded.seq == 10

    def test_save_handles_write_error(self, temp_dir, monkeypatch):
        """Test _save() handles write errors gracefully."""
        
        store = WSSessionStore(base_dir=temp_dir)
        
        # Mock Path.write_text to raise an exception
        def mock_write_text(*args, **kwargs):
            raise OSError("Permission denied")
        
        monkeypatch.setattr(Path, "write_text", mock_write_text)
        
        # Should not raise, just log warning
        session = PersistedSession(session_id="sess_err", seq=1)
        store.save("app_err", session)  # Should silently fail
        
        # In-memory data should still be updated
        assert "app_err" in store._data
        assert store._data["app_err"]["session_id"] == "sess_err"


# ── Integration Tests ─────────────────────────────────────────────────────


class TestSessionStoreIntegration:
    """Integration tests for real-world usage patterns."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_resume_workflow(self, temp_dir):
        """Test typical Resume workflow: save → check fresh → load."""
        store = WSSessionStore(base_dir=temp_dir)
        
        # Initial connection: save session
        now = datetime.now(tz=timezone.utc).isoformat()
        session = PersistedSession(
            session_id="sess_resume_test",
            seq=100,
            intents=1073807360,
            last_active=now,
            bot_username="ResumeBot",
        )
        store.save("app_resume", session)
        
        # Simulate restart: new store instance
        store2 = WSSessionStore(base_dir=temp_dir)
        loaded = store2.get("app_resume")
        
        # Check if session is resumable and fresh
        assert loaded.is_resumable is True
        assert loaded.is_fresh() is True
        
        # Use the loaded session data
        assert loaded.session_id == "sess_resume_test"
        assert loaded.seq == 100

    def test_expired_session_workflow(self, temp_dir):
        """Test handling of expired session: should re-Identify."""
        store = WSSessionStore(base_dir=temp_dir)
        
        # Save old session (2 hours ago)
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        session = PersistedSession(
            session_id="sess_old",
            seq=50,
            last_active=old_time,
        )
        store.save("app_expired", session)
        
        # Load and check freshness
        loaded = store.get("app_expired")
        assert loaded.is_resumable is True
        assert loaded.is_fresh() is False  # Too old
        
        # Application should clear and re-Identify
        store.clear("app_expired")
        reloaded = store.get("app_expired")
        assert reloaded.is_resumable is False

    def test_heartbeat_touch_workflow(self, temp_dir):
        """Test heartbeat ACK updates timestamp via touch()."""
        store = WSSessionStore(base_dir=temp_dir)
        
        # Initial session
        session = PersistedSession(
            session_id="sess_heartbeat",
            seq=10,
            last_active=(datetime.now(tz=timezone.utc) - timedelta(seconds=30)).isoformat(),
        )
        store.save("app_heartbeat", session)
        
        # Simulate heartbeat ACK updates
        for _ in range(3):
            time.sleep(0.01)
            store.touch("app_heartbeat")
        
        # Verify timestamp was updated
        final = store.get("app_heartbeat")
        assert final.age_seconds < 1  # Very recent
        
        # Other data unchanged
        assert final.session_id == "sess_heartbeat"
        assert final.seq == 10
