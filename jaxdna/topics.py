"""Keyword-rule topic tagging. A post may carry several topics.

Rules are deliberately simple and editable. Each topic lists lowercase
substrings or regex patterns (prefixed with 're:'). Upgrade path: replace
with embedding clustering once volume justifies it.
"""
import re

TOPICS = {
    "downtown": ["downtown", "the landing", "riverfront", "urban core", "brooklyn", "lavilla", "springfield",
                 "san marco", "riverside", "five points", "elbow", "dia ", "four seasons", "shipyards", "emerald trail"],
    "jea_utilities": ["jea", "electric bill", "power bill", "water bill", "utility", "utilities", "power outage", "outage"],
    "schools_education": ["dcps", "duval schools", "duval county public schools", "school board", "teacher", "teachers",
                          "elementary", "middle school", "high school", "school closure", "school closures", "unf", "jacksonville university", " fscj", "edward waters"],
    "crime_safety": ["crime", "shooting", "shot ", "murder", "homicide", "robbery", "robbed", "stolen", "theft", "burglar",
                     "jso", "sheriff", "police", "unsafe", "dangerous", "carjack", "gang"],
    "traffic_roads": ["traffic", "i-95", "i95", "i-295", "i295", "i-10", "butler", "jtb", "blanding", "atlantic blvd",
                      "beach blvd", "pothole", "potholes", "construction", "road work", "roadwork", "commute", "drivers", "accident", "wreck", "fdot"],
    "transit_jta": ["jta", "bus ", "buses", "skyway", "u2c", "transit", "first coast flyer", "light rail", "bike lane", "bike lanes", "sidewalk", "sidewalks", "walkab"],
    "jaguars_sports": ["jaguars", "jags", "duuuval", "trevor lawrence", "everbank", "tiaa bank field", "stadium", "nfl", "jumbo shrimp",
                       "icemen", "armada", "florida-georgia", "gator bowl", "tailgat", "touchdown", "quarterback", "coach", "preseason", "playoffs"],
    "river_beaches_environment": ["st. johns", "st johns", "river", "beach", "beaches", "ocean", "intracoastal", "flood", "flooding",
                                  "septic", "algae", "manatee", "dolphin", "kayak", "hanna park", "timucuan", "preserve", "tree canopy", "trees"],
    "housing_cost": ["rent", "rents", "housing", "apartment", "apartments", "mortgage", "home prices", "house prices", "affordable",
                     "affordability", "hoa", "insurance", "property tax", "cost of living", "eviction", "homeless", "gentrif"],
    "politics_city_hall": ["city council", "councilman", "councilwoman", "council member", "mayor", "deegan", "city hall",
                           "ordinance", "budget", "millage", "election", "ballot", "referendum", "tallahassee", "desantis", "legislature", "amendment"],
    "weather_storms": ["hurricane", "tropical storm", "storm", "evacuat", "humidity", "humid", "heat index", "heat wave",
                       "thunderstorm", "lightning", "tornado", "rain", "flood watch", "cold front", "freeze"],
    "food_drink": ["restaurant", "restaurants", "brunch", "brewery", "breweries", "coffee", "bar ", "bars", "food truck", "michelin",
                   "james beard", "tacos", "bbq", "barbecue", "seafood", "pizza", "sushi", "cocktail", "dinner", "lunch"],
    "jobs_economy": ["jobs", "hiring", "layoff", "layoffs", "salary", "wages", "economy", "business", "startup", "headquarters",
                     "relocat", "jaxport", "port ", "logistics", "fintech", "fis ", "mayo clinic", "baptist health", "growth", "incentive"],
    "airport_travel": ["airport", "jia", " jax airport", "flight", "flights", "amtrak", "brightline", "tsa"],
    "arts_culture_events": ["concert", "festival", "museum", "moca", "cummer", "theatre", "theater", "art walk", "artwalk", "jazz fest",
                            "florida theatre", "daily's place", "dailys place", "amphitheat", "riverside arts market", "parade", "fireworks", "zoo"],
    "healthcare": ["hospital", "uf health", "er ", "emergency room", "clinic", "doctor", "healthcare", "health care", "mental health", "nurse"],
}

_STEMS = {"evacuat", "gentrif", "walkab", "tailgat", "amphitheat", "relocat"}
_COMPILED = {}
for topic, patterns in TOPICS.items():
    parts = []
    for p in patterns:
        if p.startswith("re:"):
            parts.append(p[3:])
        else:
            p = p.strip()
            esc = re.escape(p)
            # Word boundaries so 'er' does not match 'better' and 'unf' does not match 'unfair'.
            # A trailing boundary is skipped for stems meant to catch suffixes (evacuat, gentrif, walkab, tailgat, amphitheat, relocat).
            lead = r"\b" if p[0].isalnum() else ""
            trail = r"\b" if p[-1].isalnum() and p not in _STEMS else ""
            parts.append(lead + esc + trail)
    _COMPILED[topic] = re.compile("|".join(parts), re.IGNORECASE)


def tag(text):
    """Return list of topic names matching the text. Empty list means 'general'."""
    low = f" {text.lower()} "
    return [t for t, rx in _COMPILED.items() if rx.search(low)]


def tag_all(conn):
    """Tag every post that has no topic rows yet. Posts with no match get topic 'general'."""
    rows = conn.execute(
        "SELECT p.id, p.text FROM posts p LEFT JOIN post_topics t ON t.post_id = p.id WHERE t.post_id IS NULL"
    ).fetchall()
    out = []
    for r in rows:
        topics = tag(r["text"]) or ["general"]
        out.extend((r["id"], t) for t in topics)
    conn.executemany("INSERT OR IGNORE INTO post_topics (post_id, topic) VALUES (?,?)", out)
    conn.commit()
    return len(rows)


def retag_all(conn):
    """Wipe and recompute topics (use after editing TOPICS)."""
    conn.execute("DELETE FROM post_topics")
    conn.commit()
    return tag_all(conn)
