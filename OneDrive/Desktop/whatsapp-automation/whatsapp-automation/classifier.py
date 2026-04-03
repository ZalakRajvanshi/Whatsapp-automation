"""
Reply type classifier for WhatsApp recruitment replies.

Primary:  Grok API (xAI) — set GROK_API_KEY in config.py to enable.
Fallback: Keyword matching (~70-80% accuracy) — used when API key is blank.

Classifies each reply as:
  Positive — candidate is interested / wants more info
  Negative — candidate is declining / not available / not looking
  Neutral  — question, maybe, or anything unrecognised

Key rule for keyword fallback: NEGATIVE is checked first.
This handles polite declines like "great opportunity but I can't join" —
the decline intent wins even if positive words are also present.
"""

import re
import config


# ─────────────────────────────────────────────────────────────────────────────
# Keyword fallback lists (used only when GROK_API_KEY is not set)
# ─────────────────────────────────────────────────────────────────────────────

NEGATIVE_PHRASES = [
    # Can't join / not able
    "won't be able", "wont be able", "not able to join", "unable to join",
    "can't join", "cannot join", "cant join", "not in a position to",

    # Currently employed / just joined
    "currently working", "currently employed", "currently in a job",
    "already working", "just joined", "recently joined", "joined recently",
    "started recently", "new job",

    # Happy where they are
    "happy at current", "happy with current", "happy where i am",
    "happy in current", "content at current", "settled here", "settled at",
    "comfortable here",

    # Not looking / wrong time
    "not looking right now", "not actively looking", "not looking at the moment",
    "not currently looking", "not at this time", "not right now",
    "not the right time", "wrong time", "bad timing", "not a good time",

    # Maybe later (soft decline)
    "maybe later", "some other time", "another time", "next time",
    "some other opportunity", "pass for now", "pass on this",

    # Direct refusal
    "not interested", "not really interested", "no thanks", "no thank you",
    "not for me", "doesn't suit me", "not suitable", "not relevant",
    "decline", "declining", "have to decline", "must decline",

    # Not available
    "not available", "unavailable", "too busy", "busy right now",

    # Already have something
    "already have an offer", "got an offer", "already placed",
    "serving notice",

    # Hindi / informal
    "nahi", "nhi", "nahin", "mat bhejo",
    "please don't contact", "please stop", "remove me", "please remove",
    "unsubscribe",
]

NEGATIVE_WORDS = ["no", "nope", "pass"]  # checked with word boundary


POSITIVE_PHRASES = [
    # Direct yes
    "yes", "yeah", "yep", "yup", "sure", "sure thing", "of course",
    "absolutely", "definitely",

    # Interested
    "interested", "very interested", "quite interested",
    "sounds interesting", "looks interesting",

    # Wants more info (engagement = positive)
    "tell me more", "please share", "share more", "send details",
    "more details", "share the jd", "send the jd", "share jd",
    "job description", "send me", "share it",

    # Open to it
    "open to it", "open to this", "open to explore",
    "open to opportunities", "open for",

    # Wants to connect / talk
    "let's connect", "lets connect", "let's talk", "lets talk",
    "set up a call", "schedule a call", "when can we", "when can i",
    "happy to discuss", "happy to talk", "would love to", "love to",

    # Positive reactions
    "sounds good", "sounds great", "looks good", "looks great",
    "seems good", "great opportunity", "good opportunity",
    "please proceed", "go ahead", "proceed",

    # Hindi / informal
    "haan", "bilkul", "zaroor",
]

POSITIVE_WORDS = ["ok", "okay"]  # checked with word boundary


# ─────────────────────────────────────────────────────────────────────────────
# Keyword-based fallback
# ─────────────────────────────────────────────────────────────────────────────

def _classify_keywords(text: str) -> str:
    t = text.lower().strip()

    for phrase in NEGATIVE_PHRASES:
        if phrase in t:
            return config.REPLY_TYPE_NEGATIVE

    for word in NEGATIVE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", t):
            return config.REPLY_TYPE_NEGATIVE

    for phrase in POSITIVE_PHRASES:
        if phrase in t:
            return config.REPLY_TYPE_POSITIVE

    for word in POSITIVE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", t):
            return config.REPLY_TYPE_POSITIVE

    return config.REPLY_TYPE_NEUTRAL


# ─────────────────────────────────────────────────────────────────────────────
# Grok API classifier
# ─────────────────────────────────────────────────────────────────────────────

def _classify_grok(text: str) -> str:
    """
    Calls the Grok API to classify the reply.
    Returns Positive, Negative, or Neutral.
    Falls back to keyword classifier on any error.
    """
    try:
        from openai import OpenAI  # pip install openai
    except ImportError:
        print("[Classifier] 'openai' package not installed — pip install openai. Falling back to keywords.")
        return _classify_keywords(text)

    try:
        client = OpenAI(
            api_key=config.GROK_API_KEY,
            base_url="https://api.x.ai/v1",
        )

        system_prompt = (
            "You are a recruitment assistant. Classify the following WhatsApp reply "
            "from a job candidate into exactly one of these categories:\n"
            "  Positive  — candidate is interested, wants more info, or is open to the role\n"
            "  Negative  — candidate is declining, not available, not looking, or already employed\n"
            "  Neutral   — candidate asked a question, said maybe, or the intent is unclear\n\n"
            "Important: if the message contains any decline intent (e.g. 'good opportunity but "
            "I can't join right now'), classify it as Negative even if positive words appear.\n\n"
            "Reply with ONLY one word: Positive, Negative, or Neutral."
        )

        response = client.chat.completions.create(
            model=config.GROK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": text},
            ],
            max_tokens=5,
            temperature=0,
        )

        label = response.choices[0].message.content.strip().capitalize()

        if label in (config.REPLY_TYPE_POSITIVE, config.REPLY_TYPE_NEGATIVE, config.REPLY_TYPE_NEUTRAL):
            return label

        # Unexpected output — fall back
        print(f"[Classifier] Grok returned unexpected label '{label}' — falling back to keywords.")
        return _classify_keywords(text)

    except Exception as e:
        print(f"[Classifier] Grok API error: {e} — falling back to keywords.")
        return _classify_keywords(text)


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

def classify_reply(text: str) -> str:
    """
    Classify a WhatsApp reply as Positive, Negative, or Neutral.

    If multiple messages were received, join them before calling:
        classify_reply(" ".join(new_msgs))

    Uses Grok API when GROK_API_KEY is set in config.py.
    Falls back to keyword matching otherwise.

    Returns one of:
        config.REPLY_TYPE_POSITIVE  ("Positive")
        config.REPLY_TYPE_NEGATIVE  ("Negative")
        config.REPLY_TYPE_NEUTRAL   ("Neutral")
    """
    if not text:
        return config.REPLY_TYPE_NEUTRAL

    if config.GROK_API_KEY:
        return _classify_grok(text)

    return _classify_keywords(text)
