"""Synthetic sample posts for testing the pipeline without network access.

Everything produced here is clearly fake and is flagged synthetic=True in the export.
"""
import datetime as dt
import random

from . import db

POS = [
    "Downtown Jacksonville is finally coming alive, the riverfront walk last night was gorgeous.",
    "Shoutout to the JEA crew who had our power back on within an hour after the storm.",
    "Took the kids to Hanna Park this weekend. Best beach day of the year, water was perfect.",
    "New brewery in Riverside is excellent, Jacksonville's food scene keeps getting better.",
    "Jaguars looked sharp today. DUUUVAL! Great atmosphere at the stadium.",
    "Honestly the Cummer Museum gardens are one of the most underrated spots in Jacksonville.",
    "Moved to Jacksonville from Atlanta two years ago and I love it here. No regrets.",
    "The new bike lanes on Riverside Ave are a real improvement, felt safe riding downtown.",
    "Jacksonville Zoo membership is the best money we spend all year. Kids adore it.",
    "Jazz Fest was fantastic, Jacksonville knows how to throw a festival.",
    "Our DCPS teacher went above and beyond this semester. Grateful for Duval schools right now.",
    "Skyline view from the Main Street bridge at sunset never gets old. Love this city.",
]
NEG = [
    "Traffic on I-95 through downtown Jacksonville is a nightmare every single day now.",
    "JEA bill went up again. How is anyone supposed to afford this in Jacksonville?",
    "Another shooting on the Westside last night. Jacksonville has to get a handle on crime.",
    "Rent in Jacksonville is out of control. My lease renewal jumped 20 percent.",
    "City Council wasted three hours arguing and passed nothing useful. Typical Jacksonville politics.",
    "Jaguars blew a 17 point lead. Same old Jags, I can't keep doing this.",
    "Potholes on Blanding are going to destroy my car. Does the city ever fix roads?",
    "JTA bus was 40 minutes late again. Transit in Jacksonville is unusable if you have a job.",
    "Flooding in San Marco after one afternoon storm. Drainage in this city is a joke.",
    "Property insurance in Duval County doubled. We are seriously thinking about leaving Jacksonville.",
    "DCPS closing more schools. The school board has completely lost the plot.",
    "Humidity in Jacksonville in August is unbearable. Why do we live here.",
]
NEU = [
    "Does anyone know when the Emerald Trail segment near LaVilla opens in Jacksonville?",
    "Looking for a good dentist near the beaches in Jacksonville, any recommendations?",
    "JEA board meets Tuesday to discuss the rate proposal.",
    "What time does the Riverside Arts Market open on Saturdays?",
    "City Council committee will take up the budget amendment next week.",
    "Is the Jacksonville airport parking garage back open after construction?",
    "Jaguars preseason schedule was released this morning.",
    "Anyone tried the new Vietnamese place on Beach Blvd in Jacksonville?",
    "How is the commute from Nocatee to downtown Jacksonville these days?",
    "Duval schools first day is August 11 this year.",
    "Which Jacksonville neighborhoods are considered walkable?",
    "Reminder that hurricane season runs through November in Jacksonville.",
]


def generate(conn, days=120, per_day=14, seed=7):
    rng = random.Random(seed)
    now = dt.datetime.now(dt.timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    i = 0
    for d in range(days, -1, -1):
        day = now - dt.timedelta(days=d)
        # Slow mood drift plus an "event" dip around day 40 and a bump around day 15.
        mood = 0.05 + 0.15 * (d / days) * (-1 if d % 2 == 0 else 1) * 0.3
        if 36 <= d <= 44:
            mood -= 0.35   # bad week (say, a rate hike vote)
        if 12 <= d <= 16:
            mood += 0.3    # good week (say, a playoff win and a festival)
        n = per_day + rng.randint(-5, 8)
        for _ in range(n):
            r = rng.random() + mood
            if r > 0.62:
                text, kind = rng.choice(POS), "pos"
            elif r < 0.33:
                text, kind = rng.choice(NEG), "neg"
            else:
                text, kind = rng.choice(NEU), "neu"
            source = "reddit" if rng.random() < 0.7 else "bluesky"
            ts = int((day + dt.timedelta(minutes=rng.randint(-700, 700))).timestamp())
            rows.append(dict(
                id=f"synthetic:{i}", source=source, subsource="fixture", kind="post",
                created_utc=ts, text=text, url=None, engagement=rng.randint(0, 40),
            ))
            i += 1
    inserted = db.insert_posts(conn, rows)
    db.set_meta(conn, "synthetic", "yes")
    return inserted
