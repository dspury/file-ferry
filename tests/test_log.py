"""Tests for the SQLite audit log in log.py."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from file_ferry.log import SCHEMA_VERSION, LogStore
from file_ferry.models import (
    OrganizeOpRecord,
    ProbeRecord,
    ProjectRecord,
    ProxyRecord,
    RunStatus,
    VerificationRecord,
)


@pytest.fixture
def store(tmp_path) -> LogStore:
    s = LogStore(tmp_path / "ferry.db")
    s.initialize()
    return s


class TestSchema:
    def test_initialize_creates_db(self, store: LogStore, tmp_path) -> None:
        assert (tmp_path / "ferry.db").exists()

    def test_schema_version_recorded(self, store: LogStore) -> None:
        run = store.start_run("ferry test")
        assert run > 0  # just exercising the connection works
        # verify schema_meta row
        import sqlite3

        with sqlite3.connect(store.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            assert row is not None
            assert row[0] == str(SCHEMA_VERSION)

    def test_initialize_is_idempotent(self, tmp_path) -> None:
        s = LogStore(tmp_path / "ferry.db")
        s.initialize()
        s.initialize()  # second call must not raise
        assert (tmp_path / "ferry.db").exists()

    def test_initialize_migrates_legacy_organize_operations(self, tmp_path) -> None:
        """The v0.2.2 audit column is added to pre-existing databases."""
        import sqlite3

        db_path = tmp_path / "legacy.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE organize_ops ("
                "id INTEGER PRIMARY KEY, run_id INTEGER, source_path TEXT NOT NULL, "
                "destination_path TEXT NOT NULL, codec_family TEXT, "
                "resolution_bucket TEXT, file_size INTEGER, moved_at TEXT NOT NULL)"
            )

        legacy = LogStore(db_path)
        legacy.initialize()
        run_id = legacy.start_run("ferry organize ./raw")
        legacy.insert_organize_op(
            OrganizeOpRecord(
                run_id=run_id,
                source_path="/in/clip.mov",
                destination_path="/out/clip.mov",
                codec_family="prores",
                resolution_bucket="1080p",
                file_size=1024,
                moved_at=datetime.now(UTC),
            )
        )

        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(organize_ops)")}
            operation = conn.execute("SELECT operation FROM organize_ops").fetchone()[0]
        assert "operation" in columns
        assert operation == "copy"

    def test_initialize_migrates_legacy_probe_schema(self, tmp_path) -> None:
        """Regression for #42: pre-v7 probe tables get the new columns.

        Simulates a v6 database by creating a minimal probes table that
        omits the nine v7 columns. After `initialize()`, the migration
        must have added them so a real `insert_probe` succeeds.
        """
        import sqlite3

        db_path = tmp_path / "legacy_probe.db"
        with sqlite3.connect(db_path) as conn:
            # Mimic the v6 schema: probes table without the v7 columns.
            conn.execute(
                "CREATE TABLE runs ("
                "id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, "
                "command TEXT NOT NULL, config_hash TEXT, status TEXT NOT NULL, error TEXT)"
            )
            conn.execute(
                "CREATE TABLE files ("
                "id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, size INTEGER, mtime REAL, "
                "first_seen_run INTEGER REFERENCES runs(id), "
                "last_seen_run INTEGER REFERENCES runs(id))"
            )
            conn.execute(
                "CREATE TABLE probes ("
                "id INTEGER PRIMARY KEY, file_id INTEGER REFERENCES files(id), "
                "run_id INTEGER REFERENCES runs(id), codec TEXT, container TEXT, "
                "width INTEGER, height INTEGER, frame_rate REAL, color_space TEXT, "
                "bit_depth INTEGER, duration REAL, audio_channels INTEGER, "
                "audio_sample_rate INTEGER, probed_at TEXT NOT NULL)"
            )

        legacy = LogStore(db_path)
        legacy.initialize()

        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(probes)")}
        assert "r_frame_rate" in columns
        assert "is_vfr" in columns
        assert "color_transfer" in columns
        assert "color_primaries" in columns
        assert "sample_aspect_ratio" in columns
        assert "timecode" in columns
        assert "audio_codec" in columns
        assert "audio_bit_depth" in columns
        assert "modification_time" in columns


class TestRuns:
    def test_start_run_returns_id(self, store: LogStore) -> None:
        run_id = store.start_run("ferry probe ./raw")
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_finish_run_marks_status(self, store: LogStore) -> None:
        run_id = store.start_run("ferry probe ./raw")
        store.finish_run(run_id, RunStatus.SUCCESS)
        record = store.get_run(run_id)
        assert record is not None
        assert record.status == RunStatus.SUCCESS
        assert record.finished_at is not None

    def test_finish_run_with_error(self, store: LogStore) -> None:
        run_id = store.start_run("ferry probe ./raw")
        store.finish_run(run_id, RunStatus.FAILED, error="boom")
        record = store.get_run(run_id)
        assert record is not None
        assert record.status == RunStatus.FAILED
        assert record.error == "boom"

    def test_get_run_missing_returns_none(self, store: LogStore) -> None:
        assert store.get_run(99999) is None

    def test_start_run_persists_config_hash(self, store: LogStore) -> None:
        run_id = store.start_run("ferry proxy ./raw", config_hash="abc123def456")
        record = store.get_run(run_id)
        assert record is not None
        assert record.config_hash == "abc123def456"

    def test_start_run_config_hash_optional(self, store: LogStore) -> None:
        run_id = store.start_run("ferry probe ./raw")
        record = store.get_run(run_id)
        assert record is not None
        assert record.config_hash is None


class TestFiles:
    def test_upsert_file_creates_new(self, store: LogStore) -> None:
        fid = store.upsert_file("/tmp/clip.mov", size=1024, mtime=12345.0)
        assert fid > 0
        record = store.get_file(fid)
        assert record is not None
        assert record.path == "/tmp/clip.mov"
        assert record.size == 1024

    def test_upsert_file_returns_existing_id(self, store: LogStore) -> None:
        fid1 = store.upsert_file("/tmp/clip.mov")
        fid2 = store.upsert_file("/tmp/clip.mov")
        assert fid1 == fid2

    def test_upsert_updates_last_seen_run(self, store: LogStore) -> None:
        run1 = store.start_run("ferry probe ./raw")
        fid = store.upsert_file("/tmp/clip.mov", run_id=run1)
        record = store.get_file(fid)
        assert record is not None
        assert record.first_seen_run == run1
        assert record.last_seen_run == run1

        run2 = store.start_run("ferry probe ./raw")
        store.upsert_file("/tmp/clip.mov", run_id=run2)
        record2 = store.get_file(fid)
        assert record2 is not None
        assert record2.first_seen_run == run1  # unchanged
        assert record2.last_seen_run == run2  # updated


class TestProbes:
    def test_insert_probe(self, store: LogStore) -> None:
        run_id = store.start_run("ferry probe ./raw")
        file_id = store.upsert_file("/tmp/clip.mov", run_id=run_id)
        now = datetime.now(UTC)
        pid = store.insert_probe(
            ProbeRecord(
                file_id=file_id,
                run_id=run_id,
                codec="h264",
                container="mov",
                width=1920,
                height=1080,
                frame_rate=23.976,
                color_space="bt709",
                bit_depth=8,
                duration=120.5,
                audio_channels=2,
                audio_sample_rate=48000,
                probed_at=now,
            )
        )
        assert pid > 0

    def test_probe_round_trip_includes_v7_columns(self, store: LogStore, tmp_path) -> None:
        """Regression for #42: every MediaProbe field round-trips through SQLite.

        Exercises the nine columns added in schema v7 (r_frame_rate,
        is_vfr, color_transfer, color_primaries, sample_aspect_ratio,
        timecode, audio_codec, audio_bit_depth, modification_time).
        Without the migration or insert/read updates, this test fails
        because either the INSERT rejects unknown columns or the
        SELECT loses the values.
        """
        run_id = store.start_run("ferry probe ./raw")
        file_id = store.upsert_file("/tmp/vfr_clip.mov", run_id=run_id)
        now = datetime.now(UTC)
        mtime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        store.insert_probe(
            ProbeRecord(
                file_id=file_id,
                run_id=run_id,
                codec="h264",
                container="mov",
                width=1920,
                height=1080,
                frame_rate=29.97,
                r_frame_rate=30.0,
                is_vfr=True,
                color_space="bt709",
                color_transfer="bt709",
                color_primaries="bt709",
                bit_depth=10,
                sample_aspect_ratio="16:9",
                timecode="01:02:03:04",
                audio_codec="pcm_s24le",
                audio_channels=2,
                audio_sample_rate=48000,
                audio_bit_depth=24,
                duration=120.5,
                modification_time=mtime,
                probed_at=now,
            )
        )

        results = store.get_latest_probes_by_paths(["/tmp/vfr_clip.mov"])
        assert len(results) == 1
        probe = results["/tmp/vfr_clip.mov"]
        assert probe.r_frame_rate == 30.0
        assert probe.is_vfr is True
        assert probe.color_transfer == "bt709"
        assert probe.color_primaries == "bt709"
        assert probe.sample_aspect_ratio == "16:9"
        assert probe.timecode == "01:02:03:04"
        assert probe.audio_codec == "pcm_s24le"
        assert probe.audio_bit_depth == 24
        assert probe.modification_time == mtime


class TestProxies:
    def test_insert_proxy(self, store: LogStore) -> None:
        run_id = store.start_run("ferry proxy ./raw")
        file_id = store.upsert_file("/tmp/clip.mov", run_id=run_id)
        pid = store.insert_proxy(
            ProxyRecord(
                source_file_id=file_id,
                proxy_path="/tmp/proxy.mov",
                run_id=run_id,
                codec="ProRes422Proxy",
                width=1920,
                height=1080,
                file_size=1048576,
                generated_at=datetime.now(UTC),
            )
        )
        assert pid > 0


class TestProjects:
    def test_insert_project(self, store: LogStore) -> None:
        run_id = store.start_run("ferry resolve create ./raw")
        pid = store.insert_project(
            ProjectRecord(
                name="Episode-12",
                path="/tmp/Episode-12.drp",
                run_id=run_id,
                resolution="1080",
                frame_rate="24",
                color_space="Rec.709",
                bin_count=5,
                timeline_count=1,
                resolve_version="20.0",
                created_at=datetime.now(UTC),
            )
        )
        assert pid > 0


class TestVerifications:
    def test_insert_verification(self, store: LogStore) -> None:
        run_id = store.start_run("ferry verify ./raw")
        vid = store.insert_verification(
            VerificationRecord(
                folder="/tmp/raw",
                run_id=run_id,
                files_checked=10,
                files_missing=0,
                files_modified=0,
                files_added=0,
                checksum_algo="xxhash",
                verified_at=datetime.now(UTC),
            )
        )
        assert vid > 0


class TestOrganizeOps:
    def test_insert_organize_op(self, store: LogStore) -> None:
        run_id = store.start_run("ferry organize ./raw")
        oid = store.insert_organize_op(
            OrganizeOpRecord(
                run_id=run_id,
                source_path="/in/clip.mov",
                destination_path="/out/prores/1080p/clip.mov",
                codec_family="prores",
                resolution_bucket="1080p",
                file_size=1024,
                moved_at=datetime.now(UTC),
            )
        )
        assert oid > 0


class TestQueries:
    def test_get_latest_probes_by_paths_empty(self, store: LogStore) -> None:
        assert store.get_latest_probes_by_paths([]) == {}

    def test_get_latest_probes_returns_latest(self, store: LogStore) -> None:
        run1 = store.start_run("probe 1")
        fid = store.upsert_file("/tmp/clip.mov", run_id=run1)
        store.insert_probe(
            ProbeRecord(
                file_id=fid,
                run_id=run1,
                codec="h264",
                container="mov",
                width=1920,
                height=1080,
                frame_rate=24.0,
                color_space="bt709",
                bit_depth=8,
                duration=60.0,
                audio_channels=2,
                audio_sample_rate=48000,
                probed_at=datetime.now(UTC),
            )
        )
        # A later, different probe for the same file
        run2 = store.start_run("probe 2")
        store.insert_probe(
            ProbeRecord(
                file_id=fid,
                run_id=run2,
                codec="h264",
                container="mov",
                width=3840,
                height=2160,
                frame_rate=30.0,
                color_space="bt2020",
                bit_depth=10,
                duration=60.0,
                audio_channels=2,
                audio_sample_rate=48000,
                probed_at=datetime.now(UTC),
            )
        )

        results = store.get_latest_probes_by_paths(["/tmp/clip.mov"])
        assert "/tmp/clip.mov" in results
        assert results["/tmp/clip.mov"].height == 2160  # latest wins
        assert results["/tmp/clip.mov"].frame_rate == 30.0

    def test_get_latest_probes_omits_missing(self, store: LogStore) -> None:
        results = store.get_latest_probes_by_paths(["/nonexistent/clip.mov"])
        assert results == {}

    def test_get_latest_probes_multiple_files(self, store: LogStore) -> None:
        run_id = store.start_run("probe batch")
        fid_a = store.upsert_file("/a.mov", run_id=run_id)
        fid_b = store.upsert_file("/b.mov", run_id=run_id)
        now = datetime.now(UTC)
        for fid in (fid_a, fid_b):
            store.insert_probe(
                ProbeRecord(
                    file_id=fid,
                    run_id=run_id,
                    codec="h264",
                    container="mov",
                    width=1920,
                    height=1080,
                    frame_rate=24.0,
                    color_space="bt709",
                    bit_depth=8,
                    duration=60.0,
                    audio_channels=2,
                    audio_sample_rate=48000,
                    probed_at=now,
                )
            )

        results = store.get_latest_probes_by_paths(["/a.mov", "/b.mov", "/c.mov"])
        assert set(results.keys()) == {"/a.mov", "/b.mov"}


class TestContextManager:
    def test_connection_closed_on_success(self, store: LogStore) -> None:
        store.start_run("test")
        # If context manager didn't close properly, the next call would block on lock.

    def test_rollback_on_error(self, store: LogStore, tmp_path) -> None:
        """A failing transaction must not leave partial state."""
        import sqlite3

        s = LogStore(tmp_path / "rollback.db")
        s.initialize()

        with pytest.raises(RuntimeError, match="simulated failure"), s._connect() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, command, status) VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00", "x", "running"),
            )
            # Force an error mid-transaction
            raise RuntimeError("simulated failure")

        # After rollback, no runs should exist
        with sqlite3.connect(s.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            assert count == 0
