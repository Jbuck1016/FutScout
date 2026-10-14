from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "pipeline" / "import_transfermarkt_values.py").read_text(encoding="utf-8")
history_source = (ROOT / "pipeline" / "import_transfermarkt_player_history.py").read_text(encoding="utf-8")
page = (ROOT / "dashboard" / "players.html").read_text(encoding="utf-8")
market_page = (ROOT / "dashboard" / "market-values.html").read_text(encoding="utf-8")
index_page = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
migration = (ROOT / "supabase" / "migrations" / "20260915040000_transfermarkt_market_values.sql").read_text(encoding="utf-8")
history_migration = (ROOT / "supabase" / "migrations" / "20260915041000_player_transfer_history.sql").read_text(encoding="utf-8")
history_restore = (ROOT / "supabase" / "migrations" / "20260915042500_restore_player_transfer_history.sql").read_text(encoding="utf-8")

ast.parse(source)
ast.parse(history_source)
assert "PARSE_API_KEY" in source
assert "SUPABASE_SERVICE_KEY" in source
assert "parse_market_value" in source
assert "fuzzy_name_in_team" in source
assert "unresolved" in source
assert "v_player_market_values_latest" in migration
assert "security_invoker = true" in migration
assert "enable row level security" in migration
assert "grant select on table public.v_player_market_values_latest to anon, authenticated" in migration
assert "SUPABASE_SERVICE_KEY" not in page
assert "PARSE_API_KEY" not in page
assert "v_player_market_values_latest" in page
assert "Market value" in page
assert "v_player_market_value_history" not in page
assert "v_player_transfer_history" not in page
assert "Market value &amp; transfer history" not in page
assert "get_player_profile" in history_source
assert "get_player_transfers" in history_source
assert "--limit" in history_source
assert "player_transfer_events" in history_migration
assert "v_player_market_value_history" in history_migration
assert "v_player_transfer_history" in history_migration
assert history_migration.count("security_invoker = true") == 2
assert "enable row level security" in history_migration
assert "player_transfer_events" in history_restore
assert "v_player_market_value_history" in history_restore
assert "v_player_transfer_history" in history_restore
assert history_restore.count("security_invoker = true") == 2
assert "['Market values', 'market-values.html']" in (ROOT / "dashboard" / "site-tools.js").read_text(encoding="utf-8")
assert "market-values.html" in index_page
assert 'src="gate.js' in market_page
assert "v_player_market_values_latest" in market_page
assert "mv_player_season" in market_page
assert "mv_player_role" in market_page
assert "v_team_directory" not in market_page
assert 'id="mvTitle">Market values</h1>' in market_page
assert "not a quality score" in market_page.lower()
assert "SUPABASE_SERVICE_KEY" not in market_page
assert "PARSE_API_KEY" not in market_page
print("transfermarkt market-value contract: PASS")
