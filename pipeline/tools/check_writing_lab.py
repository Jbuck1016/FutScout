"""Static contract checks for the private Writing Lab workflow."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def main() -> None:
    page = (ROOT / "dashboard" / "writing-lab.html").read_text(encoding="utf-8")
    home = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    worker = (ROOT / "pipeline" / "process_writing_lab_queue.py").read_text(encoding="utf-8")
    migration = (
        ROOT / "supabase" / "migrations" / "20260915224025_writing_lab_projects.sql"
    ).read_text(encoding="utf-8")

    shell = (ROOT / "dashboard" / "site-tools.js").read_text(encoding="utf-8")
    require("'writing-lab.html':{d:" in home and "['Writing lab', 'writing-lab.html']" in shell,
            "homepage and shell registry expose the Writing Lab")
    require("x-writing-key" in page and "crypto.subtle.digest" in page,
            "browser workspaces use an unguessable scoped key")
    require(all(term in page for term in ("Article leads", "Team evidence", "Plot desk")),
            "evidence pack has an editorial hierarchy")
    require(all(term in page for term in ("Article draft", "Workspace notes", "Published article URL")),
            "notes, full draft and publication record persist together")
    require(all(term in page for term in ("passes", "touches", "heat", "shots")),
            "article-ready team and player plot families are available")
    require(all(term in page for term in ("Premier League", "Champions League", "Europa League", "La Liga")),
            "competition selector covers domestic and European analysis")
    theme = (ROOT / "dashboard" / "theme.css").read_text(encoding="utf-8")
    require(theme.count("color-scheme:dark") >= 2 and "#edf0e9" not in page,
            "native dropdown choices follow the theme colour scheme, not a page palette")
    require("retryScrape" in page, "failed match requests can be re-queued in place")
    require("events_cup" in page and "matches_cup" in worker,
            "cup writing evidence stays outside league-only analytics")
    require("CANONICAL_COMPETITIONS" in worker and "resolve_canonical_fixture_id" in worker,
            "modeled leagues use the governed canonical ingestion path")
    require("enqueue_rebuild_if_new_data" in worker,
            "a manual canonical ingest queues the normal analytics publisher")
    require("CANONICAL.has(p.competition)?'events':'events_cup'" in page
            and "p.canonical_game_id||p.game_id" in page,
            "Writing Lab reads from the table selected by ingestion scope")
    require("--watch" in worker and "scrape_status" in worker,
            "the local worker can process the browser queue continuously")
    require("(\"ENG-Premier League\", \"2526\")" in worker,
            "a stable browser carrier survives a stale provider season index")
    require("ws.get(" in worker and "matchCentreData" in worker,
            "direct match-id scraping bypasses schedule membership checks")
    require("enable row level security" in migration.lower(),
            "workspace storage enables row-level security")
    require("anon_delete" not in migration and "grant select, insert, update" in migration.lower(),
            "browser workspaces cannot delete the research archive")
    require(migration.lower().count("create policy") == 3,
            "read, create and update each have an explicit ownership policy")


if __name__ == "__main__":
    main()
