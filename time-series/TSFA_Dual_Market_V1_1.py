"""Time Series & Factor Analysis – aplikasi Streamlit (Visualization, Volatility, Correlation, Portfolio, DataHub)."""
import io, os, zipfile, zlib, itertools, json
from pathlib import Path
import numpy as np, pandas as pd, streamlit as st
import plotly.graph_objects as go, plotly.express as pe
from plotly.subplots import make_subplots
from scipy import stats, optimize
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf
from statsmodels.regression.rolling import RollingOLS
from arch import arch_model
from sklearn.covariance import LedoitWolf
from tsfa_storage_engine import TSFAStorageEngine
from tsfa_version_manager import TSFAVersionManager

st.set_page_config("Time Series & Factor Analysis", layout="wide")
CACHE = "datahub"; os.makedirs(CACHE, exist_ok=True)
STORAGE = TSFAStorageEngine(base_dir=CACHE)
VERSIONS = TSFAVersionManager(STORAGE)
# Universe awal V1: 15 saham likuid/terkenal per pasar + benchmark.
# Daftar ini adalah watchlist awal, bukan rekomendasi investasi atau ranking likuiditas.
MARKETS = {
    "Indonesia (BEI)": {
        "IHSG": "^JKSE", "BBCA": "BBCA.JK", "BBRI": "BBRI.JK", "BMRI": "BMRI.JK",
        "BBNI": "BBNI.JK", "TLKM": "TLKM.JK", "ASII": "ASII.JK", "ANTM": "ANTM.JK",
        "MDKA": "MDKA.JK", "INDF": "INDF.JK", "ICBP": "ICBP.JK", "UNVR": "UNVR.JK",
        "GOTO": "GOTO.JK", "ADRO": "ADRO.JK", "PTBA": "PTBA.JK", "KLBF": "KLBF.JK",
    },
    "Amerika Serikat (NYSE/NASDAQ)": {
        "S&P 500": "^GSPC", "NASDAQ Composite": "^IXIC", "Apple": "AAPL",
        "Microsoft": "MSFT", "NVIDIA": "NVDA", "Amazon": "AMZN", "Alphabet": "GOOGL",
        "Meta": "META", "Berkshire Hathaway": "BRK-B", "JPMorgan": "JPM",
        "Broadcom": "AVGO", "Tesla": "TSLA", "Walmart": "WMT", "Eli Lilly": "LLY",
        "Exxon Mobil": "XOM",
    },
}
# Tetap sediakan beberapa ETF/indeks lama agar kompatibel dengan pilihan analisis sebelumnya.
LEGACY_POP = {"Dow Jones": "^DJI", "NASDAQ-100": "^NDX", "Russell 2000": "^RUT",
              "SPDR S&P 500 ETF": "SPY", "Invesco QQQ": "QQQ", "iShares 20+Y Treasury": "TLT",
              "iShares 7-10Y Treasury": "IEF", "SPDR Gold Shares": "GLD",
              "iShares MSCI EM": "EEM", "iShares MSCI EAFE": "EFA", "Vanguard Total Stock": "VTI"}
POP = {**MARKETS["Indonesia (BEI)"], **MARKETS["Amerika Serikat (NYSE/NASDAQ)"], **LEGACY_POP}
COL = pe.colors.qualitative.Plotly
WIN = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260, "10Y": 2520, "Max": 0}
VW = {"15D": 15, "1M": 21, "2M": 42, "3M": 63, "6M": 126, "1Y": 252}
FFURL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
sl = lambda x, n: x if not n else x.iloc[-n:]
show = lambda f: st.plotly_chart(f, width="stretch")
tbl = lambda d, **k: st.dataframe(d, width="stretch", **k)

# ---------------------------------------------------------------- DATA LAYER
# Storage V1.1: Raw + Clean + Version History. Legacy flat CSV remains read-only fallback.
def _path(t):
    return os.path.join(CACHE, t.replace("^", "_").replace("/", "-") + ".csv")

def _market_for_ticker(t, preferred=None):
    t = str(t).strip().upper()
    if t.endswith(".JK") or t == "^JKSE":
        return "indonesia"
    if preferred in ("Indonesia (BEI)", "indonesia", "Indonesia"):
        return "indonesia"
    return "us"

def _clean_path(t, market=None):
    market = market or _market_for_ticker(t, st.session_state.get("market"))
    m = STORAGE._market(market)
    safe = STORAGE._safe_ticker(t)
    return STORAGE.clean_dir / m / f"{safe}.csv"

def stored():
    items = []
    for market_dir in STORAGE.clean_dir.iterdir() if STORAGE.clean_dir.exists() else []:
        if market_dir.is_dir():
            for f in market_dir.glob("*.csv"):
                items.append(f.stem)
    # fallback legacy files for gradual migration visibility
    for f in Path(CACHE).glob("*.csv"):
        if not f.name.startswith("__"):
            t = ("^" + f.stem[1:]) if f.stem.startswith("_") else f.stem
            if t not in items: items.append(t)
    return sorted(set(items))

def key(t):
    market = _market_for_ticker(t, st.session_state.get("market"))
    p = _clean_path(t, market)
    legacy = Path(_path(t))
    stamp = p.stat().st_mtime if p.exists() else (legacy.stat().st_mtime if legacy.exists() else 0)
    return (t, bool(st.session_state.get("demo", False)), (market, stamp))

def download(t, market=None):
    import yfinance as yf
    market = market or _market_for_ticker(t, st.session_state.get("market"))
    d = yf.download(t, period="max", auto_adjust=False, progress=False)
    if d is None or d.empty:
        raise ValueError(f"Tidak ada data untuk '{t}' (cek ticker/internet).")
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    needed = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in d.columns]
    d = d[needed].copy()
    d.index = pd.to_datetime(d.index)
    result = STORAGE.save_dataset(t, market, d, provider="Yahoo Finance")
    if result.get("status") not in ("PASS", "UNCHANGED"):
        raise ValueError(f"Data {t} ditolak validasi: {result.get('errors', result)}")
    return pd.read_csv(_clean_path(t, market), index_col=0, parse_dates=True)

def _gsim(rng, n, w=2e-6, a=.08, b=.9):
    r = np.zeros(n); v = w / (1 - a - b)
    for i in range(n):
        r[i] = np.sqrt(v) * rng.standard_t(6) / np.sqrt(1.5); v = w + a * r[i] ** 2 + b * v
    return r
def _idx(n=2600): return pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
def synth(t, n=2600):
    rng = np.random.default_rng(zlib.crc32(t.encode())); r = rng.uniform(.2, 1.2) * _gsim(np.random.default_rng(1), n) + _gsim(rng, n, 3e-6) + 3e-4
    p = 100 * np.exp(np.cumsum(r)); return pd.DataFrame({"Close": p, "Adj Close": p, "Volume": rng.integers(10**6, 10**7, n)}, index=_idx(n))

@st.cache_data(show_spinner="Memuat data…")
def get_px(t, demo, stamp):
    if demo:
        return synth(t)
    market = stamp[0] if isinstance(stamp, tuple) else _market_for_ticker(t, st.session_state.get("market"))
    p = _clean_path(t, market)
    if p.exists():
        return pd.read_csv(p, index_col=0, parse_dates=True)
    # Legacy fallback is imported through validation before it is used.
    legacy = Path(_path(t))
    if legacy.exists():
        old = pd.read_csv(legacy, index_col=0, parse_dates=True)
        result = STORAGE.save_dataset(t, market, old, provider="Legacy CSV migration")
        if result.get("status") in ("PASS", "UNCHANGED"):
            return pd.read_csv(_clean_path(t, market), index_col=0, parse_dates=True)
        raise ValueError(f"Legacy data {t} gagal validasi: {result.get('errors', result)}")
    return download(t, market)
prices = lambda t: get_px(*key(t))
lr = lambda t: np.log(prices(t)["Adj Close"]).diff().dropna()
sr = lambda t: prices(t)["Adj Close"].pct_change().dropna()

def _parse(txt, cols):
    rows = [[x.strip() for x in l.split(",")] for l in txt]
    rows = [s for s in rows if len(s[0]) == 8 and s[0].isdigit() and len(s) == len(cols) + 1]
    d = pd.DataFrame(rows, columns=["d"] + cols); d.index = pd.to_datetime(d.pop("d"), format="%Y%m%d"); return d.astype(float) / 100
def dl_factors():
    import requests
    out = []
    for f, c in [("F-F_Research_Data_5_Factors_2x3_daily_CSV.zip", ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]), ("F-F_Momentum_Factor_daily_CSV.zip", ["Mom"])]:
        z = zipfile.ZipFile(io.BytesIO(requests.get(FFURL + f, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).content))
        out.append(_parse(z.read(z.namelist()[0]).decode("latin1").splitlines(), c))
    d = pd.concat(out, axis=1).dropna(); d.to_csv(os.path.join(CACHE, "__factors.csv")); return d
@st.cache_data(show_spinner="Memuat faktor Fama-French…")
def factors(demo, stamp):
    if demo:
        rng = np.random.default_rng(7); i = _idx()
        d = pd.DataFrame({c: rng.normal(0, .004, len(i)) for c in ["SMB", "HML", "RMW", "CMA", "Mom"]}, index=i)
        d.insert(0, "Mkt-RF", _gsim(np.random.default_rng(1), len(i))); d["RF"] = 8e-5; return d
    p = os.path.join(CACHE, "__factors.csv")
    return pd.read_csv(p, index_col=0, parse_dates=True) if os.path.exists(p) else dl_factors()
def fac():
    p = os.path.join(CACHE, "__factors.csv"); return factors(bool(st.session_state.get("demo", False)), os.path.getmtime(p) if os.path.exists(p) else 0)

def active_market_tickers():
    market = st.session_state.get("market", "Combined (Indonesia + USA)")
    if market == "Indonesia (BEI)": return MARKETS["Indonesia (BEI)"]
    if market == "Amerika Serikat (NYSE/NASDAQ)": return MARKETS["Amerika Serikat (NYSE/NASDAQ)"]
    return {**MARKETS["Indonesia (BEI)"], **MARKETS["Amerika Serikat (NYSE/NASDAQ)"], **LEGACY_POP}

def _reset_market_widgets():
    for k in ["viz", "vol", "cor", "pf"]:
        st.session_state.pop(k, None)

def pick(k, default, mx, mn=1):
    market_pop = active_market_tickers()
    o = {f"{a} ({b})": b for a, b in market_pop.items()}
    # Ticker yang pernah diunduh tetap dapat dipilih, tetapi dipisahkan menurut suffix pasar.
    market = st.session_state.get("market", "Combined (Indonesia + USA)")
    for ticker in stored():
        is_id = ticker.endswith(".JK") or ticker == "^JKSE"
        if market == "Indonesia (BEI)" and is_id and ticker not in o.values():
            o[ticker] = ticker
        elif market == "Amerika Serikat (NYSE/NASDAQ)" and not is_id and ticker not in o.values():
            o[ticker] = ticker
        elif market == "Combined (Indonesia + USA)" and ticker not in o.values():
            o[ticker] = ticker
    valid_defaults = [a for a, b in o.items() if b in default]
    # Default yang sesuai pasar aktif agar tab tidak kosong saat pasar diganti.
    if not valid_defaults:
        if market == "Indonesia (BEI)":
            fallback = ["^JKSE", "BBCA.JK"] if k == "cor" else ["^JKSE"]
        elif market == "Amerika Serikat (NYSE/NASDAQ)":
            fallback = ["^GSPC", "AAPL"] if k == "cor" else ["^GSPC"]
        else:
            fallback = ["^GSPC"]
        valid_defaults = [a for a, b in o.items() if b in fallback][:mx]
    c = st.multiselect("Series", list(o), valid_defaults, key=k, max_selections=mx)
    x = st.text_input("Ticker tambahan (pisahkan koma)", key=k + "x")
    out = ([o[a] for a in c] + [s.strip().upper() for s in x.split(",") if s.strip()])[:mx]
    if len(out) < mn: st.info(f"Pilih minimal {mn} series."); return None
    return out

def acfig(x, title, n=20):
    a = acf(x, nlags=n, fft=True)[1:]; b = 1.96 / np.sqrt(len(x))
    f = go.Figure(go.Bar(x=list(range(1, n + 1)), y=a, marker_color=["crimson" if abs(v) > b else "steelblue" for v in a]))
    f.add_hline(y=b, line_dash="dot"); f.add_hline(y=-b, line_dash="dot")
    f.update_layout(title=title, height=260, margin=dict(l=10, r=10, t=40, b=10)); return f
def histfig(x, title):
    g = np.linspace(x.min(), x.max(), 200); f = go.Figure(go.Histogram(x=x, histnorm="probability density", nbinsx=60, marker_color="steelblue"))
    f.add_trace(go.Scatter(x=g, y=stats.norm.pdf(g, x.mean(), x.std()), line=dict(color="crimson"), name="Normal"))
    f.update_layout(title=title, height=260, showlegend=False, margin=dict(l=10, r=10, t=40, b=10)); return f
def retfig(r, title, h=230):
    sd, mu = r.std(), r.mean(); big = r[(r - mu).abs() > 3 * sd]
    f = go.Figure(go.Scatter(x=r.index, y=r, line=dict(color="darkorange", width=1), name="return"))
    for s in (2, -2): f.add_hline(y=mu + s * sd, line_dash="dot", line_color="grey")
    f.add_trace(go.Scatter(x=big.index, y=big, mode="markers", marker=dict(color="red", size=5), name=">3 sd"))
    f.update_layout(title=title, height=h, margin=dict(l=10, r=10, t=40, b=10), showlegend=False); return f

# ---------------------------------------------------------------- MODELS
@st.cache_data(show_spinner="Mengestimasi model volatilitas…")
def fit_garch(t, demo, stamp, vm, dist, mean, yrs):
    r = np.log(get_px(t, demo, stamp)["Adj Close"]).diff().dropna() * 100
    kw = dict(mean=mean, vol="GARCH", p=1, o=1 if "GJR" in vm else 0, q=1, dist=dist)
    res = arch_model(r if not yrs else r.iloc[-yrs * 252:], **kw).fit(disp="off")
    full = arch_model(r, **kw).fix(res.params); cv = full.conditional_volatility / 100
    p = res.params; pers = p.get("alpha[1]", 0) + p.get("beta[1]", 0) + .5 * p.get("gamma[1]", 0)
    fc = np.sqrt(252 * full.forecast(horizon=63, reindex=False).variance.iloc[-1].values) / 100
    lrun = np.sqrt(252 * full.forecast(horizon=1500, reindex=False).variance.iloc[-1, -1]) / 100
    return dict(cv=cv, z=full.resid / full.conditional_volatility, fc=fc, lr=lrun, pers=pers, hl=np.log(.5) / np.log(pers) if 0 < pers < 1 else np.nan,
                par=pd.DataFrame({"Estimasi": p, "Std err": res.std_err, "p-value": res.pvalues}), ll=res.loglikelihood, aic=res.aic, n=int(res.nobs))

def hexp(cv, h=20, coms=(1, 5, 25, 125)):
    """Regresi HExp (Bollerslev dkk. 2018, disederhanakan): log rata-rata varians h hari ke depan pada log EWMA varians masa lalu."""
    v = cv ** 2; X = pd.concat({f"EWMA com={c}": np.log(v.ewm(com=c - 1).mean()) for c in coms}, axis=1)
    y = np.log(v.rolling(h).mean().shift(-h)); d = pd.concat([y.rename("y"), X], axis=1).dropna()
    m = sm.OLS(d["y"], sm.add_constant(d.drop(columns="y"))).fit(cov_type="HC1")
    pred = m.predict(sm.add_constant(X.dropna(), has_constant="add"))
    return np.sqrt(252 * np.exp(pred)), pd.DataFrame({"Koef": m.params, "Std err": m.bse, "t": m.tvalues}), m.rsquared

def _q(z, a, b):
    s11, s12, s22 = np.cov(z.T)[0, 0], np.cov(z.T)[0, 1], np.cov(z.T)[1, 1]; q11, q12, q22 = s11, s12, s22; o = np.empty((len(z), 3))
    for i, (x, y) in enumerate(z.tolist()):
        o[i] = q11, q12, q22; k = 1 - a - b
        q11 = k * s11 + a * x * x + b * q11; q12 = k * s12 + a * x * y + b * q12; q22 = k * s22 + a * y * y + b * q22
    return o
def _ll(z, q):
    r = q[:, 1] / np.sqrt(q[:, 0] * q[:, 2]); x, y = z[:, 0], z[:, 1]
    return np.sum(-.5 * (np.log(1 - r ** 2) + (x * x + y * y - 2 * r * x * y) / (1 - r ** 2) - x * x - y * y))
@st.cache_data(show_spinner="Mengestimasi DCC(1,1)…")
def dcc(ta, da, sa, tb, db, sb):
    za = fit_garch(ta, da, sa, "GARCH(1,1)", "normal", "Constant", 0)["z"]; zb = fit_garch(tb, db, sb, "GARCH(1,1)", "normal", "Constant", 0)["z"]
    Z = pd.concat([za, zb], axis=1).dropna(); z = Z.values
    res = optimize.minimize(lambda p: -_ll(z, _q(z, *p)), [.03, .95], bounds=[(1e-4, .5), (.3, .9999)], method="L-BFGS-B")
    a, b = res.x; q = _q(z, a, b); ll0 = _ll(z, np.tile([1, np.corrcoef(z.T)[0, 1], 1], (len(z), 1)))
    return dict(q=pd.DataFrame(q, index=Z.index, columns=["q11", "q12", "q22"]), a=a, b=b, ll=-res.fun, gain=-res.fun - ll0, Z=Z)

# ---------------------------------------------------------------- TABS
def tab_viz():
    t = pick("viz", ["^GSPC"], 1)
    if not t: return
    t = t[0]; df = prices(t); w = st.radio("Window", list(WIN), 4, horizontal=True, key="vw"); d = sl(df, WIN[w])
    px_ = df["Adj Close"]; r = np.log(d["Adj Close"]).diff().dropna(); ytd = px_.iloc[-1] / px_[px_.index.year < px_.index[-1].year].iloc[-1] - 1
    c = st.columns(6); c[0].metric("Tanggal akhir", str(df.index[-1].date())); c[1].metric("Close", f"{df['Close'].iloc[-1]:,.2f}"); c[2].metric("Adj Close", f"{px_.iloc[-1]:,.2f}")
    c[3].metric("Volume", f"{df['Volume'].iloc[-1]:,.0f}"); c[4].metric("1D", f"{px_.iloc[-1] / px_.iloc[-2] - 1:+.2%}"); c[5].metric("YTD", f"{ytd:+.2%}")
    L, R = st.columns([3, 2])
    with L:
        f = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[.4, .6], vertical_spacing=.03)
        f.add_trace(go.Scatter(x=d.index, y=d["Adj Close"], line=dict(color="#1f77b4")), 1, 1)
        rr = retfig(r, "")
        for tr in rr.data: f.add_trace(tr, 2, 1)
        for s in (2, -2): f.add_hline(y=r.mean() + s * r.std(), line_dash="dot", line_color="grey", row=2, col=1)
        f.update_layout(height=470, showlegend=False, margin=dict(l=10, r=10, t=30, b=10), title=f"{t} – harga (Adj Close) dan log return harian"); show(f)
        a, b, c3 = st.columns(3); a.plotly_chart(acfig(r, "ACF return"), width="stretch"); b.plotly_chart(acfig(r ** 2, "ACF return²"), width="stretch"); c3.plotly_chart(histfig(r, "Distribusi"), width="stretch")
    with R:
        n = len(r); mu, sd = r.mean(), r.std(); cum = np.exp(r.cumsum()); dd = cum / cum.cummax() - 1; q = lambda p: -np.quantile(r, p)
        rows = [("Observasi", f"{n:,}"), ("Dari / sampai", f"{r.index[0].date()} / {r.index[-1].date()}"), ("Rata-rata harian", f"{mu:+.3%}"), ("Return tahunan", f"{mu * 252:+.1%}"),
                ("Volatilitas tahunan", f"{sd * np.sqrt(252):.1%}"), ("Return/volatilitas", f"{mu * 252 / (sd * np.sqrt(252)):+.2f}"), ("Return majemuk", f"{cum.iloc[-1] - 1:+.1%}"),
                ("Hari positif", f"{(r > 0).mean():.1%}"), ("Hari terbaik", f"{r.max():+.2%} ({r.idxmax().date()})"), ("Hari terburuk", f"{r.min():+.2%} ({r.idxmin().date()})"),
                ("Max drawdown", f"{dd.min():.1%}"), ("Drawdown kini", f"{dd.iloc[-1]:.1%}"), ("Skewness", f"{stats.skew(r):+.2f}"), ("Excess kurtosis", f"{stats.kurtosis(r):+.2f}"),
                ("Jarque-Bera p", f"{stats.jarque_bera(r)[1]:.3f}"), ("Ljung-Box p (10 lag)", f"{acorr_ljungbox(r, lags=[10])['lb_pvalue'].iloc[0]:.3f}"),
                ("VaR 95% / 99% (1 hari)", f"{q(.05):.2%} / {q(.01):.2%}"), ("Expected shortfall 95%", f"{-r[r <= np.quantile(r, .05)].mean():.2%}"),
                ("Hari di luar 3 sd", f"{((r - mu).abs() > 3 * sd).sum()} (normal: {n * .0027:.1f})")]
        tbl(pd.DataFrame(rows, columns=["Statistik", "Nilai"]), hide_index=True, height=700)
    st.caption("Annualisasi = ×252 hari. Merah pada ACF: di luar pita 95% untuk independen. Jarque-Bera menguji normalitas; Ljung-Box menguji 10 autokorelasi pertama sama dengan nol.")

def tab_vol():
    S = pick("vol", ["^GSPC", "GLD", "TLT"], 6)
    if not S: return
    c = st.columns(6); W = c[0].multiselect("Window", list(VW), ["1M", "1Y"]); pn = WIN[c[1].selectbox("Periode tampil", ["6M", "1Y", "3Y", "5Y", "10Y", "Max"], 3)]
    yrs = {"5Y": 5, "10Y": 10, "Max": 0}[c[2].selectbox("Model dilatih pada", ["5Y", "10Y", "Max"], 1)]
    vm = c[3].selectbox("Model volatilitas", ["GJR-GARCH(1,1,1)", "GARCH(1,1)"]); mean = c[4].selectbox("Model mean", ["Constant", "Zero"]); dist = c[5].selectbox("Error", ["normal", "t"])
    est = st.multiselect("Estimator", ["Rolling (kuadrat)", "GARCH average", "Daily GARCH", "HExp forecast"], ["Rolling (kuadrat)", "GARCH average", "Daily GARCH"])
    view = st.radio("Tampilan", ["Volatilitas", "Return terstandardisasi", "Model fit", "HExp"], horizontal=True)
    M = {t: fit_garch(*key(t), vm, dist, mean, yrs) for t in S}; fut = pd.bdate_range(prices(S[0]).index[-1] + pd.Timedelta(days=1), periods=63)
    if view == "Volatilitas":
        f = go.Figure()
        for i, t in enumerate(S):
            c_, m, r = COL[i % 10], M[t], lr(t); cv = m["cv"]
            for w in W:
                if "Rolling (kuadrat)" in est: s = sl(np.sqrt(252 * (r ** 2).rolling(VW[w]).mean()), pn); f.add_trace(go.Scatter(x=s.index, y=s * 100, name=f"{t} roll {w}", line=dict(color=c_, width=1), opacity=.4))
                if "GARCH average" in est: s = sl(np.sqrt(252 * (cv ** 2).rolling(VW[w]).mean()), pn); f.add_trace(go.Scatter(x=s.index, y=s * 100, name=f"{t} GARCH avg {w}", line=dict(color=c_, width=2.5)))
            if "Daily GARCH" in est: s = sl(cv * np.sqrt(252), pn); f.add_trace(go.Scatter(x=s.index, y=s * 100, name=f"{t} daily GARCH", line=dict(color=c_, width=1, dash="dot")))
            f.add_trace(go.Scatter(x=fut, y=m["fc"] * 100, name=f"{t} forecast 63d", line=dict(color=c_, dash="dash")))
            f.add_hline(y=m["lr"] * 100, line_dash="dot", line_color=c_, opacity=.5)
            if "HExp forecast" in est: h = sl(hexp(cv)[0], pn); f.add_trace(go.Scatter(x=h.index, y=h * 100, name=f"{t} HExp 20d", line=dict(color=c_, dash="dashdot")))
        f.update_layout(height=520, yaxis_title="Volatilitas tahunan (%)", title="Garis tipis: rolling; tebal: rata-rata GARCH; putus-putus: forecast 63 hari; titik-titik horizontal: level jangka panjang"); show(f)
        rows = []
        for t in S:
            m, r = M[t], lr(t); ro = np.sqrt(252 * (r ** 2).rolling(21).mean()).dropna(); ga = np.sqrt(252 * (m["cv"] ** 2).rolling(21).mean()).iloc[-1]
            rows.append([t, ro.iloc[-1], ro.mean(), f"{ro.min():.1%} - {ro.max():.1%}", (ro < ro.iloc[-1]).mean(), ga, m["lr"], m["fc"][-1], f"{m['pers']:.4f} / {m['hl']:.0f}d", hexp(m["cv"])[0].iloc[-1]])
        d = pd.DataFrame(rows, columns=["Series", "Roll 1M", "Rata2", "Min - max", "Persentil", "GARCH 1M", "Long-run", "+63d", "Persist. / half-life", "HExp +20d"])
        tbl(d.style.format({c: "{:.1%}" for c in ["Roll 1M", "Rata2", "Persentil", "GARCH 1M", "Long-run", "+63d", "HExp +20d"]}), hide_index=True)
    else:
        t = st.selectbox("Detail untuk", S); m = M[t]
        if view == "Return terstandardisasi":
            z = sl(m["z"], pn); show(retfig(z, f"Return terstandardisasi z = return / vol bersyarat – {t}", 300))
            a, b, c3 = st.columns(3); a.plotly_chart(acfig(m["z"], "ACF z"), width="stretch"); b.plotly_chart(acfig(m["z"] ** 2, "ACF z²"), width="stretch"); c3.plotly_chart(histfig(m["z"], "Distribusi z"), width="stretch")
        elif view == "Model fit":
            tbl(m["par"].style.format("{:.4f}")); z = m["z"]
            st.write(f"Observasi {m['n']:,} | log-likelihood {m['ll']:.1f} | AIC {m['aic']:.1f} | persistensi {m['pers']:.4f} | half-life {m['hl']:.0f} hari | Ljung-Box p(z, 10) = {acorr_ljungbox(z, lags=[10])['lb_pvalue'].iloc[0]:.3f} | p(z², 10) = {acorr_ljungbox(z ** 2, lags=[10])['lb_pvalue'].iloc[0]:.3f} | excess kurtosis z = {stats.kurtosis(z):+.2f}")
        else:
            h, co, r2 = hexp(m["cv"]); tbl(co.style.format("{:.4f}")); st.write(f"R² = {r2:.3f}. Target: log rata-rata varians 20 hari ke depan; prediksi terakhir: {h.iloc[-1]:.1%} (volatilitas tahunan).")
            s = sl(h, pn); f = go.Figure([go.Scatter(x=s.index, y=s * 100, name="HExp 20d"), go.Scatter(x=s.index, y=sl(m["cv"] * np.sqrt(252), pn) * 100, name="GARCH harian", line=dict(width=1))]); f.update_layout(height=380); show(f)
    st.caption("Volatilitas dianualisasi (×252). HExp di sini = versi sederhana: OLS (skala log) varians masa depan pada EWMA varians GARCH dengan centre of mass 1, 5, 25, 125, tanpa koreksi bias; bukan replikasi persis paper.")

def tab_corr():
    S = pick("cor", ["^GSPC", "TLT", "GLD"], 8, 2)
    if not S: return
    pairs = list(itertools.combinations(S, 2)); pr = st.selectbox("Pasangan", pairs, format_func=lambda p: f"{p[0]} / {p[1]}")
    c = st.columns(3); W = c[0].multiselect("Window", list(VW), ["1M", "1Y"], key="cw"); pn = WIN[c[1].selectbox("Periode tampil", ["1Y", "3Y", "5Y", "10Y", "Max"], 2, key="cp")]
    est = c[2].multiselect("Estimator", ["Rolling", "DCC average", "Daily DCC"], ["Rolling", "DCC average", "Daily DCC"])
    a, b = pr; R = pd.concat({t: lr(t) for t in S}, axis=1).dropna(); D = dcc(*key(a), *key(b)); q = D["q"]; f = go.Figure()
    for i, w in enumerate(W):
        n = VW[w]
        if "Rolling" in est: s = sl(R[a].rolling(n).corr(R[b]), pn); f.add_trace(go.Scatter(x=s.index, y=s, name=f"rolling {w}", line=dict(color=COL[i], width=1), opacity=.45))
        if "DCC average" in est: qa = q.rolling(n).mean(); s = sl(qa.q12 / np.sqrt(qa.q11 * qa.q22), pn); f.add_trace(go.Scatter(x=s.index, y=s, name=f"DCC avg {w}", line=dict(color=COL[i], width=3)))
    if "Daily DCC" in est: s = sl(q.q12 / np.sqrt(q.q11 * q.q22), pn); f.add_trace(go.Scatter(x=s.index, y=s, name="DCC harian", line=dict(color="black", width=1)))
    f.update_layout(height=430, yaxis=dict(range=[-1, 1], title="Korelasi"), title=f"{a} / {b}"); show(f)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Model DCC(1,1)"); tbl(pd.DataFrame({"Nilai": [D["a"], D["b"], D["a"] + D["b"], np.log(.5) / np.log(D["a"] + D["b"]), D["ll"], D["gain"], len(q)]},
                  index=["a (shock)", "b (persistensi)", "a + b", "Half-life (hari)", "Log-likelihood", "Gain LL vs korelasi konstan", "Hari bersama"]).style.format("{:.4f}"))
        st.caption("Langkah 1: GARCH(1,1) normal tiap series; langkah 2: DCC(1,1) (Engle 2002) pada residual standar, estimasi QML sendiri (bukan paket resmi).")
        st.subheader("Korelasi sampel"); show(pe.imshow(R.corr(), zmin=-1, zmax=1, color_continuous_scale="RdBu_r", text_auto=".2f", height=350))
    with c2:
        x, y = R[a], R[b]; lo = lambda u, v: ((u < u.quantile(.05)) & (v < v.quantile(.05))).sum() / (u < u.quantile(.05)).sum(); hi = lambda u, v: ((u > u.quantile(.95)) & (v > v.quantile(.95))).sum() / (u > u.quantile(.95)).sum()
        st.subheader("Statistik pasangan"); tbl(pd.DataFrame({"Nilai": [x.corr(y), stats.spearmanr(x, y)[0], stats.kendalltau(x, y)[0], D["q"].q12.iloc[-1] / np.sqrt(D["q"].q11.iloc[-1] * D["q"].q22.iloc[-1]), lo(x, y), hi(x, y)]},
                  index=["Pearson", "Spearman", "Kendall", "DCC terakhir", "Ketergantungan ekor bawah 5%", "Ketergantungan ekor atas 5%"]).style.format("{:+.3f}"))
        v = st.radio("Scatter matrix", ["Devolatilised (z GARCH)", "Raw"], horizontal=True)
        Z = pd.concat({t: fit_garch(*key(t), "GARCH(1,1)", "normal", "Constant", 0)["z"] for t in S}, axis=1).dropna() if v.startswith("Dev") else R
        g = pe.scatter_matrix(sl(Z, 1260), opacity=.35, height=420); g.update_traces(diagonal_visible=False, marker_size=2); show(g)

def tab_port():
    S = pick("pf", ["SPY", "TLT", "GLD", "QQQ"], 12, 1)
    if not S: return
    A, B, C = st.tabs(["Factor analysis", "Back-testing", "Optimiser"])
    with A:
        active_market = st.session_state.get("market")
        if active_market != "Amerika Serikat (NYSE/NASDAQ)":
            if active_market == "Indonesia (BEI)":
                st.warning("Faktor Fama-French yang tersedia berasal dari AS, bukan faktor lokal BEI. Factor Analysis tidak dijalankan untuk pasar Indonesia.")
            else:
                st.warning("Faktor Fama-French adalah faktor pasar AS. Factor Analysis tidak dijalankan untuk portofolio Combined agar tidak mencampur faktor AS dan aset BEI.")
            st.info("Pilih pasar Amerika Serikat untuk Factor Analysis. Tab Optimiser tetap dapat digunakan untuk aset pasar yang dipilih.")
        else:
            active_market = st.session_state.get("market")
            if active_market == "Indonesia (BEI)":
                st.warning("Faktor Fama-French yang tersedia berasal dari AS, bukan faktor lokal BEI. Analisis faktor untuk saham Indonesia dinonaktifkan agar tidak menghasilkan interpretasi yang keliru.")
                st.info("Gunakan Visualization, Volatility, Correlation, dan Optimiser untuk analisis saham BEI. Model faktor lokal memerlukan sumber faktor dan risk-free rate Indonesia yang tervalidasi.")
                return
            if active_market == "Combined (Indonesia + USA)":
                st.warning("Faktor Fama-French adalah faktor pasar AS. Portofolio Combined tidak boleh diregresikan langsung terhadap faktor AS seolah-olah seluruh aset berasal dari pasar AS.")
                st.info("Pindah ke pasar Amerika Serikat untuk menjalankan Factor Analysis. Optimiser pada tab tersendiri tetap dapat digunakan untuk kombinasi aset.")
                return
            w0 = st.data_editor(pd.DataFrame({"Aset": S, "Bobot %": 100 / len(S)}), hide_index=True, key="w" + ",".join(S)); w = w0["Bobot %"].values / w0["Bobot %"].sum()
            c = st.columns(2); win = WIN[c[0].radio("Periode regresi", ["1Y", "3Y", "5Y", "10Y", "Max"], 2, horizontal=True)]; F = fac(); fc = c[1].multiselect("Faktor", [x for x in F if x != "RF"], [x for x in F if x != "RF"])
            P = pd.concat({t: sr(t) for t in S}, axis=1).dropna(); I = P.index.intersection(F.index); I = I[-win:] if win else I
            if len(I) < 60 or not fc: st.warning("Data tumpang tindih dengan faktor kurang dari 60 hari / faktor belum dipilih."); return
            y = P.loc[I].values @ w - F.loc[I, "RF"].values; y = pd.Series(y, I); X = F.loc[I, fc]; m = sm.OLS(y, sm.add_constant(X)).fit(cov_type="HC1")
            rc = pd.Series({k: m.params[k] * np.cov(X[k], y)[0, 1] / y.var() for k in fc}); res_share = 1 - rc.sum()
            t_ = pd.DataFrame({"Beta": m.params[fc], "Std err": m.bse[fc], "t": m.tvalues[fc], "p": m.pvalues[fc], "Return %/th": m.params[fc] * X.mean() * 252 * 100, "Risiko %": rc * 100}).sort_values("Risiko %", ascending=False)
            c1, c2 = st.columns(2)
            e = go.Figure(go.Bar(y=t_.index, x=t_.Beta, orientation="h", error_x=dict(array=1.96 * t_["Std err"]), marker_color=["steelblue" if p < .05 else "lightgrey" for p in t_.p])); e.update_layout(title="Eksposur (beta, CI 95%; abu = tidak signifikan)", height=330); c1.plotly_chart(e, width="stretch")
            r_ = go.Figure(go.Bar(y=list(t_.index) + ["Residual"], x=list(t_["Risiko %"]) + [res_share * 100], orientation="h", marker_color=["steelblue"] * len(t_) + ["darkorange"])); r_.update_layout(title="Kontribusi risiko (% varians; negatif = hedging)", height=330); c2.plotly_chart(r_, width="stretch")
            tbl(t_.style.format("{:+.3f}"))
            cum = lambda s: (np.exp(s.cumsum()) - 1) * 100; ex = pd.Series(sm.add_constant(X).values @ m.params.values, I); g = go.Figure()
            for s, n in [(y, "Portofolio (excess RF)"), (ex, "Dijelaskan faktor"), (y - ex, "Alpha + residual")]: g.add_trace(go.Scatter(x=I, y=cum(np.log1p(s)), name=n))
            g.update_layout(title="Return kumulatif (%) – dipecah", height=330); show(g)
            pv = y + F.loc[I, "RF"]; ddn = (1 + pv).cumprod(); st.write(f"R² = {m.rsquared:.3f} | alpha = {m.params['const'] * 252:+.2%}/th (p={m.pvalues['const']:.3f}) | volatilitas = {y.std() * np.sqrt(252):.1%} | max drawdown = {(ddn / ddn.cummax() - 1).min():.1%} | beta pasar = {m.params.get('Mkt-RF', np.nan):+.2f}")
            st.caption("OLS dengan galat standar HC1. Kontribusi risiko = beta × cov(faktor, portofolio) / var(portofolio) (alokasi Euler); residual = bagian yang tak dijelaskan. Faktor = Fama-French 5 + Momentum (harian, Kenneth French), bukan 153 faktor JKP.")
    with B:
        if st.session_state.get("market") != "Amerika Serikat (NYSE/NASDAQ)":
            st.info("Back-testing berbasis faktor AS hanya tersedia pada mode Amerika Serikat.")
        else:
            if len(I) < 60 or not fc: return
            c = st.columns(2); f1 = c[0].selectbox("Faktor", fc); n = c[1].slider("Window rolling (hari)", 63, 756, 252)
            ro = RollingOLS(y, sm.add_constant(X), window=n).fit(); s = ro.params[f1].dropna(); g = go.Figure(go.Scatter(x=s.index, y=s, name=f"beta rolling {n}d")); g.add_hline(y=m.params[f1], line_dash="dash", annotation_text="OLS seluruh periode")
            g.update_layout(title=f"Eksposur {f1} sepanjang waktu", height=330); show(g); g2 = go.Figure(go.Scatter(x=ro.rsquared.dropna().index, y=ro.rsquared.dropna(), name="R²")); g2.update_layout(title="R² rolling", height=250); show(g2)
    with C: opt_tab(S)

def opt_tab(S):
    if len(S) < 2: st.info("Pilih minimal 2 aset di atas."); return
    P = pd.concat({t: sr(t) for t in S}, axis=1).dropna(); c = st.columns(4); P = sl(P, WIN[c[0].radio("Jendela estimasi", ["1Y", "3Y", "5Y"], 2, horizontal=True)])
    cm = c[1].selectbox("Matriks kovarians", ["Sampel", "Sampel shrunk (Ledoit-Wolf)"]); meth = c[2].selectbox("Isi return harapan", ["Rata-rata historis, shrink 50%", "Rata-rata historis", "Nol"]); obj = c[3].selectbox("Objektif", ["Max Sharpe", "Min variance", "Mean-variance", "Risk parity"])
    Sg = (LedoitWolf().fit(P).covariance_ if "Ledoit" in cm else P.cov().values) * 252; h = P.mean().values * 252; mu0 = {"Rata-rata historis, shrink 50%": .5 * h + .5 * h.mean(), "Rata-rata historis": h}.get(meth, np.zeros(len(S)))
    ed = st.data_editor(pd.DataFrame({"Aset": S, "Return harapan %": (mu0 * 100).round(2), "Min %": 0.0, "Max %": 100.0}), hide_index=True, key="o" + ",".join(S) + meth + str(len(P)))
    ra = st.slider("Risk aversion (mean-variance)", 1.0, 10.0, 3.0); mu = ed["Return harapan %"].values / 100; n = len(S); bd = [(a / 100, b / 100) for a, b in zip(ed["Min %"], ed["Max %"])]
    if sum(a for a, _ in bd) > 1 or sum(b for _, b in bd) < 1: st.error("Batas bobot tidak feasible (Σmin ≤ 100% ≤ Σmax)."); return
    fn = {"Max Sharpe": lambda w: -(w @ mu) / np.sqrt(w @ Sg @ w), "Min variance": lambda w: w @ Sg @ w, "Mean-variance": lambda w: -(w @ mu) + ra / 2 * (w @ Sg @ w), "Risk parity": lambda w: np.sum((w * (Sg @ w) / (w @ Sg @ w) - 1 / n) ** 2)}[obj]
    sol = lambda f, cons=(): optimize.minimize(f, np.ones(n) / n, bounds=bd, constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}, *cons], method="SLSQP")
    r = sol(fn); w = r.x; vol = lambda x: np.sqrt(x @ Sg @ x); eq = np.ones(n) / n; rcn = w * (Sg @ w) / (w @ Sg @ w) * 100
    st.dataframe(pd.DataFrame({"Aset": S, "Sekarang %": 100 / n, "Hasil %": w * 100, "Kontribusi risiko %": rcn}).set_index("Aset").style.format("{:.2f}"), width="stretch")
    st.write(f"Return {w @ mu:.2%} | volatilitas {vol(w):.2%} | Sharpe (rf=0) {w @ mu / vol(w):.2f} | status solver: {'OK' if r.success else r.message}")
    fr = []
    for tg in np.linspace(max(min(mu), 0) if False else min(mu), max(mu), 30):
        q = sol(lambda x: x @ Sg @ x, [{"type": "eq", "fun": lambda x, tg=tg: x @ mu - tg}])
        if q.success: fr.append((vol(q.x), tg))
    g = go.Figure()
    if fr: g.add_trace(go.Scatter(x=[a * 100 for a, _ in fr], y=[b * 100 for _, b in fr], name="Frontier efisien (batas sama)"))
    g.add_trace(go.Scatter(x=np.sqrt(np.diag(Sg)) * 100, y=mu * 100, mode="markers+text", text=S, name="Aset", textposition="top center"))
    g.add_trace(go.Scatter(x=[vol(eq) * 100], y=[eq @ mu * 100], mode="markers", marker=dict(symbol="diamond", size=12), name="Bobot sama")); g.add_trace(go.Scatter(x=[vol(w) * 100], y=[w @ mu * 100], mode="markers", marker=dict(symbol="star", size=16, color="green"), name="Optimal"))
    g.update_layout(height=430, xaxis_title="Volatilitas (%/th)", yaxis_title="Return harapan (%/th)"); show(g)
    st.caption("Optimiser memperbesar selisih return harapan: coba kembalikan return harapan ke 'shrink 50%' atau 'Nol' dan lihat seberapa berubah alokasinya. Return diasumsikan di atas kas; tanpa biaya transaksi.")

def tab_hub():
    demo = st.session_state.get("demo", False)
    market_label = st.session_state.get("market", "Combined (Indonesia + USA)")
    market_pop = active_market_tickers()
    st.subheader(f"DataHub V1.1 – {market_label}")
    st.caption("Penyimpanan: Raw + Clean + Version History. Format data CSV, metadata JSON, audit JSONL, dan fingerprint SHA-256.")
    if demo:
        st.warning("Mode demo aktif: data sintetis; unduhan dan perubahan penyimpanan dinonaktifkan.")

    c = st.columns([2, 1, 2, 2, 2])
    ticker = c[0].text_input("Tambah ticker", key="hub_new_ticker").strip().upper()
    if c[1].button("Unduh", disabled=demo, key="hub_download") and ticker:
        try:
            mkt = _market_for_ticker(ticker, market_label)
            result = STORAGE.save_dataset(ticker, mkt, _download_yahoo_raw(ticker), provider="Yahoo Finance")
            if result.get("status") in ("PASS", "UNCHANGED"):
                st.success(f"{ticker}: {result['status']} – versi {result.get('version_id', 'aktif')}")
            else:
                st.error(f"{ticker} ditolak: {result.get('errors')}")
            st.cache_data.clear()
        except Exception as e: st.error(f"{type(e).__name__}: {e}")

    def many(pairs):
        bar = st.progress(0.0)
        for i, (symbol, mkt) in enumerate(pairs):
            try:
                result = STORAGE.save_dataset(symbol, mkt, _download_yahoo_raw(symbol), provider="Yahoo Finance")
                if result.get("status") not in ("PASS", "UNCHANGED"):
                    st.warning(f"{symbol}: ditolak – {result.get('errors')}")
            except Exception as e: st.warning(f"{symbol}: {type(e).__name__}: {e}")
            bar.progress((i + 1) / max(len(pairs), 1))
        st.cache_data.clear()

    if c[2].button("Unduh watchlist pasar terpilih", disabled=demo, key="hub_watchlist"):
        if market_label == "Indonesia (BEI)": pairs = [(x, "indonesia") for x in MARKETS["Indonesia (BEI)"].values()]
        elif market_label == "Amerika Serikat (NYSE/NASDAQ)": pairs = [(x, "us") for x in MARKETS["Amerika Serikat (NYSE/NASDAQ)"].values()]
        else: pairs = ([(x, "indonesia") for x in MARKETS["Indonesia (BEI)"].values()] + [(x, "us") for x in MARKETS["Amerika Serikat (NYSE/NASDAQ)"].values()] + [(x, "us") for x in LEGACY_POP.values()])
        many(pairs)
    if c[3].button("Update semua", disabled=demo, key="hub_update_all"):
        pairs = [(x, _market_for_ticker(x)) for x in stored()]
        many(pairs)
    if c[4].button("Unduh faktor Fama-French", disabled=demo, key="hub_factors"):
        try:
            d = dl_factors(); st.cache_data.clear(); st.success(f"Faktor AS: {d.index[0].date()} – {d.index[-1].date()}")
        except Exception as e: st.error(f"{type(e).__name__}: {e}")

    st.markdown("### Dataset aktif (Clean)")
    rows = []
    for market_dir in STORAGE.clean_dir.iterdir() if STORAGE.clean_dir.exists() else []:
        if not market_dir.is_dir(): continue
        for f in market_dir.glob("*.csv"):
            try:
                df = pd.read_csv(f, index_col=0, parse_dates=True)
                ticker_name = f.stem
                active = VERSIONS.get_active_version(ticker_name, market_dir.name)
                rows.append({"Ticker": ticker_name, "Market": market_dir.name, "Versi aktif": active.get("active_version") if active else "-", "Tanggal awal": df.index.min().date(), "Tanggal akhir": df.index.max().date(), "Baris": len(df), "SHA-256": STORAGE._hash_file(f)[:16] + "…", "Update cache": pd.Timestamp(f.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")})
            except Exception as e:
                rows.append({"Ticker": f.stem, "Market": market_dir.name, "Status": f"Perlu pemeriksaan: {e}"})
    if rows: tbl(pd.DataFrame(rows), hide_index=True)
    else: st.info("Belum ada dataset Clean. Unduh watchlist atau ticker terlebih dahulu.")

    st.markdown("### Version History, Compare, dan Rollback")
    mcol, tcol = st.columns(2)
    market_choice = mcol.selectbox("Market versi", ["indonesia", "us"], key="vh_market")
    version_tickers = []
    base = STORAGE.version_dir / market_choice
    if base.exists(): version_tickers = sorted(x.name for x in base.iterdir() if x.is_dir())
    if not version_tickers:
        st.info("Belum ada arsip versi untuk market ini.")
        return
    ticker_choice = tcol.selectbox("Ticker versi", version_tickers, key="vh_ticker")
    vdir = base / ticker_choice
    versions = sorted([x.stem for x in vdir.glob("*.json")], key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    if versions:
        st.write("Versi tersedia:", ", ".join(versions))
        v1, v2 = st.columns(2)
        va = v1.selectbox("Versi A", versions, index=0, key="vh_a")
        vb = v2.selectbox("Versi B", versions, index=max(0, len(versions)-1), key="vh_b")
        if st.button("Bandingkan versi", key="vh_compare"):
            if va == vb: st.info("Pilih dua versi yang berbeda untuk perbandingan.")
            else:
                try:
                    comp = VERSIONS.compare_versions(ticker_choice, market_choice, va, vb)
                    st.json({k: v for k, v in comp.items() if k != "changed_values"})
                    if comp["changed_values"]: st.dataframe(pd.DataFrame([{ "Kolom": col, **item } for col, vals in comp["changed_values"].items() for item in vals]), hide_index=True)
                    else: st.success("Tidak ada perubahan nilai pada tanggal yang sama.")
                except Exception as e: st.error(f"Perbandingan gagal: {e}")
        rollback_to = st.selectbox("Rollback ke versi tervalidasi", versions, key="vh_rollback")
        if st.button("Jadikan versi ini aktif", key="vh_do_rollback"):
            try:
                result = VERSIONS.rollback(ticker_choice, market_choice, rollback_to)
                st.success(f"Rollback berhasil. Versi aktif: {result['active_version']}")
                st.cache_data.clear()
            except Exception as e: st.error(f"Rollback gagal: {e}")

    st.markdown("### Audit Trail")
    if STORAGE.audit_file.exists():
        try:
            audit = [json.loads(line) for line in STORAGE.audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            if audit: tbl(pd.DataFrame(audit[::-1]).head(100), hide_index=True)
        except Exception as e: st.warning(f"Audit tidak dapat dibaca: {e}")
    else: st.info("Audit log belum tersedia.")

def _download_yahoo_raw(ticker):
    import yfinance as yf
    data = yf.download(ticker, period="max", auto_adjust=False, progress=False)
    if data is None or data.empty:
        raise ValueError(f"Tidak ada data untuk '{ticker}' (cek ticker/internet).")
    if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
    data.index = pd.to_datetime(data.index)
    return data.copy()

# ---------------------------------------------------------------- MAIN
st.sidebar.title("Time Series & Factor Analysis")
st.sidebar.selectbox(
    "Pilih pasar",
    ["Indonesia (BEI)", "Amerika Serikat (NYSE/NASDAQ)", "Combined (Indonesia + USA)"],
    key="market", on_change=_reset_market_widgets,
)
st.sidebar.checkbox("Mode demo (data sintetis, tanpa internet)", key="demo")
st.sidebar.caption("Harga: Yahoo Finance melalui yfinance (historis harian). Faktor Fama-French yang tersedia saat ini berasal dari pasar AS. Data demo bersifat sintetis. Untuk riset/edukasi, bukan nasihat investasi.")
T = st.tabs(["Visualization", "Volatility Analysis", "Correlation Analysis", "Portfolio Analysis", "DataHub"])
for tab, fn in zip(T, [tab_viz, tab_vol, tab_corr, tab_port, tab_hub]):
    with tab:
        try: fn()
        except Exception as e: st.error(f"{type(e).__name__}: {e}")
