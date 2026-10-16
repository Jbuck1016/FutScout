"""Offline regressions; never contacts production or providers."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "offline-test-only")
import pandas as pd
import scrape_and_load as loader
from scrape_league import schedule_payloads
from feed_validation import validate_completed_feed
from publish_dashboard_data import publish, git
from rescrape_queue import _prune_stale_events


def test_ingestion():
    for payload in ({}, {"events": [{"expandedMinute": 24}]}, {"events": [{"minute": "bad"}]}):
        try:
            validate_completed_feed(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("truncated feed accepted")
    validate_completed_feed({"events": [{"expandedMinute": 98}]})
    with patch.object(loader, "ensure_event_json", return_value={"events": [{"minute": 24}]}), \
         patch.object(loader, "upsert_match") as write:
        try:
            loader.process_match(None, None, pd.Series({"game_id": "123"}), "ESP-La Liga", "2627", historical=True)
        except ValueError:
            pass
        else:
            raise AssertionError("incomplete feed accepted")
        write.assert_not_called()
    prior = {"game_id": "fd-10", "date": "2026-10-20", "home_team": "A", "away_team": "B"}
    source = {**prior, "game_id": "123", "date": "2026-10-21"}
    result = schedule_payloads(pd.DataFrame([source]), [prior], "ESP-La Liga", "2627")
    assert result[0]["game_id"] == "fd-10"
    result = schedule_payloads(pd.DataFrame([source]), [prior], "USA-MLS", "2627")
    assert result[0]["game_id"] == "123"


def test_publisher():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        remote, source, collaborator = [base / name for name in ("remote", "source", "collaborator")]
        remote.mkdir(); source.mkdir()
        git(remote, "init", "--bare", "--initial-branch=main")
        git(source, "init", "--initial-branch=main")
        for name, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
            git(source, "config", name, value)
        (source / "dashboard").mkdir()
        bundle = source / "dashboard/model-lab-data.js"
        bundle.write_text("old")
        git(source, "add", "."); git(source, "commit", "-m", "baseline")
        git(source, "remote", "add", "origin", str(remote)); git(source, "push", "origin", "main")
        subprocess.run(["git", "clone", str(remote), str(collaborator)], check=True, capture_output=True)
        for name, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
            git(collaborator, "config", name, value)
        (collaborator / "unrelated.txt").write_text("preserve remote work")
        git(collaborator, "add", "."); git(collaborator, "commit", "-m", "concurrent work")
        git(collaborator, "push", "origin", "main")
        bundle.write_text("new")
        (source / "secret-local.txt").write_text("not for publication")
        before = git(source, "status", "--porcelain")
        assert publish(source, ["dashboard/model-lab-data.js"], "dry") .startswith("dry-run")
        result = publish(source, ["dashboard/model-lab-data.js"], "publish", True)
        assert len(result) == 40
        assert git(remote, "show", "main:unrelated.txt") == "preserve remote work"
        assert git(remote, "show", "main:dashboard/model-lab-data.js") == "new"
        assert "secret-local.txt" not in git(remote, "ls-tree", "-r", "--name-only", "main")
        assert git(source, "status", "--porcelain") == before
        assert publish(source, ["dashboard/model-lab-data.js"], "again", True) == "unchanged"
        try:
            publish(source, ["secret-local.txt"], "bad", True)
        except ValueError:
            pass
        else:
            raise AssertionError("unapproved file accepted")


def test_paginated_repair():
    from types import SimpleNamespace
    class Query:
        def __init__(self):
            self.offset = 0
            self.deleted = []
            self.deleting = False
        def table(self, *_): return self
        def select(self, *_): self.deleting = False; return self
        def eq(self, *_): return self
        def order(self, *_): return self
        def range(self, start, end): self.offset = start; return self
        def delete(self): self.deleting = True; return self
        def in_(self, _, ids): self.deleted.extend(ids); return self
        def execute(self):
            if self.deleting: return SimpleNamespace(data=[])
            return SimpleNamespace(data=[{"ws_id": n} for n in range(self.offset + 1, min(self.offset + 1001, 2002))])
    client = Query()
    assert _prune_stale_events(client, "test", set(range(1, 2001))) == 1
    assert client.deleted == [2001]


if __name__ == "__main__":
    test_ingestion()
    test_publisher()
    test_paginated_repair()
    print("PASS: partial feeds rejected before writes; rescheduled identity stable; isolated publication preserves concurrent and dirty work")
