import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv


# ==================================================
# CONFIG
# ==================================================

load_dotenv()


API_URL = (
    "https://open.echotik.live/"
    "api/v3/echotik/product/list"
)


REGION = "US"

PAGE_SIZE = 10


# ==================================================
# AUTH
# ==================================================

def get_auth():

    username = os.getenv(
        "ECHOTIK_USERNAME"
    )

    password = os.getenv(
        "ECHOTIK_PASSWORD"
    )

    if not username or not password:

        raise RuntimeError(
            "Missing EchoTik credentials in .env"
        )

    return (
        username,
        password
    )


# ==================================================
# HELPERS
# ==================================================

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


def days_ago_date(
    days
):

    target = (
        datetime.now()
        - timedelta(
            days=days
        )
    )

    return int(
        target.strftime(
            "%Y%m%d"
        )
    )


def calculate_age(
    first_crawl_dt
):

    value = str(
        first_crawl_dt
        or ""
    ).strip()


    if not value:

        return None


    try:

        first_seen = datetime.strptime(
            value,
            "%Y%m%d"
        )

        return (
            datetime.now()
            - first_seen
        ).days

    except ValueError:

        return None


# ==================================================
# MOMENTUM
# ==================================================

def calculate_momentum(
    raw
):

    sales_1d = safe_int(
        raw.get(
            "total_sale_1d_cnt",
            0
        )
    )


    sales_7d = safe_int(
        raw.get(
            "total_sale_7d_cnt",
            0
        )
    )


    sales_15d = safe_int(
        raw.get(
            "total_sale_15d_cnt",
            0
        )
    )


    sales_30d = safe_int(
        raw.get(
            "total_sale_30d_cnt",
            0
        )
    )


    # ==============================================
    # 1D VS PRIOR 6 DAYS
    # ==============================================

    if (
        sales_1d > 0
        and sales_7d > sales_1d
    ):

        prior_6d = (
            sales_7d
            - sales_1d
        )


        prior_daily = (
            prior_6d
            / 6
        )


        if prior_daily > 0:

            return round(
                (
                    (
                        sales_1d
                        / prior_daily
                    )
                    - 1
                )
                * 100,
                1
            )


    # ==============================================
    # 7D VS PRIOR 8 DAYS
    # ==============================================

    if sales_15d > sales_7d:

        prior_8d = (
            sales_15d
            - sales_7d
        )


        recent_daily = (
            sales_7d
            / 7
        )


        prior_daily = (
            prior_8d
            / 8
        )


        if prior_daily > 0:

            return round(
                (
                    (
                        recent_daily
                        / prior_daily
                    )
                    - 1
                )
                * 100,
                1
            )


    # ==============================================
    # 7D VS PRIOR 23 DAYS
    # ==============================================

    if sales_30d > sales_7d:

        prior_23d = (
            sales_30d
            - sales_7d
        )


        recent_daily = (
            sales_7d
            / 7
        )


        prior_daily = (
            prior_23d
            / 23
        )


        if prior_daily > 0:

            return round(
                (
                    (
                        recent_daily
                        / prior_daily
                    )
                    - 1
                )
                * 100,
                1
            )


    return 0.0


# ==================================================
# RESPONSE EXTRACTION
# ==================================================

def extract_products(
    payload
):

    data = payload.get(
        "data",
        []
    )


    if isinstance(
        data,
        list
    ):

        return data


    if isinstance(
        data,
        dict
    ):

        for key in [
            "list",
            "items",
            "products",
            "records",
            "rows",
        ]:

            value = data.get(
                key
            )


            if isinstance(
                value,
                list
            ):

                return value


        for value in data.values():

            if isinstance(
                value,
                list
            ):

                return value


    return []


# ==================================================
# NORMALIZE
# ==================================================

def normalize_product(
    raw
):

    videos_7d = safe_int(
        raw.get(
            "total_ifl_video_7d_cnt",
            0
        )
    )


    lives_7d = safe_int(
        raw.get(
            "total_ifl_live_7d_cnt",
            0
        )
    )


    return {

        "id":
            str(
                raw.get(
                    "product_id",
                    ""
                )
            ),

        "name":
            str(
                raw.get(
                    "product_name",
                    ""
                )
            ),

        "first_crawl":
            raw.get(
                "first_crawl_dt"
            ),

        "age":
            calculate_age(
                raw.get(
                    "first_crawl_dt"
                )
            ),

        "price":
            safe_float(
                raw.get(
                    "spu_avg_price",
                    0
                )
            ),

        "sales_7d":
            safe_int(
                raw.get(
                    "total_sale_7d_cnt",
                    0
                )
            ),

        "sales_15d":
            safe_int(
                raw.get(
                    "total_sale_15d_cnt",
                    0
                )
            ),

        "sales_30d":
            safe_int(
                raw.get(
                    "total_sale_30d_cnt",
                    0
                )
            ),

        "momentum":
            calculate_momentum(
                raw
            ),

        "promotions_7d":
            (
                videos_7d
                + lives_7d
            ),

        "creators":
            safe_int(
                raw.get(
                    "total_ifl_cnt",
                    0
                )
            ),

        "views_7d":
            safe_int(
                raw.get(
                    "total_views_7d_cnt",
                    0
                )
            ),

        "trend":
            safe_int(
                raw.get(
                    "sales_trend_flag",
                    0
                )
            ),
    }


# ==================================================
# TWO REMAINING TEST BUCKETS
#
# EXACTLY TWO API REQUESTS.
# ==================================================

BUCKETS = {

    "🌱 VERY NEW + TRACTION": {

        "region":
            REGION,

        # First discovered within approximately 180 days.
        "min_first_crawl_dt":
            days_ago_date(
                180
            ),

        # Require some real sales traction.
        "min_total_sale_30d_cnt":
            500,

        # FlipRadar product universe.
        "max_spu_avg_price":
            100,

        # Active-sales ranking.
        "product_sort_field":
            4,

        "sort_type":
            1,

        "page_num":
            1,

        "page_size":
            PAGE_SIZE,
    },


    "🎯 RISING + LOWER CREATOR SATURATION": {

        "region":
            REGION,

        # Keep product relatively young.
        "min_first_crawl_dt":
            days_ago_date(
                365
            ),

        # Require EchoTik rising-sales signal.
        "sales_trend_flag":
            1,

        # Require meaningful traction.
        "min_total_sale_30d_cnt":
            500,

        "max_spu_avg_price":
            100,

        # Avoid extremely mature creator saturation.
        "max_total_ifl_cnt":
            5000,

        "product_sort_field":
            4,

        "sort_type":
            1,

        "page_num":
            1,

        "page_size":
            PAGE_SIZE,
    },
}


# ==================================================
# REQUEST
# ==================================================

def fetch_bucket(
    name,
    params
):

    print()
    print(
        "=" * 100
    )

    print(
        name
    )

    print(
        "=" * 100
    )


    for key, value in params.items():

        print(
            f"{key}: {value}"
        )


    response = requests.get(
        API_URL,
        params=params,
        auth=get_auth(),
        timeout=30
    )


    print()
    print(
        f"HTTP status: {response.status_code}"
    )


    if response.status_code != 200:

        print()
        print(
            "ERROR RESPONSE:"
        )

        print(
            response.text
        )

        return []


    payload = response.json()


    print(
        f"API code: {payload.get('code')}"
    )


    print(
        f"API message: {payload.get('message')}"
    )


    products = [

        normalize_product(
            raw
        )

        for raw in extract_products(
            payload
        )
    ]


    print(
        f"Products returned: {len(products)}"
    )


    return products


# ==================================================
# DISPLAY
# ==================================================

def print_products(
    products
):

    if not products:

        print()
        print(
            "No products returned."
        )

        return


    for rank, product in enumerate(
        products,
        start=1
    ):

        age = product[
            "age"
        ]


        age_text = (
            f"{age}d"
            if age is not None
            else "?"
        )


        print()
        print(
            f"{rank}. {product['name']}"
        )


        print(
            f"   ID: {product['id']}"
        )


        print(
            f"   First crawl: {product['first_crawl']}"
        )


        print(
            f"   Age: {age_text}"
        )


        print(
            f"   Price: ${product['price']:.2f}"
        )


        print(
            f"   7D Sales: {product['sales_7d']:,}"
        )


        print(
            f"   30D Sales: {product['sales_30d']:,}"
        )


        print(
            f"   Momentum: {product['momentum']:+.1f}%"
        )


        print(
            f"   7D Promotions: "
            f"{product['promotions_7d']:,}"
        )


        print(
            f"   Lifetime Creators: "
            f"{product['creators']:,}"
        )


        print(
            f"   7D Views: "
            f"{product['views_7d']:,}"
        )


        print(
            f"   Trend Flag: "
            f"{product['trend']}"
        )


# ==================================================
# SUMMARY
# ==================================================

def print_summary(
    products
):

    if not products:

        return


    under_90 = sum(

        1

        for product in products

        if (
            product[
                "age"
            ] is not None
            and product[
                "age"
            ] <= 90
        )
    )


    under_180 = sum(

        1

        for product in products

        if (
            product[
                "age"
            ] is not None
            and product[
                "age"
            ] <= 180
        )
    )


    momentum_20 = sum(

        1

        for product in products

        if product[
            "momentum"
        ] >= 20
    )


    momentum_50 = sum(

        1

        for product in products

        if product[
            "momentum"
        ] >= 50
    )


    low_promo = sum(

        1

        for product in products

        if product[
            "promotions_7d"
        ] <= 300
    )


    low_creator = sum(

        1

        for product in products

        if product[
            "creators"
        ] <= 5000
    )


    strong_early = sum(

        1

        for product in products

        if (
            product[
                "age"
            ] is not None

            and product[
                "age"
            ] <= 365

            and product[
                "momentum"
            ] >= 20

            and product[
                "sales_7d"
            ] >= 500
        )
    )


    print()
    print(
        "-" * 100
    )

    print(
        "BUCKET SUMMARY"
    )

    print(
        "-" * 100
    )


    print(
        f"Age <= 90 days: "
        f"{under_90}/{len(products)}"
    )


    print(
        f"Age <= 180 days: "
        f"{under_180}/{len(products)}"
    )


    print(
        f"Momentum >= +20%: "
        f"{momentum_20}/{len(products)}"
    )


    print(
        f"Momentum >= +50%: "
        f"{momentum_50}/{len(products)}"
    )


    print(
        f"7D promotions <= 300: "
        f"{low_promo}/{len(products)}"
    )


    print(
        f"Lifetime creators <= 5,000: "
        f"{low_creator}/{len(products)}"
    )


    print(
        "Strong early profile "
        "(<=365d, >=20% momentum, >=500 7D sales): "
        f"{strong_early}/{len(products)}"
    )


# ==================================================
# OVERLAP
# ==================================================

def print_overlap(
    results
):

    names = list(
        results.keys()
    )


    if len(
        names
    ) < 2:

        return


    first = names[
        0
    ]

    second = names[
        1
    ]


    first_ids = {

        product[
            "id"
        ]

        for product in results[
            first
        ]
    }


    second_ids = {

        product[
            "id"
        ]

        for product in results[
            second
        ]
    }


    shared = (
        first_ids
        & second_ids
    )


    print()
    print(
        "=" * 100
    )

    print(
        "CROSS-BUCKET OVERLAP"
    )

    print(
        "=" * 100
    )


    print(
        f"Shared products: {len(shared)}"
    )


    if shared:

        for product_id in shared:

            print(
                f"  {product_id}"
            )


# ==================================================
# MAIN
# ==================================================

def main():

    print()
    print(
        "FlipRadar Discovery Bucket Diagnostic"
    )


    print(
        "Testing the final 2 discovery buckets."
    )


    print(
        "This run makes EXACTLY 2 EchoTik API requests."
    )


    print(
        "Nothing is written to flipradar.db."
    )


    results = {}


    for name, params in BUCKETS.items():

        products = fetch_bucket(
            name,
            params
        )


        results[
            name
        ] = products


        print_products(
            products
        )


        print_summary(
            products
        )


    print_overlap(
        results
    )


    print()
    print(
        "=" * 100
    )

    print(
        "DONE"
    )

    print(
        "=" * 100
    )


    print(
        "Paste the terminal output back into ChatGPT."
    )


if __name__ == "__main__":

    main()