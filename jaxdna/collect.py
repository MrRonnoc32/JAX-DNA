"""Collectors for Reddit and Bluesky. API only, no HTML scraping.

Credentials come from environment variables (see .env.example):
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
  BSKY_HANDLE, BSKY_APP_PASSWORD  (Bluesky app password; the public no-login
  endpoint returns 403 to cloud servers such as GitHub Actions)
"""
import datetime as dt
import os
import sys
import time

from . import db
from .filters import clean_text, keep


def _log(msg):
    print(f"[collect] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- Reddit

def collect_reddit(conn, cfg):
    rcfg = cfg["reddit"]
    fcfg = cfg["filters"]
    if not rcfg.get("enabled", True):
        return
    try:
        import praw
    except ImportError:
        _log("praw not installed; skipping Reddit. pip install praw")
        return

    cid, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        _log("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set; skipping Reddit.")
        return

    reddit = praw.Reddit(client_id=cid, client_secret=secret, user_agent=rcfg["user_agent"])
    reddit.read_only = True

    def submission_rows(sub, subsource):
        rows = []
        text = clean_text(f"{sub.title}. {sub.selftext or ''}")
        if keep(text, fcfg):
            rows.append(dict(
                id=f"reddit:{sub.fullname}", source="reddit", subsource=subsource, kind="submission",
                created_utc=int(sub.created_utc), text=text,
                url=f"https://www.reddit.com{sub.permalink}", engagement=int(sub.score or 0),
            ))
        if rcfg.get("include_comments", True):
            try:
                sub.comments.replace_more(limit=0)
                for c in sub.comments.list()[: rcfg.get("max_comments_per_submission", 200)]:
                    ctext = clean_text(getattr(c, "body", ""))
                    if keep(ctext, fcfg):
                        rows.append(dict(
                            id=f"reddit:{c.fullname}", source="reddit", subsource=subsource, kind="comment",
                            created_utc=int(c.created_utc), text=ctext,
                            url=f"https://www.reddit.com{c.permalink}", engagement=int(c.score or 0),
                        ))
            except Exception as e:  # noqa: BLE001
                _log(f"comment fetch failed for {sub.id}: {e}")
        return rows

    # Subreddit listings: new + hot + top(month). Overlap is deduped by primary key.
    for name in rcfg["subreddits"]:
        subsource = f"r/{name}"
        fetched = inserted = 0
        limit = rcfg.get("submissions_per_subreddit", 500)
        try:
            sr = reddit.subreddit(name)
            seen = set()
            for listing in (sr.new(limit=limit), sr.hot(limit=min(limit, 100)), sr.top(time_filter="month", limit=min(limit, 200))):
                for sub in listing:
                    if sub.id in seen:
                        continue
                    seen.add(sub.id)
                    rows = submission_rows(sub, subsource)
                    fetched += len(rows)
                    inserted += db.insert_posts(conn, rows)
            _log(f"{subsource}: fetched {fetched}, inserted {inserted}")
            db.log_run(conn, "reddit", subsource, fetched, inserted)
        except Exception as e:  # noqa: BLE001
            _log(f"{subsource} failed: {e}")
            db.log_run(conn, "reddit", subsource, fetched, inserted, note=str(e))

    # Site-wide keyword search (catches mentions outside local subreddits).
    for term in rcfg.get("site_wide_search_terms", []):
        subsource = f"search:{term}"
        fetched = inserted = 0
        try:
            for sub in reddit.subreddit("all").search(
                f'"{term}"', sort="new", time_filter=rcfg.get("site_wide_time_filter", "week"), limit=250
            ):
                rows = submission_rows(sub, subsource)
                fetched += len(rows)
                inserted += db.insert_posts(conn, rows)
            _log(f"{subsource}: fetched {fetched}, inserted {inserted}")
            db.log_run(conn, "reddit", subsource, fetched, inserted)
        except Exception as e:  # noqa: BLE001
            _log(f"{subsource} failed: {e}")
            db.log_run(conn, "reddit", subsource, fetched, inserted, note=str(e))


# ---------------------------------------------------------------- Bluesky

def collect_bluesky(conn, cfg):
    bcfg = cfg["bluesky"]
    fcfg = cfg["filters"]
    if not bcfg.get("enabled", True):
        return
    try:
        from atproto import Client
    except ImportError:
        _log("atproto not installed; skipping Bluesky. pip install atproto")
        return

    handle, app_pw = os.getenv("BSKY_HANDLE"), os.getenv("BSKY_APP_PASSWORD")
    if handle and app_pw:
        # Authenticated: goes through bsky.social, which is not blocked for cloud runners.
        client = Client()
        try:
            client.login(handle, app_pw)
            _log(f"bluesky: logged in as {handle}")
        except Exception as e:  # noqa: BLE001
            _log(f"bluesky login failed ({e}); falling back to public AppView")
            client = Client(base_url="https://public.api.bsky.app")
    else:
        _log("BSKY_HANDLE / BSKY_APP_PASSWORD not set; using public AppView (often 403 from cloud servers)")
        client = Client(base_url="https://public.api.bsky.app")
    lookback = bcfg.get("lookback_days", 365)
    since_floor = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback)).timestamp())

    for term in bcfg["search_terms"]:
        subsource = f"search:{term}"
        # Incremental: only go back to the newest post we already have for this term.
        newest_have = max(db.latest_created(conn, "bluesky", subsource), since_floor)
        since_iso = dt.datetime.fromtimestamp(newest_have, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = None
        fetched = inserted = 0
        try:
            while fetched < bcfg.get("max_posts_per_term", 2000):
                params = {"q": term, "limit": 100, "sort": "latest", "since": since_iso}
                if cursor:
                    params["cursor"] = cursor
                resp = client.app.bsky.feed.search_posts(params)
                posts = resp.posts or []
                if not posts:
                    break
                rows = []
                for p in posts:
                    rec = p.record
                    text = clean_text(getattr(rec, "text", ""))
                    if not keep(text, fcfg):
                        continue
                    created = getattr(rec, "created_at", None)
                    try:
                        ts = int(dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp())
                    except Exception:  # noqa: BLE001
                        ts = int(time.time())
                    rkey = p.uri.rsplit("/", 1)[-1]
                    handle_free_url = f"https://bsky.app/profile/{p.author.did}/post/{rkey}"
                    rows.append(dict(
                        id=f"bsky:{p.uri}", source="bluesky", subsource=subsource, kind="post",
                        created_utc=ts, text=text, url=handle_free_url,
                        engagement=int(getattr(p, "like_count", 0) or 0),
                    ))
                fetched += len(posts)
                inserted += db.insert_posts(conn, rows)
                cursor = resp.cursor
                if not cursor:
                    break
                time.sleep(0.5)  # polite pacing; public AppView rate limits are generous but finite
            _log(f"bluesky {subsource}: fetched {fetched}, inserted {inserted}")
            db.log_run(conn, "bluesky", subsource, fetched, inserted)
        except Exception as e:  # noqa: BLE001
            _log(f"bluesky {subsource} failed: {e}")
            db.log_run(conn, "bluesky", subsource, fetched, inserted, note=str(e))


def run(conn, cfg, sources=("reddit", "bluesky")):
    if "reddit" in sources:
        collect_reddit(conn, cfg)
    if "bluesky" in sources:
        collect_bluesky(conn, cfg)
    n = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
    _log(f"database now holds {n} posts")
