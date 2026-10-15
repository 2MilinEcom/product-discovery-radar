import math


# ==================================================
# HELPERS
# ==================================================

def clamp(value, minimum, maximum):

    return max(
        minimum,
        min(
            value,
            maximum
        )
    )


# ==================================================
# FLIP SCORE
# ==================================================

def calculate_flip_score(product):

    seven_day_sales = float(
        product.get(
            "seven_day_sales",
            0
        )
        or 0
    )

    growth = float(
        product.get(
            "growth",
            0
        )
        or 0
    )

    age_days = float(
        product.get(
            "age_days",
            365
        )
        or 365
    )

    price = float(
        product.get(
            "price",
            0
        )
        or 0
    )

    creators = float(
        product.get(
            "creators",
            0
        )
        or 0
    )

    promotion_count = float(
        product.get(
            "promotion_count_7d",
            0
        )
        or 0
    )

    sales_per_promo = float(
        product.get(
            "sales_per_promo",
            0
        )
        or 0
    )


    # --------------------------------------------------
    # SALES VELOCITY
    # Max 25 points
    #
    # Log scale prevents gigantic products from
    # automatically dominating everything.
    # --------------------------------------------------

    if seven_day_sales > 0:

        velocity_score = (
            math.log1p(
                seven_day_sales
            )
            /
            math.log1p(
                10000
            )
        ) * 25

        velocity_score = clamp(
            velocity_score,
            0,
            25
        )

    else:

        velocity_score = 0


    # --------------------------------------------------
    # MOMENTUM
    # Max 30 points
    #
    # 100%+ growth receives full momentum points.
    # --------------------------------------------------

    if growth > 0:

        momentum_score = (
            growth / 100
        ) * 30

        momentum_score = clamp(
            momentum_score,
            0,
            30
        )

    else:

        momentum_score = 0


    # --------------------------------------------------
    # PRODUCT FRESHNESS
    # Max 15 points
    # --------------------------------------------------

    if age_days <= 30:

        freshness_score = 15

    elif age_days <= 90:

        freshness_score = (
            15
            -
            (
                (
                    age_days
                    - 30
                )
                / 60
            )
            * 7
        )

    elif age_days <= 365:

        freshness_score = (
            8
            -
            (
                (
                    age_days
                    - 90
                )
                / 275
            )
            * 8
        )

    else:

        freshness_score = 0


    freshness_score = clamp(
        freshness_score,
        0,
        15
    )


    # --------------------------------------------------
    # PROMOTION EFFICIENCY
    # Max 15 points
    #
    # High sales with relatively few videos/lives
    # can be especially interesting.
    # --------------------------------------------------

    if promotion_count > 0:

        efficiency_score = (
            sales_per_promo
            / 25
        ) * 15

        efficiency_score = clamp(
            efficiency_score,
            0,
            15
        )

    elif seven_day_sales > 0:

        # We have sales but insufficient promotion data.
        efficiency_score = 5

    else:

        efficiency_score = 0


    # --------------------------------------------------
    # PRICE
    # Max 10 points
    # --------------------------------------------------

    if price <= 0:

        price_score = 0

    elif price <= 20:

        price_score = 10

    elif price <= 50:

        price_score = 8

    elif price <= 100:

        price_score = 5

    else:

        price_score = 2


    # --------------------------------------------------
    # SATURATION PENALTY
    #
    # EchoTik's creator count here is typically
    # lifetime associated creators.
    # --------------------------------------------------

    if creators <= 100:

        saturation_penalty = 0

    elif creators <= 500:

        saturation_penalty = 2

    elif creators <= 2000:

        saturation_penalty = 5

    elif creators <= 5000:

        saturation_penalty = 9

    elif creators <= 10000:

        saturation_penalty = 12

    else:

        saturation_penalty = 15


    # --------------------------------------------------
    # FINAL SCORE
    # --------------------------------------------------

    total = (
        velocity_score
        + momentum_score
        + freshness_score
        + efficiency_score
        + price_score
        - saturation_penalty
    )


    return round(
        clamp(
            total,
            0,
            100
        ),
        1
    )


# ==================================================
# OPPORTUNITY LABEL
# ==================================================

def classify_opportunity(product):

    score = float(
        product.get(
            "score",
            0
        )
        or 0
    )

    growth = float(
        product.get(
            "growth",
            0
        )
        or 0
    )


    if (
        score >= 75
        and growth >= 50
    ):

        return "🔥 Exploding"


    if (
        score >= 60
        and growth >= 20
    ):

        return "📈 Emerging"


    if score >= 50:

        return "👀 Watch"


    if (
        growth < -20
    ):

        return "📉 Cooling"


    return "➡️ Stable"