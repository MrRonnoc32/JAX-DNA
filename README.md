# JAX DNA: Jacksonville sentiment tracker

A Hedonometer-style tracker for how people posting about Jacksonville feel about the city. It pulls public posts through official APIs (no HTML scraping), scores each one with two off-the-shelf sentiment models, tags topics with keyword rules, and builds a standardized daily index plus a topic breakdown. Output is a single-file HTML dashboard.

Built for the Jacksonville Civic Council as an internal exploration. Everything runs on your Mac in Terminal.

## What is in the folder

```
run.py                 command line entry point
config.json            sources, search terms, filters, index settings
requirements.txt       Python packages
.env.example           copy to .env and add Reddit keys
jaxdna/
  collect.py           Reddit (PRAW) and Bluesky (atproto) collectors
  score.py             VADER + RoBERTa scoring
  topics.py            keyword topic rules (edit these freely)
  export.py            index math, topic summary, export.json, validation sample
  fixtures.py          synthetic demo posts (for testing only)
  db.py                SQLite schema
dashboard/
  template.html        dashboard source
  build.py             injects export.json into the template
  index.html           the built dashboard (open in a browser)
data/
  jaxdna.sqlite        all posts, scores, topics
  export.json          what the dashboard reads
  validation_sample.csv  200 posts for hand coding
```

## Setup (one time, about 15 minutes)

1. Open Terminal and go to the folder:
   `cd ~/Downloads/"JAX DNA"`

2. Create a Python environment and install packages:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   Optional, for the RoBERTa model (better on sarcasm and slang; about 500 MB download the first time):
   `pip install torch transformers`

3. Register a Reddit API app. Go to https://www.reddit.com/prefs/apps while logged in, click "create another app", choose **script**, name it "JAX DNA", set the redirect URI to `http://localhost:8080`, and save. Copy the client ID (the short string under the app name) and the secret.

4. Copy `.env.example` to `.env` and paste the two values in. Bluesky needs no key.

5. If the demo data is still loaded, delete it first: `rm data/jaxdna.sqlite`

## Running it

```
python run.py collect      # pull posts (first run: several thousand; later runs: only new ones)
python run.py score        # sentiment + topics for anything unscored
python run.py export       # compute the index, write data/export.json
python run.py dashboard    # rebuild dashboard/index.html
```
Or all four at once: `python run.py all`

Then open `dashboard/index.html` in a browser.

`python run.py status` shows counts and recent collection runs.

To keep it current, run `python run.py all` on a schedule. On a Mac, a cron line like this runs it every morning at 6:00:
```
0 6 * * * cd ~/Downloads/"JAX DNA" && .venv/bin/python run.py all >> data/cron.log 2>&1
```

## Testing without any API keys

`python run.py demo` loads 1,800 synthetic posts, scores them, and builds the dashboard. A yellow banner marks the data as fake. Delete `data/jaxdna.sqlite` before collecting real posts.

## Validating the models

1. `python run.py validate` writes `data/validation_sample.csv` with 200 random posts.
2. Open it in Excel and fill the `human_label` column with `positive`, `neutral`, or `negative`.
3. `python run.py validate --report` prints agreement rates and a confusion table for each model.

Expect VADER around 55 to 65 percent three-way agreement on this kind of text and RoBERTa around 70 to 75 percent. Below that, look at the confusion table and adjust: the neutral band is set at scores between -0.05 and 0.05 in `export.py`.

## How the index is built

1. Each post gets a score from -1 to +1. RoBERTa is the primary model when it ran; otherwise VADER.
2. Daily mean across posts. Days with fewer than `min_posts_per_day` (default 5) are dropped.
3. Seven-day rolling mean, weighted by daily volume.
4. Baseline mean and standard deviation over the whole period (or the first 90 days if `baseline` is set to `first_days`).
5. Index = (smoothed value minus baseline mean) divided by baseline SD. Zero is a typical day. The dashboard also shows the raw smoothed mean.

A second series drops every post tagged `jaguars_sports`, so game days do not drive the city number.

## Editing topics

Open `jaxdna/topics.py`. Each topic is a list of words or phrases. Matches use word boundaries, so `er` will not match `better`. After editing, run `python run.py retag` then `export` and `dashboard`.

## Known limits

- Reddit search is capped at about 250 results per query and the subreddit listings at 1,000 posts, so history is limited to what those return. Incremental runs build a longer record over time.
- Bluesky search goes back roughly a year; volume for Jacksonville is low (expect tens of posts per day).
- Posts about other Jacksonvilles (NC, IL, AR, TX) are filtered on obvious markers only.
- Keyword topics miss posts that do not use the listed words. Those land in "General".
- Off-the-shelf models misread sarcasm and local slang. Treat single-day moves with caution; the 7-day smoothing is there for a reason.
- This measures people who post publicly about Jacksonville, not a representative sample of residents.

## Privacy

Only post text, timestamp, source, engagement count, and a link are stored. No usernames or handles. The Bluesky link uses the account DID rather than the handle.

## Next steps after the prototype works

- Add X (Twitter) if the Basic tier ($200/month, 10,000 reads) proves enough, or Pro if not.
- Add Google Places reviews for parks, libraries, and civic sites as a topic layer.
- Replace keyword topics with embedding clusters once there are more than about 20,000 posts.
- Validate the index against UNF Public Opinion Research Lab polls and JCC survey data.
- Publish the dashboard once the numbers are trusted.

## Running it on GitHub instead of your Mac

The repo includes `.github/workflows/update.yml`, which runs the whole pipeline every morning on GitHub's servers and publishes the dashboard with GitHub Pages.

1. Create a repo (public recommended) and push this folder to it. Delete `data/jaxdna.sqlite` first if it still holds demo data.
2. In the repo go to Settings, then Secrets and variables, then Actions. Add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`.
3. Settings, then Pages: set Source to "GitHub Actions".
4. Actions tab: open "Update JAX DNA sentiment index" and click "Run workflow" for the first run.

After that it runs daily at 6:00 Eastern and commits the updated database, export, and dashboard back to the repo. The dashboard URL will be `https://<account>.github.io/<repo>/`.
