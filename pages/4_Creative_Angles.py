import json
import sqlite3
from datetime import datetime

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
    page_title="FlipRadar Creative Lab",
    page_icon="🧠",
    layout="wide",
)

initialize_database()
initialize_content_database()


# ==================================================
# MANUAL REVIEW DATABASE
# ==================================================

DB_NAME = "flipradar.db"


def review_connect():
    return sqlite3.connect(DB_NAME)


def initialize_review_database():
    conn = review_connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS creative_reviews (
            product_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            hooks_json TEXT NOT NULL,
            selling_angles_json TEXT NOT NULL,
            formats_json TEXT NOT NULL,
            details_json TEXT NOT NULL,
            notes TEXT,
            reviewed_at TEXT NOT NULL,
            PRIMARY KEY (product_id, video_id)
        )
        """
    )

    conn.commit()
    conn.close()


def save_review(
    product_id,
    video_id,
    hooks,
    selling_angles,
    formats,
    details,
    notes,
):
    conn = review_connect()
    cursor = conn.cursor()

    reviewed_at = datetime.now().isoformat(
        timespec="seconds"
    )

    cursor.execute(
        """
        INSERT OR REPLACE INTO creative_reviews (
            product_id,
            video_id,
            hooks_json,
            selling_angles_json,
            formats_json,
            details_json,
            notes,
            reviewed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(product_id),
            str(video_id),
            json.dumps(hooks),
            json.dumps(selling_angles),
            json.dumps(formats),
            json.dumps(details),
            notes,
            reviewed_at,
        ),
    )

    conn.commit()
    conn.close()

    return reviewed_at


def load_review(
    product_id,
    video_id,
):
    conn = review_connect()
    cursor = conn.cursor()

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
            str(product_id),
            str(video_id),
        ),
    )

    row = cursor.fetchone()

    conn.close()

    if not row:
        return None

    return {
        "hooks": json.loads(
            row[0] or "[]"
        ),
        "selling_angles": json.loads(
            row[1] or "[]"
        ),
        "formats": json.loads(
            row[2] or "[]"
        ),
        "details": json.loads(
            row[3] or "[]"
        ),
        "notes": row[4] or "",
        "reviewed_at": row[5],
    }


initialize_review_database()


# ==================================================
# HEADER
# ==================================================

st.title(
    "🧠 Creative Intelligence Lab"
)

st.caption(
    "Separate the hook that gets attention from the "
    "selling angle that makes people care about the product."
)

st.info(
    "Manual visual reviews override caption-based classifications "
    "inside the Creative Intelligence results. "
    "This page uses **zero EchoTik API requests**."
)


# ==================================================
# LOAD PRODUCTS
# ==================================================

products, market_scan_time = load_latest_scan()

if not products:
    st.warning(
        "No saved FlipRadar product scan exists yet."
    )
    st.stop()


product_names = [
    product["name"]
    for product in products
]

selected_name = st.selectbox(
    "Choose a product",
    product_names,
)

selected_product = next(
    product
    for product in products
    if product["name"] == selected_name
)

product_id = str(
    selected_product["id"]
)

st.write(
    f"**Product ID:** `{product_id}`"
)


# ==================================================
# LOAD CONTENT
# ==================================================

videos, content_scan_time = load_content_scan(
    product_id
)

if not videos:
    st.warning(
        "This product has not been Content Deep Scanned yet. "
        "Run the 3-lane Content Deep Scan first."
    )
    st.stop()


# ==================================================
# HELPERS
# ==================================================

def safe_float(
    value,
    default=0.0,
):
    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_int(
    value,
    default=0,
):
    try:
        return int(
            float(value)
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
        value or ""
    ).lower().strip()


def contains_any(
    text,
    keywords,
):
    return any(
        keyword in text
        for keyword in keywords
    )


# ==================================================
# CAPTION-BASED HOOK RULES
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
        "you need to see",
        "i can't believe",
        "crazy",
        "crawww",
        "listen up",
    ],

    "😱 Shock / Reaction": [
        "omg",
        "oh my god",
        "literally",
        "no way",
        "wtf",
        "insane",
        "shocked",
        "obsessed",
        "wow",
    ],

    "💬 Comment Reply": [
        "replying to",
        "reply to",
        "responding to",
        "someone asked",
        "you asked",
    ],

    "🎯 Direct Claim": [
        "best",
        "this works",
        "it works",
        "so good",
        "soo good",
        "10/10",
        "must have",
        "need this",
        "game changer",
        "viral korean",
        "hair growth secret",
        "best perfume",
    ],

    "⏰ Urgency / Offer Hook": [
        "right now",
        " rn",
        "today",
        "deal",
        "sale",
        "discount",
        "coupon",
        "limited time",
        "black friday",
        "cyber monday",
        "before it's gone",
        "stock up",
    ],

    "❓ Question / Education Hook": [
        "did you know",
        "why does",
        "why is",
        "how does",
        "how to",
        "here's why",
        "this is why",
        "explained",
    ],
}


# ==================================================
# CAPTION-BASED SELLING ANGLES
# ==================================================

SELLING_ANGLE_RULES = {
    "❤️ Testimonial / Personal Proof": [
        "i love",
        "love this",
        "love it",
        "obsessed",
        "i swear",
        "swear to",
        "i tried",
        "i use",
        "my favorite",
        "my fave",
        "10/10",
        "believe you",
        "so good",
        "soo good",
        "literally",
        "best perfume",
    ],

    "😍 Attraction / Partner Reaction": [
        "he's so obsessed",
        "he’s so obsessed",
        "he will",
        "he'll",
        "he’ll",
        "boyfriend",
        "husband",
        "girlfriend",
        "wife",
        "partner",
        "men love",
        "women love",
        "get him",
        "get her",
        "crawling",
        "crawwwling",
        "attract",
        "attraction",
        "date night",
        "compliments",
        "compliment",
    ],

    "✨ Transformation / Desired Result": [
        "before",
        "after",
        "results",
        "transformation",
        "hair growth",
        "growth",
        "long hair",
        "thick hair",
        "long and thick",
        "inches",
        "silk press",
        "glow",
        "clear skin",
        "soft hair",
        "healthy hair",
        "nourishing",
    ],

    "🧪 Problem → Solution": [
        "works",
        "worked",
        "fix",
        "solution",
        "problem",
        "helped",
        "help with",
        "finally",
        "struggle",
        "frizz",
        "damage",
        "dry hair",
        "thin hair",
        "hair growth",
        "secret unlocked",
    ],

    "💸 Deal / Value": [
        "deal",
        "sale",
        "discount",
        "coupon",
        "price",
        "cheap",
        "affordable",
        "good deal",
        "stock up",
        "black friday",
        "cyber monday",
        "pack of",
        "bundle",
    ],

    "🎯 Identity / Audience": [
        "curly hair",
        "curly",
        "black girl",
        "blackgirl",
        "natural hair",
        "silk press",
        "moms",
        "mom",
        "girls",
        "guys",
        "men",
        "women",
        "for anyone",
        "for people",
        "for my",
    ],

    "📚 Education / Ingredient Story": [
        "why",
        "how",
        "ingredient",
        "ingredients",
        "science",
        "because",
        "rosemary",
        "rice water",
        "makes sense",
        "interesting",
    ],

    "🔥 Viral / Social Proof": [
        "viral",
        "everyone",
        "everybody",
        "tiktok made me",
        "tiktok shop",
        "creator picks",
        "best seller",
        "bestseller",
        "sold out",
        "popular",
        "trending",
        "hype",
    ],
}


# ==================================================
# CAPTION-BASED FORMAT RULES
# ==================================================

FORMAT_RULES = {
    "💬 Comment Reply": [
        "replying to",
        "reply to",
        "responding to",
    ],

    "🎥 Tutorial / Demo": [
        "how to",
        "tutorial",
        "routine",
        "how i",
        "step by step",
        "part 2",
        "pt 2",
        "show you",
        "demo",
    ],

    "🧾 Recommendation / Review": [
        "i love",
        "love this",
        "love it",
        "10/10",
        "best",
        "favorite",
        "fave",
        "obsessed",
        "i swear",
        "so good",
        "soo good",
        "review",
    ],

    "📚 Educational / Explanation": [
        "why",
        "because",
        "interesting",
        "makes sense",
        "ingredient",
        "ingredients",
        "science",
        "explained",
    ],

    "💸 Offer / Promotion": [
        "deal",
        "sale",
        "discount",
        "coupon",
        "black friday",
        "cyber monday",
        "limited time",
        "stock up",
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
# DETECTION
# ==================================================

def detect_from_rules(
    caption,
    rules,
):
    text = normalize_text(
        caption
    )

    if not text:
        return []

    results = []

    for label, keywords in rules.items():
        if contains_any(
            text,
            keywords,
        ):
            results.append(
                label
            )

    return results


def detect_hooks(
    caption,
):
    results = detect_from_rules(
        caption,
        HOOK_RULES,
    )

    return (
        results
        if results
        else [
            "❓ Hook Unclear From Caption"
        ]
    )


def detect_selling_angles(
    caption,
):
    results = detect_from_rules(
        caption,
        SELLING_ANGLE_RULES,
    )

    return (
        results
        if results
        else [
            "❓ Selling Angle Unclear"
        ]
    )


def detect_formats(
    caption,
):
    results = detect_from_rules(
        caption,
        FORMAT_RULES,
    )

    return (
        results
        if results
        else [
            "❓ Format Unknown From Caption"
        ]
    )


def needs_visual_review(
    caption,
):
    text = normalize_text(
        caption
    )

    if not text:
        return True

    if len(
        text.split()
    ) <= 2:
        return True

    low_information = {
        "omg",
        "wow",
        "literally",
        "obsessed",
        "yes",
        "no",
        "lol",
        "love it",
        "so good",
        "soo good",
    }

    return text in low_information


# ==================================================
# MANUAL OVERRIDE
#
# Manual > caption heuristic.
# If manual category is blank,
# caption classification remains fallback.
# ==================================================

def effective_labels(
    manual_review,
    manual_key,
    automatic_values,
):
    if not manual_review:
        return (
            automatic_values,
            "🤖 Caption",
        )

    manual_values = manual_review.get(
        manual_key,
        [],
    )

    if manual_values:
        return (
            manual_values,
            "👁️ Manual",
        )

    return (
        automatic_values,
        "🤖 Caption fallback",
    )


# ==================================================
# BUILD VIDEO DATAFRAME
# ==================================================

video_rows = []


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

    likes = safe_int(
        video.get(
            "likes",
            0,
        )
    )

    comments = safe_int(
        video.get(
            "comments",
            0,
        )
    )

    favorites = safe_int(
        video.get(
            "favorites",
            0,
        )
    )

    shares = safe_int(
        video.get(
            "shares",
            0,
        )
    )

    engagements = (
        likes
        + comments
        + favorites
        + shares
    )

    if views > 0:
        engagement_rate = (
            engagements
            / views
        ) * 100

        sales_per_1000 = (
            sales
            / views
        ) * 1000

    else:
        engagement_rate = 0
        sales_per_1000 = 0

    automatic_hooks = detect_hooks(
        caption
    )

    automatic_angles = detect_selling_angles(
        caption
    )

    automatic_formats = detect_formats(
        caption
    )

    manual_review = load_review(
        product_id,
        video_id,
    )

    hooks, hook_source = effective_labels(
        manual_review,
        "hooks",
        automatic_hooks,
    )

    selling_angles, angle_source = effective_labels(
        manual_review,
        "selling_angles",
        automatic_angles,
    )

    formats, format_source = effective_labels(
        manual_review,
        "formats",
        automatic_formats,
    )

    reviewed = (
        manual_review is not None
    )

    caption_needs_review = needs_visual_review(
        caption
    )

    video_rows.append(
        {
            "Video ID": video_id,
            "Caption": caption,

            "Hooks": hooks,
            "Selling Angles": selling_angles,
            "Formats": formats,

            "Hook Source": hook_source,
            "Angle Source": angle_source,
            "Format Source": format_source,

            "Reviewed": reviewed,
            "Caption Needs Review": caption_needs_review,
            "Needs Review": (
                caption_needs_review
                and not reviewed
            ),

            "Manual Details": (
                manual_review["details"]
                if manual_review
                else []
            ),

            "Manual Notes": (
                manual_review["notes"]
                if manual_review
                else ""
            ),

            "Reviewed At": (
                manual_review["reviewed_at"]
                if manual_review
                else ""
            ),

            "Views": views,
            "Sales": sales,
            "GMV": gmv,
            "Engagement Rate": engagement_rate,
            "Sales / 1K Views": sales_per_1000,
        }
    )


video_df = pd.DataFrame(
    video_rows
)


# ==================================================
# SUMMARY
# ==================================================

def summarize_dimension(
    dataframe,
    column_name,
):
    labels = set()

    for values in dataframe[
        column_name
    ]:
        for value in values:
            labels.add(
                value
            )

    rows = []

    for label in labels:
        matching = dataframe[
            dataframe[
                column_name
            ].apply(
                lambda values:
                    label in values
            )
        ]

        if matching.empty:
            continue

        combined_views = int(
            matching[
                "Views"
            ].sum()
        )

        attributed_sales = int(
            matching[
                "Sales"
            ].sum()
        )

        attributed_gmv = float(
            matching[
                "GMV"
            ].sum()
        )

        if combined_views > 0:
            efficiency = (
                attributed_sales
                / combined_views
            ) * 1000
        else:
            efficiency = 0

        rows.append(
            {
                "Label": label,
                "Videos": len(
                    matching
                ),
                "Manual Reviews": int(
                    matching[
                        "Reviewed"
                    ].sum()
                ),
                "Combined Views": combined_views,
                "Attributed Sales": attributed_sales,
                "Attributed GMV": attributed_gmv,
                "Sales / 1K Views": efficiency,
                "Avg Engagement %": float(
                    matching[
                        "Engagement Rate"
                    ].mean()
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


hook_df = summarize_dimension(
    video_df,
    "Hooks",
)

angle_df = summarize_dimension(
    video_df,
    "Selling Angles",
)

format_df = summarize_dimension(
    video_df,
    "Formats",
)


# ==================================================
# OVERVIEW
# ==================================================

st.divider()

st.subheader(
    "Creative Dataset"
)

c1, c2, c3, c4, c5 = st.columns(
    5
)

c1.metric(
    "Videos Analyzed",
    len(video_df),
)

videos_with_captions = int(
    (
        video_df[
            "Caption"
        ].str.strip()
        != ""
    ).sum()
)

c2.metric(
    "Videos With Captions",
    videos_with_captions,
)

c3.metric(
    "Need Visual Review",
    int(
        video_df[
            "Needs Review"
        ].sum()
    ),
)

c4.metric(
    "Manually Reviewed",
    int(
        video_df[
            "Reviewed"
        ].sum()
    ),
)

manual_sales = int(
    video_df[
        video_df[
            "Reviewed"
        ]
    ][
        "Sales"
    ].sum()
)

c5.metric(
    "Sales Manually Classified",
    f"{manual_sales:,}",
)


total_sales = int(
    video_df[
        "Sales"
    ].sum()
)

total_views = int(
    video_df[
        "Views"
    ].sum()
)

manual_views = int(
    video_df[
        video_df[
            "Reviewed"
        ]
    ][
        "Views"
    ].sum()
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

st.caption(
    f"Manual reviews currently cover "
    f"**{sales_coverage:.1f}% of sampled attributed sales** "
    f"and **{views_coverage:.1f}% of sampled views**."
)


# ==================================================
# BEST SIGNAL
# ==================================================

def best_signal(
    dataframe,
    metric,
):
    if dataframe.empty:
        return None

    usable = dataframe[
        ~dataframe[
            "Label"
        ].str.contains(
            "Unclear|Unknown",
            case=False,
            regex=True,
        )
    ]

    if usable.empty:
        usable = dataframe

    if metric == "Videos":
        return usable.sort_values(
            [
                "Videos",
                "Combined Views",
            ],
            ascending=False,
        ).iloc[0]

    return usable.sort_values(
        metric,
        ascending=False,
    ).iloc[0]


# ==================================================
# HOOK INTELLIGENCE
# ==================================================

st.divider()

st.subheader(
    "🎣 Hook Intelligence"
)

st.caption(
    "Manual visual hook labels override caption heuristics "
    "when a review has been saved."
)

hook_repeat = best_signal(
    hook_df,
    "Videos",
)

hook_reach = best_signal(
    hook_df,
    "Combined Views",
)

hook_sales = best_signal(
    hook_df,
    "Attributed Sales",
)

hook_efficiency = best_signal(
    hook_df,
    "Sales / 1K Views",
)


if hook_repeat is not None:
    h1, h2, h3, h4 = st.columns(
        4
    )

    h1.metric(
        "🔁 Most Repeated",
        int(
            hook_repeat[
                "Videos"
            ]
        ),
    )
    h1.write(
        f"**{hook_repeat['Label']}**"
    )

    h2.metric(
        "👀 Biggest Reach",
        f"{int(hook_reach['Combined Views']):,}",
    )
    h2.write(
        f"**{hook_reach['Label']}**"
    )

    h3.metric(
        "🛒 Most Sales",
        f"{int(hook_sales['Attributed Sales']):,}",
    )
    h3.write(
        f"**{hook_sales['Label']}**"
    )

    h4.metric(
        "⚡ Sales / 1K",
        f"{hook_efficiency['Sales / 1K Views']:.3f}",
    )
    h4.write(
        f"**{hook_efficiency['Label']}**"
    )


if not hook_df.empty:
    hook_display = (
        hook_df
        .sort_values(
            "Combined Views",
            ascending=False,
        )
        .rename(
            columns={
                "Label": "Hook"
            }
        )
    )

    st.dataframe(
        hook_display,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# SELLING ANGLE INTELLIGENCE
# ==================================================

st.divider()

st.subheader(
    "🎯 Selling Angle Intelligence"
)

st.caption(
    "Manual visual selling-angle labels are used first. "
    "Caption classification is only the fallback."
)

angle_repeat = best_signal(
    angle_df,
    "Videos",
)

angle_reach = best_signal(
    angle_df,
    "Combined Views",
)

angle_sales = best_signal(
    angle_df,
    "Attributed Sales",
)

angle_efficiency = best_signal(
    angle_df,
    "Sales / 1K Views",
)


if angle_repeat is not None:
    a1, a2, a3, a4 = st.columns(
        4
    )

    a1.metric(
        "🔁 Most Repeated",
        int(
            angle_repeat[
                "Videos"
            ]
        ),
    )
    a1.write(
        f"**{angle_repeat['Label']}**"
    )

    a2.metric(
        "👀 Biggest Reach",
        f"{int(angle_reach['Combined Views']):,}",
    )
    a2.write(
        f"**{angle_reach['Label']}**"
    )

    a3.metric(
        "🛒 Most Sales",
        f"{int(angle_sales['Attributed Sales']):,}",
    )
    a3.write(
        f"**{angle_sales['Label']}**"
    )

    a4.metric(
        "⚡ Sales / 1K",
        f"{angle_efficiency['Sales / 1K Views']:.3f}",
    )
    a4.write(
        f"**{angle_efficiency['Label']}**"
    )


if not angle_df.empty:
    angle_display = (
        angle_df
        .sort_values(
            "Attributed Sales",
            ascending=False,
        )
        .rename(
            columns={
                "Label": "Selling Angle"
            }
        )
    )

    st.dataframe(
        angle_display,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# FORMAT INTELLIGENCE
# ==================================================

st.divider()

st.subheader(
    "🎥 Format Intelligence"
)

st.caption(
    "Manual visual format labels override "
    "caption-inferred formats."
)

if not format_df.empty:
    format_display = (
        format_df
        .sort_values(
            "Combined Views",
            ascending=False,
        )
        .rename(
            columns={
                "Label": "Format"
            }
        )
    )

    st.dataframe(
        format_display,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# HOOK + SELLING ANGLE COMBINATIONS
# ==================================================

st.divider()

st.subheader(
    "🧬 Hook + Selling Angle Combinations"
)

combination_rows = []

for _, row in video_df.iterrows():
    for hook in row[
        "Hooks"
    ]:
        for angle in row[
            "Selling Angles"
        ]:
            combination_rows.append(
                {
                    "Hook": hook,
                    "Selling Angle": angle,
                    "Views": row[
                        "Views"
                    ],
                    "Sales": row[
                        "Sales"
                    ],
                    "GMV": row[
                        "GMV"
                    ],
                    "Manual Review": (
                        1
                        if row[
                            "Reviewed"
                        ]
                        else 0
                    ),
                    "Video ID": row[
                        "Video ID"
                    ],
                }
            )


if combination_rows:
    combo_raw = pd.DataFrame(
        combination_rows
    )

    combo_summary = (
        combo_raw
        .groupby(
            [
                "Hook",
                "Selling Angle",
            ],
            as_index=False,
        )
        .agg(
            {
                "Views": "sum",
                "Sales": "sum",
                "GMV": "sum",
                "Manual Review": "sum",
                "Video ID": "count",
            }
        )
    )

    combo_summary = combo_summary.rename(
        columns={
            "Views": "Combined Views",
            "Sales": "Attributed Sales",
            "GMV": "Attributed GMV",
            "Manual Review": "Manual Reviews",
            "Video ID": "Videos",
        }
    )

    combo_summary[
        "Sales / 1K Views"
    ] = combo_summary.apply(
        lambda row: (
            (
                row[
                    "Attributed Sales"
                ]
                / row[
                    "Combined Views"
                ]
            ) * 1000
            if row[
                "Combined Views"
            ] > 0
            else 0
        ),
        axis=1,
    )

    combo_summary = combo_summary.sort_values(
        [
            "Attributed Sales",
            "Combined Views",
        ],
        ascending=False,
    )

    st.dataframe(
        combo_summary,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# VIDEO EXPLORER
# ==================================================

st.divider()

st.subheader(
    "🔬 Classified Video Explorer"
)

explorer_mode = st.radio(
    "Rank videos by",
    [
        "👀 Views",
        "🛒 Sales",
        "⚡ Sales Efficiency",
    ],
    horizontal=True,
)


if explorer_mode == "👀 Views":
    explorer_df = video_df.sort_values(
        "Views",
        ascending=False,
    )

elif explorer_mode == "🛒 Sales":
    explorer_df = video_df.sort_values(
        "Sales",
        ascending=False,
    )

else:
    explorer_df = video_df.sort_values(
        "Sales / 1K Views",
        ascending=False,
    )


for _, row in explorer_df.iterrows():
    st.write(
        f"### {int(row['Views']):,} views"
    )

    caption = str(
        row[
            "Caption"
        ]
        or ""
    )

    if caption:
        st.write(
            caption
        )
    else:
        st.caption(
            "No caption available."
        )

    if row[
        "Reviewed"
    ]:
        st.success(
            "👁️ Manual visual classification active"
        )

    st.write(
        "**Hook:** "
        + " • ".join(
            row[
                "Hooks"
            ]
        )
    )

    st.caption(
        f"Source: {row['Hook Source']}"
    )

    st.write(
        "**Selling angle:** "
        + " • ".join(
            row[
                "Selling Angles"
            ]
        )
    )

    st.caption(
        f"Source: {row['Angle Source']}"
    )

    st.write(
        "**Format:** "
        + " • ".join(
            row[
                "Formats"
            ]
        )
    )

    st.caption(
        f"Source: {row['Format Source']}"
    )

    v1, v2, v3, v4 = st.columns(
        4
    )

    v1.metric(
        "Sales",
        f"{int(row['Sales']):,}",
    )

    v2.metric(
        "GMV",
        f"${float(row['GMV']):,.0f}",
    )

    v3.metric(
        "Sales / 1K",
        f"{row['Sales / 1K Views']:.3f}",
    )

    v4.metric(
        "Engagement",
        f"{row['Engagement Rate']:.2f}%",
    )

    if row[
        "Reviewed"
    ]:
        if row[
            "Manual Details"
        ]:
            st.write(
                "**Observed creative details:**"
            )

            for detail in row[
                "Manual Details"
            ]:
                st.write(
                    f"• {detail}"
                )

        if row[
            "Manual Notes"
        ]:
            st.write(
                "**Review notes:**"
            )

            st.write(
                row[
                    "Manual Notes"
                ]
            )

    elif row[
        "Needs Review"
    ]:
        st.warning(
            "👁️ Visual review recommended: the caption does not "
            "contain enough information to explain why this video worked."
        )

    st.caption(
        f"Video ID: {row['Video ID']}"
    )

    st.divider()


# ==================================================
# UNRESOLVED VISUAL REVIEW QUEUE
# ==================================================

st.subheader(
    "👁️ Visual Review Needed"
)

st.caption(
    "These videos still have weak caption information "
    "and have not been manually reviewed."
)

visual_review_df = video_df[
    video_df[
        "Needs Review"
    ]
].copy()

visual_review_df = visual_review_df.sort_values(
    "Sales / 1K Views",
    ascending=False,
)


if visual_review_df.empty:
    st.success(
        "No unresolved visual reviews remain."
    )

else:
    visual_display = visual_review_df[
        [
            "Caption",
            "Views",
            "Sales",
            "GMV",
            "Sales / 1K Views",
            "Engagement Rate",
            "Video ID",
        ]
    ].copy()

    visual_display = visual_display.rename(
        columns={
            "Sales": "Attributed Sales",
            "GMV": "Attributed GMV",
            "Engagement Rate": "Engagement %",
        }
    )

    st.dataframe(
        visual_display,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# MANUALLY REVIEWED VIDEOS
# ==================================================

reviewed_df = video_df[
    video_df[
        "Reviewed"
    ]
].copy()


if not reviewed_df.empty:
    st.divider()

    st.subheader(
        "✅ Manually Reviewed Videos"
    )

    reviewed_display = reviewed_df[
        [
            "Caption",
            "Views",
            "Sales",
            "Sales / 1K Views",
            "Hooks",
            "Selling Angles",
            "Formats",
            "Reviewed At",
            "Video ID",
        ]
    ].copy()

    reviewed_display[
        "Hooks"
    ] = reviewed_display[
        "Hooks"
    ].apply(
        lambda values:
            " • ".join(values)
    )

    reviewed_display[
        "Selling Angles"
    ] = reviewed_display[
        "Selling Angles"
    ].apply(
        lambda values:
            " • ".join(values)
    )

    reviewed_display[
        "Formats"
    ] = reviewed_display[
        "Formats"
    ].apply(
        lambda values:
            " • ".join(values)
    )

    reviewed_display = reviewed_display.rename(
        columns={
            "Sales": "Attributed Sales"
        }
    )

    st.dataframe(
        reviewed_display,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# VISUAL REVIEW WORKSPACE
#
# All videos originally needing visual review stay
# editable here, even after being reviewed.
# ==================================================

workspace_df = video_df[
    video_df[
        "Caption Needs Review"
    ]
].copy()


if not workspace_df.empty:
    workspace_df[
        "_reviewed_sort"
    ] = workspace_df[
        "Reviewed"
    ].astype(
        int
    )

    workspace_df = workspace_df.sort_values(
        [
            "_reviewed_sort",
            "Sales / 1K Views",
        ],
        ascending=[
            True,
            False,
        ],
    )

    st.divider()

    st.subheader(
        "🎬 Visual Review Workspace"
    )

    st.caption(
        "Unreviewed videos appear first. "
        "Reviewed videos remain selectable so labels can be edited."
    )

    review_video_ids = workspace_df[
        "Video ID"
    ].tolist()

    label_lookup = {}

    for _, row in workspace_df.iterrows():
        marker = (
            "✅"
            if row[
                "Reviewed"
            ]
            else "⬜"
        )

        label_lookup[
            row[
                "Video ID"
            ]
        ] = (
            f"{marker} "
            f"{int(row['Views']):,} views • "
            f"{int(row['Sales']):,} sales • "
            f"{row['Sales / 1K Views']:.3f}/1K • "
            f"{row['Video ID']}"
        )

    selected_video_id = st.selectbox(
        "Choose a video to review",
        review_video_ids,
        format_func=lambda value:
            label_lookup[
                value
            ],
    )

    review_row = workspace_df[
        workspace_df[
            "Video ID"
        ] == selected_video_id
    ].iloc[0]

    existing_review = load_review(
        product_id,
        selected_video_id,
    )

    st.write(
        f"### {int(review_row['Views']):,} views"
    )

    if str(
        review_row[
            "Caption"
        ]
    ).strip():
        st.write(
            review_row[
                "Caption"
            ]
        )
    else:
        st.caption(
            "No caption available."
        )

    r1, r2, r3, r4 = st.columns(
        4
    )

    r1.metric(
        "Sales",
        f"{int(review_row['Sales']):,}",
    )

    r2.metric(
        "GMV",
        f"${float(review_row['GMV']):,.0f}",
    )

    r3.metric(
        "Sales / 1K",
        f"{review_row['Sales / 1K Views']:.3f}",
    )

    r4.metric(
        "Engagement",
        f"{review_row['Engagement Rate']:.2f}%",
    )

    player_url = (
        "https://www.tiktok.com/player/v1/"
        + selected_video_id
    )

    st.iframe(
        player_url,
        height=650,
    )

    st.caption(
        "If TikTok reports the video as unavailable, "
        "choose another review item."
    )


    # ==================================================
    # MANUAL OPTIONS
    # ==================================================

    MANUAL_HOOK_OPTIONS = [
        "👀 Curiosity / Pattern Interrupt",
        "😱 Shock / Reaction",
        "🎯 Direct Claim",
        "💬 Comment Reply",
        "📖 Story / Storytime",
        "❓ Question",
        "⏰ Urgency / Scarcity",
        "🎭 Visual Pattern Interrupt",
        "🔥 Controversy / Hot Take",
        "🧪 Demonstration Hook",
        "💸 Deal / Offer Hook",
    ]

    MANUAL_SELLING_OPTIONS = [
        "❤️ Testimonial / Personal Proof",
        "😍 Attraction / Partner Reaction",
        "✨ Transformation / Desired Result",
        "🧪 Problem → Solution",
        "💸 Deal / Value",
        "🎯 Identity / Audience",
        "📚 Education / Ingredient Story",
        "🔥 Viral / Social Proof",
        "🏆 Quality / Premium",
        "😌 Convenience / Ease",
        "🎁 Gift / Occasion",
        "😨 Fear / Pain Avoidance",
        "🌟 Aspirational Lifestyle",
    ]

    MANUAL_FORMAT_OPTIONS = [
        "🗣️ Talking Head / UGC",
        "🎥 Product Demonstration",
        "🎭 POV / Skit",
        "😱 Reaction",
        "💬 Comment Reply",
        "🎙️ Voiceover",
        "✨ Before / After",
        "🧾 Recommendation / Review",
        "📦 Unboxing",
        "📚 Educational Explainer",
        "📹 Lifestyle / B-Roll",
        "👥 Partner / Couple Content",
        "🛒 Deal / Promotion",
    ]

    MANUAL_DETAIL_OPTIONS = [
        "Product shown in first 3 seconds",
        "Face visible in opening frame",
        "On-screen text in opening",
        "Spoken hook immediately",
        "Before / after proof",
        "Physical product demonstration",
        "Partner reaction shown",
        "Creator reaction shown",
        "Close-up product shot",
        "Comment screenshot shown",
        "Price / discount shown",
        "Strong call to action",
        "Fast cuts / high editing pace",
        "Storytelling structure",
        "Benefit shown visually",
        "Result shown visually",
        "Social proof shown",
        "Multiple products compared",
    ]


    default_hooks = (
        existing_review[
            "hooks"
        ]
        if existing_review
        else []
    )

    default_angles = (
        existing_review[
            "selling_angles"
        ]
        if existing_review
        else []
    )

    default_formats = (
        existing_review[
            "formats"
        ]
        if existing_review
        else []
    )

    default_details = (
        existing_review[
            "details"
        ]
        if existing_review
        else []
    )

    default_notes = (
        existing_review[
            "notes"
        ]
        if existing_review
        else ""
    )


    st.write(
        "### Label what you actually see"
    )

    if existing_review:
        st.success(
            "This video already has a manual review. "
            "Saving again will update it."
        )

    manual_hooks = st.multiselect(
        "🎣 Hook",
        MANUAL_HOOK_OPTIONS,
        default=default_hooks,
        key=f"hooks_{selected_video_id}",
    )

    manual_angles = st.multiselect(
        "🎯 Selling angle",
        MANUAL_SELLING_OPTIONS,
        default=default_angles,
        key=f"angles_{selected_video_id}",
    )

    manual_formats = st.multiselect(
        "🎥 Format",
        MANUAL_FORMAT_OPTIONS,
        default=default_formats,
        key=f"formats_{selected_video_id}",
    )

    manual_details = st.multiselect(
        "🔍 Creative details",
        MANUAL_DETAIL_OPTIONS,
        default=default_details,
        key=f"details_{selected_video_id}",
    )

    manual_notes = st.text_area(
        "📝 Notes",
        value=default_notes,
        placeholder=(
            "Example: creator opens with a reaction, "
            "shows the perfume bottle, explains the benefit, "
            "then ends with a CTA."
        ),
        key=f"notes_{selected_video_id}",
    )

    if existing_review:
        st.caption(
            "Last saved: "
            + str(
                existing_review[
                    "reviewed_at"
                ]
            )
        )

    if st.button(
        "💾 Save Visual Review",
        type="primary",
        key=f"save_{selected_video_id}",
    ):
        reviewed_at = save_review(
            product_id=product_id,
            video_id=selected_video_id,
            hooks=manual_hooks,
            selling_angles=manual_angles,
            formats=manual_formats,
            details=manual_details,
            notes=manual_notes,
        )

        st.success(
            f"Review saved locally at {reviewed_at}."
        )

        st.rerun()


# ==================================================
# FOOTER
# ==================================================

st.divider()

st.caption(
    "Creative Intelligence hierarchy: "
    "**manual visual review → caption heuristic fallback**."
)

st.caption(
    "If a manually reviewed category is left blank, "
    "FlipRadar keeps the caption-based classification "
    "for that category."
)

st.caption(
    "Manual reviews are stored locally in flipradar.db "
    "and persist across Streamlit restarts."
)

st.caption(
    "Opening TikTok embeds and saving manual reviews "
    "uses zero EchoTik API requests."
)

if content_scan_time:
    st.caption(
        f"Content dataset cached: {content_scan_time}"
    )