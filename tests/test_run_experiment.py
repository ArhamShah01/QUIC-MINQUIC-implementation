import csv

from experiments.run_experiment import BASELINE, GRID_FACTORS, _write_sweep, build_grid


def test_grid_varies_one_factor_at_a_time():
    grid = build_grid()
    assert grid[0] == BASELINE
    assert len(grid) == len({tuple(sorted(c.items())) for c in grid})
    for condition in grid:
        changed = [k for k in BASELINE if condition[k] != BASELINE[k]]
        assert len(changed) <= 1
        if changed:
            assert condition[changed[0]] in GRID_FACTORS[changed[0]]


def test_write_sweep_puts_condition_columns_first(tmp_path):
    path = tmp_path / "sweep.csv"
    rows = [
        dict(BASELINE, protocol="quic", run=1, status="ok", goodput_mbps="10"),
        dict(BASELINE, protocol="minquic", run=1, status="timeout"),
    ]
    _write_sweep(path, rows)
    with path.open(newline="") as f:
        read = list(csv.DictReader(f))
    assert list(read[0])[:8] == list(BASELINE) + ["protocol", "run", "status"]
    assert read[1]["status"] == "timeout"
    assert read[1]["goodput_mbps"] == ""


def test_summarise_reports_mean_and_ratio():
    from experiments.analyse_sweep import summarise

    rows = [
        dict(BASELINE, protocol="quic", run=1, status="ok", goodput_mbps="10"),
        dict(BASELINE, protocol="quic", run=2, status="ok", goodput_mbps="12"),
        dict(BASELINE, protocol="minquic", run=1, status="ok", goodput_mbps="22"),
        dict(BASELINE, protocol="minquic", run=2, status="timeout", goodput_mbps=""),
    ]
    rows = [{k: str(v) for k, v in r.items()} for r in rows]
    [entry] = summarise(rows, "goodput_mbps")
    assert entry["quic_mean"] == 11
    assert entry["quic_n"] == 2
    assert entry["minquic_mean"] == 22
    assert entry["minquic_failed"] == 1
    assert entry["ratio"] == 2
