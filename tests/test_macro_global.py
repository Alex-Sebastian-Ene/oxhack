"""experiments/macro_global.py: input alignment, the month-by-month simulation (nowcasting from the
last published month, oil lags), that training recovers a known relation, and how the Survey of
Professional Forecasters is matched to forecast origins and turned into changes over each horizon.

Synthetic data only: no downloads. Needs torch, jax and numpyro (skipped otherwise).
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")
pytest.importorskip("numpyro")
import torch  # noqa: E402
from torch import nn  # noqa: E402

import macro_bayes as mb  # noqa: E402
import macro_global as mg  # noqa: E402

M, K = 60, 2


class Stub(nn.Module):
    """Location = coef . inputs, a negligible scale: a known one-step rule for the simulator."""

    def __init__(self, coef: dict) -> None:
        super().__init__()
        self.w = torch.zeros(mg.OWN + mb.LAGS + 1)
        for i, c in coef.items():
            self.w[i] = c

    def forward(self, x, k):
        return x @ self.w, torch.full((len(x),), 1e-9), torch.full((len(x),), 5.0)


def toy():
    st = SimpleNamespace(xs=1.0, x2=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    info = {"keys": ["s0", "s1"], "pub_lag": np.array([0, 1])}
    data = {"oil_m": np.zeros(M), "dM": np.zeros((M, K))}
    return st, info, data


def run(net, st, info, data, t, fut):
    return mg.simulate([net], st, info, data, np.array([t]), fut, None, n=1, noise=False)[0, 0]


class Recorder(nn.Module):
    """A fixed one-step rule (own lag 1, oil lag 0, volatility state) that records what it is given."""

    def __init__(self, seq: bool) -> None:
        super().__init__()
        self.seq, self.calls = seq, []

    def forward(self, x, k, s=None):
        self.calls.append((x.numpy().copy(), None if s is None else s.numpy().copy()))
        loc = 0.5 * x[:, 0] + 0.3 * x[:, mg.OWN] + 0.1 * x[:, -1]
        return loc, torch.full((len(x),), 1e-9), torch.full((len(x),), 5.0)


class SeqStub(nn.Module):
    """Location = coef * Brent's change `lag` steps before the sequence's last step."""

    seq = True

    def __init__(self, lag: int, coef: float = 1.0) -> None:
        super().__init__()
        self.lag, self.coef = lag, coef

    def forward(self, x, k, s):
        return self.coef * s[:, -1 - self.lag, 1], torch.full((len(x),), 1e-9), torch.full((len(x),), 5.0)


def flat_inputs(data, s, k):
    """The 26 inputs as macro_global.py built them with 12 own and 13 oil lags: y[s-1..s-12],
    z[s..s-12], v[s] (zeros before the first month)."""
    z, y = data["oil_m"], data["dM"][:, k]
    own = [y[s - lag] if s - lag >= 0 else 0.0 for lag in range(1, mg.OWN + 1)]
    oil = [z[s - lag] if s - lag >= 0 else 0.0 for lag in range(mb.LAGS)]
    return np.array(own + oil + [mb.log_vol(z)[s]])


def test_inputs_line_up_with_months():
    rng = np.random.default_rng(0)
    st = SimpleNamespace(xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    data = {"oil_m": rng.normal(size=M), "dM": rng.normal(size=(M, K))}
    f = mg.features(data, st)
    s, k, x, y = mg.training_rows(f, M - 1)
    i = np.flatnonzero((s == 30) & (k == 1))[0]
    assert y[i] == data["dM"][30, 1]
    assert x[i, 0] == data["dM"][29, 1] and x[i, mg.OWN - 1] == data["dM"][30 - mg.OWN, 1]  # own lags 1..OWN
    assert x[i, mg.OWN] == data["oil_m"][30] and x[i, mg.OWN + 12] == data["oil_m"][18]  # oil lags 0..12
    assert x.shape[1] == mg.OWN + mb.LAGS + 1
    for i in (0, np.flatnonzero((s == 30) & (k == 1))[0], len(s) - 1):  # 24-month features, same flat inputs
        assert x[i] == pytest.approx(flat_inputs(data, s[i], k[i]), abs=1e-12)


def test_sequences_end_in_the_forecast_month():
    rng = np.random.default_rng(2)
    st = SimpleNamespace(xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    data = {"oil_m": rng.normal(size=M), "dM": rng.normal(size=(M, K))}
    f = mg.features(data, st)
    s, k, x, y = mg.training_rows(f, M - 1)
    q = mg.sequences(f, s, k)
    assert q.shape == (len(s), mg.SEQ, 3)
    i = np.flatnonzero((s == 40) & (k == 1))[0]
    v = mb.log_vol(data["oil_m"])
    assert q[i, -1, 1] == data["oil_m"][40] and q[i, 0, 1] == data["oil_m"][40 - mg.SEQ + 1]  # Brent, lags 0..23
    assert q[i, -1, 0] == data["dM"][39, 1] and q[i, 0, 0] == data["dM"][40 - mg.SEQ, 1]  # own, lags 1..24
    assert q[i, -1, 2] == pytest.approx(v[40]) and q[i, -5, 2] == pytest.approx(v[36])  # volatility state
    j = np.flatnonzero((s == 13) & (k == 0))[0]  # before the first month: zeros
    assert q[j, :mg.SEQ - 14, :2] == pytest.approx(0.0) and q[j, -1, 1] == data["oil_m"][13]


def test_buffers_feed_both_networks_their_training_inputs():
    """Every simulated month's inputs, flat and sequence, are what features() gives once the simulated
    path (nowcast, own changes, the oil path) is written into the data."""
    rng = np.random.default_rng(3)
    st, info, data = toy()
    data["oil_m"], data["dM"] = rng.normal(size=M), rng.normal(size=(M, K))
    t, fut = 40, rng.normal(size=(1, 1, 12))
    for seq in (False, True):
        rec = Recorder(seq)
        mg.simulate([rec], st, info, data, np.array([t]), fut, None, n=1, noise=False)
        assert len(rec.calls) == 13  # month t (nowcast for the lag-1 series), then t+1..t+12
        done = {"oil_m": data["oil_m"].copy(), "dM": data["dM"].copy()}
        done["oil_m"][t + 1:t + 13] = fut[0, 0]
        for j, (x, _) in enumerate(rec.calls):
            loc = 0.5 * x[:, 0] + 0.3 * x[:, mg.OWN] + 0.1 * x[:, -1]
            done["dM"][t + j] = np.where(np.arange(K) < 1 - j, done["dM"][t + j], loc)  # series 0 is published at t
        f = mg.features(done, st)
        for j, (x, s) in enumerate(rec.calls):
            for kk in range(K):
                assert x[kk] == pytest.approx(flat_inputs(done, t + j, kk), abs=1e-6)
                if seq:
                    assert s[kk] == pytest.approx(mg.sequences(f, np.array([t + j]), np.array([kk]))[0], abs=1e-6)
                else:
                    assert s is None


def test_tcn_sees_oil_at_lag_0_in_the_right_month():
    st, info, data = toy()
    fut = np.zeros((1, 1, 12))
    fut[0, 0, 0] = 0.1  # Brent moves in the first month after the origin
    now, later = run(SeqStub(0), st, info, data, 40, fut), run(SeqStub(1), st, info, data, 40, fut)
    assert now[:2] == pytest.approx([0.1, 0.1])  # series 0 after 1 and 3 months, as for the flat inputs
    assert later[:2] == pytest.approx([0.0, 0.1])
    data["oil_m"][40] = 0.2  # a move in the origin month is lag 1 for month t+1
    assert run(SeqStub(1), st, info, data, 40, np.zeros((1, 1, 12)))[0] == pytest.approx(0.2)


def test_nowcast_starts_from_last_published_month():
    st, info, data = toy()
    t = 40
    data["dM"][t - 1] = 1.0  # last month published for the lag-1 series
    data["dM"][t] = 1.0      # published only for the lag-0 series
    out = run(Stub({0: 0.5}), st, info, data, t, np.zeros((1, 1, 12)))
    # lag 0: month t is known (1.0), so month t+1 = 0.5. Lag 1: month t is nowcast as 0.5, so t+1 = 0.25.
    assert out[0] == pytest.approx(0.5)
    assert out[4] == pytest.approx(0.25)


def test_oil_path_enters_at_the_right_lag():
    st, info, data = toy()
    fut = np.zeros((1, 1, 12))
    fut[0, 0, 0] = 0.1  # Brent moves in the first month after the origin
    now = run(Stub({mg.OWN: 1.0}), st, info, data, 40, fut)          # responds to oil in the same month
    later = run(Stub({mg.OWN + 1: 1.0}), st, info, data, 40, fut)    # responds a month later
    assert now[:2] == pytest.approx([0.1, 0.1])  # series 0 after 1 and 3 months
    assert later[:2] == pytest.approx([0.0, 0.1])


def test_fit_nets_seeds_and_per_draw_oil_paths(monkeypatch):
    monkeypatch.setattr(mg, "QUICK", True)  # 3 epochs: only the plumbing is under test
    rng = np.random.default_rng(4)
    st, info, data = toy()
    data["oil_m"], data["dM"] = rng.normal(size=M), rng.normal(size=(M, K))
    info["floor"] = np.full(K, 0.05)
    nets, training = mg.fit_nets(data, info, st, M - 13, "global_tcn", seeds=2, base_seed=7000)
    assert len(training) == 2 and all(isinstance(n, mg.SeqNet) for n in nets)
    f = mg.features(data, st)
    s, k, x, y = mg.training_rows(f, M - 13)
    again, _ = mg.train(x, k, y, s, info["floor"], True, seed=7000 + 200 + 1, seq=mg.sequences(f, s, k))
    assert all(torch.equal(a, b) for a, b in zip(nets[1].state_dict().values(), again.state_dict().values()))
    fut = np.zeros((4, 1, 12))
    fut[:, 0, 0] = [0.1, 0.2, 0.3, 0.4]
    out = mg.simulate([SeqStub(0), SeqStub(0)], st, info, data, np.array([40]), fut, None, n=4, noise=False)
    assert out[:, 0, 0] == pytest.approx(fut[:, 0, 0])  # draw i follows oil path i
    assert np.isfinite(mg.simulate(nets, st, info, data, np.array([40]), fut, np.random.default_rng(0), n=4)).all()


@pytest.mark.parametrize("tcn", [False, True])
def test_training_recovers_momentum_and_oil(tcn):
    """global, and the TCN without the linear term: both must find own lag 1 and oil lag 0."""
    rng = np.random.default_rng(1)
    n = 400
    z = rng.normal(size=n)
    dM = np.zeros((n, K))
    for s in range(1, n):
        dM[s] = 0.5 * dM[s - 1] + np.array([0.8, -0.4]) * z[s] + 0.3 * rng.standard_normal(K)
    st = SimpleNamespace(xs=1.0, vm=0.0, vs=1.0, ym=np.zeros(K), ys=np.ones(K))
    f = mg.features({"oil_m": z, "dM": dM}, st)
    s, k, x, y = mg.training_rows(f, n - 1)
    seq = mg.sequences(f, s, k) if tcn else None
    net, info = mg.train(x, k, y, s, np.full(K, 0.05), linear=False, seed=0, seq=seq)
    assert isinstance(net, mg.SeqNet) == tcn
    assert info["best_epoch"] > 5  # it trained, unlike the windowed networks
    truth = 0.5 * x[:, 0] + np.where(k == 0, 0.8, -0.4) * x[:, mg.OWN]
    args = (torch.as_tensor(x, dtype=torch.float32), torch.as_tensor(k))
    with torch.no_grad():
        loc = net(*args, *(() if seq is None else (torch.as_tensor(seq, dtype=torch.float32),)))[0].numpy()
    assert np.corrcoef(loc, truth)[0, 1] > 0.95


# --- Survey of Professional Forecasters -------------------------------------------------------

RELEASES = """Deadline and Release Dates for the Survey of Professional Forecasters

Survey         True Deadline Date       News Release Date

1992 Q1             2/22/92
     Q2             5/18/92             5/22/92*

2018 Q4             11/6/18             11/13/18

2019 Q1             3/12/19**           3/22/19**
     Q2\t\t    5/7/19\t\t5/10/19

**The 2026Q1, 2019Q1, 2013Q4, and 1996Q1 surveys were all delayed because of federal government
 shutdowns.
"""


def surveys(quarters, released):
    return pd.DataFrame({"YEAR": [y for y, _ in quarters], "QUARTER": [q for _, q in quarters],
                         "released": pd.to_datetime(released)})


def test_release_dates_are_parsed_with_the_year_carried_down():
    rel = mg.parse_release_dates(RELEASES)
    assert list(zip(rel["YEAR"], rel["QUARTER"])) == [(1992, 2), (2018, 4), (2019, 1), (2019, 2)]  # 1992Q1 has no date
    assert list(rel["released"].dt.strftime("%Y-%m-%d")) == ["1992-05-22", "2018-11-13", "2019-03-22", "2019-05-10"]


def test_surveys_meet_the_origin_at_the_end_of_their_release_month():
    s = surveys([(2018, 4), (2019, 1), (2019, 2)], ["2018-11-13", "2019-03-22", "2019-05-10"])  # 2019Q1 came late
    dates = pd.date_range("2018-10-01", "2019-06-01", freq="MS")
    row, m = mg.spf_match(dates, s, latest=False)
    got = {f"{d:%Y-%m}": (r, k) for d, r, k in zip(dates, row, m) if r >= 0}
    # m: months from the middle of the survey quarter (Nov, Feb, May) to the origin
    assert got == {"2018-11": (0, 0), "2019-03": (1, 1), "2019-05": (2, 0)}
    row, m = mg.spf_match(dates, s, latest=True)
    assert list(row) == [-1, 0, 0, 0, 0, 1, 1, 2, 2]  # nothing public at the end of 2018-10
    assert list(m[1:]) == [0, 1, 2, 3, 1, 2, 0, 1]  # end of 2019-02 still has only the 2018Q4 survey


def test_quarterly_path_becomes_the_change_over_each_horizon():
    g = np.array([[1.0, 2.0, 3.0, 4.0]])  # growth of quarters q+1..q+4
    change = lambda m, h: mg.spf_change(g, np.array([m]), h)[0]  # noqa: E731
    assert change(0, 12) == pytest.approx(10.0)  # the 4-quarter change, q to q+4
    assert change(1, 12) == pytest.approx(2 / 3 + 2 + 3 + 4 + 4 / 3)  # a month on: q+4's rate carries on
    assert change(2, 12) == pytest.approx(1 / 3 + 2 + 3 + 4 + 8 / 3)
    assert change(3, 12) == pytest.approx(2 + 3 + 4 + 4)
    assert change(0, 3) == pytest.approx(1.0) and change(0, 6) == pytest.approx(3.0)
    assert change(0, 1) == pytest.approx(1 / 3) and change(1, 6) == pytest.approx(2 / 3 + 2 + 1)


def perfect_surveys(L: pd.Series) -> pd.DataFrame:
    """The surveys a perfect forecaster would fill in for monthly 100 x log CPI L: annualised growth
    of the quarterly average CPI (as the SPF defines it) for quarters q-1..q+4, released on the 12th
    of quarter q's middle month."""
    q = np.exp(L / 100).resample("QS").mean()
    a = 100 * ((q / q.shift(1)) ** 4 - 1)
    rows = []
    for i in range(1, len(q) - 4):
        d = q.index[i]
        rows.append({"YEAR": d.year, "QUARTER": d.quarter, "released": d + pd.DateOffset(months=1, days=11),
                     **{f"CPI{k}": a.iloc[i + k - 2] for k in range(1, 7)}})
    return pd.DataFrame(rows)


def test_a_perfect_survey_reproduces_the_cpi_change_after_its_release():
    # monthly inflation constant within each calendar quarter, different between quarters: then the
    # quarter's average stands for its middle month (up to the log of an average), so from a release
    # month the survey's path gives the true 3-, 6- and 12-month changes
    rng = np.random.default_rng(3)
    months = pd.date_range("2000-01-01", "2006-12-01", freq="MS")
    rate = np.repeat(rng.uniform(0.0, 0.5, len(months) // 3), 3)
    L = pd.Series(np.cumsum(rate), index=months)
    F = mg.spf_forecasts(months, perfect_surveys(L), latest=False)
    hit = np.flatnonzero(np.isfinite(F[:, 0]))
    assert len(hit) >= 20 and all(months[i].month in (2, 5, 8, 11) for i in hit)
    for hi, h in enumerate(mg.mn.HORIZONS):
        if h == 1:
            continue  # one month is a third of the next quarter's growth, not the month's own
        truth = L.values[hit + h] - L.values[hit]
        assert np.abs(F[hit, hi] - truth).max() < 2e-3, h


def test_steady_inflation_is_read_the_same_from_every_origin():
    months = pd.date_range("2000-01-01", "2006-12-01", freq="MS")
    L = pd.Series(np.arange(len(months)) * 100 * np.log(1.03) / 12, index=months)  # 3% a year
    F = mg.spf_forecasts(months, perfect_surveys(L), latest=True)
    ok = np.isfinite(F[:, -1])
    assert ok.sum() > 60
    np.testing.assert_allclose(F[ok], (100 * np.log(1.03) * np.array(mg.mn.HORIZONS) / 12)[None].repeat(ok.sum(), 0),
                               atol=1e-6)


def test_region_skill_scores_every_forecaster_on_the_origins_all_of_them_share():
    rng = np.random.default_rng(0)
    clim = rng.uniform(1, 2, (40, 3))
    ours, theirs = clim * 0.8, clim * 0.9
    theirs[:10, 1] = np.nan                            # a benchmark that started late, on one output
    n, s, ok, _ = mg.region_skill({"ours": ours, "theirs": theirs}, clim, np.array([0, 1]))
    assert n == 30 and not ok[:10].any() and ok[10:].all()
    assert s["ours"] == pytest.approx(0.2) and s["theirs"] == pytest.approx(0.1)
    r = mg.compare(ours, theirs, clim, np.array([0, 1]))  # the pairwise comparison agrees on a pair
    assert (r["n"], r["s1"], r["s2"]) == (n, pytest.approx(s["ours"]), pytest.approx(s["theirs"]))
    n, s, _, _ = mg.region_skill({"ours": ours, "theirs": theirs}, clim, np.array([2]))
    assert n == 40                                     # an output the late start doesn't touch keeps every origin
