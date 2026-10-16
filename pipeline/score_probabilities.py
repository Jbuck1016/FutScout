"""One score distribution for evaluation, saved forecasts, and simulation.

The grid expands until omitted joint Poisson mass is <= 1e-12. The last
cell is an exact score, never an overflow bucket. ``minimum`` is a lower
bound on support, not a truncation request. Production goal rates are
clipped to [0.05, 6] upstream; this helper also accepts zero for tests.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import poisson

MINIMUM_SCORE = 12
TAIL_TOLERANCE = 1e-12
SCORE_CONTRACT_VERSION = "poisson-adaptive-tail-1e-12-v1"


def score_matrix(home: float, away: float, minimum: int = MINIMUM_SCORE) -> np.ndarray:
    rates = np.asarray([home, away], dtype=float)
    if not np.isfinite(rates).all() or (rates < 0).any():
        raise ValueError("goal rates must be finite and non-negative")
    if isinstance(minimum, bool) or not isinstance(minimum, (int, np.integer)) or minimum < 1:
        raise ValueError("minimum score must be a positive integer")
    maximum = max(MINIMUM_SCORE, int(minimum), int(poisson.ppf(1 - TAIL_TOLERANCE / 2, rates).max()))
    if maximum > 1000:
        raise ValueError("requested goal rates exceed bounded score-grid support")
    grid = np.arange(maximum + 1)
    matrix = np.outer(poisson.pmf(grid, home), poisson.pmf(grid, away))
    return matrix / matrix.sum()


def result_masses(matrix: np.ndarray) -> np.ndarray:
    """Return H, D, A in the application's fixed class order."""
    return np.array([np.tril(matrix, -1).sum(), np.trace(matrix), np.triu(matrix, 1).sum()])


def score_dict(home: float, away: float, minimum: int = MINIMUM_SCORE) -> dict[str, float]:
    matrix = score_matrix(home, away, minimum)
    return {f"{h}-{a}": float(matrix[h, a])
            for h in range(len(matrix)) for a in range(len(matrix))}
