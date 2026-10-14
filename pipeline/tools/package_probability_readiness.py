"""Create and verify a minimal probability/label patch entirely offline.

Reads committed base files and this isolated checkout. Writes only beneath an
explicit new workspace output directory. Never modifies another checkout,
loads a model, fits data, reads credentials, or contacts a service.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MODIFIED = (
    "pipeline/train_match_baselines.py", "pipeline/model_artifact.py",
    "pipeline/generate_match_predictions.py", "pipeline/simulate_league_table.py",
)
ADDED = ("pipeline/score_probabilities.py", "pipeline/tools/check_probability_integration.py")
SCHEMA = "supabase/migrations/20260901230956_model_data_foundations.sql"
ALLOWED_FUNCTIONS = {
    MODIFIED[0]: {"poisson_result_probabilities"},
    MODIFIED[1]: {"_explanation_group", "_match_explanation", "scoreline_distribution", "predict_rows"},
    MODIFIED[2]: {"persist_predictions"},
    MODIFIED[3]: {"_score_distribution", "_poisson_probabilities"},
}


def git(*args):
    # Pin LF for this command only. Do not inherit Windows autocrlf defaults
    # or change repository/global configuration in a shared environment.
    result = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", *args],
                            cwd=ROOT, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plain_poisson_source(source):
    """Strip only the optional experimental DC branch from the package COPY."""
    replacements = (
        ("import math\n\n", ""),
        ("def score_matrix(home: float, away: float, minimum: int = MINIMUM_SCORE,\n                 rho: float = 0.0) -> np.ndarray:",
         "def score_matrix(home: float, away: float, minimum: int = MINIMUM_SCORE) -> np.ndarray:"),
        ('    if not math.isfinite(rho):\n        raise ValueError("rho must be finite")\n', ""),
        ("    if rho:\n        # Dixon-Coles low-score correction; all four factors must stay positive.\n"
         "        factors = np.array([[1 - home * away * rho, 1 + home * rho],\n"
         "                            [1 + away * rho, 1 - rho]])\n"
         "        if (factors <= 0).any():\n"
         '            raise ValueError("rho gives non-positive low-score probabilities")\n'
         "        matrix[:2, :2] *= factors\n", ""),
        ("def score_dict(home: float, away: float, minimum: int = MINIMUM_SCORE,\n               rho: float = 0.0) -> dict[str, float]:",
         "def score_dict(home: float, away: float, minimum: int = MINIMUM_SCORE) -> dict[str, float]:"),
        ("score_matrix(home, away, minimum, rho)", "score_matrix(home, away, minimum)"),
    )
    for before, after in replacements:
        if source.count(before) != 1:
            raise AssertionError("source changed; review DC stripping before packaging")
        source = source.replace(before, after)
    assert "rho" not in source and "Dixon" not in source
    return source


def unchanged_contract(path, old, new):
    trees = [ast.parse(text) for text in (old, new)]
    functions = [{node.name: ast.dump(node, include_attributes=False)
                  for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                 for tree in trees]
    names = set(functions[0]) | set(functions[1])
    changed = sorted(name for name in names if functions[0].get(name) != functions[1].get(name))
    assert set(changed) <= ALLOWED_FUNCTIONS[path], (path, changed)
    # All module constants, classes and entry-point behavior are unchanged.
    other = [[ast.dump(node, include_attributes=False) for node in tree.body
              if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Import, ast.ImportFrom))]
             for tree in trees]
    assert other[0] == other[1], path
    imports = [[ast.dump(node, include_attributes=False) for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom)) and
                not (isinstance(node, ast.ImportFrom) and node.module in ("score_probabilities", "scipy.stats"))]
               for tree in trees]
    assert imports[0] == imports[1], path
    return {"changed_functions": changed, "unchanged_function_count": len(names) - len(changed),
            "other_module_statements_unchanged": True}


def file_hashes(directory):
    return {str(path.relative_to(directory)).replace("\\", "/"): sha(path.read_bytes())
            for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts}


def run(base, output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / "artifacts"):
        raise ValueError("package output must stay within this isolated checkout's artifacts directory")
    output.mkdir(parents=True, exist_ok=True)
    clean = output / "clean_base"
    if clean.exists():
        raise ValueError("clean_base already exists; choose a fresh output directory")
    base_commit = git("rev-parse", f"{base}^{{commit}}").decode().strip()
    source_commit = git("rev-parse", "HEAD").decode().strip()
    before = {path: git("show", f"{base_commit}:{path}").decode() for path in MODIFIED}
    after = {path: (ROOT / path).read_text(encoding="utf-8") for path in (*MODIFIED, *ADDED)}
    after[ADDED[0]] = plain_poisson_source(after[ADDED[0]])
    unchanged = {path: unchanged_contract(path, before[path], after[path]) for path in MODIFIED}
    patch_text = "".join("".join(difflib.unified_diff(
        before.get(path, "").splitlines(keepends=True), after[path].splitlines(keepends=True),
        fromfile=f"a/{path}" if path in before else "/dev/null", tofile=f"b/{path}"))
        for path in (*MODIFIED, *ADDED))
    patch_path = output / "probability_labels_only.patch"
    patch_path.write_text(patch_text, encoding="utf-8", newline="\n")
    assert b"\r" not in patch_path.read_bytes(), "patch must preserve LF"
    # Export the committed base to a disposable ordinary directory, never a
    # second repository or a shared/operational worktree.
    archived = git("archive", "--format=zip", base_commit, "pipeline", SCHEMA,
                   "dashboard/model-review.html")
    archive_path = output / "committed_base.zip"
    archive_path.write_bytes(archived)
    clean.mkdir()
    with zipfile.ZipFile(io.BytesIO(archived)) as archive:
        for entry in archive.infolist():
            target = (clean / entry.filename).resolve()
            if not target.is_relative_to(clean):
                raise ValueError("archive member leaves isolated export")
        archive.extractall(clean)
    original_hashes = file_hashes(clean)
    for path in MODIFIED:
        assert (clean / path).read_bytes() == before[path].encode("utf-8")
        assert b"\r" not in (clean / path).read_bytes(), "modified base files must preserve LF"
    prefix = str(clean.relative_to(ROOT)).replace("\\", "/")
    git("apply", "--check", f"--directory={prefix}", str(patch_path))
    git("apply", f"--directory={prefix}", str(patch_path))
    for path, source in after.items():
        assert (clean / path).read_bytes() == source.encode("utf-8"), "patched file bytes must preserve LF"
    assert not (clean / "pipeline/soccer_forecast_research.py").exists()
    assert not (clean / "pipeline/soccer_player_strength.py").exists()
    sys.path.insert(0, str(ROOT / "pipeline"))
    import numpy as np
    import score_probabilities as research
    packaged = {"__name__": "packaged_probability_helper"}
    exec(compile(after[ADDED[0]], "packaged_probability_helper", "exec"), packaged)
    for home, away in ((0, 0), (.05, 6), (6, .05), (6, 6), (1.23456789, .98765432)):
        np.testing.assert_array_equal(research.score_matrix(home, away), packaged["score_matrix"](home, away))
    test_runs = []
    for script, extra in (
        ("check_probability_integration.py", ["--report", str(output / "clean_base_contract_checks.json")]),
        ("check_league_table_simulator.py", []),
        ("check_model_review_dashboard.py", []),
    ):
        command = [sys.executable, "-B", str(clean / "pipeline/tools" / script), *extra]
        result = subprocess.run(command, cwd=clean, capture_output=True, text=True)
        (output / f"{script}.log").write_text(result.stdout + result.stderr, encoding="utf-8", newline="\n")
        test_runs.append({"script": script, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"clean-base test failed: {script}; inspect saved log")
    git("apply", "--reverse", "--check", f"--directory={prefix}", str(patch_path))
    git("apply", "--reverse", f"--directory={prefix}", str(patch_path))
    restored = file_hashes(clean)
    assert original_hashes == restored, "reverse patch did not restore exact exported files"
    git("apply", f"--directory={prefix}", str(patch_path))
    for path, source in after.items():
        assert (clean / path).read_bytes() == source.encode("utf-8"), "reapplied file bytes must preserve LF"
    manifest = {
        "mode": "offline minimal patch against an exported committed base; no operational checkout changed",
        "base_commit": base_commit, "source_research_commit": source_commit,
        "patch": patch_path.name, "patch_sha256": sha(patch_path.read_bytes()),
        "base_archive_sha256": sha(archived),
        "line_endings": {"required": "LF", "git_command_overrides": ["core.autocrlf=false", "core.eol=lf"],
                         "configuration_scope": "per command only; no repository/global settings changed",
                         "patch_and_modified_base_files_lf_verified": True,
                         "patched_and_reapplied_file_bytes_verified": True},
        "files": {path: {"before_sha256": sha(before[path].encode()) if path in before else None,
                          "after_sha256": sha(after[path].encode())} for path in (*MODIFIED, *ADDED)},
        "unchanged_model_contracts": unchanged,
        "default_poisson_helper_equal_to_research": True,
        "no_research_modules_required": True,
        "apply_check_passed": True, "clean_base_tests": test_runs,
        "reverse_patch_restored_all_original_files": True,
        "base_files_hashes": original_hashes,
        "exclusions": ["Dixon-Coles", "time decay", "player models", "advanced features", "metric predicate changes",
                       "model artifacts and training", "schema migration", "new dependencies", "scheduled jobs", "deployment"],
        "limitation": "Apply check is against the declared base only; current operational/Claude changes need separate hunk review."
    }
    (output / "package_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: manifest[key] for key in ("base_commit", "patch_sha256", "clean_base_tests",
          "reverse_patch_restored_all_original_files", "limitation")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="21b7f3c")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.base, args.output)
