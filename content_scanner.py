import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv


# ==================================================
# ENVIRONMENT
# ==================================================

load_dotenv()


ECHOTIK_USERNAME = os.getenv(
    "ECHOTIK_USERNAME",
    ""
).strip()


ECHOTIK_PASSWORD = os.getenv(
    "ECHOTIK_PASSWORD",
    ""
).strip()


# ==================================================
# ENDPOINTS
# ==================================================

ECHOTIK_PRODUCT_VIDEO_URL = (
    "https://open.echotik.live/"
    "api/v3/echotik/product/video/list"
)


ECHOTIK_INFLUENCER_DETAIL_URL = (
    "https://open.echotik.live/"
    "api/v3/echotik/influencer/detail"
)


# ==================================================
# ECHOTIK SORT FIELDS
# ==================================================

SORT_BY_VIEWS = 1
SORT_BY_VIDEO_SALES = 2
SORT_BY_VIDEO_GMV = 3


# ==================================================
# HELPERS
# ==================================================

def safe_int(value, default=0):

    try:
        return int(float(value))

    except (
        TypeError,
        ValueError
    ):
        return default


def safe_float(value, default=0.0):

    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return default


def format_created_time(value):

    if not value:
        return ""

    try:

        timestamp = int(
            float(value)
        )

        return datetime.fromtimestamp(
            timestamp
        ).strftime(
            "%Y-%m-%d %H:%M"
        )

    except Exception:
        return ""


def build_profile_url(username):

    username = str(
        username or ""
    ).strip()

    if not username:
        return ""

    return (
        "https://www.tiktok.com/"
        f"@{username}"
    )


def build_canonical_video_url(
    username,
    video_id
):

    username = str(
        username or ""
    ).strip()

    video_id = str(
        video_id or ""
    ).strip()

    if (
        not username
        or not video_id
    ):
        return ""

    return (
        "https://www.tiktok.com/"
        f"@{username}/video/{video_id}"
    )


# ==================================================
# AUTH
# ==================================================

def get_auth():

    if (
        not ECHOTIK_USERNAME
        or not ECHOTIK_PASSWORD
    ):

        raise RuntimeError(
            "EchoTik credentials are missing from .env."
        )

    return (
        ECHOTIK_USERNAME,
        ECHOTIK_PASSWORD
    )


# ==================================================
# RESPONSE CHECK
# ==================================================

def check_response(
    response,
    context
):

    if response.status_code == 400:

        raise RuntimeError(
            f"EchoTik rejected the {context} request. "
            f"Details: {response.text}"
        )


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
            f"EchoTik denied access to {context}."
        )


    if response.status_code == 429:

        raise RuntimeError(
            "EchoTik rate limit reached."
        )


    response.raise_for_status()


    result = response.json()


    if result.get(
        "code"
    ) not in (
        0,
        "0"
    ):

        raise RuntimeError(
            f"EchoTik {context} error: "
            + str(
                result.get(
                    "message",
                    result
                )
            )
        )


    return result


# ==================================================
# EXTRACT LIST
# ==================================================

def extract_list(result):

    data = result.get(
        "data",
        []
    )


    if isinstance(
        data,
        dict
    ):

        data = (
            data.get("list")
            or data.get("items")
            or data.get("records")
            or data.get("data")
            or []
        )


    if not isinstance(
        data,
        list
    ):

        return []


    return data


# ==================================================
# NORMALIZE ONE VIDEO
# ==================================================

def normalize_video(
    raw,
    product_id,
    discovery_lane=""
):

    video_id = str(
        raw.get(
            "video_id",
            ""
        )
    )


    creator_user_id = str(
        raw.get(
            "user_id",
            ""
        )
    )


    creator_username = str(
        raw.get(
            "unique_id",
            ""
        )
        or ""
    )


    creator_name = str(
        raw.get(
            "nick_name",
            ""
        )
        or ""
    )


    return {

        # ------------------------------------------
        # VIDEO IDENTITY
        # ------------------------------------------

        "video_id":
            video_id,

        "creator_user_id":
            creator_user_id,

        "creator":
            creator_user_id,

        "creator_username":
            creator_username,

        "creator_name":
            creator_name,

        "creator_avatar":
            "",

        "creator_followers":
            0,

        "creator_profile_url":
            build_profile_url(
                creator_username
            ),

        "canonical_url":
            build_canonical_video_url(
                creator_username,
                video_id
            ),


        # ------------------------------------------
        # DISCOVERY
        # ------------------------------------------

        "discovery_lanes":
            [
                discovery_lane
            ]
            if discovery_lane
            else [],


        # ------------------------------------------
        # CONTENT
        # ------------------------------------------

        "caption":
            raw.get(
                "video_desc",
                ""
            ),

        "created":
            format_created_time(
                raw.get(
                    "create_time"
                )
            ),

        "create_time":
            safe_int(
                raw.get(
                    "create_time"
                )
            ),

        "duration":
            safe_int(
                raw.get(
                    "duration"
                )
            ),


        # ------------------------------------------
        # VIEWS
        # ------------------------------------------

        "views":
            safe_int(
                raw.get(
                    "total_views_cnt"
                )
            ),

        "views_1d":
            safe_int(
                raw.get(
                    "total_views_1d_cnt"
                )
            ),

        "views_7d":
            safe_int(
                raw.get(
                    "total_views_7d_cnt"
                )
            ),

        "views_30d":
            safe_int(
                raw.get(
                    "total_views_30d_cnt"
                )
            ),


        # ------------------------------------------
        # ENGAGEMENT
        # ------------------------------------------

        "likes":
            safe_int(
                raw.get(
                    "total_digg_cnt"
                )
            ),

        "comments":
            safe_int(
                raw.get(
                    "total_comments_cnt"
                )
            ),

        "favorites":
            safe_int(
                raw.get(
                    "total_favorites_cnt"
                )
            ),

        "shares":
            safe_int(
                raw.get(
                    "total_shares_cnt"
                )
            ),


        # ------------------------------------------
        # SALES
        # ------------------------------------------

        "video_sales":
            safe_int(
                raw.get(
                    "total_video_sale_cnt"
                )
            ),

        "video_gmv":
            safe_float(
                raw.get(
                    "total_video_sale_gmv_amt"
                )
            ),


        # ------------------------------------------
        # PRODUCT
        # ------------------------------------------

        "product_id":
            str(
                raw.get(
                    "product_id",
                    product_id
                )
            ),


        # ------------------------------------------
        # OTHER
        # ------------------------------------------

        "hashtags":
            raw.get(
                "hash_tag",
                ""
            ),

        "cover":
            raw.get(
                "reflow_cover",
                ""
            ),

        "region":
            raw.get(
                "region",
                ""
            ),

        "video_url":
            raw.get(
                "play_addr",
                ""
            )
            or ""
    }


# ==================================================
# REQUEST ONE DISCOVERY LANE
# ==================================================

def request_content_lane(
    product_id,
    sort_field,
    lane_name,
    days=30,
    page_size=10
):

    page_size = max(
        1,
        min(
            int(page_size),
            10
        )
    )


    now = datetime.now()

    start = (
        now
        - timedelta(
            days=int(days)
        )
    )


    params = {

        "product_id":
            str(product_id),

        "min_create_time":
            int(
                start.timestamp()
            ),

        "max_create_time":
            int(
                now.timestamp()
            ),

        "product_video_sort_field":
            int(
                sort_field
            ),

        # EchoTik convention:
        # 0 = ascending
        # 1 = descending
        "sort_type":
            1,

        "page_num":
            1,

        "page_size":
            page_size
    }


    print(
        "----------------------------------------"
    )

    print(
        f"Content lane: {lane_name}"
    )

    print(
        f"Sort field: {sort_field}"
    )

    print(
        f"Product: {product_id}"
    )

    print(
        f"Window: last {days} days"
    )

    print(
        "----------------------------------------"
    )


    response = requests.get(
        ECHOTIK_PRODUCT_VIDEO_URL,
        params=params,
        auth=get_auth(),
        timeout=30
    )


    result = check_response(
        response,
        f"{lane_name} content lane"
    )


    raw_videos = extract_list(
        result
    )


    videos = []


    for raw in raw_videos:

        if not isinstance(
            raw,
            dict
        ):
            continue


        video = normalize_video(
            raw,
            product_id,
            lane_name
        )


        if not video[
            "video_id"
        ]:
            continue


        videos.append(
            video
        )


    return videos


# ==================================================
# 3-LANE CONTENT DEEP SCAN
# ==================================================

def scan_product_content_deep(
    product_id,
    days=30,
    page_size=10
):

    """
    Uses exactly 3 EchoTik requests:

    1. Viral       -> sort by views
    2. Converting  -> sort by video sales
    3. Revenue     -> sort by video GMV

    Results are merged and deduplicated by video_id.
    """


    print()
    print(
        "=================================================="
    )

    print(
        "FLIPRADAR 3-LANE CONTENT DEEP SCAN"
    )

    print(
        "=================================================="
    )

    print(
        f"Product ID: {product_id}"
    )

    print(
        f"Window: last {days} days"
    )

    print(
        "EchoTik requests: 3"
    )

    print(
        "=================================================="
    )


    # ==================================================
    # LANE 1 — VIRAL
    # ==================================================

    viral = request_content_lane(
        product_id=product_id,
        sort_field=SORT_BY_VIEWS,
        lane_name="viral",
        days=days,
        page_size=page_size
    )


    # EchoTik ordering isn't perfectly reliable,
    # so sort the returned sample ourselves.
    viral = sorted(
        viral,
        key=lambda item:
            item.get(
                "views",
                0
            ),
        reverse=True
    )


    # ==================================================
    # LANE 2 — CONVERTING
    # ==================================================

    converting = request_content_lane(
        product_id=product_id,
        sort_field=SORT_BY_VIDEO_SALES,
        lane_name="converting",
        days=days,
        page_size=page_size
    )


    converting = sorted(
        converting,
        key=lambda item:
            item.get(
                "video_sales",
                0
            ),
        reverse=True
    )


    # ==================================================
    # LANE 3 — REVENUE
    # ==================================================

    revenue = request_content_lane(
        product_id=product_id,
        sort_field=SORT_BY_VIDEO_GMV,
        lane_name="revenue",
        days=days,
        page_size=page_size
    )


    revenue = sorted(
        revenue,
        key=lambda item:
            item.get(
                "video_gmv",
                0
            ),
        reverse=True
    )


    # ==================================================
    # MERGE + DEDUPLICATE
    # ==================================================

    merged_by_id = {}


    for lane in [
        viral,
        converting,
        revenue
    ]:

        for video in lane:

            video_id = str(
                video.get(
                    "video_id",
                    ""
                )
            )


            if not video_id:
                continue


            if video_id not in merged_by_id:

                merged_by_id[
                    video_id
                ] = dict(
                    video
                )

                continue


            existing = merged_by_id[
                video_id
            ]


            existing_lanes = list(
                existing.get(
                    "discovery_lanes",
                    []
                )
            )


            for lane_name in video.get(
                "discovery_lanes",
                []
            ):

                if lane_name not in existing_lanes:

                    existing_lanes.append(
                        lane_name
                    )


            existing[
                "discovery_lanes"
            ] = existing_lanes


            # Keep the strongest known metric values.

            existing[
                "views"
            ] = max(
                safe_int(
                    existing.get(
                        "views"
                    )
                ),
                safe_int(
                    video.get(
                        "views"
                    )
                )
            )


            existing[
                "video_sales"
            ] = max(
                safe_int(
                    existing.get(
                        "video_sales"
                    )
                ),
                safe_int(
                    video.get(
                        "video_sales"
                    )
                )
            )


            existing[
                "video_gmv"
            ] = max(
                safe_float(
                    existing.get(
                        "video_gmv"
                    )
                ),
                safe_float(
                    video.get(
                        "video_gmv"
                    )
                )
            )


    merged = list(
        merged_by_id.values()
    )


    # Main visual ordering:
    # highest views first.
    merged = sorted(
        merged,
        key=lambda item: (
            item.get(
                "views",
                0
            ),
            item.get(
                "video_sales",
                0
            ),
            item.get(
                "video_gmv",
                0
            )
        ),
        reverse=True
    )


    # ==================================================
    # LOG SUMMARY
    # ==================================================

    print()
    print(
        "=================================================="
    )

    print(
        "CONTENT DEEP SCAN COMPLETE"
    )

    print(
        "=================================================="
    )

    print(
        f"Viral lane: "
        f"{len(viral)}"
    )

    print(
        f"Converting lane: "
        f"{len(converting)}"
    )

    print(
        f"Revenue lane: "
        f"{len(revenue)}"
    )

    print(
        f"Unique videos after merge: "
        f"{len(merged)}"
    )


    if viral:

        print(
            "Top viral:"
        )

        print(
            f"  {viral[0]['views']:,} views"
        )


    if converting:

        print(
            "Top converter:"
        )

        print(
            f"  {converting[0]['video_sales']:,} sales"
        )


    if revenue:

        print(
            "Top revenue:"
        )

        print(
            f"  ${revenue[0]['video_gmv']:,.2f}"
        )


    print(
        "=================================================="
    )


    return merged


# ==================================================
# OLD SINGLE-LANE FUNCTION
#
# Kept so older code does not break.
# ==================================================

def scan_product_videos(
    product_id,
    page_size=10
):

    return request_content_lane(
        product_id=product_id,
        sort_field=SORT_BY_VIEWS,
        lane_name="viral",
        days=30,
        page_size=page_size
    )


# ==================================================
# CREATOR PROFILE RECOVERY
# ==================================================

def resolve_creator_profiles(
    videos
):

    user_ids = []


    for video in videos:

        user_id = str(
            video.get(
                "creator_user_id"
            )
            or video.get(
                "creator"
            )
            or ""
        ).strip()


        if (
            user_id
            and user_id not in user_ids
        ):

            user_ids.append(
                user_id
            )


    # EchoTik batch creator lookup:
    # keep to 10 per request.
    user_ids = user_ids[
        :10
    ]


    if not user_ids:

        return videos, 0


    params = {

        "user_ids":
            ",".join(
                user_ids
            )
    }


    print(
        "----------------------------------------"
    )

    print(
        "Resolving creator profiles..."
    )

    print(
        f"Creators requested: "
        f"{len(user_ids)}"
    )

    print(
        "----------------------------------------"
    )


    response = requests.get(
        ECHOTIK_INFLUENCER_DETAIL_URL,
        params=params,
        auth=get_auth(),
        timeout=30
    )


    result = check_response(
        response,
        "creator profile"
    )


    data = extract_list(
        result
    )


    creator_map = {}


    for creator in data:

        if not isinstance(
            creator,
            dict
        ):
            continue


        user_id = str(
            creator.get(
                "user_id",
                ""
            )
        ).strip()


        username = str(
            creator.get(
                "unique_id",
                ""
            )
            or ""
        ).strip()


        if not user_id:
            continue


        creator_map[
            user_id
        ] = {

            "username":
                username,

            "name":
                str(
                    creator.get(
                        "nick_name",
                        ""
                    )
                    or ""
                ),

            "avatar":
                str(
                    creator.get(
                        "avatar",
                        ""
                    )
                    or ""
                ),

            "followers":
                safe_int(
                    creator.get(
                        "total_followers_cnt"
                    )
                )
        }


    enriched_videos = []


    for original_video in videos:

        video = dict(
            original_video
        )


        user_id = str(
            video.get(
                "creator_user_id"
            )
            or video.get(
                "creator"
            )
            or ""
        ).strip()


        creator_data = creator_map.get(
            user_id
        )


        if creator_data:

            username = creator_data[
                "username"
            ]


            video[
                "creator_username"
            ] = username


            video[
                "creator_name"
            ] = creator_data[
                "name"
            ]


            video[
                "creator_avatar"
            ] = creator_data[
                "avatar"
            ]


            video[
                "creator_followers"
            ] = creator_data[
                "followers"
            ]


            video[
                "creator_profile_url"
            ] = build_profile_url(
                username
            )


            video[
                "canonical_url"
            ] = build_canonical_video_url(
                username,
                video.get(
                    "video_id",
                    ""
                )
            )


        enriched_videos.append(
            video
        )


    resolved_count = sum(

        1

        for user_id in user_ids

        if user_id in creator_map

    )


    print(
        f"Resolved "
        f"{resolved_count} creators."
    )


    return (
        enriched_videos,
        resolved_count
    )