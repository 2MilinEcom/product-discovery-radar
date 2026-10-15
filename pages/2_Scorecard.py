import pandas as pd
import streamlit as st

from database import (
    initialize_database,
    load_latest_scan
)

from content_database import (
    initialize_content_database,
    load_content_scan
)

from content_scoring import (
    calculate_content_score,
    calculate_commerce_score,
    calculate_opportunity_score,
    classify_market_stage,
    content_label,
    commerce_label,
    opportunity_label
)


# ==================================================
# CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar Scorecard",
    page_icon="🎯",
    layout="wide"
)


initialize_database()
initialize_content_database()


# ==================================================
# HEADER
# ==================================================

st.title(
    "🎯 FlipRadar Scorecard"
)


st.caption(
    "Separate product momentum, content strength, "
    "commerce performance, and market stage."
)


# ==================================================
# LOAD PRODUCTS
# ==================================================

products, market_scan_time = (
    load_latest_scan()
)


if not products:

    st.warning(
        "No saved FlipRadar market scan exists yet."
    )

    st.stop()


# ==================================================
# PRODUCT SELECTOR
# ==================================================

product_names = [

    product[
        "name"
    ]

    for product in products
]


selected_name = st.selectbox(
    "Choose a product",
    product_names
)


selected = next(

    product

    for product in products

    if product[
        "name"
    ] == selected_name
)


product_id = str(
    selected[
        "id"
    ]
)


st.write(
    f"**Product ID:** `{product_id}`"
)


# ==================================================
# LOAD CONTENT CACHE
# ==================================================

videos, content_scan_time = (
    load_content_scan(
        product_id
    )
)


if not videos:

    st.warning(
        "This product does not have a cached Content Deep Scan yet. "
        "Open the Content Scan page and run the 3-lane scan first."
    )

    st.stop()


# ==================================================
# CALCULATE SCORES
# ==================================================

product_score = float(
    selected.get(
        "score",
        0
    )
    or 0
)


content_result = (
    calculate_content_score(
        videos
    )
)


commerce_result = (
    calculate_commerce_score(
        videos
    )
)


content_score = content_result[
    "score"
]


commerce_score = commerce_result[
    "score"
]


opportunity_score = (
    calculate_opportunity_score(
        product_score,
        content_score,
        commerce_score
    )
)


# ==================================================
# MARKET-STAGE CLASSIFICATION
# ==================================================

stage = classify_market_stage(
    selected,
    content_score,
    commerce_score,
    opportunity_score
)


# ==================================================
# SCOREBOARD
# ==================================================

st.divider()

st.subheader(
    "Scoreboard"
)


score1, score2, score3, score4 = (
    st.columns(
        4
    )
)


score1.metric(
    "Product Score",
    f"{product_score:.1f} / 100"
)


score2.metric(
    "Content Score",
    f"{content_score:.1f} / 100"
)


score3.metric(
    "Commerce Score",
    f"{commerce_score:.1f} / 100"
)


score4.metric(
    "Opportunity Score",
    f"{opportunity_score:.1f} / 100"
)


label1, label2, label3, label4 = (
    st.columns(
        4
    )
)


label1.write(
    f"**{selected.get('status', '—')}**"
)


label2.write(
    f"**{content_label(content_score)}**"
)


label3.write(
    f"**{commerce_label(commerce_score)}**"
)


label4.write(
    f"**{opportunity_label(opportunity_score)}**"
)


st.caption(
    "Opportunity Score weighting: "
    "45% Product + 35% Content + 20% Commerce."
)


# ==================================================
# MARKET STAGE
# ==================================================

st.divider()

st.subheader(
    "🧭 Market-Stage Classification"
)


st.write(
    f"## {stage['label']}"
)


st.write(
    f"**{stage['short']}**"
)


if stage[
    "tone"
] == "success":

    st.success(
        stage[
            "description"
        ]
    )


elif stage[
    "tone"
] == "warning":

    st.warning(
        stage[
            "description"
        ]
    )


else:

    st.info(
        stage[
            "description"
        ]
    )


st.write(
    "### Why FlipRadar classified it this way"
)


for reason in stage[
    "reasons"
]:

    st.write(
        f"• {reason}"
    )


# ==================================================
# WHAT THE SCORES MEAN
# ==================================================

st.divider()

st.subheader(
    "What the scores mean"
)


interpret1, interpret2, interpret3 = (
    st.columns(
        3
    )
)


with interpret1:

    st.write(
        "### 📦 Product"
    )

    st.write(
        "Is the product itself currently an attractive "
        "market opportunity?"
    )

    st.caption(
        "Driven by sales momentum, velocity, freshness, "
        "promotion efficiency, price and saturation."
    )


with interpret2:

    st.write(
        "### 🎬 Content"
    )

    st.write(
        "Is TikTok repeatedly producing strong creative "
        "around this product?"
    )

    st.caption(
        "Mostly driven by virality, repeatability, "
        "creator diversity, reach and engagement."
    )


with interpret3:

    st.write(
        "### 💰 Commerce"
    )

    st.write(
        "Is that content actually producing attributed "
        "sales and revenue?"
    )

    st.caption(
        "Driven by sales efficiency, attributed sales, "
        "GMV and conversion repeatability."
    )


# ==================================================
# PRODUCT SIGNALS
# ==================================================

st.divider()

st.subheader(
    "📦 Product Signals"
)


p1, p2, p3, p4 = st.columns(
    4
)


p1.metric(
    "7D Sales",
    f"{int(selected.get('seven_day_sales', 0)):,}"
)


p2.metric(
    "Sales Momentum",
    f"{float(selected.get('growth', 0)):.1f}%"
)


p3.metric(
    "Product Age",
    f"{int(selected.get('age_days', 0))} days"
)


p4.metric(
    "7D Promotions",
    f"{int(selected.get('promotion_count_7d', 0)):,}"
)


# ==================================================
# CONTENT METRICS
# ==================================================

metrics = content_result[
    "metrics"
]


st.divider()

st.subheader(
    "🎬 Content Signals"
)


c1, c2, c3, c4 = st.columns(
    4
)


c1.metric(
    "Sampled Views",
    f"{int(metrics['total_views']):,}"
)


c2.metric(
    "Videos 1M+",
    int(
        metrics[
            "videos_1m"
        ]
    )
)


c3.metric(
    "Unique Creators",
    int(
        metrics[
            "unique_creators"
        ]
    )
)


c4.metric(
    "Top Video Share",
    f"{metrics['top_video_share']:.1f}%"
)


c5, c6, c7, c8 = st.columns(
    4
)


c5.metric(
    "Videos 500K+",
    int(
        metrics[
            "videos_500k"
        ]
    )
)


c6.metric(
    "Videos 100K+",
    int(
        metrics[
            "videos_100k"
        ]
    )
)


c7.metric(
    "Engagement Rate",
    f"{metrics['engagement_rate']:.2f}%"
)


c8.metric(
    "Videos Sampled",
    int(
        metrics[
            "video_count"
        ]
    )
)


# ==================================================
# COMMERCE METRICS
# ==================================================

st.divider()

st.subheader(
    "💰 Commerce Signals"
)


m1, m2, m3, m4 = st.columns(
    4
)


m1.metric(
    "Attributed Sales",
    f"{int(metrics['total_sales']):,}"
)


m2.metric(
    "Attributed GMV",
    f"${metrics['total_gmv']:,.0f}"
)


m3.metric(
    "Sales / 1K Views",
    f"{metrics['sales_per_1000_views']:.3f}"
)


m4.metric(
    "Top Converter Sales",
    f"{int(metrics['top_converter_sales']):,}"
)


# ==================================================
# CONTENT SCORE BREAKDOWN
# ==================================================

st.divider()

st.subheader(
    "🎬 Content Score Breakdown"
)


content_rows = []


for signal, points in content_result[
    "breakdown"
].items():

    maximum = content_result[
        "maximums"
    ][
        signal
    ]


    content_rows.append(
        {

            "Signal":
                signal,

            "Points":
                points,

            "Maximum":
                maximum,

            "Percent of Component":
                round(
                    (
                        points
                        / maximum
                    ) * 100
                    if maximum > 0
                    else 0,
                    1
                )
        }
    )


content_df = pd.DataFrame(
    content_rows
)


st.dataframe(
    content_df,
    width="stretch",
    hide_index=True
)


# ==================================================
# COMMERCE SCORE BREAKDOWN
# ==================================================

st.divider()

st.subheader(
    "💰 Commerce Score Breakdown"
)


commerce_rows = []


for signal, points in commerce_result[
    "breakdown"
].items():

    maximum = commerce_result[
        "maximums"
    ][
        signal
    ]


    commerce_rows.append(
        {

            "Signal":
                signal,

            "Points":
                points,

            "Maximum":
                maximum,

            "Percent of Component":
                round(
                    (
                        points
                        / maximum
                    ) * 100
                    if maximum > 0
                    else 0,
                    1
                )
        }
    )


commerce_df = pd.DataFrame(
    commerce_rows
)


st.dataframe(
    commerce_df,
    width="stretch",
    hide_index=True
)


# ==================================================
# CREATIVE EFFICIENCY
# ==================================================

st.divider()

st.subheader(
    "🧪 Creative Efficiency"
)


video_rows = []


for video in videos:

    views = float(
        video.get(
            "views",
            0
        )
        or 0
    )


    sales = float(
        video.get(
            "video_sales",
            0
        )
        or 0
    )


    if views > 0:

        sales_per_1000 = (
            sales
            / views
        ) * 1000

    else:

        sales_per_1000 = 0


    video_rows.append(
        {

            "Creator":
                (
                    video.get(
                        "creator_username",
                        ""
                    )

                    or video.get(
                        "creator_user_id",
                        ""
                    )

                    or "Unknown"
                ),

            "Caption":
                str(
                    video.get(
                        "caption",
                        ""
                    )
                    or ""
                )[:100],

            "Views":
                int(
                    views
                ),

            "Attributed Sales":
                int(
                    sales
                ),

            "Video GMV":
                float(
                    video.get(
                        "video_gmv",
                        0
                    )
                    or 0
                ),

            "Sales / 1K Views":
                round(
                    sales_per_1000,
                    3
                )
        }
    )


video_df = pd.DataFrame(
    video_rows
)


video_df = video_df.sort_values(
    "Sales / 1K Views",
    ascending=False
)


st.dataframe(
    video_df,
    width="stretch",
    hide_index=True
)


# ==================================================
# NOTES
# ==================================================

st.divider()


st.caption(
    "Market-stage classifications are FlipRadar heuristics. "
    "They are intended to distinguish early breakout products, "
    "mature winners, creative-led opportunities, and cooling products."
)


st.caption(
    "Content and commerce calculations use the cached 3-lane "
    "EchoTik sample, not every TikTok video for the product. "
    "Combined views are summed video view counters, not unique viewers."
)


if content_scan_time:

    st.caption(
        f"Content dataset cached: {content_scan_time}"
    )