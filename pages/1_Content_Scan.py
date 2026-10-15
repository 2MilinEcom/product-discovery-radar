import pandas as pd
import streamlit as st

from database import (
    initialize_database,
    load_latest_scan
)

from content_scanner import (
    scan_product_content_deep,
    resolve_creator_profiles
)

from content_database import (
    initialize_content_database,
    save_content_scan,
    load_content_scan
)


# ==================================================
# CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar Content Scan",
    page_icon="🎬",
    layout="wide"
)


initialize_database()
initialize_content_database()


# ==================================================
# HEADER
# ==================================================

st.title(
    "🎬 Content Deep Scan"
)


st.caption(
    "Find the viral, converting, and highest-revenue "
    "TikTok videos associated with a TikTok Shop product."
)


# ==================================================
# LOAD PRODUCTS
# ==================================================

products, scan_time = (
    load_latest_scan()
)


if not products:

    st.warning(
        "FlipRadar has no saved product scan yet. "
        "Return to the main Radar page and run "
        "a market scan first."
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


info1, info2, info3 = st.columns(
    3
)


info1.metric(
    "FlipScore",
    selected.get(
        "score",
        0
    )
)


info2.metric(
    "Sales Momentum",
    f"{selected.get('growth', 0)}%"
)


info3.metric(
    "7D Product Sales",
    f"{int(selected.get('seven_day_sales', 0)):,}"
)


# ==================================================
# DEEP CONTENT SCAN
# ==================================================

st.divider()

st.subheader(
    "🔭 30-Day Content Discovery"
)


st.write(
    "FlipRadar searches three different content lanes:"
)


lane1, lane2, lane3 = st.columns(
    3
)


with lane1:

    st.write(
        "### 🚀 Viral"
    )

    st.caption(
        "Videos surfaced by total views."
    )


with lane2:

    st.write(
        "### 🛒 Converting"
    )

    st.caption(
        "Videos surfaced by attributed product sales."
    )


with lane3:

    st.write(
        "### 💰 Revenue"
    )

    st.caption(
        "Videos surfaced by attributed video GMV."
    )


st.info(
    "Running a new Content Deep Scan uses "
    "**3 EchoTik API requests**. "
    "Results are saved locally afterward."
)


if st.button(
    "🔭 Run 3-Lane Content Deep Scan",
    width="stretch"
):

    try:

        with st.spinner(
            "Searching viral, converting, "
            "and revenue-driving videos..."
        ):

            videos = scan_product_content_deep(
                product_id=product_id,
                days=30,
                page_size=10
            )


            save_content_scan(
                product_id,
                selected_name,
                videos
            )


        st.success(
            f"Deep Scan complete — "
            f"{len(videos)} unique videos found."
        )


    except Exception as error:

        st.error(
            f"Content Deep Scan failed: {error}"
        )


# ==================================================
# LOAD CACHE
# ==================================================

videos, fetched_at = (
    load_content_scan(
        product_id
    )
)


if not videos:

    st.info(
        "No cached Content Deep Scan exists "
        "for this product yet."
    )

    st.stop()


st.caption(
    f"Cached scan: {fetched_at}"
)


# ==================================================
# REQUIRED FIELDS
# ==================================================

df = pd.DataFrame(
    videos
)


required_columns = {

    "video_id":
        "",

    "creator":
        "",

    "creator_user_id":
        "",

    "creator_username":
        "",

    "creator_name":
        "",

    "creator_avatar":
        "",

    "creator_followers":
        0,

    "creator_profile_url":
        "",

    "canonical_url":
        "",

    "discovery_lanes":
        None,

    "caption":
        "",

    "created":
        "",

    "duration":
        0,

    "views":
        0,

    "views_1d":
        0,

    "views_7d":
        0,

    "views_30d":
        0,

    "likes":
        0,

    "comments":
        0,

    "favorites":
        0,

    "shares":
        0,

    "video_sales":
        0,

    "video_gmv":
        0,

    "cover":
        "",

    "video_url":
        ""
}


for column, default in required_columns.items():

    if column not in df.columns:

        if column == "discovery_lanes":

            df[
                column
            ] = [
                []
                for _ in range(
                    len(
                        df
                    )
                )
            ]

        else:

            df[
                column
            ] = default


# ==================================================
# OLD CACHE COMPATIBILITY
# ==================================================

df[
    "creator_user_id"
] = df[
    "creator_user_id"
].replace(
    "",
    pd.NA
).fillna(
    df[
        "creator"
    ]
)


def normalize_lane_list(value):

    if isinstance(
        value,
        list
    ):

        return value


    if not value:

        return []


    return [
        str(
            value
        )
    ]


df[
    "discovery_lanes"
] = df[
    "discovery_lanes"
].apply(
    normalize_lane_list
)


# ==================================================
# NUMERIC CLEANUP
# ==================================================

numeric_columns = [

    "creator_followers",

    "duration",

    "views",

    "views_1d",

    "views_7d",

    "views_30d",

    "likes",

    "comments",

    "favorites",

    "shares",

    "video_sales",

    "video_gmv"
]


for column in numeric_columns:

    df[
        column
    ] = pd.to_numeric(
        df[
            column
        ],
        errors="coerce"
    ).fillna(
        0
    )


# ==================================================
# URL HELPERS
# ==================================================

def get_tiktok_player_url(
    video_id
):

    video_id = str(
        video_id
    ).strip()


    if not video_id:

        return ""


    return (
        "https://www.tiktok.com/"
        f"player/v1/{video_id}"
    )


df[
    "tiktok_player"
] = df[
    "video_id"
].astype(
    str
).apply(
    get_tiktok_player_url
)


# ==================================================
# CREATOR RECOVERY
# ==================================================

unique_creator_ids = set()


resolved_creator_ids = set()


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

        unique_creator_ids.add(
            creator_id
        )


    if video.get(
        "creator_username"
    ):

        resolved_creator_ids.add(
            creator_id
        )


st.divider()

st.subheader(
    "👤 Creator Links"
)


creator_col1, creator_col2 = st.columns(
    2
)


creator_col1.metric(
    "Unique Creators",
    len(
        unique_creator_ids
    )
)


creator_col2.metric(
    "Creators Resolved",
    len(
        resolved_creator_ids
    )
)


if (
    len(
        resolved_creator_ids
    )
    < len(
        unique_creator_ids
    )
):

    st.caption(
        "Creator recovery is optional and uses "
        "approximately one additional EchoTik request "
        "for up to 10 creators."
    )


    if st.button(
        "👤 Resolve TikTok Creator Links",
        width="stretch"
    ):

        try:

            with st.spinner(
                "Resolving TikTok creators..."
            ):

                enriched_videos, resolved_count = (
                    resolve_creator_profiles(
                        videos
                    )
                )


                save_content_scan(
                    product_id,
                    selected_name,
                    enriched_videos
                )


            st.success(
                f"Resolved {resolved_count} creator profiles."
            )


            st.rerun()


        except Exception as error:

            st.error(
                f"Creator recovery failed: {error}"
            )


# ==================================================
# LANE COUNTS
# ==================================================

def in_lane(
    lanes,
    target
):

    return (
        target
        in normalize_lane_list(
            lanes
        )
    )


viral_count = int(
    df[
        "discovery_lanes"
    ].apply(
        lambda lanes:
            in_lane(
                lanes,
                "viral"
            )
    ).sum()
)


converting_count = int(
    df[
        "discovery_lanes"
    ].apply(
        lambda lanes:
            in_lane(
                lanes,
                "converting"
            )
    ).sum()
)


revenue_count = int(
    df[
        "discovery_lanes"
    ].apply(
        lambda lanes:
            in_lane(
                lanes,
                "revenue"
            )
    ).sum()
)


# ==================================================
# HERO RESULTS
# ==================================================

st.divider()

st.subheader(
    "🏆 Best Content Signals"
)


hero1, hero2, hero3 = st.columns(
    3
)


top_viral = df.sort_values(
    "views",
    ascending=False
).iloc[
    0
]


top_converting = df.sort_values(
    "video_sales",
    ascending=False
).iloc[
    0
]


top_revenue = df.sort_values(
    "video_gmv",
    ascending=False
).iloc[
    0
]


with hero1:

    st.write(
        "### 🚀 Top Viral"
    )

    st.metric(
        "Views",
        f"{int(top_viral['views']):,}"
    )

    st.caption(
        str(
            top_viral[
                "caption"
            ]
        )[
            :120
        ]
    )


with hero2:

    st.write(
        "### 🛒 Top Converter"
    )

    st.metric(
        "Video Sales",
        f"{int(top_converting['video_sales']):,}"
    )

    st.caption(
        str(
            top_converting[
                "caption"
            ]
        )[
            :120
        ]
    )


with hero3:

    st.write(
        "### 💰 Top Revenue"
    )

    st.metric(
        "Video GMV",
        f"${top_revenue['video_gmv']:,.0f}"
    )

    st.caption(
        str(
            top_revenue[
                "caption"
            ]
        )[
            :120
        ]
    )


# ==================================================
# OVERVIEW
# ==================================================

total_views = int(
    df[
        "views"
    ].sum()
)


total_sales = int(
    df[
        "video_sales"
    ].sum()
)


total_gmv = float(
    df[
        "video_gmv"
    ].sum()
)


total_likes = int(
    df[
        "likes"
    ].sum()
)


total_comments = int(
    df[
        "comments"
    ].sum()
)


total_favorites = int(
    df[
        "favorites"
    ].sum()
)


total_shares = int(
    df[
        "shares"
    ].sum()
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


st.divider()

st.subheader(
    "30-Day Content Overview"
)


o1, o2, o3, o4 = st.columns(
    4
)


o1.metric(
    "Unique Videos Found",
    len(
        df
    )
)


o2.metric(
    "Combined Views",
    f"{total_views:,}"
)


o3.metric(
    "Attributed Sales",
    f"{total_sales:,}"
)


o4.metric(
    "Attributed GMV",
    f"${total_gmv:,.0f}"
)


o5, o6, o7, o8 = st.columns(
    4
)


o5.metric(
    "Viral Lane Videos",
    viral_count
)


o6.metric(
    "Converting Lane Videos",
    converting_count
)


o7.metric(
    "Revenue Lane Videos",
    revenue_count
)


o8.metric(
    "Sales / 1K Views",
    f"{sales_per_1000_views:.2f}"
)


# ==================================================
# VIRAL REPEATABILITY
# ==================================================

videos_100k = int(
    (
        df[
            "views"
        ]
        >= 100000
    ).sum()
)


videos_500k = int(
    (
        df[
            "views"
        ]
        >= 500000
    ).sum()
)


videos_1m = int(
    (
        df[
            "views"
        ]
        >= 1000000
    ).sum()
)


top_video_views = int(
    df[
        "views"
    ].max()
)


if total_views > 0:

    top_video_share = (
        top_video_views
        / total_views
    ) * 100

else:

    top_video_share = 0


st.divider()

st.subheader(
    "🔥 Viral Repeatability"
)


v1, v2, v3, v4 = st.columns(
    4
)


v1.metric(
    "Videos 100K+",
    videos_100k
)


v2.metric(
    "Videos 500K+",
    videos_500k
)


v3.metric(
    "Videos 1M+",
    videos_1m
)


v4.metric(
    "Top Video Share",
    f"{top_video_share:.1f}%"
)


if (
    videos_1m >= 3
):

    st.success(
        "🔥 Strong repeatability signal: "
        "multiple videos have crossed 1M views."
    )


elif (
    videos_100k >= 3
    and top_video_share < 60
):

    st.success(
        "📈 Multiple videos have significant traction "
        "without one video dominating everything."
    )


elif (
    top_video_share >= 70
):

    st.warning(
        "⚠️ Most sampled attention is concentrated "
        "in a single viral video."
    )


else:

    st.info(
        "Content traction exists, but viral "
        "repeatability is not yet especially strong."
    )


# ==================================================
# ENGAGEMENT
# ==================================================

st.divider()

st.subheader(
    "Engagement"
)


e1, e2, e3, e4, e5 = st.columns(
    5
)


e1.metric(
    "Likes",
    f"{total_likes:,}"
)


e2.metric(
    "Comments",
    f"{total_comments:,}"
)


e3.metric(
    "Favorites",
    f"{total_favorites:,}"
)


e4.metric(
    "Shares",
    f"{total_shares:,}"
)


e5.metric(
    "Engagement Rate",
    f"{engagement_rate:.2f}%"
)


# ==================================================
# PREVIEW SORT
# ==================================================

st.divider()

st.subheader(
    "🎥 Video Explorer"
)


preview_mode = st.radio(
    "Rank videos by",
    [
        "🚀 Views",
        "🛒 Sales",
        "💰 GMV"
    ],
    horizontal=True
)


if preview_mode == "🚀 Views":

    preview_df = df.sort_values(
        "views",
        ascending=False
    )


elif preview_mode == "🛒 Sales":

    preview_df = df.sort_values(
        "video_sales",
        ascending=False
    )


else:

    preview_df = df.sort_values(
        "video_gmv",
        ascending=False
    )


preview_rows = (
    preview_df.head(
        10
    ).to_dict(
        "records"
    )
)


# ==================================================
# VIDEO CARDS
# ==================================================

for start_index in range(
    0,
    len(
        preview_rows
    ),
    2
):

    columns = st.columns(
        2
    )


    current_rows = preview_rows[
        start_index:
        start_index + 2
    ]


    for column, video in zip(
        columns,
        current_rows
    ):

        with column:

            video_id = str(
                video.get(
                    "video_id",
                    ""
                )
            )


            username = str(
                video.get(
                    "creator_username",
                    ""
                )
                or ""
            ).strip()


            player_url = (
                get_tiktok_player_url(
                    video_id
                )
            )


            original_url = str(
                video.get(
                    "canonical_url",
                    ""
                )
                or ""
            )


            profile_url = str(
                video.get(
                    "creator_profile_url",
                    ""
                )
                or ""
            )


            lanes = normalize_lane_list(
                video.get(
                    "discovery_lanes",
                    []
                )
            )


            lane_labels = []


            if "viral" in lanes:

                lane_labels.append(
                    "🚀 Viral"
                )


            if "converting" in lanes:

                lane_labels.append(
                    "🛒 Converting"
                )


            if "revenue" in lanes:

                lane_labels.append(
                    "💰 Revenue"
                )


            if lane_labels:

                st.caption(
                    " • ".join(
                        lane_labels
                    )
                )


            if username:

                st.write(
                    f"### @{username}"
                )


            st.write(
                f"**{int(video.get('views', 0)):,} views**"
            )


            caption = str(
                video.get(
                    "caption",
                    ""
                )
                or ""
            )


            if caption:

                st.caption(
                    caption[
                        :180
                    ]
                )


            if player_url:

                st.iframe(
                    player_url,
                    height=650,
                )


            sales_col, gmv_col, share_col = st.columns(
                3
            )


            sales_col.metric(
                "Sales",
                f"{int(video.get('video_sales', 0)):,}"
            )


            gmv_col.metric(
                "GMV",
                f"${float(video.get('video_gmv', 0)):,.0f}"
            )


            share_col.metric(
                "Shares",
                f"{int(video.get('shares', 0)):,}"
            )


            if original_url:

                st.link_button(
                    "↗️ Open Original Post",
                    original_url,
                    width="stretch"
                )


            if profile_url:

                st.link_button(
                    "👤 Creator Profile",
                    profile_url,
                    width="stretch"
                )


            st.caption(
                f"Video ID: {video_id}"
            )


# ==================================================
# TABLE
# ==================================================

st.divider()

st.subheader(
    "📊 Content Dataset"
)


table_df = df.copy()


table_df[
    "Lanes"
] = table_df[
    "discovery_lanes"
].apply(
    lambda lanes:
        ", ".join(
            normalize_lane_list(
                lanes
            )
        )
)


display = table_df[
    [
        "creator_username",
        "Lanes",
        "caption",
        "views",
        "video_sales",
        "video_gmv",
        "likes",
        "comments",
        "favorites",
        "shares",
        "created",
        "canonical_url",
        "creator_profile_url"
    ]
].copy()


display.columns = [

    "Creator",
    "Found In",
    "Caption",
    "Views",
    "Video Sales",
    "Video GMV",
    "Likes",
    "Comments",
    "Favorites",
    "Shares",
    "Created",
    "Original Post",
    "Creator Profile"
]


display[
    "Creator"
] = display[
    "Creator"
].apply(
    lambda value:
        f"@{value}"
        if value
        else "Unresolved"
)


display = display.sort_values(
    "Views",
    ascending=False
)


st.dataframe(
    display,
    width="stretch",
    hide_index=True,
    column_config={

        "Original Post":
            st.column_config.LinkColumn(
                "Original Post",
                display_text="Open"
            ),

        "Creator Profile":
            st.column_config.LinkColumn(
                "Creator Profile",
                display_text="Profile"
            )
    }
)