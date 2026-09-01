"""
JSON API — current-date campaign data (pure, no data folder)
Returns ONLY campaigns: start <= today-7 AND end > today.
Data is generated in-memory on every request.
"""
import datetime as dt
import random

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

SEED = 42

MARKETING_CHANNELS = [
    "Organic Search", "Paid Search", "Social Media - Instagram",
    "Social Media - Facebook", "Email Marketing", "Affiliate",
    "Influencer Marketing", "Direct/App", "Referral", "SMS Marketing",
]
CAMPAIGN_TYPES = [
    "Seasonal Sale", "Flash Sale", "New Product Launch", "Brand Awareness",
    "Retargeting", "Loyalty Program", "Clearance Sale", "Festival Special",
]
CUSTOMER_SEGMENTS = ["Premium", "Regular", "Budget", "New"]

START_DATE = dt.date(2024, 1, 1)
END_DATE = dt.date(2026, 9, 1)


def _today() -> dt.date:
    t = dt.date.today()
    if t < START_DATE:
        return START_DATE
    if t > END_DATE:
        return END_DATE
    return t


def generate_campaigns_df(seed: int = SEED) -> pd.DataFrame:
    random.seed(seed)
    np.random.seed(seed)
    rows = []
    cid = 1
    for year in [2024, 2025, 2026]:
        for month in range(1, 13):
            active = np.random.choice(MARKETING_CHANNELS, size=np.random.randint(3, 6), replace=False)
            for ch in active:
                start = dt.date(year, month, np.random.randint(1, 10))
                duration = np.random.randint(5, 21)
                end = min(start + dt.timedelta(days=duration), END_DATE)
                if start > END_DATE:
                    continue
                rows.append({
                    "campaign_id": f"CAMP{1000+cid}",
                    "campaign_name": f"{ch} {random.choice(CAMPAIGN_TYPES)} {start.strftime('%b %Y')}",
                    "channel": ch,
                    "campaign_start_date": start,
                    "campaign_end_date": end,
                    "campaign_type": random.choice(CAMPAIGN_TYPES),
                    "target_segment": random.choice(CUSTOMER_SEGMENTS + ["All"]),
                    "discount_percentage": random.choice([5, 10, 15, 20, 25, 30]),
                    "impressions": int(np.random.randint(40000, 300000)),
                    "clicks": int(np.random.randint(1500, 25000)),
                    "conversions": int(np.random.randint(20, 600)),
                    "campaign_cost": round(float(np.random.uniform(8000, 70000)), 2),
                    "revenue_generated": round(float(np.random.uniform(40000, 600000)), 2),
                })
                rows[-1]["roi"] = round((rows[-1]["revenue_generated"] - rows[-1]["campaign_cost"]) / rows[-1]["campaign_cost"], 3)
                cid += 1
    df = pd.DataFrame(rows)
    df["campaign_start_date"] = pd.to_datetime(df["campaign_start_date"]).dt.date
    df["campaign_end_date"] = pd.to_datetime(df["campaign_end_date"]).dt.date
    return df


def active_campaigns(today: dt.date | None = None, seed: int = SEED) -> pd.DataFrame:
    if today is None:
        today = _today()
    df = generate_campaigns_df(seed=seed)
    df["campaign_start_date"] = pd.to_datetime(df["campaign_start_date"]).dt.date
    df["campaign_end_date"] = pd.to_datetime(df["campaign_end_date"]).dt.date
    filtered = df[(df["campaign_start_date"] <= today - dt.timedelta(days=7)) & (df["campaign_end_date"] > today)].copy()

    import hashlib

    h = int(hashlib.md5(f"{seed}-{today.isoformat()}".encode()).hexdigest(), 16)
    target = 20 + (h % 11)

    if 20 <= len(filtered) <= 30:
        return filtered.sort_values("campaign_start_date")
    if len(filtered) > target:
        return filtered.sample(n=target, random_state=h % (2**31)).sort_values("campaign_start_date")

    need = target - len(filtered)
    rng = random.Random(h)
    rows = []
    existing = set(filtered["campaign_id"]) if not filtered.empty else set()
    cid = 9000
    for _ in range(need):
        while f"CAMP{cid}" in existing:
            cid += 1
        ch = rng.choice(MARKETING_CHANNELS)
        start = today - dt.timedelta(days=rng.randint(7, 14))
        end = today + dt.timedelta(days=rng.randint(7, 21))
        cost = round(float(rng.uniform(8000, 70000)), 2)
        rev = round(float(rng.uniform(40000, 600000)), 2)
        rows.append({
            "campaign_id": f"CAMP{cid}",
            "campaign_name": f"{ch} {rng.choice(CAMPAIGN_TYPES)} {today.strftime('%b %Y')} (Active)",
            "channel": ch,
            "campaign_start_date": start,
            "campaign_end_date": end,
            "campaign_type": rng.choice(CAMPAIGN_TYPES),
            "target_segment": rng.choice(CUSTOMER_SEGMENTS + ["All"]),
            "discount_percentage": rng.choice([5, 10, 15, 20, 25, 30]),
            "impressions": int(rng.randint(40000, 300000)),
            "clicks": int(rng.randint(1500, 25000)),
            "conversions": int(rng.randint(20, 600)),
            "campaign_cost": cost,
            "revenue_generated": rev,
            "roi": round((rev - cost) / cost, 3),
        })
        existing.add(f"CAMP{cid}")
        cid += 1

    synth = pd.DataFrame(rows)
    combined = pd.concat([filtered, synth], ignore_index=True) if not filtered.empty else synth
    return combined.sort_values("campaign_start_date")


app = FastAPI(title="AutomaSQL Campaigns API", description="start <= today-7 AND end > today", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs", "endpoint": "/api/campaigns"}


@app.get("/health")
def health():
    return {"status": "ok", "today": _today().isoformat()}


@app.get("/api/campaigns")
def get_campaigns(
    channel: str | None = Query(None),
    campaign_type: str | None = Query(None, alias="type"),
    as_of: str | None = Query(None, description="YYYY-MM-DD override for testing"),
):
    if as_of:
        try:
            today = dt.date.fromisoformat(as_of)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "as_of must be YYYY-MM-DD"})
    else:
        today = _today()
    df = active_campaigns(today=today)
    if channel:
        df = df[df["channel"] == channel]
    if campaign_type:
        df = df[df["campaign_type"] == campaign_type]
    records = df.copy()
    records["campaign_start_date"] = records["campaign_start_date"].astype(str)
    records["campaign_end_date"] = records["campaign_end_date"].astype(str)
    return {
        "as_of": today.isoformat(),
        "filter": {"start_date_max": (today - dt.timedelta(days=7)).isoformat(), "end_date_min": (today + dt.timedelta(days=1)).isoformat(), "rule": "campaign_start_date <= today-7 AND campaign_end_date > today"},
        "count": len(records),
        "campaigns": records.to_dict(orient="records"),
    }


@app.get("/api/campaigns/{campaign_id}")
def get_campaign_by_id(campaign_id: str, as_of: str | None = None):
    if as_of:
        try:
            today = dt.date.fromisoformat(as_of)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "as_of must be YYYY-MM-DD"})
    else:
        today = _today()
    df = active_campaigns(today=today)
    row = df[df["campaign_id"] == campaign_id]
    if row.empty:
        return JSONResponse(status_code=404, content={"error": f"campaign {campaign_id} not found or not active today"})
    rec = row.iloc[0].to_dict()
    rec["campaign_start_date"] = str(rec["campaign_start_date"])
    rec["campaign_end_date"] = str(rec["campaign_end_date"])
    return {"as_of": today.isoformat(), "campaign": rec}
