import os
import re
from datetime import datetime

import requests
from dotenv import load_dotenv


# ==================================================
# ENVIRONMENT
# ==================================================

load_dotenv()

FASTMOSS_API_KEY = os.getenv(
    "FASTMOSS_API_KEY",
    "",
).strip()


# ==================================================
# FASTMOSS API
# ==================================================

FASTMOSS_PRODUCT_VIDEO_URL = (
    "https://openapi.fastmoss.com/product/v1/videoList"
)

DEFAULT_DAYS = 30
DEFAULT_PAGE_SIZE = 30

VALID_SORT_FIELDS = {
    "play_count",
    "digg_count",
    "comment_count",
    "share_count",
    "units_sold",
    "gmv",
}


# ==================================================
# HELPERS
# ==================================================

def safe_int(
    value,
    default=0,
):
    try:
        return int(
            float(
                value
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_float(
    value,
    default=0.0,
):
    try:
        return float(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return default


def format_created_time(
    timestamp,
):
    timestamp = safe_int(
        timestamp,
        0,
    )

    if timestamp <= 0:
        return ""

    try:
        return datetime.fromtimestamp(
            timestamp
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:
        return ""


def extract_username_from_tiktok_url(
    url,
):
    text = str(
        url
        or ""
    ).strip()

    if not text:
        return ""

    match = re.search(
        r"tiktok\.com/@([^/?]+)/video/",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(1)


def extract_hashtags(
    caption,
):
    text = str(
        caption
        or ""
    )

    hashtags = re.findall(
        r"#[A-Za-z0-9_]+",
        text,
    )

    return " ".join(
        hashtags
    )


def build_profile_url(
    username,
):
    username = str(
        username
        or ""
    ).strip().lstrip("@")

    if not username:
        return ""

    return (
        "https://www.tiktok.com/@"
        f"{username}"
    )


# ==================================================
# NORMALIZATION
# ==================================================

def normalize_fastmoss_video(
    raw,
    product_id="",
    discovery_lane="fastmoss_converting",
):
    """
    Convert one FastMoss product-video result into the same
    normalized shape FlipRadar already uses for content videos.
    """

    if not isinstance(
        raw,
        dict,
    ):
        raw = {}

    nested_video = raw.get(
        "video",
        {},
    )

    if not isinstance(
        nested_video,
        dict,
    ):
        nested_video = {}

    video_id = str(
        raw.get(
            "video_id",
            "",
        )
        or ""
    ).strip()

    tiktok_url = str(
        nested_video.get(
            "tiktok_url",
            "",
        )
        or ""
    ).strip()

    creator_user_id = str(
        nested_video.get(
            "uid",
            "",
        )
        or raw.get(
            "uid",
            "",
        )
        or ""
    ).strip()

    creator_username = (
        extract_username_from_tiktok_url(
            tiktok_url
        )
    )

    caption = str(
        nested_video.get(
            "video_desc",
            "",
        )
        or ""
    )

    create_time = safe_int(
        nested_video.get(
            "create_time",
            0,
        )
    )

    canonical_url = (
        tiktok_url
        or (
            "https://www.tiktok.com/@_/"
            f"video/{video_id}"
            if video_id
            else ""
        )
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
            creator_username,

        "creator_avatar":
            "",

        "creator_followers":
            0,

        "creator_profile_url":
            build_profile_url(
                creator_username
            ),

        "canonical_url":
            canonical_url,

        # ------------------------------------------
        # DISCOVERY
        # ------------------------------------------
        "discovery_lanes":
            [
                discovery_lane
            ]
            if discovery_lane
            else [],

        "data_provider":
            "FastMoss",

        # ------------------------------------------
        # CONTENT
        # ------------------------------------------
        "caption":
            caption,

        "created":
            format_created_time(
                create_time
            ),

        "create_time":
            create_time,

        "duration":
            safe_int(
                nested_video.get(
                    "duration",
                    0,
                )
            ),

        # ------------------------------------------
        # VIEWS
        # ------------------------------------------
        "views":
            safe_int(
                raw.get(
                    "play_count",
                    0,
                )
            ),

        # FastMoss's product-video response does not
        # expose period-specific view counters here.
        "views_1d":
            0,

        "views_7d":
            0,

        "views_30d":
            0,

        # ------------------------------------------
        # ENGAGEMENT
        # ------------------------------------------
        "likes":
            safe_int(
                raw.get(
                    "digg_count",
                    0,
                )
            ),

        "comments":
            safe_int(
                raw.get(
                    "comment_count",
                    0,
                )
            ),

        "favorites":
            0,

        "shares":
            safe_int(
                raw.get(
                    "share_count",
                    0,
                )
            ),

        # ------------------------------------------
        # SALES
        # ------------------------------------------
        "video_sales":
            safe_int(
                raw.get(
                    "units_sold",
                    0,
                )
            ),

        "video_gmv":
            safe_float(
                raw.get(
                    "gmv",
                    0,
                )
            ),

        "video_sales_7d":
            safe_int(
                raw.get(
                    "day7_units_sold",
                    0,
                )
            ),

        "video_sales_14d":
            safe_int(
                raw.get(
                    "day14_units_sold",
                    0,
                )
            ),

        "video_sales_28d":
            safe_int(
                raw.get(
                    "day28_units_sold",
                    0,
                )
            ),

        "video_sales_60d":
            safe_int(
                raw.get(
                    "day60_units_sold",
                    0,
                )
            ),

        "video_sales_90d":
            safe_int(
                raw.get(
                    "day90_units_sold",
                    0,
                )
            ),

        "video_gmv_7d":
            safe_float(
                raw.get(
                    "day7_gmv",
                    0,
                )
            ),

        "video_gmv_14d":
            safe_float(
                raw.get(
                    "day14_gmv",
                    0,
                )
            ),

        "video_gmv_28d":
            safe_float(
                raw.get(
                    "day28_gmv",
                    0,
                )
            ),

        "video_gmv_60d":
            safe_float(
                raw.get(
                    "day60_gmv",
                    0,
                )
            ),

        "video_gmv_90d":
            safe_float(
                raw.get(
                    "day90_gmv",
                    0,
                )
            ),

        # ------------------------------------------
        # PRODUCT
        # ------------------------------------------
        "product_id":
            str(
                raw.get(
                    "product_id",
                    product_id,
                )
                or product_id
            ),

        # ------------------------------------------
        # OTHER
        # ------------------------------------------
        "hashtags":
            extract_hashtags(
                caption
            ),

        "cover":
            str(
                nested_video.get(
                    "cover",
                    "",
                )
                or ""
            ),

        "region":
            str(
                nested_video.get(
                    "region",
                    "",
                )
                or ""
            ),

        # FastMoss gives the TikTok page URL rather
        # than a direct MP4. Talking-vs-Visual already
        # has a yt-dlp fallback using the TikTok video ID.
        "video_url":
            "",

        "tiktok_url":
            tiktok_url,

        "fastmoss_url":
            str(
                nested_video.get(
                    "fastmoss_url",
                    "",
                )
                or ""
            ),

        "is_ad":
            safe_int(
                raw.get(
                    "is_ad",
                    0,
                )
            ),

        "seller_id":
            str(
                raw.get(
                    "seller_id",
                    "",
                )
                or ""
            ),
    }


# ==================================================
# REQUEST PRODUCT VIDEOS
# ==================================================

def request_fastmoss_product_videos(
    product_id,
    days=DEFAULT_DAYS,
    page_size=DEFAULT_PAGE_SIZE,
    page=1,
    sort_field="units_sold",
    sort_order="desc",
):
    """
    Exactly ONE FastMoss API request.

    The endpoint can sort by:
    - play_count
    - digg_count
    - comment_count
    - share_count
    - units_sold
    - gmv
    """

    if not FASTMOSS_API_KEY:
        raise RuntimeError(
            "FASTMOSS_API_KEY is missing from .env."
        )

    product_id = str(
        product_id
        or ""
    ).strip()

    if not product_id:
        raise ValueError(
            "product_id is required."
        )

    sort_field = str(
        sort_field
        or "units_sold"
    ).strip()

    if sort_field not in VALID_SORT_FIELDS:
        raise ValueError(
            "Unsupported FastMoss sort field: "
            f"{sort_field}"
        )

    resolved_page_size = max(
        1,
        min(
            safe_int(
                page_size,
                DEFAULT_PAGE_SIZE,
            ),
            100,
        ),
    )

    resolved_page = max(
        1,
        safe_int(
            page,
            1,
        ),
    )

    resolved_days = max(
        1,
        safe_int(
            days,
            DEFAULT_DAYS,
        ),
    )

    resolved_order = (
        "asc"
        if str(
            sort_order
        ).lower() == "asc"
        else "desc"
    )

    payload = {
        "filter": {
            "product_id":
                product_id,

            "days":
                resolved_days,
        },

        "orderby": {
            "field":
                sort_field,

            "order":
                resolved_order,
        },

        "page":
            resolved_page,

        "pagesize":
            resolved_page_size,
    }

    headers = {
        "Content-Type":
            "application/json",

        "Authorization":
            f"Bearer {FASTMOSS_API_KEY}",
    }

    print()
    print(
        "----------------------------------------"
    )
    print(
        "FastMoss content request"
    )
    print(
        f"Product: {product_id}"
    )
    print(
        f"Window: last {resolved_days} days"
    )
    print(
        f"Sort: {sort_field} {resolved_order}"
    )
    print(
        f"Page: {resolved_page}"
    )
    print(
        f"Page size: {resolved_page_size}"
    )
    print(
        "FastMoss requests: 1"
    )
    print(
        "----------------------------------------"
    )

    try:
        response = requests.post(
            FASTMOSS_PRODUCT_VIDEO_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

    except requests.RequestException as exc:
        raise RuntimeError(
            "FastMoss product-video request failed: "
            f"{exc}"
        ) from exc

    try:
        body = response.json()

    except ValueError as exc:
        raise RuntimeError(
            "FastMoss returned a non-JSON response "
            f"(HTTP {response.status_code})."
        ) from exc

    if response.status_code != 200:
        message = (
            body.get(
                "msg",
                body.get(
                    "message",
                    "",
                ),
            )
            if isinstance(
                body,
                dict,
            )
            else ""
        )

        raise RuntimeError(
            "FastMoss product-video request failed "
            f"(HTTP {response.status_code}): "
            f"{message}"
        )

    if not isinstance(
        body,
        dict,
    ):
        raise RuntimeError(
            "FastMoss returned an unexpected response."
        )

    api_code = body.get(
        "code"
    )

    if api_code not in {
        0,
        "0",
        None,
    }:
        raise RuntimeError(
            "FastMoss API error: "
            f"{body.get('msg', body.get('message', api_code))}"
        )

    data = body.get(
        "data",
        {},
    )

    if not isinstance(
        data,
        dict,
    ):
        raise RuntimeError(
            "FastMoss returned an unexpected data payload."
        )

    raw_videos = data.get(
        "list",
        [],
    )

    if not isinstance(
        raw_videos,
        list,
    ):
        raw_videos = []

    return raw_videos


# ==================================================
# ONE-REQUEST FUNNEL CONTENT SCAN
# ==================================================

def scan_product_content_fastmoss(
    product_id,
    days=DEFAULT_DAYS,
    page_size=DEFAULT_PAGE_SIZE,
):
    """
    FlipRadar funnel scan.

    Exactly ONE FastMoss request per product.

    We intentionally sort by attributed units sold because the
    Discovery Funnel's next job is to determine whether sales are
    coming from talking content. This is not meant to replace a
    broader viral-content research scan in every situation.
    """

    raw_videos = request_fastmoss_product_videos(
        product_id=product_id,
        days=days,
        page_size=page_size,
        page=1,
        sort_field="units_sold",
        sort_order="desc",
    )

    normalized = []

    seen_ids = set()

    for raw in raw_videos:
        video = normalize_fastmoss_video(
            raw=raw,
            product_id=product_id,
            discovery_lane="fastmoss_converting",
        )

        video_id = str(
            video.get(
                "video_id",
                "",
            )
        ).strip()

        if not video_id:
            continue

        if video_id in seen_ids:
            continue

        seen_ids.add(
            video_id
        )

        normalized.append(
            video
        )

    normalized = sorted(
        normalized,
        key=lambda item: (
            safe_int(
                item.get(
                    "video_sales",
                    0,
                )
            ),
            safe_float(
                item.get(
                    "video_gmv",
                    0,
                )
            ),
            safe_int(
                item.get(
                    "views",
                    0,
                )
            ),
        ),
        reverse=True,
    )

    print()
    print(
        "=================================================="
    )
    print(
        "FASTMOSS FUNNEL CONTENT SCAN COMPLETE"
    )
    print(
        "=================================================="
    )
    print(
        f"Product ID: {product_id}"
    )
    print(
        "FastMoss requests used: 1"
    )
    print(
        f"Videos returned: {len(normalized)}"
    )

    if normalized:
        print(
            "Top attributed-sales video:"
        )
        print(
            f"  {normalized[0]['video_sales']:,} sales"
        )
        print(
            f"  {normalized[0]['views']:,} views"
        )
        print(
            f"  ${normalized[0]['video_gmv']:,.2f} GMV"
        )

    print(
        "=================================================="
    )

    return normalized


# ==================================================
# OPTIONAL BROADER FASTMOSS DEEP SCAN
# ==================================================

def scan_product_content_fastmoss_multi_lane(
    product_id,
    days=DEFAULT_DAYS,
    page_size=10,
):
    """
    Optional 3-request FastMoss equivalent of the old EchoTik deep scan:

    1. Viral      -> play_count
    2. Converting -> units_sold
    3. Revenue    -> gmv

    Discovery Funnel should normally use the one-request
    scan_product_content_fastmoss() function instead.
    """

    lane_specs = [
        (
            "fastmoss_viral",
            "play_count",
        ),
        (
            "fastmoss_converting",
            "units_sold",
        ),
        (
            "fastmoss_revenue",
            "gmv",
        ),
    ]

    merged_by_id = {}

    for lane_name, sort_field in lane_specs:
        raw_videos = request_fastmoss_product_videos(
            product_id=product_id,
            days=days,
            page_size=page_size,
            page=1,
            sort_field=sort_field,
            sort_order="desc",
        )

        for raw in raw_videos:
            video = normalize_fastmoss_video(
                raw=raw,
                product_id=product_id,
                discovery_lane=lane_name,
            )

            video_id = str(
                video.get(
                    "video_id",
                    "",
                )
            ).strip()

            if not video_id:
                continue

            if video_id not in merged_by_id:
                merged_by_id[
                    video_id
                ] = video

                continue

            existing = merged_by_id[
                video_id
            ]

            existing_lanes = list(
                existing.get(
                    "discovery_lanes",
                    [],
                )
            )

            for lane in video.get(
                "discovery_lanes",
                [],
            ):
                if lane not in existing_lanes:
                    existing_lanes.append(
                        lane
                    )

            existing[
                "discovery_lanes"
            ] = existing_lanes

            existing[
                "views"
            ] = max(
                safe_int(
                    existing.get(
                        "views",
                        0,
                    )
                ),
                safe_int(
                    video.get(
                        "views",
                        0,
                    )
                ),
            )

            existing[
                "video_sales"
            ] = max(
                safe_int(
                    existing.get(
                        "video_sales",
                        0,
                    )
                ),
                safe_int(
                    video.get(
                        "video_sales",
                        0,
                    )
                ),
            )

            existing[
                "video_gmv"
            ] = max(
                safe_float(
                    existing.get(
                        "video_gmv",
                        0,
                    )
                ),
                safe_float(
                    video.get(
                        "video_gmv",
                        0,
                    )
                ),
            )

    merged = list(
        merged_by_id.values()
    )

    merged = sorted(
        merged,
        key=lambda item: (
            safe_int(
                item.get(
                    "views",
                    0,
                )
            ),
            safe_int(
                item.get(
                    "video_sales",
                    0,
                )
            ),
            safe_float(
                item.get(
                    "video_gmv",
                    0,
                )
            ),
        ),
        reverse=True,
    )

    return merged


# ==================================================
# DIRECT TEST
# ==================================================

if __name__ == "__main__":
    print(
        "This module is intended to be imported by FlipRadar."
    )
    print(
        "Import scan_product_content_fastmoss(product_id) "
        "for a 1-request funnel content scan."
    )
