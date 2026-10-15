import math


# ==================================================
# HELPERS
# ==================================================

def clamp(value, minimum=0, maximum=100):

    return max(
        minimum,
        min(
            value,
            maximum
        )
    )


def safe_float(value, default=0.0):

    try:

        return float(
            value
        )

    except (
        TypeError,
        ValueError
    ):

        return default


def safe_int(value, default=0):

    try:

        return int(
            float(value)
        )

    except (
        TypeError,
        ValueError
    ):

        return default


def log_score(
    value,
    target,
    max_points
):

    value = max(
        safe_float(
            value
        ),
        0
    )


    target = max(
        safe_float(
            target
        ),
        1
    )


    if value <= 0:

        return 0


    score = (
        math.log1p(
            value
        )
        / math.log1p(
            target
        )
    ) * max_points


    return clamp(
        score,
        0,
        max_points
    )


# ==================================================
# VIDEO METRICS
# ==================================================

def calculate_video_metrics(
    videos
):

    if not videos:

        return {

            "video_count":
                0,

            "total_views":
                0,

            "total_sales":
                0,

            "total_gmv":
                0,

            "total_engagements":
                0,

            "engagement_rate":
                0,

            "sales_per_1000_views":
                0,

            "videos_100k":
                0,

            "videos_500k":
                0,

            "videos_1m":
                0,

            "unique_creators":
                0,

            "top_video_views":
                0,

            "top_video_share":
                0,

            "top_converter_sales":
                0,

            "top_video_gmv":
                0,

            "videos_with_100_sales":
                0
        }


    total_views = sum(

        safe_int(
            video.get(
                "views",
                0
            )
        )

        for video in videos
    )


    total_sales = sum(

        safe_int(
            video.get(
                "video_sales",
                0
            )
        )

        for video in videos
    )


    total_gmv = sum(

        safe_float(
            video.get(
                "video_gmv",
                0
            )
        )

        for video in videos
    )


    total_likes = sum(

        safe_int(
            video.get(
                "likes",
                0
            )
        )

        for video in videos
    )


    total_comments = sum(

        safe_int(
            video.get(
                "comments",
                0
            )
        )

        for video in videos
    )


    total_favorites = sum(

        safe_int(
            video.get(
                "favorites",
                0
            )
        )

        for video in videos
    )


    total_shares = sum(

        safe_int(
            video.get(
                "shares",
                0
            )
        )

        for video in videos
    )


    total_engagements = (
        total_likes
        + total_comments
        + total_favorites
        + total_shares
    )


    if total_views > 0:

        engagement_rate = (
            total_engagements
            / total_views
        ) * 100


        sales_per_1000_views = (
            total_sales
            / total_views
        ) * 1000

    else:

        engagement_rate = 0

        sales_per_1000_views = 0


    videos_100k = sum(

        1

        for video in videos

        if safe_int(
            video.get(
                "views",
                0
            )
        ) >= 100000
    )


    videos_500k = sum(

        1

        for video in videos

        if safe_int(
            video.get(
                "views",
                0
            )
        ) >= 500000
    )


    videos_1m = sum(

        1

        for video in videos

        if safe_int(
            video.get(
                "views",
                0
            )
        ) >= 1000000
    )


    creator_ids = set()


    for video in videos:

        creator_id = str(

            video.get(
                "creator_user_id"
            )

            or video.get(
                "creator"
            )

            or ""

        ).strip()


        if creator_id:

            creator_ids.add(
                creator_id
            )


    top_video_views = max(

        [

            safe_int(
                video.get(
                    "views",
                    0
                )
            )

            for video in videos

        ],

        default=0
    )


    if total_views > 0:

        top_video_share = (
            top_video_views
            / total_views
        ) * 100

    else:

        top_video_share = 0


    top_converter_sales = max(

        [

            safe_int(
                video.get(
                    "video_sales",
                    0
                )
            )

            for video in videos

        ],

        default=0
    )


    top_video_gmv = max(

        [

            safe_float(
                video.get(
                    "video_gmv",
                    0
                )
            )

            for video in videos

        ],

        default=0
    )


    videos_with_100_sales = sum(

        1

        for video in videos

        if safe_int(
            video.get(
                "video_sales",
                0
            )
        ) >= 100
    )


    return {

        "video_count":
            len(
                videos
            ),

        "total_views":
            total_views,

        "total_sales":
            total_sales,

        "total_gmv":
            total_gmv,

        "total_engagements":
            total_engagements,

        "engagement_rate":
            engagement_rate,

        "sales_per_1000_views":
            sales_per_1000_views,

        "videos_100k":
            videos_100k,

        "videos_500k":
            videos_500k,

        "videos_1m":
            videos_1m,

        "unique_creators":
            len(
                creator_ids
            ),

        "top_video_views":
            top_video_views,

        "top_video_share":
            top_video_share,

        "top_converter_sales":
            top_converter_sales,

        "top_video_gmv":
            top_video_gmv,

        "videos_with_100_sales":
            videos_with_100_sales
    }


# ==================================================
# CONTENT SCORE
#
# Content-first:
#
# Viral repeatability            25
# Breakout video count           20
# View scale                     15
# Creator diversity              10
# Engagement quality             10
# Sales efficiency support       15
# Low concentration               5
#
# TOTAL                         100
# ==================================================

def calculate_content_score(
    videos
):

    metrics = calculate_video_metrics(
        videos
    )


    # --------------------------------------------------
    # VIRAL REPEATABILITY
    # MAX 25
    # --------------------------------------------------

    videos_1m = metrics[
        "videos_1m"
    ]


    videos_500k = metrics[
        "videos_500k"
    ]


    videos_100k = metrics[
        "videos_100k"
    ]


    if videos_1m >= 5:

        repeatability_score = 25


    elif videos_1m >= 3:

        repeatability_score = 22


    elif videos_1m == 2:

        repeatability_score = 17


    elif videos_1m == 1:

        repeatability_score = 12


    elif videos_500k >= 3:

        repeatability_score = 9


    elif videos_100k >= 3:

        repeatability_score = 6


    elif videos_100k >= 1:

        repeatability_score = 3


    else:

        repeatability_score = 0


    # --------------------------------------------------
    # BREAKOUT VIDEO COUNT
    # MAX 20
    # --------------------------------------------------

    breakout_score = (

        videos_1m * 4

        + max(
            videos_500k
            - videos_1m,
            0
        ) * 2

        + max(
            videos_100k
            - videos_500k,
            0
        ) * 0.5
    )


    breakout_score = clamp(
        breakout_score,
        0,
        20
    )


    # --------------------------------------------------
    # VIEW SCALE
    # MAX 15
    # --------------------------------------------------

    view_scale_score = log_score(

        metrics[
            "total_views"
        ],

        50000000,

        15
    )


    # --------------------------------------------------
    # CREATOR DIVERSITY
    # MAX 10
    # --------------------------------------------------

    creator_score = clamp(

        (
            metrics[
                "unique_creators"
            ]
            / 8
        ) * 10,

        0,

        10
    )


    # --------------------------------------------------
    # ENGAGEMENT QUALITY
    # MAX 10
    # --------------------------------------------------

    engagement_score = clamp(

        (
            metrics[
                "engagement_rate"
            ]
            / 4
        ) * 10,

        0,

        10
    )


    # --------------------------------------------------
    # SALES EFFICIENCY SUPPORT
    # MAX 15
    #
    # Commerce supports Content Score,
    # but does not dominate it.
    # --------------------------------------------------

    sales_efficiency_score = clamp(

        metrics[
            "sales_per_1000_views"
        ] * 15,

        0,

        15
    )


    # --------------------------------------------------
    # LOW CONCENTRATION / REPEATABILITY
    # MAX 5
    # --------------------------------------------------

    concentration = metrics[
        "top_video_share"
    ]


    if concentration <= 40:

        concentration_score = 5


    elif concentration <= 60:

        concentration_score = (

            5

            - (
                (
                    concentration
                    - 40
                )
                / 20
            ) * 2
        )


    elif concentration <= 80:

        concentration_score = (

            3

            - (
                (
                    concentration
                    - 60
                )
                / 20
            ) * 3
        )


    else:

        concentration_score = 0


    concentration_score = clamp(
        concentration_score,
        0,
        5
    )


    total = (

        repeatability_score
        + breakout_score
        + view_scale_score
        + creator_score
        + engagement_score
        + sales_efficiency_score
        + concentration_score
    )


    return {

        "score":
            round(
                clamp(
                    total
                ),
                1
            ),

        "metrics":
            metrics,

        "breakdown": {

            "Viral Repeatability":
                round(
                    repeatability_score,
                    1
                ),

            "Breakout Videos":
                round(
                    breakout_score,
                    1
                ),

            "View Scale":
                round(
                    view_scale_score,
                    1
                ),

            "Creator Diversity":
                round(
                    creator_score,
                    1
                ),

            "Engagement Quality":
                round(
                    engagement_score,
                    1
                ),

            "Sales Efficiency Support":
                round(
                    sales_efficiency_score,
                    1
                ),

            "Low Viral Concentration":
                round(
                    concentration_score,
                    1
                )
        },

        "maximums": {

            "Viral Repeatability":
                25,

            "Breakout Videos":
                20,

            "View Scale":
                15,

            "Creator Diversity":
                10,

            "Engagement Quality":
                10,

            "Sales Efficiency Support":
                15,

            "Low Viral Concentration":
                5
        }
    }


# ==================================================
# COMMERCE SCORE
# ==================================================

def calculate_commerce_score(
    videos
):

    metrics = calculate_video_metrics(
        videos
    )


    # --------------------------------------------------
    # SALES EFFICIENCY
    # MAX 30
    # --------------------------------------------------

    efficiency_score = clamp(

        (
            metrics[
                "sales_per_1000_views"
            ]
            / 0.75
        ) * 30,

        0,

        30
    )


    # --------------------------------------------------
    # ATTRIBUTED SALES SCALE
    # MAX 25
    # --------------------------------------------------

    sales_scale_score = log_score(

        metrics[
            "total_sales"
        ],

        10000,

        25
    )


    # --------------------------------------------------
    # GMV SCALE
    # MAX 20
    # --------------------------------------------------

    gmv_scale_score = log_score(

        metrics[
            "total_gmv"
        ],

        250000,

        20
    )


    # --------------------------------------------------
    # TOP CONVERTER
    # MAX 15
    # --------------------------------------------------

    top_converter_score = clamp(

        (
            metrics[
                "top_converter_sales"
            ]
            / 1500
        ) * 15,

        0,

        15
    )


    # --------------------------------------------------
    # CONVERSION REPEATABILITY
    # MAX 10
    # --------------------------------------------------

    repeat_conversion_score = clamp(

        (
            metrics[
                "videos_with_100_sales"
            ]
            / 5
        ) * 10,

        0,

        10
    )


    total = (

        efficiency_score
        + sales_scale_score
        + gmv_scale_score
        + top_converter_score
        + repeat_conversion_score
    )


    return {

        "score":
            round(
                clamp(
                    total
                ),
                1
            ),

        "metrics":
            metrics,

        "breakdown": {

            "Sales Efficiency":
                round(
                    efficiency_score,
                    1
                ),

            "Attributed Sales Scale":
                round(
                    sales_scale_score,
                    1
                ),

            "Attributed GMV Scale":
                round(
                    gmv_scale_score,
                    1
                ),

            "Top Converter Strength":
                round(
                    top_converter_score,
                    1
                ),

            "Conversion Repeatability":
                round(
                    repeat_conversion_score,
                    1
                )
        },

        "maximums": {

            "Sales Efficiency":
                30,

            "Attributed Sales Scale":
                25,

            "Attributed GMV Scale":
                20,

            "Top Converter Strength":
                15,

            "Conversion Repeatability":
                10
        }
    }


# ==================================================
# OPPORTUNITY SCORE
#
# Product   45%
# Content   35%
# Commerce  20%
# ==================================================

def calculate_opportunity_score(
    product_score,
    content_score,
    commerce_score
):

    product_score = clamp(
        safe_float(
            product_score
        )
    )


    content_score = clamp(
        safe_float(
            content_score
        )
    )


    commerce_score = clamp(
        safe_float(
            commerce_score
        )
    )


    opportunity_score = (

        product_score * 0.45

        + content_score * 0.35

        + commerce_score * 0.20
    )


    return round(
        clamp(
            opportunity_score
        ),
        1
    )


# ==================================================
# SCORE LABELS
# ==================================================

def content_label(
    score
):

    score = safe_float(
        score
    )


    if score >= 85:

        return "🔥 Exceptional"


    if score >= 70:

        return "📈 Strong"


    if score >= 55:

        return "👀 Promising"


    if score >= 40:

        return "➡️ Moderate"


    return "📉 Weak"


def commerce_label(
    score
):

    score = safe_float(
        score
    )


    if score >= 85:

        return "🔥 Exceptional"


    if score >= 70:

        return "📈 Strong"


    if score >= 55:

        return "👀 Promising"


    if score >= 40:

        return "➡️ Moderate"


    return "📉 Weak"


def opportunity_label(
    score
):

    score = safe_float(
        score
    )


    if score >= 80:

        return "🔥 Breakout Signal"


    if score >= 65:

        return "📈 Strong Signal"


    if score >= 50:

        return "👀 Watch Closely"


    if score >= 35:

        return "➡️ Mixed Signal"


    return "📉 Weak Signal"


# ==================================================
# MARKET-STAGE CLASSIFICATION
#
# This is intentionally separate from Opportunity Score.
#
# It answers:
#
# "WHAT KIND of opportunity is this?"
#
# rather than simply:
#
# "How strong are the metrics?"
# ==================================================

def classify_market_stage(
    product,
    content_score,
    commerce_score,
    opportunity_score
):

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
            9999
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


    content_score = safe_float(
        content_score
    )


    commerce_score = safe_float(
        commerce_score
    )


    opportunity_score = safe_float(
        opportunity_score
    )


    # ==================================================
    # 1. EARLY BREAKOUT
    #
    # Young + accelerating + strong product/content.
    # ==================================================

    if (
        age_days <= 180
        and growth >= 40
        and product_score >= 60
        and content_score >= 65
        and commerce_score >= 50
    ):

        return {

            "label":
                "🚀 Early Breakout Candidate",

            "short":
                "Young product with strong acceleration and validated content.",

            "description":
                (
                    "This is the profile FlipRadar is primarily looking for: "
                    "a relatively young product with accelerating sales, "
                    "repeatable TikTok content, and evidence that the content "
                    "can convert into purchases."
                ),

            "tone":
                "success",

            "reasons": [

                f"Product age is only {age_days} days.",

                f"Sales momentum is +{growth:.1f}%.",

                f"Product Score is {product_score:.1f}.",

                f"Content Score is {content_score:.1f}.",

                f"Commerce Score is {commerce_score:.1f}."
            ]
        }


    # ==================================================
    # 2. EMERGING BREAKOUT
    #
    # Still relatively young with positive acceleration.
    # ==================================================

    if (
        age_days <= 365
        and growth >= 20
        and product_score >= 50
        and content_score >= 55
    ):

        return {

            "label":
                "📈 Emerging Breakout",

            "short":
                "Positive momentum with improving content validation.",

            "description":
                (
                    "The product appears to be gaining traction and has "
                    "meaningful creative support, but it does not yet meet "
                    "FlipRadar's stricter Early Breakout conditions."
                ),

            "tone":
                "success",

            "reasons": [

                f"Product age is {age_days} days.",

                f"Sales momentum is +{growth:.1f}%.",

                f"Product Score is {product_score:.1f}.",

                f"Content Score is {content_score:.1f}."
            ]
        }


    # ==================================================
    # 3. MATURE WINNER
    #
    # Established product that remains commercially strong.
    # ==================================================

    if (
        age_days > 365
        and product_score >= 60
        and content_score >= 70
        and commerce_score >= 65
        and growth >= 0
    ):

        return {

            "label":
                "🏆 Mature Winner",

            "short":
                "Established product that is still performing strongly.",

            "description":
                (
                    "This product is no longer early, but its product metrics, "
                    "content ecosystem, and commerce signals remain strong. "
                    "It is useful as a benchmark for what a proven winner "
                    "looks like."
                ),

            "tone":
                "success",

            "reasons": [

                f"Product has been tracked for {age_days} days.",

                f"Sales momentum remains {growth:+.1f}%.",

                f"Content Score is {content_score:.1f}.",

                f"Commerce Score is {commerce_score:.1f}."
            ]
        }


    # ==================================================
    # 4. PROVEN CREATIVE / MATURE PRODUCT
    #
    # Strong content and commerce, but product itself
    # is old, cooling, or already mature.
    # ==================================================

    if (
        content_score >= 75
        and commerce_score >= 60
        and (
            age_days > 365
            or growth < 0
            or product_score < 50
        )
    ):

        return {

            "label":
                "🧠 Proven Creative / Mature Product",

            "short":
                "Creative formula is proven, but the product is not early.",

            "description":
                (
                    "The TikTok content ecosystem is clearly working and "
                    "producing commerce, but the product itself looks mature, "
                    "cooling, or already well-established. This can be very "
                    "useful for studying hooks, formats, angles, and creators, "
                    "even if the product is no longer an early breakout."
                ),

            "tone":
                "info",

            "reasons": [

                f"Product age is {age_days} days.",

                f"Sales momentum is {growth:+.1f}%.",

                f"Product Score is only {product_score:.1f}.",

                f"Content Score remains strong at {content_score:.1f}.",

                f"Commerce Score remains strong at {commerce_score:.1f}."
            ]
        }


    # ==================================================
    # 5. CREATIVE-LED WATCH
    #
    # Content looks strong before product metrics fully
    # confirm the opportunity.
    # ==================================================

    if (
        content_score >= 70
        and product_score < 55
        and commerce_score < 60
    ):

        return {

            "label":
                "🎬 Creative-Led Watch",

            "short":
                "Content is moving faster than product validation.",

            "description":
                (
                    "TikTok content is showing meaningful traction, but "
                    "product and commerce metrics have not fully confirmed "
                    "the opportunity yet. This may be worth monitoring for "
                    "sales acceleration."
                ),

            "tone":
                "info",

            "reasons": [

                f"Content Score is {content_score:.1f}.",

                f"Product Score is {product_score:.1f}.",

                f"Commerce Score is {commerce_score:.1f}.",

                f"Current sales momentum is {growth:+.1f}%."
            ]
        }


    # ==================================================
    # 6. COMMERCE-LED WATCH
    #
    # Sells efficiently but creative ecosystem is less
    # obviously viral/repeatable.
    # ==================================================

    if (
        commerce_score >= 70
        and content_score < 70
    ):

        return {

            "label":
                "💰 Commerce-Led Watch",

            "short":
                "Commercial performance is stronger than viral breadth.",

            "description":
                (
                    "The content sample converts well, but the broader viral "
                    "or repeatability signal is less developed. This can be "
                    "interesting for performance-driven product research."
                ),

            "tone":
                "info",

            "reasons": [

                f"Commerce Score is {commerce_score:.1f}.",

                f"Content Score is {content_score:.1f}.",

                f"Product Score is {product_score:.1f}."
            ]
        }


    # ==================================================
    # 7. COOLING
    # ==================================================

    if (
        growth <= -20
        and product_score < 50
    ):

        return {

            "label":
                "📉 Cooling",

            "short":
                "Sales momentum is declining and product strength is weak.",

            "description":
                (
                    "The product is currently losing sales momentum. "
                    "Unless content or commerce signals materially improve, "
                    "it is less aligned with FlipRadar's early-breakout goal."
                ),

            "tone":
                "warning",

            "reasons": [

                f"Sales momentum is {growth:.1f}%.",

                f"Product Score is {product_score:.1f}.",

                f"Product age is {age_days} days."
            ]
        }


    # ==================================================
    # 8. MIXED WATCH
    # ==================================================

    if opportunity_score >= 50:

        return {

            "label":
                "👀 Mixed-Signal Watch",

            "short":
                "Some signals are attractive, but confirmation is incomplete.",

            "description":
                (
                    "The product has enough combined strength to remain "
                    "interesting, but the product, content, and commerce "
                    "signals are not aligned strongly enough for a breakout "
                    "classification."
                ),

            "tone":
                "info",

            "reasons": [

                f"Opportunity Score is {opportunity_score:.1f}.",

                f"Product Score is {product_score:.1f}.",

                f"Content Score is {content_score:.1f}.",

                f"Commerce Score is {commerce_score:.1f}."
            ]
        }


    # ==================================================
    # 9. EARLY / UNPROVEN
    # ==================================================

    if age_days <= 180:

        return {

            "label":
                "🌱 Early but Unproven",

            "short":
                "The product is young, but signals are not strong enough yet.",

            "description":
                (
                    "The product is still relatively young, so it may be "
                    "worth monitoring. However, current sales, content, or "
                    "commerce data do not yet support a breakout classification."
                ),

            "tone":
                "info",

            "reasons": [

                f"Product age is {age_days} days.",

                f"Sales momentum is {growth:+.1f}%.",

                f"Opportunity Score is {opportunity_score:.1f}."
            ]
        }


    # ==================================================
    # 10. LOW SIGNAL
    # ==================================================

    return {

        "label":
            "➡️ Low Signal",

        "short":
            "No strong breakout pattern is visible yet.",

        "description":
            (
                "The current combination of product momentum, content "
                "performance, and commerce evidence does not show a strong "
                "FlipRadar opportunity."
            ),

        "tone":
            "warning",

        "reasons": [

            f"Product Score is {product_score:.1f}.",

            f"Content Score is {content_score:.1f}.",

            f"Commerce Score is {commerce_score:.1f}.",

            f"Sales momentum is {growth:+.1f}%."
        ]
    }