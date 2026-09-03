#!/usr/bin/env python3
"""JAX DNA command line.

  python run.py collect [--source reddit|bluesky]   pull new posts (API only)
  python run.py score   [--force] [--no-roberta]    sentiment + topic tagging
  python run.py export                              compute index, write data/export.json
  python run.py dashboard                           build dashboard/index.html from the export
  python run.py all                                 collect + score + export + dashboard
  python run.py validate                            write data/validation_sample.csv for hand coding
  python run.py validate --report                   score the hand-coded CSV
  python run.py demo                                load synthetic posts, then score/export/dashboard
  python run.py status                              row counts and last runs
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except ImportError:
    pass

from jaxdna import db, collect, score, topics, export, fixtures  # noqa: E402
from dashboard.build import build_dashboard  # noqa: E402


def load_cfg():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["collect", "score", "export", "dashboard", "all", "validate", "demo", "status", "retag"])
    ap.add_argument("--source", choices=["reddit", "bluesky"], help="collect from one source only")
    ap.add_argument("--force", action="store_true", help="rescore every post")
    ap.add_argument("--no-roberta", action="store_true", help="VADER only")
    ap.add_argument("--report", action="store_true", help="with validate: score the filled-in CSV")
    args = ap.parse_args()

    cfg = load_cfg()
    if args.no_roberta:
        cfg["scoring"]["use_roberta"] = False
    conn = db.connect(cfg["database"])
    synthetic = db.get_meta(conn, "synthetic") == "yes"

    if args.command == "collect":
        if synthetic:
            sys.exit("Database holds synthetic demo data. Delete data/jaxdna.sqlite before collecting real posts.")
        collect.run(conn, cfg, sources=(args.source,) if args.source else ("reddit", "bluesky"))

    elif args.command == "score":
        score.score_all(conn, cfg, force=args.force)
        topics.tag_all(conn)

    elif args.command == "retag":
        n = topics.retag_all(conn)
        print(f"retagged {n} posts")

    elif args.command == "export":
        export.build(conn, cfg, synthetic=synthetic)

    elif args.command == "dashboard":
        build_dashboard(cfg["export_path"], os.path.join(HERE, "dashboard", "index.html"))

    elif args.command == "all":
        if synthetic:
            sys.exit("Database holds synthetic demo data. Delete data/jaxdna.sqlite before collecting real posts.")
        collect.run(conn, cfg)
        score.score_all(conn, cfg)
        topics.tag_all(conn)
        export.build(conn, cfg)
        build_dashboard(cfg["export_path"], os.path.join(HERE, "dashboard", "index.html"))

    elif args.command == "demo":
        n = fixtures.generate(conn)
        print(f"loaded {n} synthetic posts")
        score.score_all(conn, cfg)
        topics.tag_all(conn)
        export.build(conn, cfg, synthetic=True)
        build_dashboard(cfg["export_path"], os.path.join(HERE, "dashboard", "index.html"))

    elif args.command == "validate":
        if args.report:
            export.validation_report(cfg)
        else:
            export.validation_sample(conn, cfg)

    elif args.command == "status":
        n = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
        s = conn.execute("SELECT COUNT(*) c FROM scores").fetchone()["c"]
        print(f"posts: {n}   scored: {s}   synthetic: {synthetic}")
        for r in conn.execute("SELECT source, COUNT(*) c, MIN(created_utc) a, MAX(created_utc) b FROM posts GROUP BY source"):
            import datetime as dt
            print(f"  {r['source']:8s} {r['c']:7d}  {dt.date.fromtimestamp(r['a'])} to {dt.date.fromtimestamp(r['b'])}")
        print("last collection runs:")
        for r in conn.execute("SELECT * FROM collection_log ORDER BY run_utc DESC LIMIT 10"):
            import datetime as dt
            print(f"  {dt.datetime.fromtimestamp(r['run_utc']):%Y-%m-%d %H:%M} {r['source']:8s} {str(r['subsource']):28s} fetched={r['fetched']} inserted={r['inserted']} {r['note'] or ''}")


if __name__ == "__main__":
    main()
