from __future__ import annotations
import os, glob, hashlib, json
from datetime import date, timedelta
from typing import List, Optional, Dict, Any, Iterable
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from statsmodels.tsa.holtwinters import ExponentialSmoothing

import re
from collections import defaultdict

DATA_DIR = r"C:\NedbankHackathon\Real-Time\data"

# ============================================================
# FastAPI app + CORS setup
# ============================================================
app = FastAPI(title="NedVision Analytics Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Models
# ============================================================
class ForecastRequest(BaseModel):
    branch: str
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    horizon_days: int = Field(30, ge=1, le=120)
    files: Optional[List[str]] = None
    model: Optional[str] = Field("hw", description="hw | prophet")


class Adjustment(BaseModel):
    date: date
    delta: float
    label: Optional[str] = None

class SimulationRequest(BaseModel):
    branch: str
    base_from_date: Optional[date] = None
    base_to_date: Optional[date] = None
    horizon_days: int = 30
    files: Optional[List[str]] = None
    adjustments: List[Adjustment] = Field(default_factory=list)

class WhatIfRequest(BaseModel):
    branch: str
    horizon_days: int = Field(..., alias="horizon_Days")
    delay_invoices: int = Field(0, alias="delayInvoices")
    early_salaries: int = Field(0, alias="earlySalaries")
    adjustment: float = Field(0, alias="adjustment")

    model_config = ConfigDict(populate_by_name=True)

DEBIT_KEYWORDS = [
    "debit order","debit-order","debitord","d/o","naedo","aedo",
    "stop order","subscription","debit ord"
]

# ============================================================
# Header Normalization Utilities
# ============================================================

def _normcols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df

def _normalize_name(s: str) -> str:
    if not isinstance(s, str): return ""
    s = s.lower()
    return re.sub(r"[\W_]+", "", s)

def _discover_statement_files(branch: str | None = None) -> list[str]:
    files = []
    # branch shards
    files += glob.glob(os.path.join(DATA_DIR, "statements", f"statement_{branch or '*'}_*.csv"))
    # consolidated
    files += glob.glob(os.path.join(DATA_DIR, "consolidated", "bank_statements_all.csv"))
    return files

DEBIT_KEYWORDS = [
    "debit order","debit-order","debitord","d/o",
    "naedo","aedo","stop order","subscription","debit ord"
]

def _read_large_csv(path: str, usecols: list[str] | None = None) -> pd.DataFrame:
    # Robust reader for both normal and large files
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", usecols=usecols)
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    try:
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig", usecols=usecols)
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    # final fallback: Python engine with auto sniffing
    return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig", usecols=usecols)

def _is_debit_keyword_hit(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in DEBIT_KEYWORDS)

def _fingerprint(paths: Iterable[str]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        try:
            st = os.stat(p)
            h.update(p.encode())
            h.update(str(st.st_mtime_ns).encode())
            h.update(str(st.st_size).encode())
        except FileNotFoundError:
            continue
    return h.hexdigest()[:16]

def _build_branch_cache(branch: str) -> str:
    """
    Build (or refresh) a per-branch daily series cache (Parquet).
    Returns the Parquet path.
    """
    files = _discover_statement_files(branch)
    if not files:
        raise HTTPException(status_code=404, detail=f"No CSVs found for {branch}")

    sig = _fingerprint(files)
    pq_path = os.path.join(CACHE_DIR, f"{branch}_{sig}.parquet")

    # If already built, reuse
    if os.path.exists(pq_path):
        return pq_path

    # Assemble minimal columns across all files
    cols = ["Date", "Debit_ZAR", "Credit_ZAR", "Balance_ZAR", "Category", "Counterparty", "Description"]
    frames = []
    for p in files:
        try:
            df = _read_large_csv(p, usecols=None)  # let coercer handle columns
            df = _coerce_numeric(df)               # your existing numeric/date coercion
            frames.append(df)
        except Exception:
            continue

    if not frames:
        raise HTTPException(status_code=400, detail=f"No readable CSVs for {branch}")

    df = pd.concat(frames, ignore_index=True)
    # Filter to branch (when reading consolidated)
    if "Account" in df.columns:
        bmask = df["Account"].astype(str).str.contains(branch, case=False, na=False)
        df = df[bmask]

    # Build daily series (uses your existing helper)
    daily = _daily_cash_series([df], None, None)  # expects a list of frames
    # Add metadata helpful for drivers
    daily.to_parquet(pq_path, index=False)
    # keep a pointer file so we know the latest cache per branch
    with open(os.path.join(CACHE_DIR, f"{branch}.json"), "w", encoding="utf-8") as f:
        json.dump({"branch": branch, "signature": sig, "parquet": pq_path}, f)
    return pq_path

def _load_branch_frames(branch: str, files: list[str] | None) -> list[pd.DataFrame]:
    """
    Backward-compatible: if explicit files passed, use those.
    Otherwise, discover & read all available for the branch.
    """
    if files:
        frames = []
        for f in files:
            if not os.path.exists(f):
                raise HTTPException(status_code=400, detail=f"File not found: {f}")
            frames.append(_coerce_numeric(pd.read_csv(f)))
        return frames

    paths = _discover_statement_files(branch)
    if not paths:
        raise HTTPException(status_code=404, detail=f"No CSVs found for {branch}")

    frames = []
    for p in paths:
        frames.append(_coerce_numeric(_read_large_csv(p)))
    return frames


def _normalize_invoice_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = _normcols(df)
    alias_map = {
        "invoice_no": {"invoice", "invoice no", "inv_no", "inv"},
        "client": {"customer", "client_name", "customer_name"},
        "counterparty_ref": {"counterparty", "reference", "ref"},
        "issue_date": {"issuedate", "issue date", "invoice_date", "date_issued"},
        "due_date": {"duedate", "due date", "date_due"},
        "amount": {"amt", "value", "total", "amount_zar"},
        "status": {"state"}
    }
    rename = {}
    for canon, aliases in alias_map.items():
        if canon in df.columns:
            continue
        for a in aliases:
            if a in df.columns:
                rename[a] = canon
                break
    df = df.rename(columns=rename)
    for c in ["invoice_no","client","counterparty_ref","issue_date","due_date","amount","status"]:
        if c not in df.columns:
            df[c] = "open" if c == "status" else pd.NA
    df["issue_date"] = pd.to_datetime(df["issue_date"], errors="coerce").dt.date
    df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce").dt.date
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["status"] = df["status"].astype(str).str.lower().str.strip()
    return df

def _normalize_statement_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = _normcols(df)
    alias = {
        "date": {"transaction_date","txn_date","trans_date"},
        "account": {"acct","account_no","account number"},
        "description": {"narration","details","memo"},
        "debit_fc": {"debit (fc)","debitfc"},
        "credit_fc": {"credit (fc)","creditfc"},
        "balance_fc": {"balance (fc)","balancefc"},
        "debit_zar": {"debit","debit (zar)","dr_zar"},
        "credit_zar": {"credit","credit (zar)","cr_zar"},
        "balance_zar": {"balance","balance (zar)"},
        "category": {"cat","tx_category"},
        "reference": {"ref","trx_ref","transaction_reference"},
        "currency": {"ccy"},
        "fx_to_zar_at_txn": {"fx","fxrate","fx_to_zar"},
        "latitude": {"lat"},
        "longitude": {"lon","lng"},
        "counterparty": {"cp","beneficiary","payer","payee","merchant"}
    }
    rename = {}
    for canon, aliases in alias.items():
        if canon in df.columns:
            continue
        for a in aliases:
            if a in df.columns:
                rename[a] = canon
                break
    df = df.rename(columns=rename)
    canonical = [
        "date","account","description","debit_fc","credit_fc","balance_fc",
        "debit_zar","credit_zar","balance_zar","category","reference",
        "currency","fx_to_zar_at_txn","latitude","longitude","counterparty"
    ]
    for c in canonical:
        if c not in df.columns:
            df[c] = pd.NA
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ["debit_fc","credit_fc","balance_fc","debit_zar","credit_zar",
              "balance_zar","fx_to_zar_at_txn","latitude","longitude"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns={
        "date":"Date","account":"Account","description":"Description",
        "debit_fc":"Debit_FC","credit_fc":"Credit_FC","balance_fc":"Balance_FC",
        "debit_zar":"Debit_ZAR","credit_zar":"Credit_ZAR","balance_zar":"Balance_ZAR",
        "category":"Category","reference":"Reference","currency":"Currency",
        "fx_to_zar_at_txn":"FX_to_ZAR_at_Txn","latitude":"Latitude",
        "longitude":"Longitude","counterparty":"Counterparty"
    })
    return df

def _normalize_adjustments_df(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x.columns = [str(c).strip().lower() for c in x.columns]
    # map common aliases
    if "date" not in x.columns:
        for a in ("txn_date","trans_date"):
            if a in x.columns:
                x.rename(columns={a:"date"}, inplace=True); break
    if "delta" not in x.columns:
        for a in ("amount","adj","adjustment","change"):
            if a in x.columns:
                x.rename(columns={a:"delta"}, inplace=True); break
    if "label" not in x.columns:
        for a in ("desc","description","note"):
            if a in x.columns:
                x.rename(columns={a:"label"}, inplace=True); break

    x["date"] = pd.to_datetime(x.get("date"), errors="coerce").dt.date
    x["delta"] = pd.to_numeric(x.get("delta"), errors="coerce")
    x["label"] = x.get("label")

    x = x.dropna(subset=["date","delta"])
    return x

# ============================================================
# Loaders
# ============================================================

def _load_invoices_csv(data_dir: str) -> pd.DataFrame:
    pattern = os.path.join(data_dir, "invoices*.csv")
    matches = glob.glob(pattern)
    base_cols = ["invoice_no","client","counterparty_ref","issue_date","due_date","amount","status"]
    if not matches:
        return pd.DataFrame(columns=base_cols)

    frames = []
    for p in matches:
        try:
            raw = _read_csv_smart(p)                 # 👈 use smart reader
            norm = _normalize_invoice_headers(raw)   # existing normalizer
            norm = _coerce_invoice_dates(norm)       # 👈 robust date coercion
            frames.append(norm)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame(columns=base_cols)

    df = pd.concat(frames, ignore_index=True)
    for c in base_cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df

def _load_branch_frames(branch: str, files: Optional[List[str]]) -> List[pd.DataFrame]:
    frames: List[pd.DataFrame] = []
    if files:
        for f in files:
            if not os.path.exists(f):
                raise HTTPException(status_code=400, detail=f"File not found: {f}")
            raw = pd.read_csv(f)
            frames.append(_normalize_statement_headers(raw))
    else:
        pattern = os.path.join(DATA_DIR, f"statement_{branch}_*.csv")
        matches = glob.glob(pattern)
        if not matches:
            raise HTTPException(status_code=404, detail=f"No CSVs found for pattern: {pattern}")
        for f in matches:
            raw = pd.read_csv(f)
            frames.append(_normalize_statement_headers(raw))
    return frames

# ============================================================
# Helpers
# ============================================================

def _daily_cash_series(frames: List[pd.DataFrame], from_date: Optional[date], to_date: Optional[date]) -> pd.DataFrame:
    df = pd.concat(frames, ignore_index=True)
    if "Date" not in df.columns:
        raise HTTPException(status_code=400, detail="CSV must contain a 'Date' column")
    if from_date:
        df = df[df["Date"] >= from_date]
    if to_date:
        df = df[df["Date"] <= to_date]
    if "Credit_ZAR" not in df.columns or "Debit_ZAR" not in df.columns:
        raise HTTPException(status_code=400, detail="CSV missing credit/debit columns")
    df["AmountZAR"] = df["Credit_ZAR"].fillna(0) - df["Debit_ZAR"].fillna(0)
    daily = df.groupby("Date", as_index=False)["AmountZAR"].sum().sort_values("Date")
    idx = pd.date_range(start=daily["Date"].min(), end=daily["Date"].max(), freq="D").date
    full = pd.DataFrame({"Date": idx}).merge(daily, on="Date", how="left")
    full["AmountZAR"] = full["AmountZAR"].fillna(0.0)
    anchor = df.dropna(subset=["Balance_ZAR"]).sort_values("Date")
    base = float(anchor.iloc[0]["Balance_ZAR"]) if not anchor.empty else 0.0
    full["cash"] = base + full["AmountZAR"].cumsum()
    return full[["Date","AmountZAR","cash"]]

def _fit_forecast(history: pd.Series, horizon_days: int) -> pd.Series:
    if len(history) < 7:
        last = history.iloc[-1] if len(history) else 0.0
        return pd.Series([last] * horizon_days)
    try:
        model = ExponentialSmoothing(history.astype(float), trend="add", seasonal=None).fit()
        return model.forecast(horizon_days)
    except Exception:
        last = history.iloc[-1]
        return pd.Series([last] * horizon_days)

def _top_drivers(df_list: List[pd.DataFrame], topn: int = 5) -> Dict[str, Any]:
    df = pd.concat(df_list, ignore_index=True)
    df["AmountZAR"] = df["Credit_ZAR"].fillna(0) - df["Debit_ZAR"].fillna(0)
    agg_cat = df.groupby("Category", dropna=False)["AmountZAR"].sum().sort_values(ascending=False)
    agg_cp = df.groupby("Counterparty", dropna=False)["AmountZAR"].sum().sort_values(ascending=False)
    return {
        "top_inflows_by_category": agg_cat[agg_cat > 0].head(topn).round(2).to_dict(),
        "top_outflows_by_category": agg_cat[agg_cat < 0].tail(topn).round(2).to_dict(),
        "top_counterparties": agg_cp.head(topn).round(2).to_dict()
    }

def _read_csv_smart(path_or_file) -> pd.DataFrame:
    try:
        df = pd.read_csv(path_or_file, encoding="utf-8-sig")
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    try:
        df = pd.read_csv(path_or_file, sep=";", encoding="utf-8-sig")
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    return pd.read_csv(path_or_file, sep=None, engine="python", encoding="utf-8-sig")

def _coerce_invoice_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure issue_date/due_date parse correctly, incl. 'YYYY/MM/DD' style.
    """
    # First general parse
    df["issue_date"] = pd.to_datetime(df["issue_date"], errors="coerce")
    df["due_date"]   = pd.to_datetime(df["due_date"],   errors="coerce")

    # If everything failed, attempt strict fallback like 'YYYY/MM/DD'
    if df["issue_date"].isna().all():
        df["issue_date"] = pd.to_datetime(df["issue_date"], format="%Y/%m/%d", errors="coerce")
    if df["due_date"].isna().all():
        df["due_date"] = pd.to_datetime(df["due_date"], format="%Y/%m/%d", errors="coerce")

    # Keep them as date (not datetime) for consistency elsewhere
    df["issue_date"] = df["issue_date"].dt.date
    df["due_date"]   = df["due_date"].dt.date
    return df

# ============================================================
# Endpoints
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/forecast")
def forecast(req: ForecastRequest):
    frames = _load_branch_frames(req.branch, req.files)
    series = _daily_cash_series(frames, req.from_date, req.to_date)
    history = series.set_index(pd.to_datetime(series["Date"]))["cash"]
    horizon = int(req.horizon_days)

    fc = _fit_forecast(history, horizon, model=(req.model or "hw"))
    last_date = history.index.max().date()
    future_index = [last_date + timedelta(days=i) for i in range(1, horizon + 1)]

    forecast_points = [{"date": d.isoformat(), "cash": float(v)} for d, v in zip(future_index, fc.values)]
    history_points  = [{"date": d.date().isoformat(), "cash": float(v)} for d, v in history.items()]
    drivers = _top_drivers(frames)

    return {
        "branch": req.branch,
        "history": history_points,
        "forecast": forecast_points,
        "drivers": drivers,
        "model": req.model or "hw"
    }


@app.get("/invoices_due")
def invoices_due(window_days: int = Query(7, ge=1, le=60)):
    df = _load_invoices_csv(DATA_DIR)
    if df.empty:
        return {"window_days": window_days, "items": []}

    # Normalize columns
    status = df.get("status", pd.Series(index=df.index, dtype="object")).astype(str).str.lower().str.strip()
    due_ts = pd.to_datetime(df.get("due_date"), errors="coerce")  # datetime64[ns] series

    # Compare apples-to-apples: use Timestamps on both sides
    today_ts = pd.Timestamp.today().normalize()  # midnight today
    horizon_ts = today_ts + pd.Timedelta(days=window_days)

    mask = (status == "open") & due_ts.notna() & (due_ts >= today_ts) & (due_ts <= horizon_ts)

    due = df.loc[mask, ["invoice_no", "client", "amount"]].copy()
    due["due_date"] = due_ts[mask]  # still Timestamp

    # Sort & shape response
    due = due.sort_values(["due_date", "client"])
    items = [
        {
            "invoice_no": r.invoice_no,
            "client": r.client,
            "amount": float(r.amount or 0),
            "due_date": pd.to_datetime(r.due_date).date().isoformat(),
            "due_label": pd.to_datetime(r.due_date).strftime("%a %d %b"),
        }
        for r in due.itertuples(index=False)
    ]
    return {"window_days": window_days, "items": items}


@app.post("/invoices_reconcile")
def invoices_reconcile(tolerance: float = 5.0):
    inv = _load_invoices_csv(DATA_DIR)
    if inv.empty:
        return {"matched": 0, "updated": 0}
    frames = _load_branch_frames("*", None)
    df = pd.concat(frames, ignore_index=True)
    df["AmountZAR"] = df["Credit_ZAR"].fillna(0) - df["Debit_ZAR"].fillna(0)
    inflows = df[df["AmountZAR"] > 0].copy()
    inflows["Date"] = pd.to_datetime(inflows["Date"], errors="coerce").dt.date
    updated = 0
    for r in inv.itertuples():
        if str(r.status).lower() != "open":
            continue
        cand = inflows
        if isinstance(r.counterparty_ref, str) and r.counterparty_ref.strip():
            cand = cand[cand["Counterparty"].astype(str).str.contains(r.counterparty_ref, case=False, na=False)]
        cand = cand[(cand["AmountZAR"] >= (r.amount - tolerance)) & (cand["AmountZAR"] <= (r.amount + tolerance))]
        if not cand.empty:
            inv.loc[inv["invoice_no"] == r.invoice_no, "status"] = "paid"
            updated += 1
    path = os.path.join(DATA_DIR, "invoices.csv")
    inv.to_csv(path, index=False)
    return {"matched": int(updated), "updated": int(updated)}

@app.post("/whatif")
def whatif(req: WhatIfRequest):
    frames = _load_branch_frames(req.branch, None)
    series = _daily_cash_series(frames, None, None)
    history = series.set_index(pd.to_datetime(series["Date"]))["cash"]
    fc = _fit_forecast(history, req.horizon_days)
    last_date = history.index.max().date()
    forecast_points = [{"date": (last_date + timedelta(days=i)).isoformat(), "cash": float(v)} for i, v in enumerate(fc.values, 1)]
    # Apply simple adjustment: delay_invoices shifts initial days downward
    if req.delay_invoices:
        for i in range(min(req.delay_invoices, len(forecast_points))):
            forecast_points[i]["cash"] -= 5000
    return {"forecast": forecast_points}

@app.post("/whatif/upload")
def whatif_upload(file: UploadFile = File(...), branch: str = "CPT02", horizon_days: int = 30):
    if not file.filename.lower().endswith((".csv",)):
        raise HTTPException(400, "CSV required")

    # 1) read & normalize adjustments
    raw = _read_csv_smart(file.file)
    adj = _normalize_adjustments_df(raw)
    if adj.empty:
        raise HTTPException(400, "No valid rows in CSV. Expect columns: date, delta[, label]")

    # 2) get base forecast (reuse your existing logic)
    frames = _load_branch_frames(branch, None)
    series = _daily_cash_series(frames, None, None)
    history = series.set_index(pd.to_datetime(series["Date"]))["cash"]
    base_fc = _fit_forecast(history, horizon_days)

    last_date = history.index.max().date()
    future_dates = [last_date + timedelta(days=i) for i in range(1, horizon_days + 1)]
    path = {d: float(v) for d, v in zip(future_dates, base_fc.values)}

    # 3) build date->delta map for dates within horizon
    deltas: Dict[date, float] = {}
    horizon_set = set(future_dates)
    for r in adj.itertuples(index=False):
        if r.date in horizon_set:
            deltas[r.date] = deltas.get(r.date, 0.0) + float(r.delta)

    if not deltas:
        # nothing aligned -> tell the user what range is valid
        first = future_dates[0].isoformat()
        last = future_dates[-1].isoformat()
        raise HTTPException(400, f"No CSV dates fall within forecast horizon ({first}..{last}).")

    # 4) apply cumulative deltas from each date forward (negatives dip)
    for d0, delta in sorted(deltas.items()):
        for d in future_dates:
            if d >= d0:
                path[d] += delta

    scenario = [{"date": d.isoformat(), "cash": path[d]} for d in future_dates]

    # small summary for debugging on UI side, optional
    summary = [{"date": d.isoformat(), "delta": deltas[d]} for d in sorted(deltas)]
    return {"forecast": scenario, "applied": summary}

@app.get("/debit_orders_due")
def debit_orders_due(branch: str = "CPT02", window_days: int = Query(7, ge=1, le=60)):
    frames = _load_branch_frames(branch, None)
    if not frames:
        return {"items": []}

    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["AmountZAR"] = pd.to_numeric(df.get("Credit_ZAR"), errors="coerce").fillna(0) \
                      - pd.to_numeric(df.get("Debit_ZAR"), errors="coerce").fillna(0)
    df = df.dropna(subset=["Date"])
    df = df[df["AmountZAR"] < 0]  # outflows only

    # last 18 months window to find cadence
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=18)
    df = df[df["Date"] >= cutoff]

    cpty = df.get("Counterparty").astype(str)
    desc = df.get("Description").astype(str)
    catg = df.get("Category").astype(str)

    key = cpty.apply(_normalize_name)
    fb  = desc.apply(_normalize_name)
    key = key.where(key.str.len() > 0, fb)

    df["_key"] = key
    df["_kw"]  = desc.apply(_is_debit_keyword_hit) | catg.apply(_is_debit_keyword_hit)

    items = []
    today = pd.Timestamp.today().normalize()
    horizon = today + pd.Timedelta(days=window_days)

    for k, g in df.groupby("_key"):
        if not k:
            continue
        dates = g["Date"].sort_values().reset_index(drop=True)
        if len(dates) < 2 and not g["_kw"].any():
            continue

        gaps = dates.diff().dropna().dt.days
        monthly_like = (len(gaps) >= 2) and (27 <= gaps.median() <= 34)
        weekly_like  = (len(gaps) >= 2) and (6  <= gaps.median() <= 8)

        if not (g["_kw"].any() or monthly_like or weekly_like):
            continue

        amt = float(g["AmountZAR"].abs().median())
        if amt <= 0:
            continue

        raw_name = str(g["Counterparty"].dropna().iloc[0]) if g["Counterparty"].notna().any() else str(g["Description"].dropna().iloc[0])
        display = (raw_name or "Unknown").strip()[:60]

        last = dates.iloc[-1]
        next_due = None

        if monthly_like or g["_kw"].any():
            # day-of-month heuristic (clamp to month-end if needed)
            preferred_dom = int(dates.dt.day.mode().iloc[0]) if not dates.dt.day.mode().empty else last.day
            # try this month
            try:
                candidate = pd.Timestamp(year=today.year, month=today.month, day=preferred_dom)
            except ValueError:
                candidate = (pd.Timestamp(year=today.year, month=today.month, day=1) + pd.offsets.MonthEnd(0))
            next_due = candidate if candidate >= today else _safe_dom_next_month(today, preferred_dom)
        elif weekly_like:
            nd = (last + pd.Timedelta(days=7)).normalize()
            next_due = nd if nd >= today else nd + pd.Timedelta(days=((today - nd).days // 7 + 1) * 7)

        if next_due is None or not (today <= next_due <= horizon):
            continue

        items.append({
            "customer": display,
            "amount": round(amt),
            "dueLabel": next_due.strftime("%a %d %b")
        })

    items = sorted(items, key=lambda x: x["amount"], reverse=True)[:10]
    return {"items": items}

def _safe_dom_next_month(today: pd.Timestamp, dom: int) -> pd.Timestamp:
    first_next = (pd.Timestamp(year=today.year, month=today.month, day=1) + pd.offsets.MonthEnd(1)) - pd.offsets.MonthBegin(1)
    # try exact day; if overflow, return month-end
    try:
        return pd.Timestamp(year=first_next.year, month=first_next.month, day=dom)
    except ValueError:
        return first_next + pd.offsets.MonthEnd(0)
    
@app.post("/admin/ingest")
def admin_ingest(branches: list[str] = ["CPT02","DBN03","JHB01","JHB02","PTA01","ELS01"]):
    out = []
    for b in branches:
        try:
            pq = _build_branch_cache(b)
            out.append({"branch": b, "cache": pq})
        except HTTPException as ex:
            out.append({"branch": b, "error": ex.detail})
    return {"built": out}

@app.get("/admin/ingest/status")
def admin_ingest_status():
    rows = []
    for p in glob.glob(os.path.join(CACHE_DIR, "*.json")):
        with open(p, "r", encoding="utf-8") as f:
            meta = json.load(f)
        sz = os.path.getsize(meta["parquet"]) if os.path.exists(meta["parquet"]) else 0
        rows.append({**meta, "size_bytes": sz})
    return {"caches": rows}

def _fit_prophet(history: pd.Series, horizon_days: int) -> pd.Series:
    # history: pandas Series indexed by Timestamp, values are cash
    from prophet import Prophet  # imported inside so app still loads if not installed
    df = pd.DataFrame({
        "ds": pd.to_datetime(history.index),
        "y": history.astype(float).values
    })
    # Prophet config tuned for cash balance (smooth, allow changepoints)
    m = Prophet(
        seasonality_mode="additive",
        yearly_seasonality=False,
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=0.1
    )
    try:
        m.add_country_holidays(country_name="ZA")
    except Exception:
        pass
    m.fit(df)

    future = m.make_future_dataframe(periods=horizon_days, freq="D", include_history=False)
    fc = m.predict(future)
    # Prophet outputs 'yhat'
    return pd.Series(fc["yhat"].astype(float).values, index=future["ds"])

def _fit_forecast(history: pd.Series, horizon_days: int, model: str = "hw") -> pd.Series:
    if len(history) < 7:
        last = history.iloc[-1] if len(history) else 0.0
        return pd.Series([last] * horizon_days)

    if model == "prophet":
        try:
            return _fit_prophet(history, horizon_days)
        except Exception:
            # fall back gracefully if prophet not available or fails
            pass

    # Holt-Winters (current default)
    try:
        model_hw = ExponentialSmoothing(
            history.astype(float),
            trend="add",
            seasonal=None,
            initialization_method="estimated"
        ).fit(optimized=True, use_brute=True)
        return model_hw.forecast(horizon_days)
    except Exception:
        last = history.iloc[-1]
        return pd.Series([last] * horizon_days)

