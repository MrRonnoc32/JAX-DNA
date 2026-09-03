"""Text cleaning and relevance filters."""
import re

URL_RE = re.compile(r"https?://\S+")
WS_RE = re.compile(r"\s+")


def clean_text(text):
    if not text:
        return ""
    text = URL_RE.sub("", text)
    text = text.replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
    return WS_RE.sub(" ", text).strip()


def keep(text, cfg):
    """Return True if the post should be stored."""
    if not text or len(text) < cfg.get("min_chars", 15):
        return False
    if text.lower() in ("[deleted]", "[removed]"):
        return False
    low = text.lower()
    for bad in cfg.get("exclude_if_contains", []):
        if bad in low:
            return False
    return True
