import streamlit as st
import pandas as pd
import requests

from scanner import scan_products

from database import (
    initialize_database,
    save_snapshot,
    save_latest_scan,
    load_latest_scan,
    add_to_watchlist,
    get_watchlist,
    get_product_history,
)


# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar",
    page_icon="📡",
    layout="wide",
)


# ==================================================
# PRODUCT IMAGE LOADER
# ==================================================

@st.cache_data(
    ttl=3600,
    show_spinner=False,
)
def fetch_product_image(
    image_url,
):
    """
    Fetch an EchoTik product image server-side.

    EchoTik's saved image host may not render when Safari
    tries to load it directly inside Streamlit. Fetching the
    bytes from Python avoids that browser-side hotlink issue.

    This does NOT call the EchoTik API and does not use API
    credits. It only requests the already-saved image URL.
    """

    image_url = str(
        image_url
        or ""
    ).strip()

    if not image_url:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept": (
            "image/avif,image/webp,image/apng,"
            "image/svg+xml,image/*,*/*;q=0.8"
        ),
    }

    try:
        response = requests.get(
            image_url,
            headers=headers,
            timeout=15,
        )

        if response.status_code != 200:
            return None

        content_type = (
            response.headers.get(
                "content-type",
                "",
            )
            .lower()
        )

        if (
            content_type
            and not content_type.startswith(
                "image/"
            )
        ):
            return None

        if not response.content:
            return None

        return response.content

    except requests.RequestException:
        return None


# ==================================================
# DATABASE
# ==================================================

initialize_database()


# ==================================================
# HEADER
# ==================================================

st.title(
    "📡 FlipRadar"
)

st.caption(
    "Find TikTok Shop products gaining momentum before everyone else."
)


# ==================================================
# LOAD PERSISTENT DATA
# ==================================================

if "products" not in st.session_state:
    saved_products, saved_scan_time = (
        load_latest_scan()
    )

    st.session_state.products = (
        saved_products
    )

    st.session_state.saved_scan_time = (
        saved_scan_time
    )


if "last_scan_message" not in st.session_state:
    st.session_state.last_scan_message = ""


# ==================================================
# SIDEBAR FILTERS
# ==================================================

st.sidebar.header(
    "Emerging Radar Settings"
)


max_price = st.sidebar.number_input(
    "Maximum product price",
    min_value=0.0,
    max_value=1000.0,
    value=100.0,
    step=5.0,
)


minimum_7d_sales = st.sidebar.number_input(
    "Minimum 7-day sales",
    min_value=0,
    max_value=1000000,
    value=500,
    step=100,
)


minimum_growth = st.sidebar.number_input(
    "Minimum momentum growth %",
    min_value=-1000.0,
    max_value=10000.0,
    value=20.0,
    step=10.0,
)


maximum_promotions = st.sidebar.number_input(
    "Maximum 7-day promotions",
    min_value=0,
    max_value=100000,
    value=3000,
    step=100,
)


maximum_age = st.sidebar.number_input(
    "Maximum product age (days)",
    min_value=1,
    max_value=3000,
    value=365,
    step=30,
)


minimum_score = st.sidebar.number_input(
    "Minimum FlipScore",
    min_value=0.0,
    max_value=100.0,
    value=40.0,
    step=5.0,
)


# ==================================================
# SCAN BUTTON
# ==================================================

if st.sidebar.button(
    "📡 Scan Now",
    width="stretch",
):
    try:
        with st.spinner(
            "Scanning TikTok Shop products..."
        ):
            products = scan_products()

            # ------------------------------------------
            # SAVE HISTORICAL SNAPSHOTS
            # ------------------------------------------

            for product in products:
                try:
                    save_snapshot(
                        product
                    )

                except Exception as error:
                    print(
                        "Snapshot save failed:",
                        error,
                    )

            # ------------------------------------------
            # SAVE PERSISTENT LATEST SCAN
            # ------------------------------------------

            save_latest_scan(
                products
            )

            # ------------------------------------------
            # UPDATE SESSION
            # ------------------------------------------

            st.session_state.products = (
                products
            )

            (
                _,
                saved_scan_time,
            ) = load_latest_scan()

            st.session_state.saved_scan_time = (
                saved_scan_time
            )

        st.session_state.last_scan_message = (
            f"Scan complete — "
            f"{len(products)} products returned."
        )

    except Exception as error:
        st.sidebar.error(
            f"Scan failed: {error}"
        )


# ==================================================
# SIDEBAR STATUS
# ==================================================

if st.session_state.last_scan_message:
    st.sidebar.success(
        st.session_state.last_scan_message
    )


if st.session_state.get(
    "saved_scan_time"
):
    st.sidebar.caption(
        "Loaded saved scan:"
    )

    st.sidebar.code(
        st.session_state.saved_scan_time
    )


# ==================================================
# PRODUCTS
# ==================================================

products = (
    st.session_state.products
)


# ==================================================
# NO DATA YET
# ==================================================

if not products:
    st.info(
        "No saved product scan exists yet.\n\n"
        "Click **📡 Scan Now** once. "
        "After that, FlipRadar will remember the products "
        "even after Streamlit is closed or restarted."
    )

    st.stop()


# ==================================================
# DATAFRAME
# ==================================================

df = pd.DataFrame(
    products
)


# ==================================================
# REQUIRED FIELDS
# ==================================================

defaults = {
    "price": 0,
    "daily_sales": 0,
    "seven_day_sales": 0,
    "fifteen_day_sales": 0,
    "thirty_day_sales": 0,
    "total_sales": 0,
    "growth": 0,
    "creators": 0,
    "video_count_7d": 0,
    "live_count_7d": 0,
    "promotion_count_7d": 0,
    "sales_per_promo": 0,
    "age_days": 0,
    "score": 0,
    "status": "➡️ Stable",
    "gmv": 0,
    "seven_day_gmv": 0,
    "rating": 0,
    "reviews": 0,
    "commission_rate": 0,
    "cover": "",
    "shop_name": "",
}


for column, default in defaults.items():
    if column not in df.columns:
        df[column] = default


# ==================================================
# TEXT CLEANUP
# ==================================================

df["cover"] = (
    df["cover"]
    .fillna("")
    .astype(str)
)

df.loc[
    df["cover"].isin(
        [
            "nan",
            "None",
            "null",
        ]
    ),
    "cover",
] = ""


# ==================================================
# NUMERIC CLEANUP
# ==================================================

numeric_columns = [
    "price",
    "daily_sales",
    "seven_day_sales",
    "fifteen_day_sales",
    "thirty_day_sales",
    "total_sales",
    "growth",
    "creators",
    "video_count_7d",
    "live_count_7d",
    "promotion_count_7d",
    "sales_per_promo",
    "age_days",
    "score",
    "gmv",
    "seven_day_gmv",
    "rating",
    "reviews",
    "commission_rate",
]


for column in numeric_columns:
    df[column] = pd.to_numeric(
        df[column],
        errors="coerce",
    ).fillna(
        0
    )


# ==================================================
# FILTER CONDITIONS
# ==================================================

price_condition = (
    df["price"]
    <= max_price
)


sales_condition = (
    df["seven_day_sales"]
    >= minimum_7d_sales
)


growth_condition = (
    df["growth"]
    >= minimum_growth
)


promotion_condition = (
    df["promotion_count_7d"]
    <= maximum_promotions
)


age_condition = (
    df["age_days"]
    <= maximum_age
)


score_condition = (
    df["score"]
    >= minimum_score
)


# ==================================================
# EMERGING PRODUCTS
# ==================================================

emerging = df[
    price_condition
    &
    sales_condition
    &
    growth_condition
    &
    promotion_condition
    &
    age_condition
    &
    score_condition
].copy()


emerging = emerging.sort_values(
    [
        "score",
        "growth",
    ],
    ascending=[
        False,
        False,
    ],
)


# ==================================================
# CURRENT SCAN
# ==================================================

st.sidebar.divider()

st.sidebar.subheader(
    "Current Scan"
)


st.sidebar.write(
    f"Products returned: **{len(df)}**"
)


if len(df) > 0:
    st.sidebar.write(
        f"Price range: "
        f"**${df['price'].min():.2f} – "
        f"${df['price'].max():.2f}**"
    )

    st.sidebar.write(
        f"7-day sales: "
        f"**{int(df['seven_day_sales'].min())} – "
        f"{int(df['seven_day_sales'].max())}**"
    )

    st.sidebar.write(
        f"Growth: "
        f"**{df['growth'].min():.1f}% – "
        f"{df['growth'].max():.1f}%**"
    )

    st.sidebar.write(
        f"7-day promotions: "
        f"**{int(df['promotion_count_7d'].min())} – "
        f"{int(df['promotion_count_7d'].max())}**"
    )


# ==================================================
# TABS
# ==================================================

(
    radar_tab,
    all_products_tab,
    inspector_tab,
    watchlist_tab,
) = st.tabs(
    [
        "🔥 Emerging Radar",
        "📦 All Products",
        "🔎 Product Inspector",
        "⭐ Watchlist",
    ]
)


# ==================================================
# EMERGING RADAR
# ==================================================

with radar_tab:
    st.subheader(
        "🔥 Emerging Product Radar"
    )

    st.caption(
        "Products with strong recent sales momentum "
        "without excessive recent promotion activity."
    )

    metric1, metric2, metric3, metric4 = st.columns(
        4
    )

    metric1.metric(
        "Products Scanned",
        len(df),
    )

    metric2.metric(
        "Candidates",
        len(emerging),
    )

    if len(emerging) > 0:
        metric3.metric(
            "Best FlipScore",
            round(
                emerging.iloc[0]["score"],
                1,
            ),
        )

        metric4.metric(
            "Highest Growth",
            f"{emerging['growth'].max():.1f}%",
        )

    else:
        metric3.metric(
            "Best FlipScore",
            "-",
        )

        metric4.metric(
            "Highest Growth",
            "-",
        )

    st.divider()

    # --------------------------------------------------
    # FILTER DIAGNOSTICS
    # --------------------------------------------------

    st.write(
        "### Filter Diagnostics"
    )

    d1, d2, d3 = st.columns(
        3
    )

    d1.metric(
        "Pass Price",
        int(
            price_condition.sum()
        ),
    )

    d2.metric(
        "Pass 7D Sales",
        int(
            sales_condition.sum()
        ),
    )

    d3.metric(
        "Pass Growth",
        int(
            growth_condition.sum()
        ),
    )

    d4, d5, d6 = st.columns(
        3
    )

    d4.metric(
        "Pass Promotion Limit",
        int(
            promotion_condition.sum()
        ),
    )

    d5.metric(
        "Pass Age",
        int(
            age_condition.sum()
        ),
    )

    d6.metric(
        "Pass FlipScore",
        int(
            score_condition.sum()
        ),
    )

    st.divider()

    # --------------------------------------------------
    # RESULTS
    # --------------------------------------------------

    if len(emerging) == 0:
        st.warning(
            "No products currently pass every Emerging Radar filter."
        )

    else:
        display = emerging[
            [
                "status",
                "name",
                "price",
                "seven_day_sales",
                "growth",
                "promotion_count_7d",
                "sales_per_promo",
                "age_days",
                "score",
            ]
        ].copy()

        display.columns = [
            "Status",
            "Product",
            "Price",
            "7D Sales",
            "Momentum %",
            "7D Promotions",
            "Sales / Promo",
            "Age Days",
            "FlipScore",
        ]

        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
        )


# ==================================================
# ALL PRODUCTS
# ==================================================

with all_products_tab:
    st.subheader(
        "All Products Returned by EchoTik"
    )

    st.caption(
        "This view ignores Emerging Radar filters. "
        "Product photos come from the saved EchoTik cover image."
    )

    all_products_display = df.sort_values(
        "score",
        ascending=False,
    ).reset_index(
        drop=True
    )

    cards_per_row = 3

    for row_start in range(
        0,
        len(all_products_display),
        cards_per_row,
    ):
        row_columns = st.columns(
            cards_per_row
        )

        for offset in range(
            cards_per_row
        ):
            row_index = (
                row_start
                + offset
            )

            if row_index >= len(
                all_products_display
            ):
                break

            product = (
                all_products_display
                .iloc[
                    row_index
                ]
            )

            with row_columns[
                offset
            ]:
                with st.container(
                    border=True
                ):
                    cover = str(
                        product.get(
                            "cover",
                            "",
                        )
                        or ""
                    ).strip()

                    image_bytes = (
                        fetch_product_image(
                            cover
                        )
                        if cover
                        else None
                    )

                    if image_bytes:
                        st.image(
                            image_bytes,
                            width="stretch",
                        )

                    else:
                        st.caption(
                            "🖼️ Product photo unavailable"
                        )

                    st.markdown(
                        f"**{product['name']}**"
                    )

                    st.caption(
                        str(
                            product[
                                "status"
                            ]
                        )
                    )

                    stat1, stat2 = st.columns(
                        2
                    )

                    stat1.metric(
                        "Price",
                        f"${product['price']:.2f}",
                    )

                    stat2.metric(
                        "FlipScore",
                        f"{product['score']:.1f}",
                    )

                    stat3, stat4 = st.columns(
                        2
                    )

                    stat3.metric(
                        "7D Sales",
                        f"{int(product['seven_day_sales']):,}",
                    )

                    stat4.metric(
                        "Momentum",
                        f"{product['growth']:+.1f}%",
                    )

                    st.caption(
                        f"Daily est. {int(product['daily_sales']):,} "
                        f"• Age {int(product['age_days'])}d "
                        f"• 7D promos {int(product['promotion_count_7d']):,}"
                    )

    st.caption(
        "*Daily Sales may be a 7-day daily average "
        "when EchoTik does not provide a usable 1-day value."
    )

    with st.expander(
        "🛠 Developer Debug View"
    ):
        selected_debug_product = st.selectbox(
            "Select a product to inspect",
            df["name"].tolist(),
            key="debug_product",
        )

        raw_record = df[
            df["name"]
            == selected_debug_product
        ].iloc[0]

        st.json(
            raw_record.to_dict()
        )


# ==================================================
# PRODUCT INSPECTOR
# ==================================================

with inspector_tab:
    st.subheader(
        "Product Inspector"
    )

    product_name = st.selectbox(
        "Select product",
        df["name"].tolist(),
        key="inspector_product",
    )

    selected = df[
        df["name"]
        == product_name
    ].iloc[0]

    # --------------------------------------------------
    # HEADER
    # --------------------------------------------------

    left, right = st.columns(
        [
            3,
            1,
        ]
    )

    with left:
        st.write(
            f"## {selected['name']}"
        )

        st.write(
            f"**Status:** "
            f"{selected['status']}"
        )

        if selected.get(
            "shop_name"
        ):
            st.caption(
                f"Shop: {selected['shop_name']}"
            )

    with right:
        cover = str(
            selected.get(
                "cover",
                "",
            )
            or ""
        ).strip()

        image_bytes = (
            fetch_product_image(
                cover
            )
            if cover
            else None
        )

        if image_bytes:
            st.caption(
                "Product photo"
            )

            st.image(
                image_bytes,
                width=220,
            )

        else:
            st.info(
                "Product photo unavailable."
            )

    # --------------------------------------------------
    # MAIN STATS
    # --------------------------------------------------

    c1, c2, c3, c4 = st.columns(
        4
    )

    c1.metric(
        "Price",
        f"${selected['price']:.2f}",
    )

    c2.metric(
        "7-Day Sales",
        int(
            selected[
                "seven_day_sales"
            ]
        ),
    )

    c3.metric(
        "Momentum",
        f"{selected['growth']:.1f}%",
    )

    c4.metric(
        "FlipScore",
        round(
            selected[
                "score"
            ],
            1,
        ),
    )

    st.divider()

    # --------------------------------------------------
    # PROMOTION
    # --------------------------------------------------

    st.write(
        "### Promotion & Saturation"
    )

    p1, p2, p3, p4 = st.columns(
        4
    )

    p1.metric(
        "7D Videos",
        int(
            selected[
                "video_count_7d"
            ]
        ),
    )

    p2.metric(
        "7D Lives",
        int(
            selected[
                "live_count_7d"
            ]
        ),
    )

    p3.metric(
        "7D Promotions",
        int(
            selected[
                "promotion_count_7d"
            ]
        ),
    )

    p4.metric(
        "Sales / Promotion",
        round(
            selected[
                "sales_per_promo"
            ],
            1,
        ),
    )

    st.caption(
        f"Lifetime associated creators: "
        f"{int(selected['creators']):,}"
    )

    st.divider()

    # --------------------------------------------------
    # SALES WINDOWS
    # --------------------------------------------------

    st.write(
        "### Sales Momentum"
    )

    s1, s2, s3, s4 = st.columns(
        4
    )

    s1.metric(
        "Daily Estimate",
        int(
            selected[
                "daily_sales"
            ]
        ),
    )

    s2.metric(
        "7 Days",
        int(
            selected[
                "seven_day_sales"
            ]
        ),
    )

    s3.metric(
        "15 Days",
        int(
            selected[
                "fifteen_day_sales"
            ]
        ),
    )

    s4.metric(
        "30 Days",
        int(
            selected[
                "thirty_day_sales"
            ]
        ),
    )

    st.caption(
        f"Momentum source: "
        f"`{selected.get('growth_source', 'unknown')}`"
    )

    st.divider()

    # --------------------------------------------------
    # COMMERCE
    # --------------------------------------------------

    st.write(
        "### Commerce"
    )

    commerce1, commerce2, commerce3 = st.columns(
        3
    )

    commerce1.metric(
        "7D GMV",
        f"${selected['seven_day_gmv']:,.0f}",
    )

    commerce2.metric(
        "Total Sales",
        f"{int(selected['total_sales']):,}",
    )

    commerce3.metric(
        "Commission",
        f"{selected['commission_rate'] * 100:.1f}%",
    )

    st.divider()

    # --------------------------------------------------
    # WATCHLIST
    # --------------------------------------------------

    if st.button(
        "⭐ Add to Watchlist",
        width="stretch",
    ):
        add_to_watchlist(
            selected.to_dict()
        )

        st.success(
            "Added to watchlist."
        )

    # --------------------------------------------------
    # HISTORY
    # --------------------------------------------------

    st.divider()

    st.subheader(
        "📈 FlipRadar Scan History"
    )

    history = get_product_history(
        str(
            selected["id"]
        )
    )

    if len(history) < 2:
        st.info(
            "FlipRadar needs at least two saved scans "
            "to build historical charts."
        )

    else:
        history_df = pd.DataFrame(
            history,
            columns=[
                "Timestamp",
                "Price",
                "Daily Sales",
                "7D Sales",
                "Creators",
                "Growth",
                "FlipScore",
            ],
        )

        history_df[
            "Timestamp"
        ] = pd.to_datetime(
            history_df[
                "Timestamp"
            ],
            format="mixed",
            errors="coerce",
        )

        history_df = (
            history_df
            .dropna(
                subset=[
                    "Timestamp"
                ]
            )
            .sort_values(
                "Timestamp"
            )
        )

        if len(
            history_df
        ) >= 2:
            st.write(
                "### 7-Day Sales History"
            )

            st.line_chart(
                history_df.set_index(
                    "Timestamp"
                )[
                    [
                        "7D Sales"
                    ]
                ],
                width="stretch",
            )

            st.write(
                "### FlipScore History"
            )

            st.line_chart(
                history_df.set_index(
                    "Timestamp"
                )[
                    [
                        "FlipScore"
                    ]
                ],
                width="stretch",
            )


# ==================================================
# WATCHLIST
# ==================================================

with watchlist_tab:
    st.subheader(
        "⭐ Watchlist"
    )

    watchlist = get_watchlist()

    if not watchlist:
        st.info(
            "You haven't saved any products yet."
        )

    else:
        watch_df = pd.DataFrame(
            watchlist,
            columns=[
                "Product ID",
                "Product",
            ],
        )

        st.dataframe(
            watch_df,
            width="stretch",
            hide_index=True,
        )
