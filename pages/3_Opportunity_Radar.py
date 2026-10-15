import math

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
    classify_market_stage
)


# ==================================================
# CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar Opportunity Radar",
    page_icon="📡",
    layout="wide"
)


initialize_database()
initialize_content_database()


# ==================================================
# HEADER
# ==================================================

st.title(
    "📡 Opportunity Radar"
)


st.caption(
    "Separate early product discovery from mature-product "
    "resurgence and creative research."
)


st.info(
    "This page only uses saved product and content data. "
    "Refreshing it uses **zero EchoTik API requests**."
)


# ==================================================
# LOAD PRODUCTS
# ==================================================

products, market_scan_time = (
    load_latest_scan()
)


if not products:

    st.warning(
        "No saved product scan exists yet."
    )

    st.stop()


# ==================================================
# HELPERS
# ==================================================

def safe_float(
    value,
    default=0.0
):

    try:

        return float(
            value
        )

    except (
        TypeError,
        ValueError
    ):

        return default


def safe_int(
    value,
    default=0
):

    try:

        return int(
            float(
                value
            )
        )

    except (
        TypeError,
        ValueError
    ):

        return default


def clamp(
    value,
    minimum=0,
    maximum=100
):

    return max(
        minimum,
        min(
            value,
            maximum
        )
    )


def short_stage(
    label
):

    replacements = {

        "🚀 Early Breakout Candidate":
            "🚀 Early Breakout",

        "📈 Emerging Breakout":
            "📈 Emerging Breakout",

        "🏆 Mature Winner":
            "🏆 Mature Winner",

        "🧠 Proven Creative / Mature Product":
            "🧠 Proven Creative",

        "🎬 Creative-Led Watch":
            "🎬 Creative-Led",

        "💰 Commerce-Led Watch":
            "💰 Commerce-Led",

        "📉 Cooling":
            "📉 Cooling",

        "👀 Mixed-Signal Watch":
            "👀 Mixed Watch",

        "🌱 Early but Unproven":
            "🌱 Early / Unproven",

        "➡️ Low Signal":
            "➡️ Low Signal"
    }


    return replacements.get(
        label,
        label
    )


# ==================================================
# EARLY DISCOVERY PRIORITY
#
# Used ONLY for products <= 365 days old.
#
# Product Score        35
# Positive Momentum    30
# Freshness            20
# 7D Sales             10
# Low Saturation        5
#
# TOTAL               100
# ==================================================

def calculate_early_scan_priority(
    product
):

    product_score = safe_float(
        product.get(
            "score",
            0
        )
    )


    momentum = safe_float(
        product.get(
            "growth",
            0
        )
    )


    age_days = safe_int(
        product.get(
            "age_days",
            9999
        )
    )


    seven_day_sales = safe_int(
        product.get(
            "seven_day_sales",
            0
        )
    )


    promotions = safe_int(
        product.get(
            "promotion_count_7d",
            0
        )
    )


    # ==================================================
    # PRODUCT SCORE
    # MAX 35
    # ==================================================

    product_points = clamp(
        (
            product_score
            / 100
        ) * 35,
        0,
        35
    )


    # ==================================================
    # MOMENTUM
    # MAX 30
    #
    # Full points at +100%.
    # Negative growth gets zero.
    # ==================================================

    momentum_points = clamp(
        (
            max(
                momentum,
                0
            )
            / 100
        ) * 30,
        0,
        30
    )


    # ==================================================
    # FRESHNESS
    # MAX 20
    #
    # Mature products lose most freshness value.
    # ==================================================

    if age_days <= 60:

        freshness_points = 20


    elif age_days <= 120:

        freshness_points = 17


    elif age_days <= 180:

        freshness_points = 14


    elif age_days <= 365:

        freshness_points = 6


    else:

        freshness_points = 0


    # ==================================================
    # SALES VALIDATION
    # MAX 10
    # ==================================================

    if seven_day_sales <= 0:

        sales_points = 0

    else:

        sales_points = (

            math.log1p(
                seven_day_sales
            )

            / math.log1p(
                10000
            )

        ) * 10


    sales_points = clamp(
        sales_points,
        0,
        10
    )


    # ==================================================
    # LOW PROMOTION SATURATION
    # MAX 5
    # ==================================================

    if promotions <= 100:

        saturation_points = 5


    elif promotions <= 300:

        saturation_points = 4


    elif promotions <= 750:

        saturation_points = 3


    elif promotions <= 1500:

        saturation_points = 2


    elif promotions <= 3000:

        saturation_points = 1


    else:

        saturation_points = 0


    total = (
        product_points
        + momentum_points
        + freshness_points
        + sales_points
        + saturation_points
    )


    return {

        "score":
            round(
                clamp(
                    total
                ),
                1
            ),

        "breakdown": {

            "Product Score":
                round(
                    product_points,
                    1
                ),

            "Positive Momentum":
                round(
                    momentum_points,
                    1
                ),

            "Freshness":
                round(
                    freshness_points,
                    1
                ),

            "7D Sales Validation":
                round(
                    sales_points,
                    1
                ),

            "Low Promotion Saturation":
                round(
                    saturation_points,
                    1
                )
        }
    }


def early_priority_label(
    score
):

    score = safe_float(
        score
    )


    if score >= 75:

        return "🚀 Scan Next"


    if score >= 60:

        return "📈 High Priority"


    if score >= 45:

        return "👀 Worth Scanning"


    if score >= 30:

        return "➡️ Lower Priority"


    return "⏸ Low Priority"


# ==================================================
# RESURGENCE PRIORITY
#
# Used ONLY for products >365 days old.
#
# This is NOT an early-product score.
#
# It asks:
#
# "Is an older product suddenly re-accelerating?"
#
# Momentum            40
# Sales Scale         25
# Low Promotions      20
# Product Strength    15
#
# TOTAL              100
# ==================================================

def calculate_resurgence_priority(
    product
):

    product_score = safe_float(
        product.get(
            "score",
            0
        )
    )


    momentum = safe_float(
        product.get(
            "growth",
            0
        )
    )


    sales = safe_int(
        product.get(
            "seven_day_sales",
            0
        )
    )


    promotions = safe_int(
        product.get(
            "promotion_count_7d",
            0
        )
    )


    # ==================================================
    # MOMENTUM
    # MAX 40
    #
    # Full at +200%.
    # ==================================================

    momentum_points = clamp(
        (
            max(
                momentum,
                0
            )
            / 200
        ) * 40,
        0,
        40
    )


    # ==================================================
    # SALES SCALE
    # MAX 25
    #
    # Roughly 20K 7-day sales reaches full points.
    # ==================================================

    if sales <= 0:

        sales_points = 0

    else:

        sales_points = (

            math.log1p(
                sales
            )

            / math.log1p(
                20000
            )

        ) * 25


    sales_points = clamp(
        sales_points,
        0,
        25
    )


    # ==================================================
    # LOW PROMOTION LOAD
    # MAX 20
    # ==================================================

    if promotions <= 50:

        promo_points = 20


    elif promotions <= 100:

        promo_points = 18


    elif promotions <= 300:

        promo_points = 14


    elif promotions <= 750:

        promo_points = 8


    elif promotions <= 1500:

        promo_points = 4


    else:

        promo_points = 0


    # ==================================================
    # PRODUCT STRENGTH
    # MAX 15
    # ==================================================

    product_points = clamp(
        (
            product_score
            / 100
        ) * 15,
        0,
        15
    )


    total = (
        momentum_points
        + sales_points
        + promo_points
        + product_points
    )


    return {

        "score":
            round(
                clamp(
                    total
                ),
                1
            ),

        "breakdown": {

            "Renewed Momentum":
                round(
                    momentum_points,
                    1
                ),

            "7D Sales Scale":
                round(
                    sales_points,
                    1
                ),

            "Low Promotion Load":
                round(
                    promo_points,
                    1
                ),

            "Product Strength":
                round(
                    product_points,
                    1
                )
        }
    }


def resurgence_label(
    score
):

    score = safe_float(
        score
    )


    if score >= 80:

        return "🔥 Strong Resurgence"


    if score >= 65:

        return "♻️ Resurgence Candidate"


    if score >= 50:

        return "👀 Resurgence Watch"


    return "➡️ Weak Resurgence"


# ==================================================
# REASON HELPERS
# ==================================================

def early_reasons(
    product
):

    reasons = []


    age = safe_int(
        product.get(
            "age_days",
            0
        )
    )


    momentum = safe_float(
        product.get(
            "growth",
            0
        )
    )


    sales = safe_int(
        product.get(
            "seven_day_sales",
            0
        )
    )


    promotions = safe_int(
        product.get(
            "promotion_count_7d",
            0
        )
    )


    product_score = safe_float(
        product.get(
            "score",
            0
        )
    )


    if age <= 60:

        reasons.append(
            f"Very fresh product at {age} days"
        )


    elif age <= 180:

        reasons.append(
            f"Young product at {age} days"
        )


    else:

        reasons.append(
            f"Still inside the discovery window at {age} days"
        )


    if momentum >= 100:

        reasons.append(
            f"Explosive +{momentum:.1f}% sales momentum"
        )


    elif momentum >= 50:

        reasons.append(
            f"Strong +{momentum:.1f}% sales momentum"
        )


    elif momentum >= 20:

        reasons.append(
            f"Positive +{momentum:.1f}% sales momentum"
        )


    if sales >= 1000:

        reasons.append(
            f"{sales:,} sales in the last 7 days"
        )


    if promotions <= 300:

        reasons.append(
            f"Only {promotions:,} recent promotions"
        )


    if product_score >= 60:

        reasons.append(
            f"Product Score is {product_score:.1f}"
        )


    return reasons


def resurgence_reasons(
    product
):

    reasons = []


    age = safe_int(
        product.get(
            "age_days",
            0
        )
    )


    momentum = safe_float(
        product.get(
            "growth",
            0
        )
    )


    sales = safe_int(
        product.get(
            "seven_day_sales",
            0
        )
    )


    promotions = safe_int(
        product.get(
            "promotion_count_7d",
            0
        )
    )


    reasons.append(
        f"Mature product at {age} days old"
    )


    if momentum > 0:

        reasons.append(
            f"Renewed sales acceleration of +{momentum:.1f}%"
        )


    if sales >= 1000:

        reasons.append(
            f"{sales:,} sales in the last 7 days"
        )


    if promotions <= 300:

        reasons.append(
            f"Only {promotions:,} recent promotions"
        )


    return reasons


# ==================================================
# BUILD RADAR DATA
# ==================================================

rows = []


for product in products:

    product_id = str(
        product.get(
            "id",
            ""
        )
    )


    product_name = str(
        product.get(
            "name",
            "Unknown Product"
        )
    )


    product_score = safe_float(
        product.get(
            "score",
            0
        )
    )


    growth = safe_float(
        product.get(
            "growth",
            0
        )
    )


    age_days = safe_int(
        product.get(
            "age_days",
            0
        )
    )


    seven_day_sales = safe_int(
        product.get(
            "seven_day_sales",
            0
        )
    )


    promotion_count = safe_int(
        product.get(
            "promotion_count_7d",
            0
        )
    )


    price = safe_float(
        product.get(
            "price",
            0
        )
    )


    early_result = (
        calculate_early_scan_priority(
            product
        )
    )


    resurgence_result = (
        calculate_resurgence_priority(
            product
        )
    )


    videos, content_scan_time = (
        load_content_scan(
            product_id
        )
    )


    content_score = None
    commerce_score = None
    opportunity_score = None
    stage_label = "Needs Content Scan"

    videos_1m = None
    sampled_views = None
    attributed_sales = None


    if videos:

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


        content_score = safe_float(
            content_result[
                "score"
            ]
        )


        commerce_score = safe_float(
            commerce_result[
                "score"
            ]
        )


        opportunity_score = (
            calculate_opportunity_score(
                product_score,
                content_score,
                commerce_score
            )
        )


        stage = classify_market_stage(
            product,
            content_score,
            commerce_score,
            opportunity_score
        )


        stage_label = stage[
            "label"
        ]


        metrics = content_result[
            "metrics"
        ]


        videos_1m = safe_int(
            metrics.get(
                "videos_1m",
                0
            )
        )


        sampled_views = safe_int(
            metrics.get(
                "total_views",
                0
            )
        )


        attributed_sales = safe_int(
            metrics.get(
                "total_sales",
                0
            )
        )


    rows.append(
        {

            "Product":
                product_name,

            "Product ID":
                product_id,

            "Full Stage":
                stage_label,

            "Stage":
                short_stage(
                    stage_label
                )
                if videos
                else "⚪ Needs Content Scan",

            "Opportunity":
                opportunity_score,

            "Product Score":
                round(
                    product_score,
                    1
                ),

            "Content Score":
                content_score,

            "Commerce Score":
                commerce_score,

            "Early Priority":
                early_result[
                    "score"
                ],

            "Early Priority Label":
                early_priority_label(
                    early_result[
                        "score"
                    ]
                ),

            "Resurgence Priority":
                resurgence_result[
                    "score"
                ],

            "Resurgence Label":
                resurgence_label(
                    resurgence_result[
                        "score"
                    ]
                ),

            "Momentum":
                round(
                    growth,
                    1
                ),

            "7D Sales":
                seven_day_sales,

            "Age":
                age_days,

            "7D Promotions":
                promotion_count,

            "Price":
                price,

            "Videos 1M+":
                videos_1m,

            "Sampled Views":
                sampled_views,

            "Attributed Sales":
                attributed_sales,

            "Content Scan":
                (
                    "✅ Scanned"
                    if videos
                    else "⚪ Not Scanned"
                ),

            "Content Scan Time":
                content_scan_time or ""
        }
    )


df = pd.DataFrame(
    rows
)


# ==================================================
# TOP SUMMARY
# ==================================================

scanned_count = int(
    (
        df[
            "Content Scan"
        ]
        == "✅ Scanned"
    ).sum()
)


early_breakout_count = int(
    df[
        "Full Stage"
    ].astype(
        str
    ).str.contains(
        "Early Breakout",
        regex=False
    ).sum()
)


emerging_count = int(
    df[
        "Full Stage"
    ].astype(
        str
    ).str.contains(
        "Emerging Breakout",
        regex=False
    ).sum()
)


proven_creative_count = int(
    df[
        "Full Stage"
    ].astype(
        str
    ).str.contains(
        "Proven Creative",
        regex=False
    ).sum()
)


st.divider()


m1, m2, m3, m4, m5 = st.columns(
    5
)


m1.metric(
    "Products",
    len(
        df
    )
)


m2.metric(
    "Content Scanned",
    scanned_count
)


m3.metric(
    "🚀 Early Breakouts",
    early_breakout_count
)


m4.metric(
    "📈 Emerging",
    emerging_count
)


m5.metric(
    "🧠 Proven Creative",
    proven_creative_count
)


# ==================================================
# FILTERS
# ==================================================

st.divider()

st.subheader(
    "Radar Filters"
)


f1, f2, f3 = st.columns(
    3
)


with f1:

    scan_filter = st.selectbox(
        "Content status",
        [
            "All Products",
            "Content Scanned",
            "Needs Content Scan"
        ]
    )


with f2:

    minimum_product_score = st.slider(
        "Minimum Product Score",
        0,
        100,
        0,
        5
    )


with f3:

    minimum_momentum = st.slider(
        "Minimum Sales Momentum",
        -100,
        300,
        -100,
        10
    )


filtered = df.copy()


filtered = filtered[
    filtered[
        "Product Score"
    ] >= minimum_product_score
]


filtered = filtered[
    filtered[
        "Momentum"
    ] >= minimum_momentum
]


if scan_filter == "Content Scanned":

    filtered = filtered[
        filtered[
            "Content Scan"
        ]
        == "✅ Scanned"
    ]


elif scan_filter == "Needs Content Scan":

    filtered = filtered[
        filtered[
            "Content Scan"
        ]
        == "⚪ Not Scanned"
    ]


# ==================================================
# EARLY DISCOVERY CANDIDATES
#
# HARD RULE:
# >365 days does NOT enter this queue.
# ==================================================

early_candidates = filtered[
    (
        filtered[
            "Content Scan"
        ]
        == "⚪ Not Scanned"
    )
    &
    (
        filtered[
            "Age"
        ]
        <= 365
    )
].copy()


early_candidates = early_candidates.sort_values(
    "Early Priority",
    ascending=False
)


# ==================================================
# RECOMMENDED NEXT EARLY SCAN
# ==================================================

st.divider()

st.subheader(
    "🚀 Recommended Next Early Content Scan"
)


if early_candidates.empty:

    st.info(
        "No unscanned products inside the 365-day "
        "early-discovery window match the current filters."
    )


else:

    next_early = early_candidates.iloc[
        0
    ]


    source_product = next(

        product

        for product in products

        if str(
            product.get(
                "id",
                ""
            )
        )
        == str(
            next_early[
                "Product ID"
            ]
        )
    )


    st.write(
        f"## {next_early['Product']}"
    )


    e1, e2, e3, e4 = st.columns(
        4
    )


    e1.metric(
        "Early Scan Priority",
        f"{float(next_early['Early Priority']):.1f} / 100"
    )


    e2.metric(
        "Product Score",
        f"{float(next_early['Product Score']):.1f}"
    )


    e3.metric(
        "Momentum",
        f"{float(next_early['Momentum']):+.1f}%"
    )


    e4.metric(
        "Age",
        f"{int(next_early['Age'])} days"
    )


    st.write(
        f"### {next_early['Early Priority Label']}"
    )


    st.caption(
        "Only products 365 days old or younger can "
        "become the recommended early Content Deep Scan."
    )


    for reason in early_reasons(
        source_product
    ):

        st.write(
            f"• {reason}"
        )


    priority_result = (
        calculate_early_scan_priority(
            source_product
        )
    )


    with st.expander(
        "See Early Scan Priority breakdown"
    ):

        breakdown_rows = []


        maximums = {

            "Product Score":
                35,

            "Positive Momentum":
                30,

            "Freshness":
                20,

            "7D Sales Validation":
                10,

            "Low Promotion Saturation":
                5
        }


        for signal, points in priority_result[
            "breakdown"
        ].items():

            breakdown_rows.append(
                {

                    "Signal":
                        signal,

                    "Points":
                        points,

                    "Maximum":
                        maximums[
                            signal
                        ]
                }
            )


        st.dataframe(
            pd.DataFrame(
                breakdown_rows
            ),
            width="stretch",
            hide_index=True
        )


# ==================================================
# EARLY DISCOVERY QUEUE
# ==================================================

st.divider()

st.subheader(
    "🚀 Early Discovery Queue"
)


st.caption(
    "Only unscanned products 365 days old or younger appear here."
)


if early_candidates.empty:

    st.info(
        "No early-stage candidates are currently available."
    )


else:

    early_display = early_candidates[
        [
            "Product",
            "Early Priority Label",
            "Early Priority",
            "Product Score",
            "Momentum",
            "7D Sales",
            "Age",
            "7D Promotions",
            "Price"
        ]
    ].copy()


    early_display = early_display.rename(
        columns={

            "Product":
                "Product Name",

            "Early Priority Label":
                "Priority",

            "Early Priority":
                "Scan Priority",

            "Momentum":
                "Momentum %",

            "Age":
                "Age Days",

            "7D Promotions":
                "7D Promos"
        }
    )


    st.dataframe(
        early_display,
        width="stretch",
        hide_index=True,
        column_config={

            "Scan Priority":
                st.column_config.ProgressColumn(
                    "Scan Priority",
                    min_value=0,
                    max_value=100,
                    format="%.1f"
                ),

            "Product Score":
                st.column_config.NumberColumn(
                    "Product Score",
                    format="%.1f"
                ),

            "Momentum %":
                st.column_config.NumberColumn(
                    "Momentum %",
                    format="%.1f%%"
                ),

            "Price":
                st.column_config.NumberColumn(
                    "Price",
                    format="$%.2f"
                )
        }
    )


# ==================================================
# RESURGENCE WATCH
# ==================================================

resurgence_candidates = filtered[
    (
        filtered[
            "Content Scan"
        ]
        == "⚪ Not Scanned"
    )
    &
    (
        filtered[
            "Age"
        ]
        > 365
    )
    &
    (
        filtered[
            "Momentum"
        ]
        > 0
    )
].copy()


resurgence_candidates = (
    resurgence_candidates
    .sort_values(
        "Resurgence Priority",
        ascending=False
    )
)


st.divider()

st.subheader(
    "♻️ Resurgence Watch"
)


st.caption(
    "Older products are kept separate from early discovery. "
    "These may be useful for identifying renewed trends, "
    "new creative angles, or second-wave demand."
)


if resurgence_candidates.empty:

    st.info(
        "No mature unscanned products currently show "
        "positive resurgence signals."
    )


else:

    top_resurgence = (
        resurgence_candidates
        .iloc[
            0
        ]
    )


    source_product = next(

        product

        for product in products

        if str(
            product.get(
                "id",
                ""
            )
        )
        == str(
            top_resurgence[
                "Product ID"
            ]
        )
    )


    st.write(
        f"### {top_resurgence['Product']}"
    )


    r1, r2, r3, r4 = st.columns(
        4
    )


    r1.metric(
        "Resurgence Score",
        f"{float(top_resurgence['Resurgence Priority']):.1f}"
    )


    r2.metric(
        "Momentum",
        f"{float(top_resurgence['Momentum']):+.1f}%"
    )


    r3.metric(
        "7D Sales",
        f"{int(top_resurgence['7D Sales']):,}"
    )


    r4.metric(
        "Age",
        f"{int(top_resurgence['Age'])} days"
    )


    st.write(
        f"**{top_resurgence['Resurgence Label']}**"
    )


    for reason in resurgence_reasons(
        source_product
    ):

        st.write(
            f"• {reason}"
        )


    resurgence_display = (
        resurgence_candidates[
            [
                "Product",
                "Resurgence Label",
                "Resurgence Priority",
                "Product Score",
                "Momentum",
                "7D Sales",
                "Age",
                "7D Promotions",
                "Price"
            ]
        ].copy()
    )


    resurgence_display = (
        resurgence_display.rename(
            columns={

                "Product":
                    "Product Name",

                "Resurgence Label":
                    "Signal",

                "Resurgence Priority":
                    "Resurgence Score",

                "Momentum":
                    "Momentum %",

                "Age":
                    "Age Days",

                "7D Promotions":
                    "7D Promos"
            }
        )
    )


    st.dataframe(
        resurgence_display,
        width="stretch",
        hide_index=True,
        column_config={

            "Resurgence Score":
                st.column_config.ProgressColumn(
                    "Resurgence Score",
                    min_value=0,
                    max_value=100,
                    format="%.1f"
                ),

            "Momentum %":
                st.column_config.NumberColumn(
                    "Momentum %",
                    format="%.1f%%"
                ),

            "Price":
                st.column_config.NumberColumn(
                    "Price",
                    format="$%.2f"
                )
        }
    )


# ==================================================
# FULLY SCORED OPPORTUNITIES
# ==================================================

st.divider()

st.subheader(
    "🎯 Fully Scored Opportunities"
)


complete = filtered[
    filtered[
        "Opportunity"
    ].notna()
].copy()


if complete.empty:

    st.info(
        "No fully scored products match the filters."
    )


else:

    complete = complete.sort_values(
        "Opportunity",
        ascending=False
    )


    complete_display = complete[
        [
            "Product",
            "Stage",
            "Opportunity",
            "Product Score",
            "Content Score",
            "Commerce Score",
            "Momentum",
            "7D Sales",
            "Age",
            "7D Promotions",
            "Videos 1M+",
            "Sampled Views",
            "Attributed Sales"
        ]
    ].copy()


    complete_display = (
        complete_display.rename(
            columns={

                "Product":
                    "Product Name",

                "Momentum":
                    "Momentum %",

                "Age":
                    "Age Days",

                "7D Promotions":
                    "7D Promos",

                "Attributed Sales":
                    "Video Sales"
            }
        )
    )


    st.dataframe(
        complete_display,
        width="stretch",
        hide_index=True,
        column_config={

            "Opportunity":
                st.column_config.ProgressColumn(
                    "Opportunity",
                    min_value=0,
                    max_value=100,
                    format="%.1f"
                ),

            "Product Score":
                st.column_config.NumberColumn(
                    "Product Score",
                    format="%.1f"
                ),

            "Content Score":
                st.column_config.NumberColumn(
                    "Content Score",
                    format="%.1f"
                ),

            "Commerce Score":
                st.column_config.NumberColumn(
                    "Commerce Score",
                    format="%.1f"
                ),

            "Momentum %":
                st.column_config.NumberColumn(
                    "Momentum %",
                    format="%.1f%%"
                )
        }
    )


# ==================================================
# STAGE BREAKDOWN
# ==================================================

st.divider()

st.subheader(
    "🧭 Stage Breakdown"
)


scored_only = df[
    df[
        "Opportunity"
    ].notna()
].copy()


if not scored_only.empty:

    stage_counts = (

        scored_only[
            "Stage"
        ]

        .value_counts()

        .reset_index()
    )


    stage_counts.columns = [
        "Market Stage",
        "Products"
    ]


    st.dataframe(
        stage_counts,
        width="stretch",
        hide_index=True
    )


else:

    st.info(
        "Run Content Deep Scans to build the "
        "market-stage comparison."
    )


# ==================================================
# NOTES
# ==================================================

st.divider()


st.caption(
    "Early Discovery Priority and Resurgence Score are "
    "separate FlipRadar heuristics. Neither is a guarantee "
    "of future sales or profitability."
)


st.caption(
    "Products older than 365 days are excluded from the "
    "Early Discovery Queue and moved into Resurgence Watch."
)


st.caption(
    "This page makes zero EchoTik requests."
)


if market_scan_time:

    st.caption(
        f"Latest saved product scan: {market_scan_time}"
    )