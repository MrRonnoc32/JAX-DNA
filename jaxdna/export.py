"""Compute the index and topic breakdown, write export.json for the dashboard.

Index method (Hedonometer-style):
  1. Each post gets a sentiment score in [-1, 1] (VADER compound; RoBERTa when present).
  2. Daily mean score across posts (days with fewer than min_posts_per_day are dropped).
  3. Rolling mean over `smoothing_days`, weighted by daily post volume.
  4. Baseline = mean and SD of the smoothed series over the baseline window.
  5. Index = (smoothed - baseline_mean) / baseline_sd, so 0 means 'typical for Jacksonville'
     and +1 means one standard deviation happier than usual.
A sports-excluded variant drops posts tagged with any topic in index.sports_topics.
"""
import datetime as dt
import json
import random
import sys

import pandas as pd

from . import db
from .topics import TOPICS

TOPIC_LABELS = {
    "downtown": "Downtown and neighborhoods",
    "jea_utilities": "JEA and utilities",
    "schools_education": "Schools and education",
    "crime_safety": "Crime and safety",
    "traffic_roads": "Traffic and roads",
    "transit_jta": "Transit, biking, walking",
    "jaguars_sports": "Jaguars and sports",
    "river_beaches_environment": "River, beaches, environment",
    "housing_cost": "Housing and cost of living",
    "politics_city_hall": "Politics and City Hall",
    "weather_storms": "Weather and storms",
    "food_drink": "Food and drink",
    "jobs_economy": "Jobs and economy",
    "airport_travel": "Airport and travel",
    "arts_culture_events": "Arts, culture, events",
    "healthcare": "Health care",
    "general": "General (no topic matched)",
}


def _log(msg):
    print(f"[export] {msg}", file=sys.stderr, flush=True)


def load_frame(conn):
    q = """
    SELECT p.id, p.source, p.kind, p.created_utc, p.text, p.url, p.engagement,
           s.vader, s.roberta, s.roberta_label
    FROM posts p JOIN scores s ON s.post_id = p.id
    """
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return df, pd.DataFrame(columns=["post_id", "topic"])
    df["date"] = pd.to_datetime(df["created_utc"], unit="s", utc=True).dt.tz_convert("America/New_York").dt.date
    topics = pd.read_sql_query("SELECT post_id, topic FROM post_topics", conn)
    return df, topics


def _series(df, score_col, icfg):
    """Return DataFrame indexed by date with columns n, mean, smoothed, index."""
    daily = df.groupby("date")[score_col].agg(["count", "mean"]).rename(columns={"count": "n"})
    daily = daily[daily["n"] >= icfg.get("min_posts_per_day", 5)]
    if daily.empty:
        return daily
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D").date
    daily = daily.reindex(idx)
    w = icfg.get("smoothing_days", 7)
    num = (daily["mean"] * daily["n"]).rolling(w, min_periods=1).sum()
    den = daily["n"].rolling(w, min_periods=1).sum()
    daily["smoothed"] = num / den
    if icfg.get("baseline") == "first_days":
        base = daily["smoothed"].dropna().iloc[: icfg.get("baseline_days", 90)]
    else:
        base = daily["smoothed"].dropna()
    mu, sd = base.mean(), base.std(ddof=0) or 1e-9
    daily["index"] = (daily["smoothed"] - mu) / sd
    daily.attrs["baseline_mean"] = float(mu)
    daily.attrs["baseline_sd"] = float(sd)
    return daily


def _series_json(daily):
    if daily.empty:
        return []
    out = []
    for d, r in daily.iterrows():
        out.append({
            "date": d.isoformat(),
            "n": int(r["n"]) if pd.notna(r["n"]) else 0,
            "mean": None if pd.isna(r["mean"]) else round(float(r["mean"]), 4),
            "smoothed": None if pd.isna(r["smoothed"]) else round(float(r["smoothed"]), 4),
            "index": None if pd.isna(r["index"]) else round(float(r["index"]), 3),
        })
    return out


def _examples(sub, score_col, k=3):
    sub = sub.dropna(subset=[score_col])
    if sub.empty:
        return {"positive": [], "negative": []}
    def fmt(rows):
        return [{"text": (t[:280] + "...") if len(t) > 280 else t, "score": round(float(s), 3),
                 "source": src, "url": u, "date": str(d)}
                for t, s, src, u, d in zip(rows["text"], rows[score_col], rows["source"], rows["url"], rows["date"])]
    return {"positive": fmt(sub.nlargest(k, score_col)), "negative": fmt(sub.nsmallest(k, score_col))}


def _recent_log(conn, n=12):
    rows = conn.execute("SELECT run_utc, source, subsource, fetched, inserted, note FROM collection_log ORDER BY run_utc DESC LIMIT ?", (n,)).fetchall()
    return [{"run_utc": r["run_utc"], "source": r["source"], "subsource": r["subsource"], "fetched": r["fetched"],
             "inserted": r["inserted"], "note": (r["note"] or "")[:160]} for r in rows]


def build(conn, cfg, synthetic=False):
    icfg = cfg["index"]
    df, topics = load_frame(conn)
    if df.empty:
        _log("no scored posts; writing empty export")
        export = {"meta": {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           "synthetic": False, "empty": True, "primary_model": "vader", "roberta_used": "no",
                           "n_posts": 0, "n_days": 0, "date_min": None, "date_max": None, "baseline_mean": 0,
                           "baseline_sd": 0, "smoothing_days": icfg.get("smoothing_days", 7),
                           "min_posts_per_day": icfg.get("min_posts_per_day", 5), "latest_index": None,
                           "change_30d": None, "pct_positive": None, "pct_negative": None, "vader_roberta_corr": None,
                           "collection_log": _recent_log(conn)},
                  "series": {"all": {"vader": []}, "no_sports": {"vader": []}}, "topics": [], "sources": []}
        with open(cfg["export_path"], "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=1)
        return export

    roberta_ok = df["roberta"].notna().mean() > 0.9
    primary = "roberta" if roberta_ok else "vader"
    _log(f"primary model: {primary} ({len(df)} scored posts)")

    sports_ids = set(topics.loc[topics["topic"].isin(icfg.get("sports_topics", [])), "post_id"])
    df_nosports = df[~df["id"].isin(sports_ids)]

    series = {
        "all": {m: _series_json(_series(df, m, icfg)) for m in ("vader", "roberta") if df[m].notna().any()},
        "no_sports": {m: _series_json(_series(df_nosports, m, icfg)) for m in ("vader", "roberta") if df_nosports[m].notna().any()},
    }
    prim_all = _series(df, primary, icfg)

    # Topic summary over the whole window plus weekly series per topic.
    merged = topics.merge(df, left_on="post_id", right_on="id")
    merged["week"] = pd.to_datetime(merged["date"]).dt.to_period("W-SAT").apply(lambda p: p.start_time.date().isoformat())
    topic_rows = []
    for t in list(TOPICS) + ["general"]:
        sub = merged[merged["topic"] == t]
        if sub.empty:
            continue
        weekly = sub.groupby("week")[primary].agg(["count", "mean"]).reset_index()
        topic_rows.append({
            "key": t,
            "label": TOPIC_LABELS.get(t, t),
            "n": int(len(sub)),
            "share": round(len(sub) / len(df), 4),
            "mean_vader": round(float(sub["vader"].mean()), 4),
            "mean_roberta": None if sub["roberta"].isna().all() else round(float(sub["roberta"].mean()), 4),
            "pct_positive": round(float((sub[primary] > 0.05).mean()), 4),
            "pct_negative": round(float((sub[primary] < -0.05).mean()), 4),
            "weekly": [{"week": w, "n": int(c), "mean": round(float(m), 4)} for w, c, m in zip(weekly["week"], weekly["count"], weekly["mean"])],
            "examples": _examples(sub, primary),
        })
    topic_rows.sort(key=lambda r: -r["n"])

    by_source = df.groupby("source").agg(n=("id", "size"), mean_vader=("vader", "mean"), mean_roberta=("roberta", "mean")).reset_index()
    sources = [{"source": r.source, "n": int(r.n), "mean_vader": round(float(r.mean_vader), 4),
                "mean_roberta": None if pd.isna(r.mean_roberta) else round(float(r.mean_roberta), 4)} for r in by_source.itertuples()]

    latest = prim_all.dropna(subset=["index"]).tail(1)
    latest_val = None if latest.empty else round(float(latest["index"].iloc[0]), 2)
    prev = prim_all.dropna(subset=["index"])
    change_30 = None
    if len(prev) > 30:
        change_30 = round(float(prev["index"].iloc[-1] - prev["index"].iloc[-31]), 2)

    export = {
        "meta": {
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "synthetic": bool(synthetic),
            "primary_model": primary,
            "roberta_used": db.get_meta(conn, "roberta_used", "no"),
            "n_posts": int(len(df)),
            "n_days": int(prim_all["n"].notna().sum()),
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "baseline_mean": round(prim_all.attrs.get("baseline_mean", 0), 4),
            "baseline_sd": round(prim_all.attrs.get("baseline_sd", 0), 4),
            "smoothing_days": icfg.get("smoothing_days", 7),
            "min_posts_per_day": icfg.get("min_posts_per_day", 5),
            "latest_index": latest_val,
            "change_30d": change_30,
            "pct_positive": round(float((df[primary] > 0.05).mean()), 4),
            "pct_negative": round(float((df[primary] < -0.05).mean()), 4),
            "vader_roberta_corr": None if not roberta_ok else round(float(df[["vader", "roberta"]].corr().iloc[0, 1]), 3),
            "collection_log": _recent_log(conn),
        },
        "series": series,
        "topics": topic_rows,
        "sources": sources,
    }
    with open(cfg["export_path"], "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=1)
    _log(f"wrote {cfg['export_path']}")
    return export


def validation_sample(conn, cfg, seed=42):
    """Write a CSV of random posts with model scores and a blank column for a human label."""
    vcfg = cfg["validation"]
    df, _ = load_frame(conn)
    if df.empty:
        return None
    k = min(vcfg.get("sample_size", 200), len(df))
    sample = df.sample(n=k, random_state=seed)[["id", "source", "date", "text", "vader", "roberta", "roberta_label", "url"]].copy()
    sample["human_label"] = ""   # fill with positive / neutral / negative
    sample["notes"] = ""
    sample.to_csv(vcfg["output_csv"], index=False)
    _log(f"wrote {vcfg['output_csv']} ({k} rows)")
    return vcfg["output_csv"]


def validation_report(cfg):
    """Read a filled-in validation CSV and print agreement stats."""
    vcfg = cfg["validation"]
    df = pd.read_csv(vcfg["output_csv"])
    df = df[df["human_label"].astype(str).str.strip().str.lower().isin(["positive", "neutral", "negative"])]
    if df.empty:
        print("No human labels found yet. Fill the human_label column with positive / neutral / negative.")
        return
    human = df["human_label"].str.strip().str.lower()
    def bucket(x):
        return "positive" if x > 0.05 else ("negative" if x < -0.05 else "neutral")
    for col in ("vader", "roberta"):
        if df[col].notna().any():
            pred = df[col].apply(bucket)
            agree = (pred == human).mean()
            print(f"{col}: 3-class agreement with human labels = {agree:.1%} (n={len(df)})")
            print(pd.crosstab(human, pred, rownames=["human"], colnames=[col]))
            print()
