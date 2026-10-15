import json
import sqlite3

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="FlipRadar Product Videos",
    page_icon="🎬",
    layout="wide",
)


DB_NAME = "flipradar.db"
STRONG_VIDEO_VIEWS = 100_000
SPEECH_ANALYSIS_VERSION = "speech_music_v3"
UNAVAILABLE_CLASSIFICATION = "🚫 Unavailable / Restricted"


# ==========================================================
# HELPERS
# ==========================================================

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


def is_terminal_video_access_error(
    error_message,
):
    message = str(
        error_message
        or ""
    ).strip().lower()

    if not message:
        return False

    terminal_markers = [
        "this post may not be comfortable for some audiences",
        "log in for access",
        "login for access",
        "this video is private",
        "this post is private",
        "video is private",
        "video unavailable",
        "this video is unavailable",
        "post is unavailable",
        "not available in your region",
        "not available in your country",
        "age-restricted",
        "age restricted",
    ]

    return any(
        marker in message
        for marker in terminal_markers
    )


def normalize_terminal_access_result(
    result,
):
    normalized = dict(
        result
        or {}
    )

    error_message = str(
        normalized.get(
            "error_message",
            "",
        )
        or ""
    ).strip()

    if is_terminal_video_access_error(
        error_message
    ):
        normalized[
            "classification"
        ] = UNAVAILABLE_CLASSIFICATION

        normalized[
            "analysis_version"
        ] = SPEECH_ANALYSIS_VERSION

        normalized[
            "classification_reason"
        ] = (
            "TikTok restricted or withheld this post from unauthenticated "
            "download access. FlipRadar excludes it from Talking-vs-Visual "
            "percentages and sales splits and does not retry it."
        )

    return normalized


def load_content_scan(
    product_id,
):
    """
    Prefer FlipRadar's shared content_database cache.
    Fall back to Discovery Funnel's local cache.
    """

    try:
        import content_database

        try:
            content_database.initialize_content_database()
        except Exception:
            pass

        videos, scanned_at = (
            content_database.load_content_scan(
                str(
                    product_id
                )
            )
        )

        if videos:
            return (
                videos,
                scanned_at,
                "Shared content cache",
            )

    except Exception:
        pass

    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                videos_json,
                scanned_at
            FROM discovery_funnel_content_cache
            WHERE product_id = ?
            """,
            (
                str(
                    product_id
                ),
            ),
        )

        row = cursor.fetchone()

    except sqlite3.Error:
        row = None

    finally:
        conn.close()

    if not row:
        return (
            [],
            None,
            "No cache",
        )

    try:
        videos = json.loads(
            row[0]
            or "[]"
        )

    except Exception:
        videos = []

    return (
        videos,
        row[1],
        "Discovery Funnel cache",
    )


def load_speech_results(
    product_id,
):
    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                video_id,
                classification,
                speech_seconds,
                audio_seconds,
                speech_share,
                error_message,
                analysis_version,
                transcript,
                transcript_word_count,
                transcript_seconds,
                transcript_share,
                whisper_avg_logprob,
                classification_reason,
                model_name,
                foreground_speech_seconds,
                foreground_speech_share,
                music_seconds,
                music_share,
                noise_seconds,
                segmenter_name
            FROM video_speech_analysis
            WHERE product_id = ?
            """,
            (
                str(
                    product_id
                ),
            ),
        )

        rows = cursor.fetchall()

    except sqlite3.Error:
        rows = []

    finally:
        conn.close()

    results = {}

    for row in rows:
        result = {
            "classification":
                row[1]
                or "❓ Unclear",

            "speech_seconds":
                safe_float(
                    row[2]
                ),

            "audio_seconds":
                safe_float(
                    row[3]
                ),

            "speech_share":
                safe_float(
                    row[4]
                ),

            "error_message":
                row[5]
                or "",

            "analysis_version":
                row[6]
                or "",

            "transcript":
                row[7]
                or "",

            "transcript_word_count":
                safe_int(
                    row[8]
                ),

            "transcript_seconds":
                safe_float(
                    row[9]
                ),

            "transcript_share":
                safe_float(
                    row[10]
                ),

            "whisper_avg_logprob":
                safe_float(
                    row[11],
                    -99,
                ),

            "classification_reason":
                row[12]
                or "",

            "model_name":
                row[13]
                or "",

            "foreground_speech_seconds":
                safe_float(
                    row[14]
                ),

            "foreground_speech_share":
                safe_float(
                    row[15]
                ),

            "music_seconds":
                safe_float(
                    row[16]
                ),

            "music_share":
                safe_float(
                    row[17]
                ),

            "noise_seconds":
                safe_float(
                    row[18]
                ),

            "segmenter_name":
                row[19]
                or "",
        }

        results[
            str(
                row[0]
            )
        ] = normalize_terminal_access_result(
            result
        )

    return results


def find_saved_product_name(
    product_id,
):
    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                products_json,
                shortlist_json
            FROM discovery_funnel_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        row = cursor.fetchone()

    except sqlite3.Error:
        row = None

    finally:
        conn.close()

    if not row:
        return ""

    collections = []

    for raw in row:
        try:
            parsed = json.loads(
                raw
                or "[]"
            )

        except Exception:
            parsed = []

        collections.append(
            parsed
        )

    for collection in collections:
        for product in collection:
            if str(
                product.get(
                    "id",
                    "",
                )
            ) == str(
                product_id
            ):
                return str(
                    product.get(
                        "name",
                        "",
                    )
                    or ""
                )

    return ""


def creator_name(
    video,
):
    return str(
        video.get(
            "creator_username",
            "",
        )
        or video.get(
            "creator",
            "",
        )
        or video.get(
            "creator_user_id",
            "",
        )
        or video.get(
            "uid",
            "",
        )
        or "Unknown"
    )


def tiktok_url(
    video,
):
    url = str(
        video.get(
            "tiktok_url",
            "",
        )
        or ""
    ).strip()

    if url:
        return url

    video_id = str(
        video.get(
            "video_id",
            "",
        )
        or ""
    ).strip()

    if not video_id:
        return ""

    return (
        "https://www.tiktok.com/@_/video/"
        + video_id
    )


def player_url(
    video_id,
):
    return (
        "https://www.tiktok.com/player/v1/"
        + str(
            video_id
        )
        + "?autoplay=0"
    )


def format_money(
    value,
):
    return (
        "$"
        + format(
            safe_float(
                value
            ),
            ",.2f",
        )
    )


# ==========================================================
# NAVIGATION / TARGET
# ==========================================================

top_left, top_right = st.columns(
    [
        1,
        5,
    ]
)

with top_left:
    if st.button(
        "← Funnel",
        width="stretch",
    ):
        st.switch_page(
            "pages/7_Discovery_Funnel.py"
        )


product_id = str(
    st.session_state.get(
        "video_review_product_id",
        "",
    )
    or ""
).strip()

product_name = str(
    st.session_state.get(
        "video_review_product_name",
        "",
    )
    or ""
).strip()


if not product_id:
    st.title(
        "🎬 Product Videos"
    )

    st.info(
        "Open Discovery Funnel and click **Review Sampled Videos** "
        "on a product. This page will then show the exact cached "
        "video sample used by the Funnel."
    )

    st.stop()


if not product_name:
    product_name = (
        find_saved_product_name(
            product_id
        )
    )


# ==========================================================
# LOAD DATA
# ==========================================================

videos, scanned_at, cache_source = (
    load_content_scan(
        product_id
    )
)

speech_results = (
    load_speech_results(
        product_id
    )
)


st.title(
    "🎬 Product Video Review"
)

st.subheader(
    product_name
    or f"Product {product_id}"
)

st.caption(
    f"Product ID: {product_id}"
)

st.info(
    "These are the cached videos Discovery Funnel used for this product. "
    "Opening this page uses **0 FastMoss requests** and "
    "**0 EchoTik requests**. Videos marked **Retry needed** remain incomplete. "
    "TikTok-restricted posts are marked **Unavailable / Restricted**, excluded "
    "from the Talking/Visual percentages, and do not block product completion."
)


if not videos:
    st.warning(
        "No cached content videos were found for this product."
    )

    st.stop()


# ==========================================================
# SUMMARY
# ==========================================================

strong_count = sum(
    1
    for video in videos
    if safe_int(
        video.get(
            "views",
            0,
        )
    ) >= STRONG_VIDEO_VIEWS
)

talking_count = 0
visual_count = 0
unavailable_count = 0
unclear_count = 0

total_attributed_sales = 0

for video in videos:
    video_id = str(
        video.get(
            "video_id",
            "",
        )
        or ""
    )

    result = speech_results.get(
        video_id,
        {}
    )

    classification = str(
        result.get(
            "classification",
            "❓ Unclear",
        )
    )

    if classification == "🗣️ Talking":
        talking_count += 1

    elif classification == "🎵 Visual / Music":
        visual_count += 1

    elif (
        classification
        == UNAVAILABLE_CLASSIFICATION
    ):
        unavailable_count += 1

    else:
        unclear_count += 1

    total_attributed_sales += safe_int(
        video.get(
            "video_sales",
            0,
        )
    )


s1, s2, s3, s4, s5, s6 = st.columns(
    6
)

s1.metric(
    "Sampled Videos",
    len(
        videos
    ),
)

s2.metric(
    "Strong Videos",
    f"{strong_count} / {len(videos)}",
)

s3.metric(
    "Talking",
    talking_count,
)

s4.metric(
    "Visual / Music",
    visual_count,
)

s5.metric(
    "Unavailable",
    unavailable_count,
)

s6.metric(
    "Unclear / Failed",
    unclear_count,
)

st.caption(
    f"Sample attributed sales across these videos: "
    f"{total_attributed_sales:,}"
)


st.caption(
    "**Strong Video = 100,000+ views.** "
    "The Funnel currently uses this simple threshold for the "
    "Strong Videos metric."
)

if scanned_at:
    st.caption(
        f"Cached scan: {scanned_at} • {cache_source}"
    )


# ==========================================================
# VIDEO TABLE
# ==========================================================

table_rows = []

for index, video in enumerate(
    videos,
    start=1,
):
    video_id = str(
        video.get(
            "video_id",
            "",
        )
        or ""
    )

    views = safe_int(
        video.get(
            "views",
            0,
        )
    )

    result = speech_results.get(
        video_id,
        {}
    )

    classification = str(
        result.get(
            "classification",
            "❓ Unclear",
        )
    )

    table_rows.append(
        {
            "Sample #":
                index,

            "Strong":
                (
                    "✅"
                    if views
                    >= STRONG_VIDEO_VIEWS
                    else "—"
                ),

            "Creator":
                creator_name(
                    video
                ),

            "Views":
                views,

            "Attributed Sales":
                safe_int(
                    video.get(
                        "video_sales",
                        0,
                    )
                ),

            "Attributed GMV":
                safe_float(
                    video.get(
                        "video_gmv",
                        0,
                    )
                ),

            "Talking / Visual":
                classification,

            "VAD Speech Share":
                (
                    safe_float(
                        result.get(
                            "speech_share",
                            0,
                        )
                    )
                    * 100
                ),

            "Whisper Words":
                safe_int(
                    result.get(
                        "transcript_word_count",
                        0,
                    )
                ),

            "Whisper Speech Share":
                (
                    safe_float(
                        result.get(
                            "transcript_share",
                            0,
                        )
                    )
                    * 100
                ),

            "Foreground Speech":
                (
                    safe_float(
                        result.get(
                            "foreground_speech_share",
                            0,
                        )
                    )
                    * 100
                ),

            "Music":
                (
                    safe_float(
                        result.get(
                            "music_share",
                            0,
                        )
                    )
                    * 100
                ),

            "Detector":
                result.get(
                    "analysis_version",
                    "",
                )
                or "legacy_vad",

            "Analysis Status":
                (
                    "🚫 Unavailable"
                    if (
                        classification
                        == UNAVAILABLE_CLASSIFICATION
                    )
                    else (
                        "✅ Classified"
                        if (
                            result.get(
                                "analysis_version",
                                "",
                            )
                            == SPEECH_ANALYSIS_VERSION
                            and classification
                            in {
                                "🗣️ Talking",
                                "🎵 Visual / Music",
                            }
                            and not str(
                                result.get(
                                    "error_message",
                                    "",
                                )
                                or ""
                            ).strip()
                        )
                        else "⚠️ Retry needed"
                    )
                ),

            "Error":
                str(
                    result.get(
                        "error_message",
                        "",
                    )
                    or ""
                )[
                    :250
                ],

            "TikTok":
                tiktok_url(
                    video
                ),

            "Video ID":
                video_id,
        }
    )


st.markdown(
    "### The sampled videos"
)

st.dataframe(
    pd.DataFrame(
        table_rows
    ),
    width="stretch",
    hide_index=True,
    column_config={
        "Views":
            st.column_config.NumberColumn(
                "Views",
                format="%d",
            ),

        "Attributed Sales":
            st.column_config.NumberColumn(
                "Attributed Sales",
                format="%d",
            ),

        "Attributed GMV":
            st.column_config.NumberColumn(
                "Attributed GMV",
                format="$%.2f",
            ),

        "VAD Speech Share":
            st.column_config.NumberColumn(
                "VAD Speech Share",
                format="%.1f%%",
            ),

        "Whisper Speech Share":
            st.column_config.NumberColumn(
                "Whisper Speech Share",
                format="%.1f%%",
            ),

        "Foreground Speech":
            st.column_config.NumberColumn(
                "Foreground Speech",
                format="%.1f%%",
            ),

        "Music":
            st.column_config.NumberColumn(
                "Music",
                format="%.1f%%",
            ),

        "TikTok":
            st.column_config.LinkColumn(
                "TikTok",
                display_text="Open video",
            ),
    },
)


# ==========================================================
# VIDEO PREVIEWS
# ==========================================================

st.markdown(
    "### Watch the sample"
)

st.caption(
    "The sample number below matches the table above. "
    "A green Strong label means the cached video has at least "
    "100,000 views."
)


for index, video in enumerate(
    videos,
    start=1,
):
    video_id = str(
        video.get(
            "video_id",
            "",
        )
        or ""
    )

    views = safe_int(
        video.get(
            "views",
            0,
        )
    )

    sales = safe_int(
        video.get(
            "video_sales",
            0,
        )
    )

    gmv = safe_float(
        video.get(
            "video_gmv",
            0,
        )
    )

    result = speech_results.get(
        video_id,
        {}
    )

    classification = str(
        result.get(
            "classification",
            "❓ Unclear",
        )
    )

    speech_share = (
        safe_float(
            result.get(
                "speech_share",
                0,
            )
        )
        * 100
    )

    strong_label = (
        "✅ STRONG"
        if views >= STRONG_VIDEO_VIEWS
        else "—"
    )

    expander_title = (
        f"Video {index} • {strong_label} • "
        f"{views:,} views • {classification}"
    )

    with st.expander(
        expander_title
    ):
        left, right = st.columns(
            [
                1,
                1,
            ]
        )

        with left:
            if video_id:
                components.iframe(
                    player_url(
                        video_id
                    ),
                    height=650,
                    scrolling=False,
                )

            else:
                st.info(
                    "No TikTok video ID is available for this preview."
                )

        with right:
            st.write(
                f"**Creator:** {creator_name(video)}"
            )

            st.write(
                f"**Views:** {views:,}"
            )

            st.write(
                f"**FastMoss / provider attributed sales:** "
                f"{sales:,}"
            )

            st.write(
                f"**Attributed GMV:** "
                f"{format_money(gmv)}"
            )

            st.write(
                f"**Classification:** "
                f"{classification}"
            )

            st.write(
                f"**VAD Speech Share:** "
                f"{speech_share:.1f}%"
            )

            transcript_word_count = safe_int(
                result.get(
                    "transcript_word_count",
                    0,
                )
            )

            transcript_share = (
                safe_float(
                    result.get(
                        "transcript_share",
                        0,
                    )
                )
                * 100
            )

            detector_version = str(
                result.get(
                    "analysis_version",
                    "",
                )
                or "legacy_vad"
            )

            st.write(
                f"**Detector:** {detector_version}"
            )

            if detector_version == "speech_music_v3":
                foreground_speech_share = (
                    safe_float(
                        result.get(
                            "foreground_speech_share",
                            0,
                        )
                    )
                    * 100
                )

                music_share = (
                    safe_float(
                        result.get(
                            "music_share",
                            0,
                        )
                    )
                    * 100
                )

                foreground_speech_seconds = (
                    safe_float(
                        result.get(
                            "foreground_speech_seconds",
                            0,
                        )
                    )
                )

                music_seconds = (
                    safe_float(
                        result.get(
                            "music_seconds",
                            0,
                        )
                    )
                )

                st.write(
                    f"**Actual speech segments:** "
                    f"{foreground_speech_seconds:.1f}s "
                    f"({foreground_speech_share:.1f}%)"
                )

                st.write(
                    f"**Music segments:** "
                    f"{music_seconds:.1f}s "
                    f"({music_share:.1f}%)"
                )

                st.write(
                    f"**Speech/Music model:** "
                    f"{result.get('segmenter_name', '') or 'inaSpeechSegmenter-smn'}"
                )

            error_message = str(
                result.get(
                    "error_message",
                    "",
                )
                or ""
            ).strip()

            if (
                classification
                == UNAVAILABLE_CLASSIFICATION
            ):
                st.warning(
                    "**TikTok access restriction:** "
                    + error_message
                )

                st.info(
                    "FlipRadar treats this post as terminally unavailable. "
                    "It is excluded from Talking-vs-Visual percentages and "
                    "sales splits and will NOT remain in the retry queue."
                )

            elif error_message:
                st.error(
                    "**Speech analysis error:** "
                    + error_message
                )

                st.warning(
                    "This video is NOT considered successfully classified. "
                    "Discovery Funnel will keep it in the retry queue."
                )

            if detector_version == "speech_music_v3":
                st.write(
                    f"**Whisper-confirmed words:** "
                    f"{transcript_word_count}"
                )

                st.write(
                    f"**Whisper speech coverage:** "
                    f"{transcript_share:.1f}%"
                )

                reason = str(
                    result.get(
                        "classification_reason",
                        "",
                    )
                    or ""
                ).strip()

                if reason:
                    st.write(
                        f"**Why it was classified this way:** "
                        f"{reason}"
                    )

                transcript = str(
                    result.get(
                        "transcript",
                        "",
                    )
                    or ""
                ).strip()

                if transcript:
                    st.write(
                        "**Whisper transcript:**"
                    )

                    st.write(
                        transcript
                    )

                else:
                    if (
                        classification
                        == UNAVAILABLE_CLASSIFICATION
                    ):
                        st.caption(
                            "No transcript was attempted because TikTok "
                            "did not provide downloadable access to this post."
                        )

                    elif error_message:
                        st.caption(
                            "No usable transcript was saved because the "
                            "speech analysis failed."
                        )

                    else:
                        st.caption(
                            "Whisper ran successfully but did not confirm "
                            "a reliable spoken transcript."
                        )

            else:
                st.warning(
                    "This video still has an older classification. "
                    "Run the Speech/Music v3 recheck in Discovery Funnel Stage 4."
                )

            caption = str(
                video.get(
                    "caption",
                    "",
                )
                or ""
            ).strip()

            if caption:
                st.write(
                    "**Caption:**"
                )

                st.write(
                    caption
                )

            url = tiktok_url(
                video
            )

            if url:
                st.link_button(
                    "Open on TikTok",
                    url,
                    width="stretch",
                )

            if views >= STRONG_VIDEO_VIEWS:
                st.success(
                    "Counts as a Strong Video because it has "
                    "at least 100,000 views."
                )

            else:
                st.caption(
                    "Does not count as Strong under the current "
                    "100,000-view threshold."
                )


st.divider()

if st.button(
    "← Back to Discovery Funnel",
    width="stretch",
):
    st.switch_page(
        "pages/7_Discovery_Funnel.py"
    )
