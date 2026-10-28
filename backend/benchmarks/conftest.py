"""Performance budgets: each benchmark must stay under its ceiling or the run fails.

Run with `pytest backend/benchmarks`. Budgets are median wall-clock seconds per call (the median
ignores one-off OS or GC hiccups that would make a mean flaky) and are deliberately generous so
shared CI runners pass; a failure means a real regression, not noise.

User-facing budgets from ROADMAP "Performance budgets" (scrub -> frame < 50 ms, 60 fps timeline,
10M-sample pan/zoom < 16 ms, session open < 1 s, idle RAM < 300 MB) get benchmarks here as the
features they measure land (M1-M2).
"""

import statistics
import time

import pytest

BUDGETS_S: dict[str, float] = {
    "test_to_ego_1m_points": 0.15,
    "test_direction_1m_points": 0.30,
    "test_pose_lookup": 250e-6,  # ~35-80 us on a dev laptop; a linear scan would be milliseconds
    "test_generate_1h_run": 3.0,
}

MIN_ROUNDS = 5
MAX_ROUNDS = 10_000
TARGET_TOTAL_S = 0.5  # keep timing until this much has been measured (or MAX_ROUNDS)

_results: list[tuple[str, float, float, int, float]] = []  # name, median, mean, rounds, budget


@pytest.fixture
def within_budget(request):
    """Time `fn(*args)` over repeated rounds and fail if the median exceeds this test's budget."""
    name = request.node.originalname
    if name not in BUDGETS_S:
        raise KeyError(f"no budget for {name}; add one to BUDGETS_S")
    budget = BUDGETS_S[name]

    def run(fn, *args, **kwargs):
        result = fn(*args, **kwargs)  # warm-up: imports, caches, allocator
        times: list[float] = []
        while len(times) < MIN_ROUNDS or (sum(times) < TARGET_TOTAL_S and len(times) < MAX_ROUNDS):
            start = time.perf_counter()
            fn(*args, **kwargs)
            times.append(time.perf_counter() - start)
        median = statistics.median(times)
        _results.append((name, median, statistics.fmean(times), len(times), budget))
        assert median <= budget, (
            f"{name}: median {median * 1e3:.3f} ms > budget {budget * 1e3:.3f} ms"
        )
        return result

    return run


def pytest_terminal_summary(terminalreporter):
    if not _results:
        return
    terminalreporter.section("performance budgets")
    terminalreporter.write_line(
        f"{'benchmark':<28} {'median':>11} {'mean':>11} {'budget':>11} {'used':>6} {'rounds':>7}"
    )
    for name, median, mean, rounds, budget in _results:
        terminalreporter.write_line(
            f"{name:<28} {median * 1e3:>8.3f} ms {mean * 1e3:>8.3f} ms {budget * 1e3:>8.3f} ms "
            f"{median / budget:>6.0%} {rounds:>7}"
        )
