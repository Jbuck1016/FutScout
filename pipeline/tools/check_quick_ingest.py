"""Contract checks for the browser-to-canonical quick ingest lane."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def main() -> None:
    page = (ROOT / "dashboard" / "quick-ingest.html").read_text(encoding="utf-8")
    home = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    worker = (ROOT / "pipeline" / "process_writing_lab_queue.py").read_text(encoding="utf-8")
    migration = next(
        (ROOT / "supabase" / "migrations").glob("*_quick_ingest_identity.sql")
    ).read_text(encoding="utf-8")

    shell = (ROOT / "dashboard" / "site-tools.js").read_text(encoding="utf-8")
    require("'quick-ingest.html':{d:" in home and "['Quick ingest', 'quick-ingest.html']" in shell,
            "homepage and shell registry expose Quick ingest")
    require("x-writing-key" in page and "crypto.subtle.digest" in page,
            "browser queue uses the existing unguessable private scope")
    require("/matches\\/(\\d+)" in page.lower(), "only a WhoScored match id is accepted")
    require(all(x in page for x in ("Premier League", "Champions League", "MLS")),
            "league and isolated competition routes are explicit")
    require("CANONICAL_COMPETITIONS" in worker,
            "worker has an allowlist for canonical publication")
    require("resolve_canonical_fixture_id" in worker and "assert_canonical_teams" in worker,
            "canonical loads require unique fixture identity and league membership")
    require("canonical_game_id" in worker,
            "source and canonical provider identifiers remain separately traceable")
    require("add column if not exists canonical_game_id" in migration.lower(),
            "database lineage stores the reconciled provider fixture id")
    require("enqueue_rebuild_if_new_data" in worker,
            "canonical loads enqueue the governed analytics publisher")
    require("matches_cup" in worker and "upsert_cup_events" in worker,
            "non-league matches remain isolated")
    require("game_id=eq." in page and "scrape_status==='error'" in page,
            "repeat submissions resume safely instead of creating duplicates")
    require("SUPABASE_SERVICE_KEY" not in page,
            "the browser never receives the service-role credential")

    sys.path.insert(0, str(ROOT / "pipeline"))
    from process_writing_lab_queue import resolve_canonical_fixture_id

    class Result:
        def __init__(self, data):
            self.data = data

    class Query:
        def __init__(self, data):
            self.data = data

        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def execute(self):
            return Result(self.data)

    class FakeSupabase:
        def table(self, name):
            if name == "matches":
                return Query([{
                    "game_id": "fd-123",
                    "date": "2026-09-15",
                    "home_team": "Internazionale",
                    "away_team": "Udinese",
                }])
            return Query([{
                "match_name": "Internazionale",
                "event_name": "Inter",
                "display_name": "Inter",
            }])

    resolved = resolve_canonical_fixture_id(
        FakeSupabase(),
        {"date": "2026-09-15", "home_team": "Inter", "away_team": "Udinese"},
        "ITA-Serie A",
        "2627",
    )
    require(resolved == "fd-123",
            "WhoScored aliases reconcile to the existing provider fixture id")


if __name__ == "__main__":
    main()
