import json
import re
import sqlite3

import pandas as pd
import streamlit as st

from database import (
    initialize_database,
    load_latest_scan,
)

from content_database import (
    initialize_content_database,
    load_content_scan,
)


# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar Creative Playbook",
    page_icon="🧬",
    layout="wide",
)

initialize_database()
initialize_content_database()

DB_NAME = "flipradar.db"


# ==================================================
# HELPERS
# ==================================================

def safe_int(
    value,
    default=0,
):
    try:
        return int(
            float(
                value
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_float(
    value,
    default=0.0,
):
    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def normalize_text(
    value,
):
    return str(
        value
        or ""
    ).lower().strip()


def term_in_text(
    text,
    term,
):
    """
    Match a word / phrase without raw-substring false positives.

    Supports:
    - exact words and phrases
    - simple plural forms for single-word terms
    - hashtag compounds for meaningful single-word terms

    Examples:
    - "deal" matches "great deal"
    - "deal" does NOT match "dealing"
    - "supplement" matches "supplements"
    - "magnesium" matches "#magnesiumcomplex"
    """

    normalized_text = normalize_text(
        text
    )

    normalized_term = normalize_text(
        term
    )

    if not normalized_term:
        return False

    # ----------------------------------------------
    # Exact word / phrase match
    # ----------------------------------------------

    exact_pattern = (
        r"(?<![a-z0-9])"
        + re.escape(
            normalized_term
        )
        + r"(?![a-z0-9])"
    )

    if re.search(
        exact_pattern,
        normalized_text,
    ):
        return True

    # ----------------------------------------------
    # Extra handling only for single alphabetic words.
    #
    # Short terms are deliberately excluded from fuzzy
    # matching so words such as "deal" cannot match
    # "dealing".
    # ----------------------------------------------

    if (
        " " in normalized_term
        or not normalized_term.isalpha()
        or len(
            normalized_term
        ) < 5
    ):
        return False

    # ----------------------------------------------
    # Simple plural forms
    # ----------------------------------------------

    plural_forms = {
        normalized_term + "s",
        normalized_term + "es",
    }

    if normalized_term.endswith(
        "y"
    ) and len(
        normalized_term
    ) > 1:
        plural_forms.add(
            normalized_term[
                :-1
            ]
            + "ies"
        )

    for plural_form in plural_forms:
        plural_pattern = (
            r"(?<![a-z0-9])"
            + re.escape(
                plural_form
            )
            + r"(?![a-z0-9])"
        )

        if re.search(
            plural_pattern,
            normalized_text,
        ):
            return True

    # ----------------------------------------------
    # Hashtag compound support
    #
    # Examples:
    # #magnesiumcomplex
    # #magnesiumbenefits
    #
    # We require a fairly specific term length to avoid
    # broad accidental matches inside unrelated hashtags.
    # ----------------------------------------------

    if len(
        normalized_term
    ) >= 6:
        hashtag_pattern = (
            r"#"
            + re.escape(
                normalized_term
            )
            + r"[a-z0-9_]+"
        )

        if re.search(
            hashtag_pattern,
            normalized_text,
        ):
            return True

    return False


def contains_any(
    text,
    keywords,
):
    return any(
        term_in_text(
            text,
            keyword,
        )
        for keyword in keywords
    )


def normalize_list_like(
    value,
):
    if value is None:
        return []

    if isinstance(
        value,
        list,
    ):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    if isinstance(
        value,
        tuple,
    ):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    if isinstance(
        value,
        str,
    ):
        text = value.strip()

        if not text:
            return []

        try:
            decoded = json.loads(
                text
            )

            if isinstance(
                decoded,
                list,
            ):
                return normalize_list_like(
                    decoded
                )

        except Exception:
            pass

        pieces = re.split(
            r"[,|\s]+",
            text,
        )

        return [
            piece.strip().lstrip("#")
            for piece in pieces
            if piece.strip()
        ]

    return [
        str(
            value
        ).strip()
    ]


def extract_creator_id(
    video,
):
    """
    Recover the best available creator identifier from cached
    video data without making another API request.

    Different EchoTik responses can store creator identity under
    different keys or nested objects. We prefer stable IDs, then
    usernames/handles as a fallback.
    """

    id_keys = [
        "creator_user_id",
        "creator_id",
        "influencer_id",
        "author_id",
        "author_uid",
        "user_id",
        "uid",
        "sec_uid",
        "sec_user_id",
    ]

    username_keys = [
        "creator_username",
        "creator_name",
        "author_name",
        "author_unique_id",
        "unique_id",
        "username",
        "user_name",
        "handle",
        "nickname",
    ]

    container_keys = [
        "creator",
        "author",
        "influencer",
        "user",
        "account",
        "owner",
    ]

    def clean_value(
        value,
    ):
        if value in (
            None,
            "",
            0,
            "0",
        ):
            return ""

        if isinstance(
            value,
            (
                dict,
                list,
                tuple,
            ),
        ):
            return ""

        text = str(
            value
        ).strip()

        if not text:
            return ""

        return text

    # ----------------------------------------------
    # Direct stable IDs
    # ----------------------------------------------

    for key in id_keys:
        value = clean_value(
            video.get(
                key
            )
        )

        if value:
            return value

    # ----------------------------------------------
    # Scanner compatibility
    #
    # content_scanner.py stores the same creator user ID
    # in both "creator_user_id" and "creator". The latter
    # is a scalar in the cached dataset, not always a dict.
    # ----------------------------------------------

    scalar_creator = clean_value(
        video.get(
            "creator"
        )
    )

    if scalar_creator:
        return scalar_creator

    # ----------------------------------------------
    # Direct usernames / handles
    # ----------------------------------------------

    for key in username_keys:
        value = clean_value(
            video.get(
                key
            )
        )

        if value:
            return f"@{value.lstrip('@')}"

    # ----------------------------------------------
    # Known nested creator containers
    # ----------------------------------------------

    for container_key in container_keys:
        container = video.get(
            container_key
        )

        if not isinstance(
            container,
            dict,
        ):
            continue

        for key in (
            id_keys
            + [
                "id",
            ]
        ):
            value = clean_value(
                container.get(
                    key
                )
            )

            if value:
                return value

        for key in username_keys:
            value = clean_value(
                container.get(
                    key
                )
            )

            if value:
                return f"@{value.lstrip('@')}"

    # ----------------------------------------------
    # Recursive fallback
    #
    # Only treat a generic "id" as a creator ID when
    # it lives inside a creator-like container.
    # ----------------------------------------------

    def walk(
        value,
        parent_key="",
        depth=0,
    ):
        if depth > 4:
            return ""

        if isinstance(
            value,
            dict,
        ):
            parent_is_creator = any(
                token in parent_key.lower()
                for token in container_keys
            )

            for key in id_keys:
                found = clean_value(
                    value.get(
                        key
                    )
                )

                if found:
                    return found

            if parent_is_creator:
                found = clean_value(
                    value.get(
                        "id"
                    )
                )

                if found:
                    return found

            for key in username_keys:
                found = clean_value(
                    value.get(
                        key
                    )
                )

                if found:
                    return f"@{found.lstrip('@')}"

            for key, nested in value.items():
                if key in (
                    "product_id",
                    "video_id",
                    "item_id",
                ):
                    continue

                found = walk(
                    nested,
                    parent_key=str(
                        key
                    ),
                    depth=depth + 1,
                )

                if found:
                    return found

        elif isinstance(
            value,
            (
                list,
                tuple,
            ),
        ):
            for nested in value:
                found = walk(
                    nested,
                    parent_key=parent_key,
                    depth=depth + 1,
                )

                if found:
                    return found

        return ""

    return walk(
        video
    )


def extract_creator_label(
    video,
    creator_key="",
):
    """
    Prefer a cached TikTok username, then creator name,
    then fall back to the stable creator key.
    """

    username = str(
        video.get(
            "creator_username",
            ""
        )
        or ""
    ).strip()

    if username:
        return f"@{username.lstrip('@')}"

    name = str(
        video.get(
            "creator_name",
            ""
        )
        or ""
    ).strip()

    if name:
        return name

    creator_key = str(
        creator_key
        or ""
    ).strip()

    return (
        creator_key
        if creator_key
        else "Unknown creator"
    )


# ==================================================
# MANUAL REVIEW LOADER
# ==================================================

def load_review(
    product_id,
    video_id,
):
    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                hooks_json,
                selling_angles_json,
                formats_json,
                details_json,
                notes,
                reviewed_at
            FROM creative_reviews
            WHERE product_id = ?
            AND video_id = ?
            """,
            (
                str(
                    product_id
                ),
                str(
                    video_id
                ),
            ),
        )

        row = cursor.fetchone()

    except sqlite3.OperationalError:
        row = None

    finally:
        conn.close()

    if not row:
        return None

    return {
        "hooks":
            json.loads(
                row[0]
                or "[]"
            ),

        "selling_angles":
            json.loads(
                row[1]
                or "[]"
            ),

        "formats":
            json.loads(
                row[2]
                or "[]"
            ),

        "details":
            json.loads(
                row[3]
                or "[]"
            ),

        "notes":
            row[4]
            or "",

        "reviewed_at":
            row[5],
    }


# ==================================================
# CAPTION RULES
# ==================================================

HOOK_RULES = {
    "👀 Curiosity / Pattern Interrupt": [
        "wait",
        "secret",
        "unlocked",
        "weird",
        "interesting",
        "makes sense",
        "happened again",
        "what happens",
        "crazy",
        "listen up",
    ],

    "😱 Shock / Reaction": [
        "omg",
        "oh my god",
        "literally",
        "no way",
        "insane",
        "shocked",
        "obsessed",
        "wow",
    ],

    "💬 Comment Reply": [
        "replying to",
        "reply to",
        "responding to",
    ],

    "🎯 Direct Claim": [
        "best",
        "this works",
        "it works",
        "so good",
        "soo good",
        "10/10",
        "must have",
        "game changer",
        "best perfume",
    ],

    "⏰ Urgency / Offer Hook": [
        "right now",
        " rn",
        "deal",
        "sale",
        "discount",
        "coupon",
        "black friday",
        "cyber monday",
        "limited time",
    ],
}


SELLING_RULES = {
    "❤️ Testimonial / Personal Proof": [
        "i love",
        "love this",
        "love it",
        "obsessed",
        "i swear",
        "i tried",
        "i use",
        "favorite",
        "fave",
        "10/10",
        "so good",
        "soo good",
        "literally",
        "best perfume",
    ],

    "😍 Attraction / Partner Reaction": [
        "he's so obsessed",
        "he’s so obsessed",
        "he will",
        "boyfriend",
        "husband",
        "girlfriend",
        "wife",
        "partner",
        "crawling",
        "crawwwling",
        "attract",
        "date night",
        "compliment",
    ],

    "✨ Transformation / Desired Result": [
        "before",
        "after",
        "results",
        "transformation",
        "hair growth",
        "long hair",
        "thick hair",
        "inches",
        "silk press",
        "glow",
    ],

    "🧪 Problem → Solution": [
        "works",
        "worked",
        "fix",
        "solution",
        "problem",
        "helped",
        "finally",
        "frizz",
        "damage",
        "dry hair",
        "thin hair",
        "hair growth",
    ],

    "💸 Deal / Value": [
        "deal",
        "sale",
        "discount",
        "coupon",
        "price",
        "cheap",
        "affordable",
        "black friday",
        "cyber monday",
        "bundle",
    ],

    "🎯 Identity / Audience": [
        "curly hair",
        "natural hair",
        "silk press",
        "moms",
        "women",
        "men",
    ],

    "📚 Education / Ingredient Story": [
        "why",
        "how",
        "ingredient",
        "science",
        "rosemary",
        "rice water",
        "makes sense",
        "interesting",
    ],

    "🔥 Viral / Social Proof": [
        "viral",
        "everyone",
        "tiktok shop",
        "creator picks",
        "best seller",
        "sold out",
        "trending",
        "hype",
    ],
}


FORMAT_RULES = {
    "💬 Comment Reply": [
        "replying to",
        "reply to",
    ],

    "🎥 Tutorial / Demo": [
        "how to",
        "tutorial",
        "routine",
        "step by step",
        "part 2",
        "pt 2",
        "demo",
    ],

    "🧾 Recommendation / Review": [
        "i love",
        "love this",
        "10/10",
        "best",
        "favorite",
        "obsessed",
        "i swear",
        "so good",
        "soo good",
    ],

    "📚 Educational / Explanation": [
        "why",
        "because",
        "interesting",
        "makes sense",
        "ingredient",
        "science",
    ],

    "💸 Offer / Promotion": [
        "deal",
        "sale",
        "discount",
        "coupon",
        "black friday",
        "cyber monday",
    ],

    "😱 Reaction / Story": [
        "omg",
        "happened again",
        "weird",
        "literally",
        "no way",
        "crazy",
    ],
}


# ==================================================
# CLASSIFICATION
# ==================================================

def detect_labels(
    caption,
    rules,
):
    text = normalize_text(
        caption
    )

    labels = []

    for label, keywords in rules.items():
        if contains_any(
            text,
            keywords,
        ):
            labels.append(
                label
            )

    return labels


def automatic_hooks(
    caption,
):
    result = detect_labels(
        caption,
        HOOK_RULES,
    )

    return (
        result
        if result
        else [
            "❓ Hook Unclear"
        ]
    )


def automatic_angles(
    caption,
):
    result = detect_labels(
        caption,
        SELLING_RULES,
    )

    return (
        result
        if result
        else [
            "❓ Selling Angle Unclear"
        ]
    )


def automatic_formats(
    caption,
):
    result = detect_labels(
        caption,
        FORMAT_RULES,
    )

    return (
        result
        if result
        else [
            "❓ Format Unknown"
        ]
    )


def manual_first(
    review,
    key,
    fallback,
):
    if (
        review
        and review.get(
            key
        )
    ):
        return (
            review[
                key
            ],
            "👁️ Manual",
        )

    return (
        fallback,
        "🤖 Caption",
    )


# ==================================================
# AUDIENCE INTELLIGENCE RULES
#
# These are intentionally NON-demographic.
# FlipRadar is inferring shopping interests, use cases,
# and purchase triggers from cached content and attributed
# sales. It is NOT claiming verified purchaser demographics.
# ==================================================

AUDIENCE_THEME_RULES = {
    "💇 Hair-care / hair-growth shoppers": [
        "hair",
        "hair growth",
        "rosemary",
        "rice water",
        "scalp",
        "silk press",
        "curly",
        "roots",
        "hairline",
        "thickening",
    ],

    "💄 Beauty / self-care shoppers": [
        "beauty",
        "makeup",
        "lip",
        "gloss",
        "concealer",
        "serum",
        "skincare",
        "skin",
        "perfume",
        "fragrance",
        "pdrn",
    ],

    "🧘 Wellness / stress-management shoppers": [
        "wellness",
        "stress",
        "stressed",
        "cortisol",
        "calm",
        "relax",
        "relaxation",
        "anxiety",
        "frustrating",
        "burnout",
        "tension",
    ],

    "🌙 Sleep / recovery shoppers": [
        "sleep",
        "sleeping",
        "bedtime",
        "night",
        "rest",
        "recovery",
        "recover",
        "tired",
        "fatigue",
    ],

    "💊 Supplement / daily-wellness shoppers": [
        "supplement",
        "magnesium",
        "vitamin",
        "capsule",
        "capsules",
        "gummy",
        "gummies",
        "daily",
        "take every day",
        "i take",
        "complex",
    ],

    "⚡ Energy / performance shoppers": [
        "energy",
        "performance",
        "workout",
        "gym",
        "pre workout",
        "protein",
        "coffee",
        "focus",
        "productive",
        "productivity",
        "boost",
    ],

    "🧠 Focus / productivity shoppers": [
        "focus",
        "focused",
        "concentration",
        "brain",
        "mental clarity",
        "productive",
        "productivity",
        "work",
        "study",
    ],

    "👜 Fashion / accessory shoppers": [
        "hoodie",
        "bag",
        "keychain",
        "charm",
        "accessory",
        "outfit",
        "clothing",
        "fashion",
        "strap",
        "pendant",
    ],

    "🧸 Collectible / novelty shoppers": [
        "squishy",
        "keychain",
        "collect",
        "all the colors",
        "need them all",
        "cute",
        "mini",
        "advent calendar",
        "toy",
    ],

    "💸 Deal / value seekers": [
        "deal",
        "sale",
        "discount",
        "coupon",
        "cheap",
        "affordable",
        "black friday",
        "cyber monday",
        "bundle",
        "free shipping",
    ],

    "⏰ Restock / scarcity responders": [
        "they're back",
        "theyre back",
        "back in stock",
        "restock",
        "restocked",
        "sold out",
        "sell out",
        "selling out",
        "going to sell out",
        "last chance",
        "limited",
        "finally",
    ],

    "✨ Results / transformation shoppers": [
        "before",
        "after",
        "results",
        "transformation",
        "grow",
        "growth",
        "long",
        "thick",
        "glow",
        "result",
    ],

    "🧪 Problem-solving shoppers": [
        "problem",
        "solution",
        "fix",
        "works",
        "worked",
        "works for me",
        "helped",
        "helped me",
        "struggling",
        "struggling with",
        "dealing with",
        "damage",
        "dry",
        "frizz",
    ],

    "🎁 Gift / occasion shoppers": [
        "gift",
        "christmas",
        "holiday",
        "stocking",
        "occasion",
        "birthday",
        "advent",
    ],

    "⚡ Convenience / everyday-use shoppers": [
        "easy",
        "everyday",
        "daily",
        "on the go",
        "portable",
        "quick",
        "seconds",
        "no mess",
    ],
}


HIGH_INTENT_PHRASES = [
    "they're back",
    "theyre back",
    "back in stock",
    "restock",
    "restocked",
    "sold out",
    "sell out",
    "selling out",
    "going to sell out",
    "right now",
    "last chance",
    "limited time",
    "finally",
    "need them all",
    "ordered",
    "all the colors",
    "must have",
    "deal",
    "sale",
    "discount",
    "coupon",
    "love this",
    "obsessed",
    "helped me",
    "works for me",
    "worked for me",
    "i take",
    "i use",
    "struggling with",
    "dealing with",
    "results",
    "result",
]


def audience_text_for_video(
    caption,
    hashtags,
):
    """
    Content evidence only.

    Product-name context is intentionally kept separate so one
    keyword in the product title cannot make every sampled video
    look like evidence for the same audience theme.
    """

    hashtag_text = " ".join(
        normalize_list_like(
            hashtags
        )
    )

    return normalize_text(
        " ".join(
            [
                str(
                    caption
                    or ""
                ),
                hashtag_text,
            ]
        )
    )


def detect_audience_theme_evidence(
    text,
):
    evidence = {}

    for theme, keywords in AUDIENCE_THEME_RULES.items():
        matched = []

        for keyword in keywords:
            if term_in_text(
                text,
                keyword,
            ):
                matched.append(
                    keyword
                )

        if matched:
            evidence[
                theme
            ] = sorted(
                set(
                    matched
                )
            )

    return evidence


def detect_audience_themes(
    text,
):
    return list(
        detect_audience_theme_evidence(
            text
        ).keys()
    )


def detect_high_intent_phrases(
    caption,
):
    text = normalize_text(
        caption
    )

    matched = []

    # Longest phrases first so more specific language wins.
    for phrase in sorted(
        HIGH_INTENT_PHRASES,
        key=len,
        reverse=True,
    ):
        if not term_in_text(
            text,
            phrase,
        ):
            continue

        # Avoid duplicate singular/plural reporting such as
        # both "result" and "results" from the same caption.
        duplicate = False

        for existing in matched:
            if (
                phrase + "s"
                == existing
                or phrase + "es"
                == existing
                or existing + "s"
                == phrase
                or existing + "es"
                == phrase
            ):
                duplicate = True
                break

        if not duplicate:
            matched.append(
                phrase
            )

    return matched


def truncate_text(
    value,
    limit=180,
):
    text = " ".join(
        str(
            value
            or ""
        ).split()
    )

    if len(
        text
    ) <= limit:
        return text

    return (
        text[
            : limit - 1
        ].rstrip()
        + "…"
    )


# ==================================================
# HEADER
# ==================================================

st.title(
    "🧬 Creative Playbook"
)

st.caption(
    "Turn FlipRadar's content data into a practical "
    "creative hypothesis for the product."
)

st.info(
    "This page uses cached content plus any saved manual visual reviews. "
    "It uses **zero EchoTik API requests**."
)


# ==================================================
# LOAD PRODUCTS
# ==================================================

products, market_scan_time = (
    load_latest_scan()
)

if not products:
    st.warning(
        "No saved products exist yet."
    )

    st.stop()


# ==================================================
# ONLY SHOW CONTENT-SCANNED PRODUCTS
# ==================================================

scanned_products = []

for product in products:
    videos, scanned_at = (
        load_content_scan(
            str(
                product[
                    "id"
                ]
            )
        )
    )

    if videos:
        scanned_products.append(
            product
        )


if not scanned_products:
    st.warning(
        "No products have a cached Content Deep Scan yet."
    )

    st.stop()


product_names = [
    product[
        "name"
    ]
    for product in scanned_products
]


selected_name = st.selectbox(
    "Choose a product",
    product_names,
)


selected_product = next(
    product
    for product in scanned_products
    if product[
        "name"
    ] == selected_name
)


product_id = str(
    selected_product[
        "id"
    ]
)


videos, content_scan_time = (
    load_content_scan(
        product_id
    )
)


st.write(
    f"**Product ID:** `{product_id}`"
)


# ==================================================
# BUILD EFFECTIVE DATASET
# ==================================================

rows = []

for video in videos:
    video_id = str(
        video.get(
            "video_id",
            "",
        )
    )

    caption = str(
        video.get(
            "caption",
            "",
        )
        or ""
    )

    hashtags = (
        video.get(
            "hashtags",
            []
        )
        or []
    )

    creator_id = extract_creator_id(
        video
    )

    creator_label = extract_creator_label(
        video,
        creator_id,
    )

    views = safe_int(
        video.get(
            "views",
            0,
        )
    )

    sales = safe_int(
        video.get(
            "video_sales",
            0,
        )
    )

    gmv = safe_float(
        video.get(
            "video_gmv",
            0,
        )
    )

    review = load_review(
        product_id,
        video_id,
    )

    hooks, hook_source = manual_first(
        review,
        "hooks",
        automatic_hooks(
            caption
        ),
    )

    angles, angle_source = manual_first(
        review,
        "selling_angles",
        automatic_angles(
            caption
        ),
    )

    formats, format_source = manual_first(
        review,
        "formats",
        automatic_formats(
            caption
        ),
    )

    efficiency = (
        (
            sales
            / views
        ) * 1000
        if views > 0
        else 0
    )

    audience_text = (
        audience_text_for_video(
            caption,
            hashtags,
        )
    )

    theme_evidence = (
        detect_audience_theme_evidence(
            audience_text
        )
    )

    audience_themes = list(
        theme_evidence.keys()
    )

    intent_phrases = (
        detect_high_intent_phrases(
            caption
        )
    )

    rows.append(
        {
            "Video ID":
                video_id,

            "Creator Key":
                creator_id,

            "Creator Label":
                creator_label,

            "Caption":
                caption,

            "Hashtags":
                normalize_list_like(
                    hashtags
                ),

            "Views":
                views,

            "Sales":
                sales,

            "GMV":
                gmv,

            "Sales / 1K":
                efficiency,

            "Hooks":
                hooks,

            "Angles":
                angles,

            "Formats":
                formats,

            "Hook Source":
                hook_source,

            "Angle Source":
                angle_source,

            "Format Source":
                format_source,

            "Reviewed":
                review is not None,

            "Details":
                (
                    review[
                        "details"
                    ]
                    if review
                    else []
                ),

            "Notes":
                (
                    review[
                        "notes"
                    ]
                    if review
                    else ""
                ),

            "Audience Themes":
                audience_themes,

            "Theme Evidence":
                theme_evidence,

            "Intent Phrases":
                intent_phrases,
        }
    )


video_df = pd.DataFrame(
    rows
)


# ==================================================
# DATA COVERAGE
# ==================================================

total_views = int(
    video_df[
        "Views"
    ].sum()
)

total_sales = int(
    video_df[
        "Sales"
    ].sum()
)

total_gmv = float(
    video_df[
        "GMV"
    ].sum()
)


reviewed_df = video_df[
    video_df[
        "Reviewed"
    ]
]


manual_sales = int(
    reviewed_df[
        "Sales"
    ].sum()
)


manual_views = int(
    reviewed_df[
        "Views"
    ].sum()
)


manual_count = len(
    reviewed_df
)


sales_coverage = (
    (
        manual_sales
        / total_sales
    ) * 100
    if total_sales > 0
    else 0
)


views_coverage = (
    (
        manual_views
        / total_views
    ) * 100
    if total_views > 0
    else 0
)


if sales_coverage >= 50:
    confidence = (
        "🟢 Stronger Manual Evidence"
    )

elif sales_coverage >= 20:
    confidence = (
        "🟡 Moderate Manual Evidence"
    )

elif sales_coverage > 0:
    confidence = (
        "🟠 Early Manual Evidence"
    )

else:
    confidence = (
        "⚪ Caption-Only Evidence"
    )


# ==================================================
# TOP METRICS
# ==================================================

st.divider()

m1, m2, m3, m4, m5 = st.columns(
    5
)

m1.metric(
    "Videos",
    len(
        video_df
    ),
)

m2.metric(
    "Sampled Views",
    f"{total_views:,}",
)

m3.metric(
    "Attributed Sales",
    f"{total_sales:,}",
)

m4.metric(
    "Manual Reviews",
    manual_count,
)

m5.metric(
    "Manual Sales Coverage",
    f"{sales_coverage:.1f}%",
)


st.write(
    f"**Evidence confidence:** {confidence}"
)

st.caption(
    f"Manual reviews cover {views_coverage:.1f}% of sampled views. "
    "Until more videos are reviewed, some conclusions still depend "
    "on caption-based heuristics."
)


# ==================================================
# DIMENSION SUMMARY
# ==================================================

def summarize(
    column_name,
):
    summary_rows = []

    all_labels = set()

    for values in video_df[
        column_name
    ]:
        for label in values:
            all_labels.add(
                label
            )

    for label in all_labels:
        matching = video_df[
            video_df[
                column_name
            ].apply(
                lambda values:
                    label in values
            )
        ]

        views = int(
            matching[
                "Views"
            ].sum()
        )

        sales = int(
            matching[
                "Sales"
            ].sum()
        )

        gmv = float(
            matching[
                "GMV"
            ].sum()
        )

        efficiency = (
            (
                sales
                / views
            ) * 1000
            if views > 0
            else 0
        )

        summary_rows.append(
            {
                "Label":
                    label,

                "Videos":
                    len(
                        matching
                    ),

                "Views":
                    views,

                "Sales":
                    sales,

                "GMV":
                    gmv,

                "Sales / 1K":
                    efficiency,

                "Manual Reviews":
                    int(
                        matching[
                            "Reviewed"
                        ].sum()
                    ),
            }
        )

    return pd.DataFrame(
        summary_rows
    )


hook_summary = summarize(
    "Hooks"
)

angle_summary = summarize(
    "Angles"
)

format_summary = summarize(
    "Formats"
)


def usable_summary(
    dataframe,
):
    if dataframe.empty:
        return dataframe

    result = dataframe[
        ~dataframe[
            "Label"
        ].str.contains(
            "Unclear|Unknown",
            case=False,
            regex=True,
        )
    ].copy()

    if result.empty:
        return dataframe

    return result


clean_hooks = usable_summary(
    hook_summary
)

clean_angles = usable_summary(
    angle_summary
)

clean_formats = usable_summary(
    format_summary
)


# ==================================================
# TOP SIGNALS
# ==================================================

top_hook = (
    clean_hooks
    .sort_values(
        "Sales",
        ascending=False,
    )
    .iloc[
        0
    ]
    if not clean_hooks.empty
    else None
)


top_angle = (
    clean_angles
    .sort_values(
        "Sales",
        ascending=False,
    )
    .iloc[
        0
    ]
    if not clean_angles.empty
    else None
)


top_format = (
    clean_formats
    .sort_values(
        "Sales",
        ascending=False,
    )
    .iloc[
        0
    ]
    if not clean_formats.empty
    else None
)


# ==================================================
# COMBINATIONS
# ==================================================

combo_rows = []

for _, row in video_df.iterrows():
    for hook in row[
        "Hooks"
    ]:
        for angle in row[
            "Angles"
        ]:
            combo_rows.append(
                {
                    "Hook":
                        hook,

                    "Selling Angle":
                        angle,

                    "Views":
                        row[
                            "Views"
                        ],

                    "Sales":
                        row[
                            "Sales"
                        ],

                    "GMV":
                        row[
                            "GMV"
                        ],

                    "Video":
                        row[
                            "Video ID"
                        ],
                }
            )


combo_df = pd.DataFrame(
    combo_rows
)


if not combo_df.empty:
    combo_summary = (
        combo_df
        .groupby(
            [
                "Hook",
                "Selling Angle",
            ],
            as_index=False,
        )
        .agg(
            {
                "Views":
                    "sum",

                "Sales":
                    "sum",

                "GMV":
                    "sum",

                "Video":
                    "count",
            }
        )
    )

    combo_summary = combo_summary.rename(
        columns={
            "Video":
                "Videos"
        }
    )

    combo_summary[
        "Sales / 1K"
    ] = combo_summary.apply(
        lambda row:
            (
                row[
                    "Sales"
                ]
                / row[
                    "Views"
                ]
            ) * 1000
            if row[
                "Views"
            ] > 0
            else 0,
        axis=1,
    )

    usable_combos = combo_summary[
        ~combo_summary[
            "Hook"
        ].str.contains(
            "Unclear",
            case=False,
            regex=False,
        )
        &
        ~combo_summary[
            "Selling Angle"
        ].str.contains(
            "Unclear",
            case=False,
            regex=False,
        )
    ].copy()

    if usable_combos.empty:
        usable_combos = (
            combo_summary.copy()
        )

    top_combo = (
        usable_combos
        .sort_values(
            [
                "Sales",
                "Views",
            ],
            ascending=False,
        )
        .iloc[
            0
        ]
    )

else:
    combo_summary = pd.DataFrame()
    top_combo = None


# ==================================================
# AUDIENCE INTELLIGENCE
# ==================================================

# --------------------------------------------------
# PRODUCT-CONTEXT THEMES
#
# These are context clues only. They are not counted as
# video-level evidence unless captions / hashtags support them.
# --------------------------------------------------

product_context_text = normalize_text(
    selected_product.get(
        "name",
        ""
    )
)

product_context_evidence = (
    detect_audience_theme_evidence(
        product_context_text
    )
)

product_context_themes = list(
    product_context_evidence.keys()
)


# --------------------------------------------------
# SALES-WEIGHTED CONTENT THEMES
# --------------------------------------------------

audience_rows = []

all_audience_themes = set()

for themes in video_df[
    "Audience Themes"
]:
    for theme in themes:
        all_audience_themes.add(
            theme
        )


for theme in all_audience_themes:
    matching = video_df[
        video_df[
            "Audience Themes"
        ].apply(
            lambda values:
                theme in values
        )
    ]

    theme_views = int(
        matching[
            "Views"
        ].sum()
    )

    theme_sales = int(
        matching[
            "Sales"
        ].sum()
    )

    theme_gmv = float(
        matching[
            "GMV"
        ].sum()
    )

    creator_values = [
        creator_key
        for creator_key in matching[
            "Creator Key"
        ].tolist()
        if str(
            creator_key
        ).strip()
    ]

    evidence_sales = {}

    for _, evidence_row in matching.iterrows():
        evidence_map = (
            evidence_row[
                "Theme Evidence"
            ]
            or {}
        )

        for term in evidence_map.get(
            theme,
            [],
        ):
            evidence_sales[
                term
            ] = (
                evidence_sales.get(
                    term,
                    0,
                )
                + int(
                    evidence_row[
                        "Sales"
                    ]
                )
            )

    strongest_terms = [
        term
        for term, _ in sorted(
            evidence_sales.items(),
            key=lambda item:
                (
                    item[
                        1
                    ],
                    item[
                        0
                    ],
                ),
            reverse=True,
        )[
            :5
        ]
    ]

    evidence_ranked = matching.sort_values(
        [
            "Sales",
            "Views",
        ],
        ascending=[
            False,
            False,
        ],
    )

    if not evidence_ranked.empty:
        strongest_video = (
            evidence_ranked.iloc[
                0
            ]
        )

        strongest_caption = truncate_text(
            strongest_video[
                "Caption"
            ],
            limit=180,
        )

        strongest_video_sales = int(
            strongest_video[
                "Sales"
            ]
        )

        strongest_video_views = int(
            strongest_video[
                "Views"
            ]
        )

    else:
        strongest_caption = ""
        strongest_video_sales = 0
        strongest_video_views = 0

    audience_rows.append(
        {
            "Audience Theme":
                theme,

            "Videos":
                len(
                    matching
                ),

            "Creators":
                len(
                    set(
                        creator_values
                    )
                ),

            "Views":
                theme_views,

            "Attributed Sales":
                theme_sales,

            "Attributed GMV":
                theme_gmv,

            "Sales / 1K":
                (
                    (
                        theme_sales
                        / theme_views
                    ) * 1000
                    if theme_views > 0
                    else 0
                ),

            "Sales Share":
                (
                    (
                        theme_sales
                        / total_sales
                    ) * 100
                    if total_sales > 0
                    else 0
                ),

            "Evidence Terms":
                strongest_terms,

            "Top Evidence Caption":
                strongest_caption,

            "Top Evidence Sales":
                strongest_video_sales,

            "Top Evidence Views":
                strongest_video_views,
        }
    )


audience_df = pd.DataFrame(
    audience_rows
)


if not audience_df.empty:
    audience_df = (
        audience_df
        .sort_values(
            [
                "Attributed Sales",
                "Views",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )


# ==================================================
# BUYING-TRIGGER LANGUAGE
# ==================================================

intent_rows = []

all_intent_phrases = set()

for phrases in video_df[
    "Intent Phrases"
]:
    for phrase in phrases:
        all_intent_phrases.add(
            phrase
        )


for phrase in all_intent_phrases:
    matching = video_df[
        video_df[
            "Intent Phrases"
        ].apply(
            lambda values:
                phrase in values
        )
    ]

    phrase_views = int(
        matching[
            "Views"
        ].sum()
    )

    phrase_sales = int(
        matching[
            "Sales"
        ].sum()
    )

    phrase_gmv = float(
        matching[
            "GMV"
        ].sum()
    )

    evidence_ranked = matching.sort_values(
        [
            "Sales",
            "Views",
        ],
        ascending=[
            False,
            False,
        ],
    )

    top_caption = (
        truncate_text(
            evidence_ranked.iloc[
                0
            ][
                "Caption"
            ],
            limit=160,
        )
        if not evidence_ranked.empty
        else ""
    )

    intent_rows.append(
        {
            "Phrase":
                phrase,

            "Videos":
                len(
                    matching
                ),

            "Views":
                phrase_views,

            "Attributed Sales":
                phrase_sales,

            "Attributed GMV":
                phrase_gmv,

            "Sales / 1K":
                (
                    (
                        phrase_sales
                        / phrase_views
                    ) * 1000
                    if phrase_views > 0
                    else 0
                ),

            "Top Evidence Caption":
                top_caption,
        }
    )


intent_df = pd.DataFrame(
    intent_rows
)


if not intent_df.empty:
    intent_df = (
        intent_df
        .sort_values(
            [
                "Attributed Sales",
                "Views",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )


# ==================================================
# SALES-WEIGHTED CREATOR CONCENTRATION
# ==================================================

creator_evidence = video_df[
    video_df[
        "Creator Key"
    ].astype(
        str
    ).str.strip() != ""
].copy()


if not creator_evidence.empty:
    creator_summary = (
        creator_evidence
        .groupby(
            "Creator Key",
            as_index=False,
        )
        .agg(
            {
                "Creator Label":
                    "first",

                "Video ID":
                    "count",

                "Views":
                    "sum",

                "Sales":
                    "sum",

                "GMV":
                    "sum",
            }
        )
        .rename(
            columns={
                "Video ID":
                    "Videos",

                "Sales":
                    "Attributed Sales",

                "GMV":
                    "Attributed GMV",
            }
        )
        .sort_values(
            "Attributed Sales",
            ascending=False,
        )
        .reset_index(
            drop=True
        )
    )

    resolved_creator_sales = int(
        creator_summary[
            "Attributed Sales"
        ].sum()
    )

    unique_creators = len(
        creator_summary
    )

    creator_video_coverage = len(
        creator_evidence
    )

    creator_video_coverage_pct = (
        (
            creator_video_coverage
            / len(
                video_df
            )
        ) * 100
        if len(
            video_df
        ) > 0
        else 0
    )

    top_creator_sales = (
        int(
            creator_summary.iloc[
                0
            ][
                "Attributed Sales"
            ]
        )
        if unique_creators > 0
        else 0
    )

    top_three_creator_sales = int(
        creator_summary.head(
            3
        )[
            "Attributed Sales"
        ].sum()
    )

    top_creator_share = (
        (
            top_creator_sales
            / resolved_creator_sales
        ) * 100
        if resolved_creator_sales > 0
        else 0
    )

    top_three_creator_share = (
        (
            top_three_creator_sales
            / resolved_creator_sales
        ) * 100
        if resolved_creator_sales > 0
        else 0
    )

else:
    creator_summary = pd.DataFrame()
    resolved_creator_sales = 0
    unique_creators = 0
    creator_video_coverage = 0
    creator_video_coverage_pct = 0
    top_creator_share = 0
    top_three_creator_share = 0


# ==================================================
# CREATOR × AUDIENCE BREAKDOWN
# ==================================================

creator_theme_rows = []

for _, row in video_df.iterrows():
    creator_key = str(
        row[
            "Creator Key"
        ]
        or ""
    ).strip()

    if not creator_key:
        continue

    creator_label = str(
        row[
            "Creator Label"
        ]
        or creator_key
    ).strip()

    for theme in row[
        "Audience Themes"
    ]:
        creator_theme_rows.append(
            {
                "Creator Key":
                    creator_key,

                "Creator":
                    creator_label,

                "Audience Theme":
                    theme,

                "Video ID":
                    row[
                        "Video ID"
                    ],

                "Views":
                    int(
                        row[
                            "Views"
                        ]
                    ),

                "Sales":
                    int(
                        row[
                            "Sales"
                        ]
                    ),

                "GMV":
                    float(
                        row[
                            "GMV"
                        ]
                    ),
            }
        )


creator_theme_raw = pd.DataFrame(
    creator_theme_rows
)


if not creator_theme_raw.empty:
    creator_theme_summary = (
        creator_theme_raw
        .groupby(
            [
                "Creator Key",
                "Creator",
                "Audience Theme",
            ],
            as_index=False,
        )
        .agg(
            {
                "Video ID":
                    "count",

                "Views":
                    "sum",

                "Sales":
                    "sum",

                "GMV":
                    "sum",
            }
        )
        .rename(
            columns={
                "Video ID":
                    "Videos",

                "Sales":
                    "Attributed Sales",

                "GMV":
                    "Attributed GMV",
            }
        )
    )

else:
    creator_theme_summary = pd.DataFrame()


# --------------------------------------------------
# PRIMARY + SECONDARY THEME BY CREATOR
# --------------------------------------------------

creator_profile_rows = []

if not creator_summary.empty:
    for _, creator_row in creator_summary.iterrows():
        creator_key = str(
            creator_row[
                "Creator Key"
            ]
        )

        theme_slice = (
            creator_theme_summary[
                creator_theme_summary[
                    "Creator Key"
                ] == creator_key
            ]
            .sort_values(
                [
                    "Attributed Sales",
                    "Views",
                ],
                ascending=[
                    False,
                    False,
                ],
            )
            if not creator_theme_summary.empty
            else pd.DataFrame()
        )

        primary_theme = (
            str(
                theme_slice.iloc[
                    0
                ][
                    "Audience Theme"
                ]
            )
            if len(
                theme_slice
            ) >= 1
            else "Unclassified"
        )

        secondary_theme = (
            str(
                theme_slice.iloc[
                    1
                ][
                    "Audience Theme"
                ]
            )
            if len(
                theme_slice
            ) >= 2
            else ""
        )

        creator_sales = int(
            creator_row[
                "Attributed Sales"
            ]
        )

        creator_profile_rows.append(
            {
                "Creator":
                    str(
                        creator_row[
                            "Creator Label"
                        ]
                    ),

                "Creator Key":
                    creator_key,

                "Videos":
                    int(
                        creator_row[
                            "Videos"
                        ]
                    ),

                "Views":
                    int(
                        creator_row[
                            "Views"
                        ]
                    ),

                "Attributed Sales":
                    creator_sales,

                "Attributed GMV":
                    float(
                        creator_row[
                            "Attributed GMV"
                        ]
                    ),

                "Sales Share":
                    (
                        (
                            creator_sales
                            / total_sales
                        ) * 100
                        if total_sales > 0
                        else 0
                    ),

                "Primary Audience Theme":
                    primary_theme,

                "Secondary Audience Theme":
                    secondary_theme,
            }
        )


creator_profile_df = pd.DataFrame(
    creator_profile_rows
)


if not creator_profile_df.empty:
    creator_profile_df = (
        creator_profile_df
        .sort_values(
            [
                "Attributed Sales",
                "Views",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )


# --------------------------------------------------
# AUDIENCE VALIDATION / CREATOR BREADTH
# --------------------------------------------------

validation_rows = []

if not audience_df.empty:
    for _, audience_row in audience_df.iterrows():
        theme = str(
            audience_row[
                "Audience Theme"
            ]
        )

        matching = video_df[
            video_df[
                "Audience Themes"
            ].apply(
                lambda values:
                    theme in values
            )
        ].copy()

        creator_keys = [
            str(
                value
            ).strip()
            for value in matching[
                "Creator Key"
            ].tolist()
            if str(
                value
            ).strip()
        ]

        creator_breadth = len(
            set(
                creator_keys
            )
        )

        theme_creator_rows = (
            creator_theme_summary[
                creator_theme_summary[
                    "Audience Theme"
                ] == theme
            ].copy()
            if not creator_theme_summary.empty
            else pd.DataFrame()
        )

        top_theme_creator_share = 0.0

        if (
            not theme_creator_rows.empty
            and int(
                audience_row[
                    "Attributed Sales"
                ]
            ) > 0
        ):
            top_theme_creator_sales = int(
                theme_creator_rows[
                    "Attributed Sales"
                ].max()
            )

            top_theme_creator_share = (
                (
                    top_theme_creator_sales
                    / int(
                        audience_row[
                            "Attributed Sales"
                        ]
                    )
                ) * 100
            )

        if creator_breadth >= 5:
            validation = (
                "✅ Broadly validated"
            )

        elif creator_breadth >= 3:
            validation = (
                "🟢 Multi-creator signal"
            )

        elif creator_breadth == 2:
            validation = (
                "🟡 Emerging multi-creator"
            )

        elif creator_breadth == 1:
            validation = (
                "⚠️ Creator-dependent"
            )

        else:
            validation = (
                "⚪ Creator unknown"
            )

        validation_rows.append(
            {
                "Audience Theme":
                    theme,

                "Creators":
                    creator_breadth,

                "Videos":
                    int(
                        audience_row[
                            "Videos"
                        ]
                    ),

                "Attributed Sales":
                    int(
                        audience_row[
                            "Attributed Sales"
                        ]
                    ),

                "Sales Share":
                    float(
                        audience_row[
                            "Sales Share"
                        ]
                    ),

                "Top Creator Share":
                    top_theme_creator_share,

                "Validation":
                    validation,
            }
        )


audience_validation_df = pd.DataFrame(
    validation_rows
)


if not audience_validation_df.empty:
    audience_validation_df = (
        audience_validation_df
        .sort_values(
            [
                "Attributed Sales",
                "Creators",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )


# ==================================================
# AUDIENCE SALES COVERAGE
# ==================================================

classified_audience_mask = (
    video_df[
        "Audience Themes"
    ].apply(
        lambda values:
            bool(
                values
            )
    )
)

classified_audience_df = video_df[
    classified_audience_mask
].copy()

classified_audience_sales = int(
    classified_audience_df[
        "Sales"
    ].sum()
)

classified_audience_views = int(
    classified_audience_df[
        "Views"
    ].sum()
)

audience_sales_coverage = (
    (
        classified_audience_sales
        / total_sales
    ) * 100
    if total_sales > 0
    else 0
)

audience_view_coverage = (
    (
        classified_audience_views
        / total_views
    ) * 100
    if total_views > 0
    else 0
)

unclassified_audience_sales = max(
    0,
    total_sales
    - classified_audience_sales,
)


# ==================================================
# AUDIENCE BLIND SPOTS
# ==================================================

unclassified_video_df = video_df[
    ~classified_audience_mask
].copy()


if not unclassified_video_df.empty:
    unclassified_video_df = (
        unclassified_video_df
        .sort_values(
            [
                "Sales",
                "Views",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )


blind_spot_rows = []

running_recoverable_sales = (
    classified_audience_sales
)


for priority_index, (
    _,
    blind_row,
) in enumerate(
    unclassified_video_df.iterrows(),
    start=1,
):
    video_sales = int(
        blind_row[
            "Sales"
        ]
    )

    video_views = int(
        blind_row[
            "Views"
        ]
    )

    sales_share = (
        (
            video_sales
            / total_sales
        ) * 100
        if total_sales > 0
        else 0
    )

    current_coverage = (
        (
            running_recoverable_sales
            / total_sales
        ) * 100
        if total_sales > 0
        else 0
    )

    projected_sales = min(
        total_sales,
        running_recoverable_sales
        + video_sales,
    )

    projected_coverage = (
        (
            projected_sales
            / total_sales
        ) * 100
        if total_sales > 0
        else 0
    )

    coverage_gain = max(
        0,
        projected_coverage
        - current_coverage,
    )

    creator_label = str(
        blind_row[
            "Creator Label"
        ]
        or blind_row[
            "Creator Key"
        ]
        or "Unknown creator"
    ).strip()

    caption = truncate_text(
        blind_row[
            "Caption"
        ],
        limit=220,
    )

    blind_spot_rows.append(
        {
            "Priority":
                priority_index,

            "Video ID":
                str(
                    blind_row[
                        "Video ID"
                    ]
                ),

            "Creator":
                creator_label,

            "Caption":
                caption,

            "Attributed Sales":
                video_sales,

            "Sales Share":
                sales_share,

            "Views":
                video_views,

            "Sales / 1K":
                float(
                    blind_row[
                        "Sales / 1K"
                    ]
                ),

            "Current Coverage":
                current_coverage,

            "Projected Coverage":
                projected_coverage,

            "Coverage Gain":
                coverage_gain,
        }
    )

    running_recoverable_sales = (
        projected_sales
    )


audience_blind_spot_df = pd.DataFrame(
    blind_spot_rows
)


top_blind_spot_sales = (
    int(
        audience_blind_spot_df.iloc[
            0
        ][
            "Attributed Sales"
        ]
    )
    if not audience_blind_spot_df.empty
    else 0
)


top_blind_spot_share = (
    float(
        audience_blind_spot_df.iloc[
            0
        ][
            "Sales Share"
        ]
    )
    if not audience_blind_spot_df.empty
    else 0
)


top_blind_spot_projected_coverage = (
    float(
        audience_blind_spot_df.iloc[
            0
        ][
            "Projected Coverage"
        ]
    )
    if not audience_blind_spot_df.empty
    else audience_sales_coverage
)


# ==================================================
# AUDIENCE EVIDENCE DEPTH
# ==================================================

content_theme_count = (
    len(
        audience_df
    )
    if not audience_df.empty
    else 0
)

if (
    audience_sales_coverage >= 75
    and content_theme_count >= 2
    and (
        unique_creators >= 3
        or sales_coverage >= 20
    )
):
    audience_confidence = (
        "🟢 Stronger Behavioral Evidence"
    )

elif (
    audience_sales_coverage >= 50
    and content_theme_count >= 1
):
    audience_confidence = (
        "🟡 Moderate Behavioral Evidence"
    )

elif (
    audience_sales_coverage >= 20
    and content_theme_count >= 1
):
    audience_confidence = (
        "🟠 Early Behavioral Evidence"
    )

else:
    audience_confidence = (
        "⚪ Limited Behavioral Evidence"
    )


# ==================================================
# AUDIENCE INTELLIGENCE UI
# ==================================================

st.divider()

st.subheader(
    "👥 Audience Intelligence"
)

st.caption(
    "FlipRadar is inferring shopping interests, needs and purchase triggers "
    "from cached content and attributed commerce. It is **not verified purchaser "
    "demographic data**."
)


a1, a2, a3, a4, a5 = st.columns(
    5
)


a1.metric(
    "Audience Evidence",
    audience_confidence,
)


a2.metric(
    "Audience Sales Coverage",
    f"{audience_sales_coverage:.1f}%",
)


a3.metric(
    "Classified Sales",
    f"{classified_audience_sales:,}",
)


a4.metric(
    "Unclassified Sales",
    f"{unclassified_audience_sales:,}",
)


a5.metric(
    "Creators Observed",
    (
        unique_creators
        if unique_creators > 0
        else "Unavailable"
    ),
)


st.caption(
    f"Audience themes currently explain {audience_sales_coverage:.1f}% "
    f"of sampled attributed sales and {audience_view_coverage:.1f}% "
    "of sampled views. Coverage is calculated on unique videos so "
    "overlapping themes are not double-counted. High coverage means "
    "the content is classifiable; it does not by itself verify who purchased."
)


# --------------------------------------------------
# LIKELY BUYER PROFILE
# --------------------------------------------------

if audience_sales_coverage < 20:
    st.warning(
        "Most attributed sales are still unclassified by audience theme. "
        "Treat the buyer profile below as a narrow signal, not a broad description "
        "of the product's full buying audience."
    )

elif audience_sales_coverage < 50:
    st.info(
        "Audience signals explain part of the attributed sales, but a substantial "
        "share remains unclassified. The profile is useful for hypothesis generation "
        "rather than as a complete audience map."
    )

elif audience_sales_coverage < 75:
    st.info(
        "Audience signals explain a majority of attributed sales, giving the profile "
        "moderate behavioral support."
    )

else:
    if (
        unique_creators >= 3
        or sales_coverage >= 20
    ):
        st.success(
            "Audience signals explain most sampled attributed sales and have "
            "additional corroboration from creator spread or manual review."
        )

    else:
        st.info(
            "Audience signals explain most sampled attributed sales, but the "
            "evidence is still caption-led because creator identity and manual "
            "review coverage are limited. Treat this as a strong content pattern, "
            "not verified buyer identity."
        )


st.write(
    "### 🎯 Likely Buyer Profile"
)


if not audience_df.empty:
    top_profile = (
        audience_df
        .head(
            3
        )
        .copy()
    )

    profile_columns = st.columns(
        len(
            top_profile
        )
    )

    for position, (
        _,
        audience_row,
    ) in enumerate(
        top_profile.iterrows()
    ):
        with profile_columns[
            position
        ]:
            st.markdown(
                f"#### #{position + 1} "
                f"{audience_row['Audience Theme']}"
            )

            st.metric(
                "Attributed Sales",
                f"{int(audience_row['Attributed Sales']):,}",
            )

            st.write(
                f"**{audience_row['Sales Share']:.1f}%** "
                "of sampled attributed sales appeared in videos "
                "containing this theme."
            )

            evidence_terms = (
                audience_row[
                    "Evidence Terms"
                ]
                or []
            )

            if evidence_terms:
                st.caption(
                    "Evidence terms: "
                    + " • ".join(
                        evidence_terms
                    )
                )

            st.caption(
                f"{int(audience_row['Videos'])} videos • "
                f"{int(audience_row['Views']):,} views • "
                f"{audience_row['Sales / 1K']:.3f} sales/1K"
            )

else:
    st.info(
        "The current cached captions and hashtags do not contain enough "
        "content-level audience language for a useful buyer profile."
    )


# --------------------------------------------------
# PRODUCT CONTEXT VS CONTENT EVIDENCE
# --------------------------------------------------

if product_context_themes:
    content_theme_set = set(
        audience_df[
            "Audience Theme"
        ].tolist()
        if not audience_df.empty
        else []
    )

    context_only = [
        theme
        for theme in product_context_themes
        if theme not in content_theme_set
    ]

    if context_only:
        st.caption(
            "Product-title context suggests "
            + " • ".join(
                context_only
            )
            + ", but the sampled captions/hashtags have not independently "
            "validated those themes yet."
        )


# --------------------------------------------------
# WHY FLIPRADAR THINKS THIS
# --------------------------------------------------

if not audience_df.empty:
    st.write(
        "### 🔎 Why FlipRadar Thinks This"
    )

    for _, audience_row in audience_df.head(
        3
    ).iterrows():
        with st.expander(
            f"{audience_row['Audience Theme']} — "
            f"{int(audience_row['Attributed Sales']):,} attributed sales"
        ):
            evidence_terms = (
                audience_row[
                    "Evidence Terms"
                ]
                or []
            )

            if evidence_terms:
                st.write(
                    "**Matched language:** "
                    + ", ".join(
                        evidence_terms
                    )
                )

            top_caption = str(
                audience_row[
                    "Top Evidence Caption"
                ]
                or ""
            ).strip()

            if top_caption:
                st.write(
                    "**Highest-sales supporting caption:**"
                )

                st.write(
                    top_caption
                )

                st.caption(
                    f"{int(audience_row['Top Evidence Sales']):,} sales • "
                    f"{int(audience_row['Top Evidence Views']):,} views"
                )

            else:
                st.caption(
                    "The evidence came from hashtags or other cached text "
                    "rather than a usable caption."
                )


# --------------------------------------------------
# BUYING TRIGGERS
# --------------------------------------------------

st.write(
    "### 🛒 Strongest Buying Triggers"
)


if not intent_df.empty:
    trigger_limit = min(
        5,
        len(
            intent_df
        ),
    )

    for index in range(
        trigger_limit
    ):
        trigger = intent_df.iloc[
            index
        ]

        st.markdown(
            f"**{index + 1}. “{trigger['Phrase']}”** — "
            f"{int(trigger['Attributed Sales']):,} attributed sales • "
            f"{trigger['Sales / 1K']:.3f} sales/1K"
        )

        top_caption = str(
            trigger[
                "Top Evidence Caption"
            ]
            or ""
        ).strip()

        if top_caption:
            st.caption(
                top_caption
            )

else:
    st.info(
        "No strong buying-trigger phrases were detected in the cached captions."
    )


# --------------------------------------------------
# CREATOR EVIDENCE
# --------------------------------------------------

st.write(
    "### 👤 Sales-Weighted Creator Evidence"
)


if not creator_summary.empty:
    creator_display = (
        creator_summary
        .head(
            10
        )
        .copy()
    )

    creator_display[
        "Attributed GMV"
    ] = creator_display[
        "Attributed GMV"
    ].map(
        lambda value:
            f"${value:,.0f}"
    )

    st.dataframe(
        creator_display,
        width="stretch",
        hide_index=True,
    )

    st.caption(
        f"Creator identity was recovered for "
        f"{creator_video_coverage}/{len(video_df)} sampled videos "
        f"({creator_video_coverage_pct:.0f}%)."
    )

    if top_three_creator_share >= 80:
        st.warning(
            "Audience evidence is highly concentrated in the top three creators. "
            "Treat the audience hypothesis as creator-dependent until more creators validate it."
        )

    elif top_three_creator_share >= 60:
        st.info(
            "A meaningful share of attributed sales is concentrated in the top three creators. "
            "The audience pattern is useful, but broader creator validation would strengthen it."
        )

    else:
        st.success(
            "Attributed sales are distributed across multiple creators, "
            "which gives the audience hypothesis broader support."
        )

else:
    st.info(
        "Creator identity is not present in a recoverable form in this cached "
        "content scan. FlipRadar can still infer shopping behavior from video "
        "language and attributed sales without making another API call."
    )


# --------------------------------------------------
# WHO IS MOVING THIS PRODUCT?
# --------------------------------------------------

if not creator_profile_df.empty:
    st.write(
        "### 🚀 Who Is Moving This Product?"
    )

    st.caption(
        "Creators are ranked by sampled attributed sales. "
        "Primary and secondary audience themes come only from the "
        "cached videos associated with each creator."
    )

    top_creator_profiles = (
        creator_profile_df
        .head(
            5
        )
        .copy()
    )

    for rank, (
        _,
        creator_row,
    ) in enumerate(
        top_creator_profiles.iterrows(),
        start=1,
    ):
        with st.container(
            border=True
        ):
            left, middle, right = st.columns(
                [
                    2.2,
                    1,
                    1.4,
                ]
            )

            with left:
                st.markdown(
                    f"#### #{rank} {creator_row['Creator']}"
                )

                st.write(
                    "**Primary audience:** "
                    f"{creator_row['Primary Audience Theme']}"
                )

                if str(
                    creator_row[
                        "Secondary Audience Theme"
                    ]
                ).strip():
                    st.caption(
                        "Secondary audience: "
                        f"{creator_row['Secondary Audience Theme']}"
                    )

            with middle:
                st.metric(
                    "Attributed Sales",
                    f"{int(creator_row['Attributed Sales']):,}",
                )

                st.caption(
                    f"{creator_row['Sales Share']:.1f}% of sampled sales"
                )

            with right:
                st.metric(
                    "Videos",
                    int(
                        creator_row[
                            "Videos"
                        ]
                    ),
                )

                st.caption(
                    f"{int(creator_row['Views']):,} views"
                )


# --------------------------------------------------
# AUDIENCE VALIDATION
# --------------------------------------------------

st.write(
    "### 🎯 Audience Validation"
)

st.caption(
    "This tests whether each audience theme appears across multiple "
    "independent creators or is mostly being driven by one creator."
)


if not audience_validation_df.empty:
    validation_display = (
        audience_validation_df
        .head(
            10
        )
        .copy()
    )

    validation_display[
        "Sales Share"
    ] = validation_display[
        "Sales Share"
    ].map(
        lambda value:
            f"{value:.1f}%"
    )

    validation_display[
        "Top Creator Share"
    ] = validation_display[
        "Top Creator Share"
    ].map(
        lambda value:
            f"{value:.1f}%"
    )

    st.dataframe(
        validation_display,
        width="stretch",
        hide_index=True,
    )

    if len(
        validation_display
    ) > 0:
        strongest_validation = (
            validation_display.iloc[
                0
            ]
        )

        st.caption(
            "Highest-sales audience theme: "
            f"{strongest_validation['Audience Theme']} • "
            f"{strongest_validation['Creators']} creators • "
            f"{strongest_validation['Validation']}."
        )

else:
    st.info(
        "Creator-level audience validation is unavailable for this cached sample."
    )


st.caption(
    "A theme supported by several creators is generally more portable than "
    "a theme whose sales come mostly from one creator. This still describes "
    "observed content behavior, not verified purchaser demographics."
)


# --------------------------------------------------
# AUDIENCE BLIND SPOTS
# --------------------------------------------------

st.write(
    "### ⚠️ Audience Blind Spots"
)

st.caption(
    "These are high-sales videos that FlipRadar still cannot place into "
    "an audience theme after exact-word, simple-plural and hashtag-compound "
    "matching. Reviewing the highest-sales blind spots first gives you the "
    "biggest potential improvement in audience coverage."
)


if not audience_blind_spot_df.empty:
    b1, b2, b3, b4 = st.columns(
        4
    )

    b1.metric(
        "Unclassified Videos",
        len(
            audience_blind_spot_df
        ),
    )

    b2.metric(
        "Unclassified Sales",
        f"{unclassified_audience_sales:,}",
    )

    b3.metric(
        "Top Blind Spot",
        f"{top_blind_spot_sales:,} sales",
    )

    b4.metric(
        "Coverage If Top Video Is Classified",
        f"{top_blind_spot_projected_coverage:.1f}%",
        delta=(
            f"+{max(0, top_blind_spot_projected_coverage - audience_sales_coverage):.1f} pts"
        ),
    )

    st.write(
        "#### 🎯 Priority Review Queue"
    )

    priority_limit = min(
        5,
        len(
            audience_blind_spot_df
        ),
    )

    for queue_index in range(
        priority_limit
    ):
        blind_row = (
            audience_blind_spot_df.iloc[
                queue_index
            ]
        )

        with st.container(
            border=True
        ):
            left, middle, right = st.columns(
                [
                    2.5,
                    1,
                    1.2,
                ]
            )

            with left:
                st.markdown(
                    f"#### #{int(blind_row['Priority'])} Priority Review"
                )

                st.write(
                    f"**Creator:** {blind_row['Creator']}"
                )

                caption = str(
                    blind_row[
                        "Caption"
                    ]
                    or ""
                ).strip()

                if caption:
                    st.write(
                        caption
                    )

                else:
                    st.caption(
                        "No usable caption was saved for this video."
                    )

                st.caption(
                    f"Video ID: {blind_row['Video ID']}"
                )

            with middle:
                st.metric(
                    "Attributed Sales",
                    f"{int(blind_row['Attributed Sales']):,}",
                )

                st.caption(
                    f"{blind_row['Sales Share']:.1f}% of sampled sales"
                )

                st.metric(
                    "Views",
                    f"{int(blind_row['Views']):,}",
                )

            with right:
                st.metric(
                    "Coverage Gain",
                    f"+{blind_row['Coverage Gain']:.1f} pts",
                )

                st.caption(
                    f"{blind_row['Current Coverage']:.1f}% → "
                    f"{blind_row['Projected Coverage']:.1f}%"
                )

                st.metric(
                    "Sales / 1K",
                    f"{blind_row['Sales / 1K']:.3f}",
                )

    top_blind_row = (
        audience_blind_spot_df.iloc[
            0
        ]
    )

    st.info(
        f"Highest-priority blind spot: video {top_blind_row['Video ID']} "
        f"accounts for {int(top_blind_row['Attributed Sales']):,} attributed sales "
        f"({top_blind_row['Sales Share']:.1f}% of the sample). "
        f"If a manual review gives this video a usable audience theme, "
        f"audience sales coverage could rise from {audience_sales_coverage:.1f}% "
        f"to {top_blind_row['Projected Coverage']:.1f}%."
    )

    with st.expander(
        "View blind-spot table"
    ):
        blind_display = (
            audience_blind_spot_df
            .head(
                10
            )
            .copy()
        )

        blind_display[
            "Sales Share"
        ] = blind_display[
            "Sales Share"
        ].map(
            lambda value:
                f"{value:.1f}%"
        )

        blind_display[
            "Current Coverage"
        ] = blind_display[
            "Current Coverage"
        ].map(
            lambda value:
                f"{value:.1f}%"
        )

        blind_display[
            "Projected Coverage"
        ] = blind_display[
            "Projected Coverage"
        ].map(
            lambda value:
                f"{value:.1f}%"
        )

        blind_display[
            "Coverage Gain"
        ] = blind_display[
            "Coverage Gain"
        ].map(
            lambda value:
                f"+{value:.1f} pts"
        )

        st.dataframe(
            blind_display,
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Projected coverage is a best-case review-priority estimate: it assumes "
        "the reviewed video can be assigned at least one meaningful audience theme. "
        "It does not assume that the theme is correct before you review the video."
    )

else:
    st.success(
        "No audience blind spots remain in the current cached sample. "
        "Every sampled video's attributed sales are attached to at least one "
        "audience theme."
    )


st.caption(
    "FlipRadar intentionally avoids claiming purchaser age, gender, ethnicity "
    "or other demographic traits from these signals. This section describes "
    "observed interests, needs and shopping behavior only."
)


# ==================================================
# CREATIVE THESIS
# ==================================================

st.divider()

st.subheader(
    "🧠 Current Creative Thesis"
)

st.caption(
    "This is a data-backed hypothesis from the sampled videos, "
    "not a guarantee that the same creative will reproduce the result."
)


t1, t2, t3 = st.columns(
    3
)


with t1:
    st.write(
        "### 🎣 Hook"
    )

    if top_hook is not None:
        st.write(
            f"**{top_hook['Label']}**"
        )

        st.metric(
            "Attributed Sales",
            f"{int(top_hook['Sales']):,}",
        )

        st.caption(
            f"{int(top_hook['Videos'])} sampled videos • "
            f"{int(top_hook['Views']):,} views"
        )


with t2:
    st.write(
        "### 🎯 Selling Angle"
    )

    if top_angle is not None:
        st.write(
            f"**{top_angle['Label']}**"
        )

        st.metric(
            "Attributed Sales",
            f"{int(top_angle['Sales']):,}",
        )

        st.caption(
            f"{int(top_angle['Videos'])} sampled videos • "
            f"{top_angle['Sales / 1K']:.3f} sales/1K"
        )


with t3:
    st.write(
        "### 🎥 Format"
    )

    if top_format is not None:
        st.write(
            f"**{top_format['Label']}**"
        )

        st.metric(
            "Attributed Sales",
            f"{int(top_format['Sales']):,}",
        )

        st.caption(
            f"{int(top_format['Videos'])} sampled videos"
        )


# ==================================================
# WINNING COMBINATION
# ==================================================

if top_combo is not None:
    st.divider()

    st.subheader(
        "🧬 Strongest Observed Combination"
    )

    c1, c2, c3, c4 = st.columns(
        4
    )

    c1.metric(
        "Videos",
        int(
            top_combo[
                "Videos"
            ]
        ),
    )

    c2.metric(
        "Views",
        f"{int(top_combo['Views']):,}",
    )

    c3.metric(
        "Sales",
        f"{int(top_combo['Sales']):,}",
    )

    c4.metric(
        "Sales / 1K",
        f"{top_combo['Sales / 1K']:.3f}",
    )

    st.write(
        f"### {top_combo['Hook']}"
    )

    st.write(
        "paired with"
    )

    st.write(
        f"### {top_combo['Selling Angle']}"
    )


# ==================================================
# CREATIVE BRIEF
# ==================================================

st.divider()

st.subheader(
    "📝 Creative Test Brief"
)


if (
    top_hook is not None
    and top_angle is not None
):
    st.write(
        "**Opening hook:** "
        f"{top_hook['Label']}"
    )

    st.write(
        "**Core selling angle:** "
        f"{top_angle['Label']}"
    )

    if top_format is not None:
        st.write(
            "**Format to study first:** "
            f"{top_format['Label']}"
        )

    if top_combo is not None:
        st.write(
            "**Combination with the strongest sampled sales evidence:** "
            f"{top_combo['Hook']} + "
            f"{top_combo['Selling Angle']}"
        )

    st.write(
        "**Testing principle:** Keep the product and offer constant "
        "while testing different hooks against the same selling angle. "
        "Then compare sales-per-1K views rather than views alone."
    )


# ==================================================
# MANUAL CREATIVE DETAILS
# ==================================================

detail_rows = []

for _, row in reviewed_df.iterrows():
    for detail in row[
        "Details"
    ]:
        detail_rows.append(
            {
                "Creative Detail":
                    detail,

                "Views":
                    row[
                        "Views"
                    ],

                "Sales":
                    row[
                        "Sales"
                    ],

                "GMV":
                    row[
                        "GMV"
                    ],

                "Video ID":
                    row[
                        "Video ID"
                    ],
            }
        )


if detail_rows:
    st.divider()

    st.subheader(
        "👁️ Manually Observed Creative Details"
    )

    detail_raw = pd.DataFrame(
        detail_rows
    )

    detail_summary = (
        detail_raw
        .groupby(
            "Creative Detail",
            as_index=False,
        )
        .agg(
            {
                "Video ID":
                    "count",

                "Views":
                    "sum",

                "Sales":
                    "sum",

                "GMV":
                    "sum",
            }
        )
    )

    detail_summary = (
        detail_summary.rename(
            columns={
                "Video ID":
                    "Videos"
            }
        )
    )

    detail_summary[
        "Sales / 1K"
    ] = detail_summary.apply(
        lambda row:
            (
                row[
                    "Sales"
                ]
                / row[
                    "Views"
                ]
            ) * 1000
            if row[
                "Views"
            ] > 0
            else 0,
        axis=1,
    )

    detail_summary = (
        detail_summary
        .sort_values(
            "Sales",
            ascending=False,
        )
    )

    st.dataframe(
        detail_summary,
        width="stretch",
        hide_index=True,
    )

else:
    st.divider()

    st.subheader(
        "👁️ Manually Observed Creative Details"
    )

    st.info(
        "No manual creative details have been saved yet. "
        "Use Creative Angles → Visual Review Workspace "
        "to label actual video behavior."
    )


# ==================================================
# TOP VIDEO EVIDENCE
# ==================================================

st.divider()

st.subheader(
    "🏆 Video Evidence"
)


evidence_mode = st.radio(
    "Rank evidence by",
    [
        "🛒 Sales",
        "⚡ Sales Efficiency",
        "👀 Views",
    ],
    horizontal=True,
)


if evidence_mode == "🛒 Sales":
    evidence_df = (
        video_df
        .sort_values(
            "Sales",
            ascending=False,
        )
    )

elif evidence_mode == "⚡ Sales Efficiency":
    evidence_df = (
        video_df
        .sort_values(
            "Sales / 1K",
            ascending=False,
        )
    )

else:
    evidence_df = (
        video_df
        .sort_values(
            "Views",
            ascending=False,
        )
    )


evidence_display = (
    evidence_df[
        [
            "Caption",
            "Views",
            "Sales",
            "GMV",
            "Sales / 1K",
            "Hooks",
            "Angles",
            "Formats",
            "Reviewed",
            "Video ID",
        ]
    ]
    .head(
        10
    )
    .copy()
)


evidence_display[
    "Hooks"
] = evidence_display[
    "Hooks"
].apply(
    lambda values:
        " • ".join(
            values
        )
)


evidence_display[
    "Angles"
] = evidence_display[
    "Angles"
].apply(
    lambda values:
        " • ".join(
            values
        )
)


evidence_display[
    "Formats"
] = evidence_display[
    "Formats"
].apply(
    lambda values:
        " • ".join(
            values
        )
)


evidence_display[
    "Reviewed"
] = evidence_display[
    "Reviewed"
].apply(
    lambda value:
        "👁️ Manual"
        if value
        else "🤖 Caption"
)


evidence_display = (
    evidence_display.rename(
        columns={
            "Sales":
                "Attributed Sales",

            "GMV":
                "Attributed GMV",

            "Angles":
                "Selling Angles",

            "Reviewed":
                "Classification",
        }
    )
)


st.dataframe(
    evidence_display,
    width="stretch",
    hide_index=True,
)


# ==================================================
# FOOTER
# ==================================================

st.divider()

st.caption(
    "Creative Playbook uses the hierarchy "
    "**manual visual review → caption heuristic fallback**."
)

st.caption(
    "Because one video can contain multiple hooks, selling angles or "
    "audience themes, category totals overlap and should not be added together."
)

st.caption(
    "Audience Intelligence is an inferred behavioral profile from cached "
    "content and attributed sales. It is not verified purchaser demographic data. "
    f"Current audience sales coverage: {audience_sales_coverage:.1f}%. "
    f"Unclassified attributed sales: {unclassified_audience_sales:,}."
)

st.caption(
    "Use this page to generate creative and audience test hypotheses, "
    "not to treat historical performance as guaranteed future performance."
)

st.caption(
    "Creative Playbook uses zero EchoTik API requests."
)


if content_scan_time:
    st.caption(
        f"Content dataset cached: {content_scan_time}"
    )
