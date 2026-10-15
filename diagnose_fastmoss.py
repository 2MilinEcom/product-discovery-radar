import json
import os
import sys

import requests
from dotenv import load_dotenv


# ==================================================
# FASTMOSS ONE-REQUEST VIDEO DIAGNOSTIC
# ==================================================

load_dotenv()

FASTMOSS_API_KEY = os.getenv(
    "FASTMOSS_API_KEY",
    "",
).strip()

FASTMOSS_PRODUCT_VIDEO_URL = (
    "https://openapi.fastmoss.com/product/v1/videoList"
)

# Bella Vita — already familiar in FlipRadar, so this makes
# it easy to compare FastMoss's video data with prior EchoTik scans.
TEST_PRODUCT_ID = "1729413742968869814"


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


def main():
    print()
    print("=" * 92)
    print("FLIPRADAR FASTMOSS PRODUCT-VIDEO DIAGNOSTIC")
    print("=" * 92)
    print("This script makes EXACTLY 1 FastMoss API request.")
    print("Nothing is written to flipradar.db.")
    print()
    print(f"Test product ID: {TEST_PRODUCT_ID}")
    print("Window: videos published in the last 30 days")
    print("Sort: attributed units sold, descending")
    print("Page size: 10")
    print()

    if not FASTMOSS_API_KEY:
        print(
            "ERROR: FASTMOSS_API_KEY was not found in .env"
        )
        sys.exit(1)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FASTMOSS_API_KEY}",
    }

    payload = {
        "filter": {
            "product_id": TEST_PRODUCT_ID,
            "days": 30,
        },
        "orderby": {
            "field": "units_sold",
            "order": "desc",
        },
        "page": 1,
        "pagesize": 10,
    }

    print("Endpoint:")
    print(FASTMOSS_PRODUCT_VIDEO_URL)
    print()
    print("Request body:")
    print(
        json.dumps(
            payload,
            indent=2,
        )
    )
    print()
    print("Sending 1 request...")
    print()

    try:
        response = requests.post(
            FASTMOSS_PRODUCT_VIDEO_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"NETWORK ERROR: {exc}")
        sys.exit(1)

    print(f"HTTP status: {response.status_code}")

    try:
        body = response.json()
    except ValueError:
        print()
        print("FastMoss did not return JSON.")
        print("Raw response:")
        print(response.text[:6000])
        sys.exit(1)

    print(f"API code: {body.get('code')}")
    print(
        "API message: "
        f"{body.get('msg', body.get('message', ''))}"
    )
    print()

    if response.status_code != 200:
        print("REQUEST FAILED")
        print(
            json.dumps(
                body,
                indent=2,
                ensure_ascii=False,
            )[:8000]
        )
        sys.exit(1)

    if body.get("code") not in {
        0,
        "0",
        None,
    }:
        print("FASTMOSS RETURNED AN API ERROR")
        print(
            json.dumps(
                body,
                indent=2,
                ensure_ascii=False,
            )[:8000]
        )
        sys.exit(1)

    data = body.get("data", {})

    if not isinstance(data, dict):
        print("Unexpected response shape.")
        print(
            json.dumps(
                body,
                indent=2,
                ensure_ascii=False,
            )[:8000]
        )
        sys.exit(1)

    videos = data.get("list", [])

    if not isinstance(videos, list):
        videos = []

    print(
        "Total matching videos reported: "
        f"{data.get('total', 'unknown')}"
    )
    print(
        f"Videos returned on this page: {len(videos)}"
    )
    print()

    if not videos:
        print(
            "The request succeeded but returned no videos."
        )
        print(
            "That can mean the product has no matching videos "
            "inside the 30-day publication window."
        )
        print()
        print("API requests used by this script: 1")
        return

    total_views = 0
    total_sales = 0
    total_gmv = 0.0

    print("=" * 92)
    print("VIDEOS")
    print("=" * 92)

    for index, item in enumerate(
        videos,
        start=1,
    ):
        video = item.get("video", {})

        if not isinstance(video, dict):
            video = {}

        views = safe_int(
            item.get("play_count", 0)
        )
        sales = safe_int(
            item.get("units_sold", 0)
        )
        gmv = safe_float(
            item.get("gmv", 0)
        )

        total_views += views
        total_sales += sales
        total_gmv += gmv

        sales_per_1k = (
            sales / views * 1000
            if views > 0
            else 0.0
        )

        print()
        print(
            f"{index}. Video ID: "
            f"{item.get('video_id', '')}"
        )
        print(
            f"   Creator UID: "
            f"{item.get('uid', '')}"
        )
        print(
            f"   Views: {views:,}"
        )
        print(
            f"   Attributed sales: {sales:,}"
        )
        print(
            f"   Attributed GMV: ${gmv:,.2f}"
        )
        print(
            f"   Sales / 1K views: "
            f"{sales_per_1k:.3f}"
        )
        print(
            f"   Likes: "
            f"{safe_int(item.get('digg_count', 0)):,}"
        )
        print(
            f"   Comments: "
            f"{safe_int(item.get('comment_count', 0)):,}"
        )
        print(
            f"   Shares: "
            f"{safe_int(item.get('share_count', 0)):,}"
        )
        print(
            f"   Is ad: "
            f"{item.get('is_ad', '')}"
        )
        print(
            f"   Duration: "
            f"{video.get('duration', '')}"
        )
        print(
            f"   Caption: "
            f"{video.get('video_desc', '')}"
        )
        print(
            f"   TikTok URL: "
            f"{video.get('tiktok_url', '')}"
        )
        print(
            f"   FastMoss URL: "
            f"{video.get('fastmoss_url', '')}"
        )
        print(
            f"   Cover present: "
            f"{bool(video.get('cover'))}"
        )

    print()
    print("=" * 92)
    print("SAMPLE SUMMARY")
    print("=" * 92)
    print(f"Videos sampled: {len(videos)}")
    print(f"Sample views: {total_views:,}")
    print(f"Sample attributed sales: {total_sales:,}")
    print(f"Sample attributed GMV: ${total_gmv:,.2f}")

    if total_views > 0:
        print(
            "Sample sales / 1K views: "
            f"{(total_sales / total_views) * 1000:.3f}"
        )

    first = videos[0]
    first_video = first.get("video", {})

    if not isinstance(first_video, dict):
        first_video = {}

    print()
    print("=" * 92)
    print("FIRST RESULT — TOP-LEVEL FIELD NAMES")
    print("=" * 92)

    for key in sorted(first.keys()):
        print(f"- {key}")

    print()
    print("=" * 92)
    print("FIRST RESULT — NESTED VIDEO FIELD NAMES")
    print("=" * 92)

    for key in sorted(first_video.keys()):
        print(f"- {key}")

    print()
    print("=" * 92)
    print("FIRST RESULT — RAW JSON")
    print("=" * 92)
    print(
        json.dumps(
            first,
            indent=2,
            ensure_ascii=False,
        )[:14000]
    )

    print()
    print("=" * 92)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 92)
    print(
        "FastMoss Product Associated Videos worked."
    )
    print(
        "API requests used by this script: 1"
    )


if __name__ == "__main__":
    main()
