"""Sentiment scoring with two off-the-shelf models.

VADER: lexicon-based, instant, weak on sarcasm. Always runs.
RoBERTa (cardiffnlp/twitter-roberta-base-sentiment-latest): trained on tweets,
better on informal text. Runs when transformers + torch are installed and the
model can be downloaded (about 500 MB the first time). Score is P(pos) - P(neg).
"""
import sys
import time

from . import db


def _log(msg):
    print(f"[score] {msg}", file=sys.stderr, flush=True)


def _vader():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    return SentimentIntensityAnalyzer()


def _roberta(model_name):
    try:
        from transformers import pipeline
    except ImportError:
        _log("transformers not installed; RoBERTa disabled. pip install torch transformers")
        return None
    try:
        return pipeline("sentiment-analysis", model=model_name, tokenizer=model_name,
                        top_k=None, truncation=True, max_length=512)
    except Exception as e:  # noqa: BLE001
        _log(f"RoBERTa unavailable ({e}); continuing with VADER only")
        return None


def _roberta_scores(pipe, texts):
    """Return list of (score, label)."""
    out = []
    for res in pipe(texts):
        probs = {d["label"].lower(): d["score"] for d in res}
        score = probs.get("positive", 0.0) - probs.get("negative", 0.0)
        label = max(probs, key=probs.get)
        out.append((score, label))
    return out


def score_all(conn, cfg, force=False):
    scfg = cfg["scoring"]
    if force:
        conn.execute("DELETE FROM scores")
        conn.commit()
    rows = db.unscored_posts(conn)
    if not rows:
        _log("nothing to score")
        return 0
    _log(f"scoring {len(rows)} posts")

    vader = _vader()
    pipe = _roberta(scfg["roberta_model"]) if scfg.get("use_roberta", True) else None
    bs = scfg.get("batch_size", 32)
    now = int(time.time())
    done = 0
    for i in range(0, len(rows), bs):
        batch = rows[i:i + bs]
        texts = [r["text"] for r in batch]
        v = [vader.polarity_scores(t)["compound"] for t in texts]
        if pipe is not None:
            rb = _roberta_scores(pipe, texts)
        else:
            rb = [(None, None)] * len(batch)
        conn.executemany(
            "INSERT OR REPLACE INTO scores (post_id, vader, roberta, roberta_label, scored_utc) VALUES (?,?,?,?,?)",
            [(r["id"], v[k], rb[k][0], rb[k][1], now) for k, r in enumerate(batch)],
        )
        conn.commit()
        done += len(batch)
        if done % (bs * 20) == 0:
            _log(f"  {done}/{len(rows)}")
    db.set_meta(conn, "roberta_used", "yes" if pipe is not None else "no")
    db.set_meta(conn, "last_scored_utc", now)
    _log(f"scored {done} posts (RoBERTa {'on' if pipe else 'off'})")
    return done
