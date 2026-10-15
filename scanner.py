import json
import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

from scoring import (
    calculate_flip_score,
    classify_opportunity,
)


# ==================================================
# ENVIRONMENT
# ==================================================

load_dotenv()

ECHOTIK_USERNAME = os.getenv(
    "ECHOTIK_USERNAME",
    "",
).strip()

ECHOTIK_PASSWORD = os.getenv(
    "ECHOTIK_PASSWORD",
    "",
).strip()

ECHOTIK_SCAN_LIMIT = int(
    os.getenv(
        "ECHOTIK_SCAN_LIMIT",
        "10",
    )
)


# ==================================================
# ECHOTIK API
# ==================================================

ECHOTIK_PRODUCT_URL = (
    "https://open.echotik.live/"
    "api/v3/echotik/product/list"
)

BREAKOUT_BUCKET = "🚀 Breakout Core"
VERY_NEW_BUCKET = "🌱 Very New Watch"


# ==================================================
# MOCK PRODUCTS
# ==================================================

MOCK_PRODUCTS = [
    {
        "id": "1001",
        "name": "Travel Makeup Bag",
        "price": 18.99,
        "daily_sales": 381,
        "previous_daily_sales": 199,
        "seven_day_sales": 1702,
        "fifteen_day_sales": 2500,
        "thirty_day_sales": 4000,
        "creators": 24,
        "age_days": 12,
        "url": "https://www.tiktok.com/shop",
        "cover": "",
        "shop_name": "Demo Shop",
        "video_count": 32,
        "live_count_7d": 4,
    },
    {
        "id": "1002",
        "name": "Mini Thermal Printer",
        "price": 27.99,
        "daily_sales": 264,
        "previous_daily_sales": 162,
        "seven_day_sales": 2160,
        "fifteen_day_sales": 3600,
        "thirty_day_sales": 6000,
        "creators": 61,
        "age_days": 21,
        "url": "https://www.tiktok.com/shop",
        "cover": "",
        "shop_name": "Demo Shop",
        "video_count": 84,
        "live_count_7d": 3,
    },
]


# ==================================================
# NUMBER HELPERS
# ==================================================

def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def first_positive_number(raw, keys, integer=True):
    for key in keys:
        if key not in raw:
            continue

        value = raw.get(key)

        try:
            number = float(value)

            if number > 0:
                if integer:
                    return int(number)

                return number

        except (TypeError, ValueError):
            pass

    return 0


# ==================================================
# DATE HELPERS
# ==================================================

def date_days_ago_yyyymmdd(days):
    target = (
        datetime.now()
        - timedelta(days=days)
    )

    return int(
        target.strftime("%Y%m%d")
    )


def calculate_age_days(value):
    if not value:
        return 30

    text = str(value)

    # YYYYMMDD
    try:
        created = datetime.strptime(
            text,
            "%Y%m%d",
        )

        return max(
            (
                datetime.now()
                - created
            ).days,
            1,
        )

    except Exception:
        pass

    # UNIX timestamp fallback
    try:
        timestamp = int(
            float(value)
        )

        created = datetime.fromtimestamp(
            timestamp
        )

        return max(
            (
                datetime.now()
                - created
            ).days,
            1,
        )

    except Exception:
        return 30


# ==================================================
# COVER IMAGE
# ==================================================

def extract_cover(value):
    """
    Extract the first usable image URL from the different
    cover formats EchoTik returns.

    EchoTik may return:
    - one URL string
    - a JSON list of URL strings
    - a JSON list of dictionaries containing "url"
    - a real Python list in either of those shapes
    """

    if not value:
        return ""

    if isinstance(value, str):
        text = value.strip()

        if text.startswith(
            (
                "http://",
                "https://",
            )
        ):
            return text

        try:
            decoded = json.loads(
                text
            )

            return extract_cover(
                decoded
            )

        except Exception:
            return ""

    if isinstance(value, dict):
        url = value.get(
            "url"
        )

        if isinstance(
            url,
            str,
        ) and url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            return url

        return ""

    if isinstance(value, list):
        for item in value:
            url = extract_cover(
                item
            )

            if url:
                return url

    return ""


# ==================================================
# MOMENTUM CALCULATION
# ==================================================

def calculate_momentum(
    one_day_sales,
    seven_day_sales,
    fifteen_day_sales,
    thirty_day_sales,
):
    # --------------------------------------------------
    # BEST OPTION:
    # Real 1-day sales versus previous 6-day average.
    # --------------------------------------------------

    if (
        one_day_sales > 0
        and seven_day_sales > one_day_sales
    ):
        previous_six_sales = (
            seven_day_sales
            - one_day_sales
        )

        previous_daily_average = (
            previous_six_sales
            / 6
        )

        if previous_daily_average > 0:
            growth = (
                (
                    one_day_sales
                    - previous_daily_average
                )
                / previous_daily_average
            ) * 100

            return (
                round(growth, 1),
                round(
                    previous_daily_average,
                    1,
                ),
                "1d_vs_prior_6d",
            )

    # --------------------------------------------------
    # SECOND OPTION:
    # Last 7 days versus previous 8 days.
    # --------------------------------------------------

    if (
        fifteen_day_sales
        > seven_day_sales
        and seven_day_sales > 0
    ):
        recent_daily_average = (
            seven_day_sales
            / 7
        )

        previous_eight_sales = (
            fifteen_day_sales
            - seven_day_sales
        )

        previous_daily_average = (
            previous_eight_sales
            / 8
        )

        if previous_daily_average > 0:
            growth = (
                (
                    recent_daily_average
                    - previous_daily_average
                )
                / previous_daily_average
            ) * 100

            return (
                round(growth, 1),
                round(
                    previous_daily_average,
                    1,
                ),
                "7d_vs_prior_8d",
            )

    # --------------------------------------------------
    # THIRD OPTION:
    # Last 7 days versus previous 23 days.
    # --------------------------------------------------

    if (
        thirty_day_sales
        > seven_day_sales
        and seven_day_sales > 0
    ):
        recent_daily_average = (
            seven_day_sales
            / 7
        )

        previous_twenty_three_sales = (
            thirty_day_sales
            - seven_day_sales
        )

        previous_daily_average = (
            previous_twenty_three_sales
            / 23
        )

        if previous_daily_average > 0:
            growth = (
                (
                    recent_daily_average
                    - previous_daily_average
                )
                / previous_daily_average
            ) * 100

            return (
                round(growth, 1),
                round(
                    previous_daily_average,
                    1,
                ),
                "7d_vs_prior_23d",
            )

    # --------------------------------------------------
    # NOT ENOUGH HISTORY
    # --------------------------------------------------

    current_average = 0

    if seven_day_sales > 0:
        current_average = (
            seven_day_sales
            / 7
        )

    return (
        0,
        round(
            current_average,
            1,
        ),
        "unavailable",
    )


# ==================================================
# ECHOTIK RESPONSE HELPERS
# ==================================================

def extract_product_list(result):
    data = result.get(
        "data",
        [],
    )

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in [
            "list",
            "items",
            "products",
            "records",
            "rows",
        ]:
            value = data.get(key)

            if isinstance(value, list):
                return value

        for value in data.values():
            if isinstance(value, list):
                return value

    return []


def handle_echotik_error(
    response,
    bucket_name,
):
    if response.status_code == 401:
        raise RuntimeError(
            "EchoTik authentication failed."
        )

    if response.status_code == 402:
        raise RuntimeError(
            "EchoTik reports insufficient API credits."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "EchoTik denied access to this endpoint."
        )

    if response.status_code == 429:
        raise RuntimeError(
            "EchoTik rate limit reached."
        )

    if response.status_code != 200:
        body = (
            response.text[:1000]
            if response.text
            else "No response body."
        )

        raise RuntimeError(
            f"EchoTik request failed for "
            f"{bucket_name}. "
            f"HTTP {response.status_code}. "
            f"Response: {body}"
        )


# ==================================================
# ECHOTIK REQUEST
# ==================================================

def request_echotik_products(
    params=None,
    bucket_name="Default EchoTik Scan",
    page_num=1,
    page_size=None,
):
    """
    Make exactly one EchoTik product-list request.

    Existing callers stay compatible:
    - page_num defaults to 1
    - page_size defaults to ECHOTIK_SCAN_LIMIT
    - page_size is capped at 10 because EchoTik rejected
      larger filtered page sizes during testing

    The new page_num argument lets future discovery code
    safely request page 2, 3, 4, etc. without changing the
    normal two-lane Scan Now behavior.
    """

    requested_size = (
        ECHOTIK_SCAN_LIMIT
        if page_size is None
        else page_size
    )

    limit = max(
        1,
        min(
            safe_int(
                requested_size,
                10,
            ),
            10,
        ),
    )

    resolved_page_num = max(
        safe_int(
            page_num,
            1,
        ),
        1,
    )

    if params is None:
        params = {
            "region": "US",
            "sort_type": 1,
            "product_sort_field": 4,
        }

    else:
        params = dict(params)

    params["page_num"] = (
        resolved_page_num
    )

    params["page_size"] = (
        limit
    )

    print(
        f"FlipRadar scanning "
        f"{bucket_name} "
        f"(page {resolved_page_num}, "
        f"size {limit})..."
    )

    response = requests.get(
        ECHOTIK_PRODUCT_URL,
        params=params,
        auth=(
            ECHOTIK_USERNAME,
            ECHOTIK_PASSWORD,
        ),
        timeout=30,
    )

    handle_echotik_error(
        response,
        bucket_name,
    )

    result = response.json()

    if result.get("code") not in (
        0,
        "0",
    ):
        raise RuntimeError(
            "EchoTik API error: "
            + str(
                result.get(
                    "message",
                    result,
                )
            )
        )

    return extract_product_list(
        result
    )


# ==================================================
# MULTI-BUCKET DISCOVERY
# ==================================================

def build_discovery_requests():
    """
    Two proven discovery lanes.

    Request 1:
    - <= 365 days since EchoTik first crawl
    - sales_trend_flag = 1
    - >= 500 sales over 30 days
    - <= $100
    - active-sales sort field 4

    Request 2:
    - <= 180 days since EchoTik first crawl
    - >= 500 sales over 30 days
    - <= $100
    - active-sales sort field 4

    With normal credentials this scanner makes exactly
    TWO EchoTik product-list requests per Scan Now.
    """

    return [
        (
            BREAKOUT_BUCKET,
            {
                "region": "US",
                "min_first_crawl_dt":
                    date_days_ago_yyyymmdd(
                        365
                    ),
                "sales_trend_flag": 1,
                "min_total_sale_30d_cnt": 500,
                "max_spu_avg_price": 100,
                "product_sort_field": 4,
                "sort_type": 1,
            },
        ),
        (
            VERY_NEW_BUCKET,
            {
                "region": "US",
                "min_first_crawl_dt":
                    date_days_ago_yyyymmdd(
                        180
                    ),
                "min_total_sale_30d_cnt": 500,
                "max_spu_avg_price": 100,
                "product_sort_field": 4,
                "sort_type": 1,
            },
        ),
    ]


def request_echotik_discovery_products():
    """
    Run the two discovery requests, merge them locally,
    and deduplicate by product_id.

    A product can belong to both buckets. We preserve all
    bucket labels in _flipradar_discovery_buckets.
    """

    merged = {}
    order = []

    raw_slot_count = 0

    for (
        bucket_name,
        params,
    ) in build_discovery_requests():

        bucket_products = (
            request_echotik_products(
                params=params,
                bucket_name=bucket_name,
            )
        )

        raw_slot_count += len(
            bucket_products
        )

        print(
            f"{bucket_name}: "
            f"{len(bucket_products)} products."
        )

        for raw in bucket_products:
            if not isinstance(
                raw,
                dict,
            ):
                continue

            product_id = str(
                raw.get(
                    "product_id",
                    "",
                )
            )

            if not product_id:
                continue

            if product_id not in merged:
                item = dict(raw)

                item[
                    "_flipradar_discovery_buckets"
                ] = [
                    bucket_name
                ]

                item[
                    "_flipradar_primary_bucket"
                ] = bucket_name

                merged[
                    product_id
                ] = item

                order.append(
                    product_id
                )

            else:
                existing = merged[
                    product_id
                ]

                buckets = existing.get(
                    "_flipradar_discovery_buckets",
                    [],
                )

                if bucket_name not in buckets:
                    buckets.append(
                        bucket_name
                    )

                existing[
                    "_flipradar_discovery_buckets"
                ] = buckets

    products = [
        merged[product_id]
        for product_id in order
    ]

    print(
        "FlipRadar discovery merge: "
        f"{raw_slot_count} raw bucket slots -> "
        f"{len(products)} unique products."
    )

    return products


# ==================================================
# NORMALIZE ECHOTIK PRODUCT
# ==================================================

def normalize_echotik_product(raw):
    product_id = str(
        raw.get(
            "product_id",
            "",
        )
    )

    name = (
        raw.get("product_name")
        or raw.get("title")
        or "Unknown Product"
    )

    # --------------------------------------------------
    # PRICE
    # --------------------------------------------------

    price = first_positive_number(
        raw,
        [
            "spu_avg_price",
            "min_price",
            "sale_price",
            "price",
        ],
        integer=False,
    )

    # --------------------------------------------------
    # SALES WINDOWS
    # --------------------------------------------------

    one_day_sales = safe_int(
        raw.get(
            "total_sale_1d_cnt"
        )
    )

    seven_day_sales = safe_int(
        raw.get(
            "total_sale_7d_cnt"
        )
    )

    fifteen_day_sales = safe_int(
        raw.get(
            "total_sale_15d_cnt"
        )
    )

    thirty_day_sales = safe_int(
        raw.get(
            "total_sale_30d_cnt"
        )
    )

    total_sales = safe_int(
        raw.get(
            "total_sale_cnt"
        )
    )

    # --------------------------------------------------
    # DISPLAY DAILY SALES
    # --------------------------------------------------

    if one_day_sales > 0:
        daily_sales = one_day_sales
        daily_sales_source = (
            "echotik_1d"
        )

    elif seven_day_sales > 0:
        daily_sales = round(
            seven_day_sales
            / 7
        )

        daily_sales_source = (
            "7d_average_estimate"
        )

    else:
        daily_sales = 0
        daily_sales_source = (
            "unavailable"
        )

    # --------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------

    (
        growth,
        previous_daily_sales,
        growth_source,
    ) = calculate_momentum(
        one_day_sales,
        seven_day_sales,
        fifteen_day_sales,
        thirty_day_sales,
    )

    # --------------------------------------------------
    # CREATOR SATURATION
    # --------------------------------------------------

    creators = safe_int(
        raw.get(
            "total_ifl_cnt"
        )
    )

    # --------------------------------------------------
    # RECENT CONTENT ACTIVITY
    # --------------------------------------------------
    #
    # Preserve the existing app behavior:
    # product-level recent videos + lives.
    #
    # Also store EchoTik influencer counts separately
    # for future discovery analysis.
    # --------------------------------------------------

    videos_7d = safe_int(
        raw.get(
            "total_video_7d_cnt"
        )
    )

    videos_total = safe_int(
        raw.get(
            "total_video_cnt"
        )
    )

    lives_7d = safe_int(
        raw.get(
            "total_live_7d_cnt"
        )
    )

    lives_total = safe_int(
        raw.get(
            "total_live_cnt"
        )
    )

    promotion_count_7d = (
        videos_7d
        + lives_7d
    )

    influencer_videos_7d = safe_int(
        raw.get(
            "total_ifl_video_7d_cnt"
        )
    )

    influencer_lives_7d = safe_int(
        raw.get(
            "total_ifl_live_7d_cnt"
        )
    )

    influencer_promotion_count_7d = (
        influencer_videos_7d
        + influencer_lives_7d
    )

    # --------------------------------------------------
    # SALES PER PROMOTION
    # --------------------------------------------------

    if promotion_count_7d > 0:
        sales_per_promo = (
            seven_day_sales
            / promotion_count_7d
        )

    else:
        sales_per_promo = 0

    # --------------------------------------------------
    # AGE
    # --------------------------------------------------

    first_crawl_dt = raw.get(
        "first_crawl_dt"
    )

    age_days = calculate_age_days(
        first_crawl_dt
    )

    # --------------------------------------------------
    # SHOP
    # --------------------------------------------------

    shop_name = (
        raw.get("seller_name")
        or raw.get("shop_name")
        or raw.get("seller_id")
        or "Unknown Shop"
    )

    # --------------------------------------------------
    # IMAGE
    # --------------------------------------------------

    # Prefer TikTok's original product image URL.
    #
    # EchoTik also returns its own mirrored cover_url, but
    # that image host can fail to render outside EchoTik.
    # The original TikTok CDN URL is therefore preferred,
    # with EchoTik's mirrored image kept as the fallback.
    cover = extract_cover(
        raw.get(
            "original_cover_url"
        )
    )

    cover_source = (
        "tiktok_original"
        if cover
        else "echotik_mirror"
    )

    if not cover:
        cover = extract_cover(
            raw.get(
                "cover_url"
            )
        )

    # --------------------------------------------------
    # DISCOVERY SOURCE
    # --------------------------------------------------

    discovery_buckets = (
        raw.get(
            "_flipradar_discovery_buckets",
            [],
        )
        or []
    )

    primary_bucket = (
        raw.get(
            "_flipradar_primary_bucket"
        )
        or (
            discovery_buckets[0]
            if discovery_buckets
            else "Default EchoTik Scan"
        )
    )

    # --------------------------------------------------
    # PRODUCT
    # --------------------------------------------------

    product = {
        "id": product_id,
        "name": name,
        "price": round(
            price,
            2,
        ),
        "daily_sales": daily_sales,
        "daily_sales_source":
            daily_sales_source,
        "previous_daily_sales":
            previous_daily_sales,
        "seven_day_sales":
            seven_day_sales,
        "fifteen_day_sales":
            fifteen_day_sales,
        "thirty_day_sales":
            thirty_day_sales,
        "total_sales":
            total_sales,
        "growth": growth,
        "growth_source":
            growth_source,
        "creators": creators,
        "creator_source":
            "lifetime",

        # Existing app uses video_count,
        # so preserve recent 7-day video count here.
        "video_count":
            videos_7d,
        "video_count_7d":
            videos_7d,
        "video_count_total":
            videos_total,
        "live_count_7d":
            lives_7d,
        "live_count_total":
            lives_total,
        "promotion_count_7d":
            promotion_count_7d,
        "sales_per_promo":
            round(
                sales_per_promo,
                2,
            ),

        # Additional provider activity fields.
        "influencer_video_count_7d":
            influencer_videos_7d,
        "influencer_live_count_7d":
            influencer_lives_7d,
        "influencer_promotion_count_7d":
            influencer_promotion_count_7d,

        "age_days":
            age_days,
        "first_crawl_dt":
            first_crawl_dt,
        "sales_trend_flag":
            safe_int(
                raw.get(
                    "sales_trend_flag",
                    0,
                )
            ),

        # Discovery metadata.
        "discovery_bucket":
            primary_bucket,
        "discovery_buckets":
            discovery_buckets,
        "discovery_bucket_count":
            len(
                discovery_buckets
            ),

        "url":
            "https://www.tiktok.com/shop",
        "cover":
            cover,
        "cover_source":
            cover_source,
        "shop_name":
            str(
                shop_name
            ),
        "gmv":
            safe_float(
                raw.get(
                    "total_sale_gmv_amt"
                )
            ),
        "seven_day_gmv":
            safe_float(
                raw.get(
                    "total_sale_gmv_7d_amt"
                )
            ),
        "thirty_day_gmv":
            safe_float(
                raw.get(
                    "total_sale_gmv_30d_amt"
                )
            ),
        "rating":
            safe_float(
                raw.get(
                    "product_rating"
                )
            ),
        "reviews":
            safe_int(
                raw.get(
                    "review_count"
                )
            ),
        "commission_rate":
            safe_float(
                raw.get(
                    "product_commission_rate"
                )
            ),
    }

    # --------------------------------------------------
    # SCORE
    # --------------------------------------------------

    product["score"] = (
        calculate_flip_score(
            product
        )
    )

    product["status"] = (
        classify_opportunity(
            product
        )
    )

    return product


# ==================================================
# LIVE ECHOTIK SCANNER
# ==================================================

def scan_echotik_products():
    raw_products = (
        request_echotik_discovery_products()
    )

    products = []
    seen_ids = set()

    for raw in raw_products:
        if not isinstance(
            raw,
            dict,
        ):
            continue

        product = (
            normalize_echotik_product(
                raw
            )
        )

        if not product["id"]:
            continue

        if product["id"] in seen_ids:
            continue

        seen_ids.add(
            product["id"]
        )

        products.append(
            product
        )

    if not products:
        raise RuntimeError(
            "EchoTik connected successfully, "
            "but no products were returned."
        )

    print(
        f"EchoTik returned "
        f"{len(products)} unique real products."
    )

    print(
        "----------------------------------------"
    )

    for product in products:
        buckets = ", ".join(
            product.get(
                "discovery_buckets",
                [],
            )
        )

        print(
            product["status"],
            "|",
            product["name"][:35],
            "| 7d:",
            product["seven_day_sales"],
            "| momentum:",
            product["growth"],
            "%",
            "| score:",
            product["score"],
            "| bucket:",
            buckets,
        )

    print(
        "----------------------------------------"
    )

    return products


# ==================================================
# MOCK SCANNER
# ==================================================

def scan_mock_products():
    products = []

    for product in MOCK_PRODUCTS:
        item = product.copy()

        item[
            "promotion_count_7d"
        ] = (
            item.get(
                "video_count",
                0,
            )
            + item.get(
                "live_count_7d",
                0,
            )
        )

        if item[
            "promotion_count_7d"
        ] > 0:
            item[
                "sales_per_promo"
            ] = (
                item[
                    "seven_day_sales"
                ]
                / item[
                    "promotion_count_7d"
                ]
            )

        else:
            item[
                "sales_per_promo"
            ] = 0

        recent = (
            item[
                "seven_day_sales"
            ]
            / 7
        )

        previous = (
            (
                item[
                    "fifteen_day_sales"
                ]
                - item[
                    "seven_day_sales"
                ]
            )
            / 8
        )

        if previous > 0:
            item["growth"] = round(
                (
                    (
                        recent
                        - previous
                    )
                    / previous
                )
                * 100,
                1,
            )

        else:
            item["growth"] = 0

        item[
            "growth_source"
        ] = (
            "7d_vs_prior_8d"
        )

        item[
            "discovery_bucket"
        ] = BREAKOUT_BUCKET

        item[
            "discovery_buckets"
        ] = [
            BREAKOUT_BUCKET
        ]

        item[
            "discovery_bucket_count"
        ] = 1

        item[
            "sales_trend_flag"
        ] = 1

        item[
            "score"
        ] = calculate_flip_score(
            item
        )

        item[
            "status"
        ] = classify_opportunity(
            item
        )

        products.append(
            item
        )

    return products


# ==================================================
# MAIN SCANNER
# ==================================================

def scan_products():
    credentials_present = (
        bool(
            ECHOTIK_USERNAME
        )
        and bool(
            ECHOTIK_PASSWORD
        )
    )

    if not credentials_present:
        print(
            "FlipRadar running in DEMO mode."
        )

        return scan_mock_products()

    return scan_echotik_products()
