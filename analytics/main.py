
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from statsmodels.tsa.holtwinters import ExponentialSmoothing

app = FastAPI(title="NedVision Analytics Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = r"C:\Nedbank\NedVision\data"

class ForecastRequest(BaseModel):
    branch: str = Field(..., description="Branch code, e.g., CPT02")
    from_date: Optional[date] = Field(None, description="Limit history from this date (inclusive)")
    to_date: Optional[date] = Field(None, description="Limit history to this date (inclusive)")
    horizon_days: int = Field(30, ge=1, le=120, description="Forecast horizon in days")
    files: Optional[List[str]] = Field(None, description="Optional explicit CSV file paths to load")

class Adjustment(BaseModel):
    date: date
    delta: float
    label: Optional[str] = None

class SimulationRequest(BaseModel):
    branch: str
    base_from_date: Optional[date] = None
    base_to_date: Optional[date] = None
    horizon_days: int = Field(30, ge=1, le=120)
    files: Optional[List[str]] = None
    adjustments: List[Adjustment] = Field(default_factory=list)

NUMERIC_COLS = [
    "Debit_FC","Credit_FC","Balance_FC","Debit_ZAR","Credit_ZAR","Balance_ZAR",
    "FX_to_ZAR_at_Txn","Latitude","Longitude"
]

def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for c in NUMERIC_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    return df

def _load_branch_frames(branch: str, files: Optional[List[str]]) -> List[pd.DataFrame]:
    frames: List[pd.DataFrame] = []
    if files:
        for f in files:
            if not os.path.exists(f):
                raise HTTPException(status_code=400, detail=f"File not found: {f}")
            frames.append(_coerce_numeric(pd.read_csv(f)))
    else:
        import glob
        pattern = os.path.join(DATA_DIR, f"statement_{branch}_*.csv")
        matches = glob.glob(pattern)
        if not matches:
            raise HTTPException(status_code=404, detail=f"No CSVs found for pattern: {pattern}")
        for f in matches:
            frames.append(_coerce_numeric(pd.read_csv(f)))
    return frames

def _daily_cash_series(frames: List[pd.DataFrame], from_date: Optional[date], to_date: Optional[date]) -> pd.DataFrame:
    df = pd.concat(frames, ignore_index=True)
    if "Date" not in df.columns:
        raise HTTPException(status_code=400, detail="CSV must contain a 'Date' column")
    if from_date:
        df = df[df["Date"] >= from_date]
    if to_date:
        df = df[df["Date"] <= to_date]

    if "Credit_ZAR" not in df.columns or "Debit_ZAR" not in df.columns:
        raise HTTPException(status_code=400, detail="CSV must contain 'Credit_ZAR' and 'Debit_ZAR' columns")
    df["AmountZAR"] = df["Credit_ZAR"].fillna(0) - df["Debit_ZAR"].fillna(0)

    daily = df.groupby("Date", as_index=False)["AmountZAR"].sum().sort_values("Date")
    daily = daily.rename(columns={"AmountZAR": "daily_change"})

    if daily.empty:
        raise HTTPException(status_code=400, detail="No rows after filtering; cannot build series")
    idx = pd.date_range(start=daily["Date"].min(), end=daily["Date"].max(), freq="D").date
    full = pd.DataFrame({"Date": idx}).merge(daily, on="Date", how="left")
    full["daily_change"] = full["daily_change"].fillna(0.0)

    anchor = None
    if "Balance_ZAR" in df.columns:
        tmp = df.dropna(subset=["Balance_ZAR"]).sort_values("Date")
        if not tmp.empty:
            anchor = float(tmp.iloc[0]["Balance_ZAR"])

    base = 0.0 if anchor is None else anchor
    full["cash"] = base + full["daily_change"].cumsum()

    return full[["Date","daily_change","cash"]]

def _fit_forecast(history: pd.Series, horizon_days: int) -> pd.Series:
    if len(history) < 7:
        last = history.iloc[-1] if len(history) else 0.0
        future = pd.Series([last] * horizon_days)
        return future

    try:
        model = ExponentialSmoothing(
            history.astype(float),
            trend="add",
            seasonal=None,
            initialization_method="estimated"
        ).fit(optimized=True, use_brute=True)
        forecast = model.forecast(horizon_days)
        return forecast
    except Exception:
        last = history.iloc[-1]
        return pd.Series([last] * horizon_days)

def _top_drivers(df_list: List[pd.DataFrame], topn: int = 5) -> Dict[str, Any]:
    df = pd.concat(df_list, ignore_index=True)
    df["AmountZAR"] = df["Credit_ZAR"].fillna(0) - df["Debit_ZAR"].fillna(0)
    agg_cat = (df.groupby("Category", dropna=False)["AmountZAR"]
                 .sum()
                 .sort_values(ascending=False))
    agg_cp = (df.groupby("Counterparty", dropna=False)["AmountZAR"]
                .sum()
                .sort_values(ascending=False))
    top_inflows = agg_cat[agg_cat > 0].head(topn).round(2).to_dict()
    top_outflows = agg_cat[agg_cat < 0].tail(topn).round(2).to_dict()
    top_counterparties = {str(k) if k is not None else "Unknown": float(v) for k, v in agg_cp.head(topn).round(2).to_dict().items()}
    return {
        "top_inflows_by_category": {str(k) if k is not None else "Uncategorised": float(v) for k, v in top_inflows.items()},
        "top_outflows_by_category": {str(k) if k is not None else "Uncategorised": float(v) for k, v in top_outflows.items()},
        "top_counterparties": top_counterparties
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/forecast")
def forecast(req: ForecastRequest):
    frames = _load_branch_frames(req.branch, req.files)
    series = _daily_cash_series(frames, req.from_date, req.to_date)

    history = series.set_index(pd.to_datetime(series["Date"]))["cash"]
    horizon = int(req.horizon_days)
    fc = _fit_forecast(history, horizon)

    last_date = history.index.max().date()
    future_index = [last_date + timedelta(days=i) for i in range(1, horizon + 1)]
    forecast_points = [{"date": d.isoformat(), "cash": float(v)} for d, v in zip(future_index, fc.values)]
    history_points = [{"date": d.date().isoformat(), "cash": float(v)} for d, v in history.items()]

    drivers = _top_drivers(frames)
    return {
        "branch": req.branch,
        "history": history_points,
        "forecast": forecast_points,
        "drivers": drivers
    }

@app.post("/simulate")
def simulate(req: SimulationRequest):
    frames = _load_branch_frames(req.branch, req.files)
    series = _daily_cash_series(frames, req.base_from_date, req.base_to_date)
    history = series.set_index(pd.to_datetime(series["Date"]))["cash"]

    horizon = int(req.horizon_days)
    base_fc = _fit_forecast(history, horizon)

    last_date = history.index.max().date()
    future_dates = [last_date + timedelta(days=i) for i in range(1, horizon + 1)]
    path = {d: float(v) for d, v in zip(future_dates, base_fc.values)}

    for adj in sorted(req.adjustments, key=lambda a: a.date):
        for d in future_dates:
            if d >= adj.date:
                path[d] += adj.delta

    adjusted = [{"date": d.isoformat(), "cash": path[d]} for d in future_dates]
    drivers = _top_drivers(frames)
    return {
        "branch": req.branch,
        "history": [{"date": d.date().isoformat(), "cash": float(v)} for d, v in history.items()],
        "forecast_base": [{"date": d.isoformat(), "cash": float(v)} for d, v in zip(future_dates, base_fc.values)],
        "forecast_adjusted": adjusted,
        "applied_adjustments": [a.dict() for a in req.adjustments],
        "drivers": drivers
    }
