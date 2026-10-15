import os
import sqlite3
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg
import pandas as pd
import requests
import streamlit as st
import webrtcvad

from database import (
    initialize_database,
    load_latest_scan,
)

from content_database import (
    initialize_content_database,
    load_content_scan,
)


# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar Talking vs Visual",
    page_icon="🗣️",
    layout="wide",
)

initialize_database()
initialize_content_database()

DB_NAME = "flipradar.db"


# ==================================================
# SETTINGS
# ==================================================

# A video counts as "Talking" when WebRTC VAD detects
# at least this much speech in the audio.
MIN_SPEECH_SECONDS = 2.0

# Also require a small share of the analyzable audio
# to contain speech so tiny spoken snippets do not
# turn an otherwise music/visual ad into "Talking".
MIN_SPEECH_SHARE = 0.08

# WebRTC VAD mode:
# 0 = least aggressive
# 3 = most aggressive
VAD_MODE = 2

# 30 ms is one of WebRTC VAD's supported frame sizes.
FRAME_MS = 30

# Keep downloads bounded.
MAX_VIDEO_BYTES = 80 * 1024 * 1024

REQUEST_TIMEOUT = 40


# ==================================================
# DATABASE
# ==================================================

def initialize_speech_database():
    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_speech_analysis (
            product_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            classification TEXT NOT NULL,
            speech_seconds REAL NOT NULL DEFAULT 0,
            audio_seconds REAL NOT NULL DEFAULT 0,
            speech_share REAL NOT NULL DEFAULT 0,
            source_url TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            analyzed_at TEXT NOT NULL,
            PRIMARY KEY (
                product_id,
                video_id
            )
        )
        """
    )

    conn.commit()
    conn.close()


def load_speech_results(
    product_id,
):
    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            video_id,
            classification,
            speech_seconds,
            audio_seconds,
            speech_share,
            source_url,
            error_message,
            analyzed_at
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

    conn.close()

    results = {}

    for row in rows:
        results[
            str(
                row[0]
            )
        ] = {
            "classification":
                row[1],

            "speech_seconds":
                float(
                    row[2]
                    or 0
                ),

            "audio_seconds":
                float(
                    row[3]
                    or 0
                ),

            "speech_share":
                float(
                    row[4]
                    or 0
                ),

            "source_url":
                row[5]
                or "",

            "error_message":
                row[6]
                or "",

            "analyzed_at":
                row[7]
                or "",
        }

    return results


def save_speech_result(
    product_id,
    video_id,
    result,
    source_url,
):
    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO video_speech_analysis (
            product_id,
            video_id,
            classification,
            speech_seconds,
            audio_seconds,
            speech_share,
            source_url,
            error_message,
            analyzed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(product_id, video_id)
        DO UPDATE SET
            classification = excluded.classification,
            speech_seconds = excluded.speech_seconds,
            audio_seconds = excluded.audio_seconds,
            speech_share = excluded.speech_share,
            source_url = excluded.source_url,
            error_message = excluded.error_message,
            analyzed_at = excluded.analyzed_at
        """,
        (
            str(
                product_id
            ),
            str(
                video_id
            ),
            str(
                result.get(
                    "classification",
                    "❓ Unclear",
                )
            ),
            float(
                result.get(
                    "speech_seconds",
                    0,
                )
            ),
            float(
                result.get(
                    "audio_seconds",
                    0,
                )
            ),
            float(
                result.get(
                    "speech_share",
                    0,
                )
            ),
            str(
                source_url
                or ""
            ),
            str(
                result.get(
                    "error_message",
                    "",
                )
            ),
            datetime.now().isoformat(
                timespec="seconds"
            ),
        ),
    )

    conn.commit()
    conn.close()


initialize_speech_database()


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


def creator_label(
    video,
):
    username = str(
        video.get(
            "creator_username",
            ""
        )
        or ""
    ).strip()

    if username:
        return f"@{username.lstrip('@')}"

    name = str(
        video.get(
            "creator_name",
            ""
        )
        or ""
    ).strip()

    if name:
        return name

    creator_id = str(
        video.get(
            "creator_user_id"
        )
        or video.get(
            "creator"
        )
        or ""
    ).strip()

    return (
        creator_id
        if creator_id
        else "Unknown creator"
    )


def clean_video_url(
    video,
):
    value = video.get(
        "video_url",
        ""
    )

    if isinstance(
        value,
        str,
    ):
        return value.strip()

    return ""


# ==================================================
# VIDEO DOWNLOAD
# ==================================================

def download_cached_video_url(
    url,
    destination,
):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": "https://www.tiktok.com/",
        "Origin": "https://www.tiktok.com",
    }

    with requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    ) as response:
        response.raise_for_status()

        total = 0

        with open(
            destination,
            "wb",
        ) as output:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if not chunk:
                    continue

                total += len(
                    chunk
                )

                if total > MAX_VIDEO_BYTES:
                    raise RuntimeError(
                        "Video exceeded the local "
                        "80 MB analysis limit."
                    )

                output.write(
                    chunk
                )


def download_video_with_ytdlp(
    video_id,
    temp_dir,
):
    try:
        import yt_dlp

    except ImportError as exc:
        raise RuntimeError(
            "The cached TikTok CDN URL has expired or is blocked, "
            "and the yt-dlp fallback is not installed. "
            "Run: python -m pip install -U yt-dlp"
        ) from exc

    # TikTok resolves the video primarily from its numeric video ID.
    # A placeholder username is sufficient for yt-dlp to request the
    # public video page and obtain a fresh media URL.
    public_url = (
        f"https://www.tiktok.com/@_/video/{video_id}"
    )

    output_template = str(
        Path(
            temp_dir
        )
        / "fresh_video.%(ext)s"
    )

    ydl_options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": output_template,
        "format": "best",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Referer": "https://www.tiktok.com/",
        },
    }

    try:
        with yt_dlp.YoutubeDL(
            ydl_options
        ) as ydl:
            info = ydl.extract_info(
                public_url,
                download=True,
            )

            downloaded_path = (
                ydl.prepare_filename(
                    info
                )
            )

    except Exception as exc:
        raise RuntimeError(
            "Cached TikTok CDN URL was unavailable, and the "
            "fresh TikTok fallback also failed: "
            f"{exc}"
        ) from exc

    candidate = Path(
        downloaded_path
    )

    if (
        candidate.exists()
        and candidate.is_file()
    ):
        return candidate

    # Some extractors can change the final extension.
    matches = sorted(
        Path(
            temp_dir
        ).glob(
            "fresh_video.*"
        )
    )

    for match in matches:
        if (
            match.is_file()
            and match.stat().st_size > 0
        ):
            return match

    raise RuntimeError(
        "yt-dlp reported success but no downloaded video file was found."
    )


def download_video(
    url,
    video_id,
    temp_dir,
):
    direct_path = (
        Path(
            temp_dir
        )
        / "cached_video.bin"
    )

    direct_error = None

    if url:
        try:
            download_cached_video_url(
                url,
                direct_path,
            )

            if (
                direct_path.exists()
                and direct_path.stat().st_size > 0
            ):
                return (
                    direct_path,
                    "Cached CDN URL",
                )

        except Exception as exc:
            direct_error = exc

    try:
        fallback_path = (
            download_video_with_ytdlp(
                video_id=video_id,
                temp_dir=temp_dir,
            )
        )

        return (
            fallback_path,
            "Fresh TikTok URL via yt-dlp",
        )

    except Exception as fallback_exc:
        if direct_error is not None:
            raise RuntimeError(
                "Cached video URL failed first: "
                f"{direct_error}. "
                "Fresh TikTok fallback then failed: "
                f"{fallback_exc}"
            ) from fallback_exc

        raise


# ==================================================
# AUDIO EXTRACTION
# ==================================================

def extract_audio_to_wav(
    video_path,
    wav_path,
):
    ffmpeg_exe = (
        imageio_ffmpeg
        .get_ffmpeg_exe()
    )

    command = [
        ffmpeg_exe,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(
            video_path
        ),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(
            wav_path
        ),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )

    if completed.returncode != 0:
        error_text = (
            completed.stderr
            or completed.stdout
            or "ffmpeg could not extract audio."
        ).strip()

        raise RuntimeError(
            error_text[
                :500
            ]
        )

    if not os.path.exists(
        wav_path
    ):
        raise RuntimeError(
            "No audio file was created."
        )


# ==================================================
# SPEECH DETECTION
# ==================================================

def analyze_wav_speech(
    wav_path,
):
    vad = webrtcvad.Vad(
        VAD_MODE
    )

    with wave.open(
        str(
            wav_path
        ),
        "rb",
    ) as wav_file:
        channels = (
            wav_file
            .getnchannels()
        )

        sample_width = (
            wav_file
            .getsampwidth()
        )

        sample_rate = (
            wav_file
            .getframerate()
        )

        frame_count = (
            wav_file
            .getnframes()
        )

        if (
            channels != 1
            or sample_width != 2
            or sample_rate != 16000
        ):
            raise RuntimeError(
                "Audio was not converted to "
                "16 kHz mono 16-bit PCM."
            )

        audio_seconds = (
            frame_count
            / sample_rate
            if sample_rate > 0
            else 0
        )

        samples_per_frame = int(
            sample_rate
            * FRAME_MS
            / 1000
        )

        bytes_per_frame = (
            samples_per_frame
            * sample_width
        )

        speech_frames = 0
        total_frames = 0

        while True:
            frame = wav_file.readframes(
                samples_per_frame
            )

            if len(
                frame
            ) < bytes_per_frame:
                break

            total_frames += 1

            try:
                is_speech = vad.is_speech(
                    frame,
                    sample_rate,
                )

            except Exception:
                is_speech = False

            if is_speech:
                speech_frames += 1

    frame_seconds = (
        FRAME_MS
        / 1000
    )

    speech_seconds = (
        speech_frames
        * frame_seconds
    )

    analyzed_seconds = (
        total_frames
        * frame_seconds
    )

    speech_share = (
        speech_seconds
        / analyzed_seconds
        if analyzed_seconds > 0
        else 0
    )

    return {
        "speech_seconds":
            speech_seconds,

        "audio_seconds":
            audio_seconds,

        "speech_share":
            speech_share,
    }


def classify_speech(
    speech_seconds,
    speech_share,
    audio_seconds,
):
    if audio_seconds <= 0:
        return (
            "🎵 Visual / Music"
        )

    if (
        speech_seconds
        >= MIN_SPEECH_SECONDS
        and speech_share
        >= MIN_SPEECH_SHARE
    ):
        return (
            "🗣️ Talking"
        )

    return (
        "🎵 Visual / Music"
    )


def analyze_video_speech(
    video_url,
    video_id,
):
    if not video_id:
        return {
            "classification":
                "❓ Unclear",

            "speech_seconds":
                0.0,

            "audio_seconds":
                0.0,

            "speech_share":
                0.0,

            "download_method":
                "",

            "error_message":
                "No video ID is available.",
        }

    try:
        with tempfile.TemporaryDirectory(
            prefix="flipradar_speech_"
        ) as temp_dir:
            temp_dir = Path(
                temp_dir
            )

            wav_path = (
                temp_dir
                / "audio.wav"
            )

            (
                video_path,
                download_method,
            ) = download_video(
                url=video_url,
                video_id=video_id,
                temp_dir=temp_dir,
            )

            extract_audio_to_wav(
                video_path,
                wav_path,
            )

            speech = (
                analyze_wav_speech(
                    wav_path
                )
            )

            classification = (
                classify_speech(
                    speech_seconds=
                        speech[
                            "speech_seconds"
                        ],
                    speech_share=
                        speech[
                            "speech_share"
                        ],
                    audio_seconds=
                        speech[
                            "audio_seconds"
                        ],
                )
            )

            return {
                "classification":
                    classification,

                "speech_seconds":
                    speech[
                        "speech_seconds"
                    ],

                "audio_seconds":
                    speech[
                        "audio_seconds"
                    ],

                "speech_share":
                    speech[
                        "speech_share"
                    ],

                "download_method":
                    download_method,

                "error_message":
                    "",
            }

    except Exception as exc:
        return {
            "classification":
                "❓ Unclear",

            "speech_seconds":
                0.0,

            "audio_seconds":
                0.0,

            "speech_share":
                0.0,

            "download_method":
                "",

            "error_message":
                str(
                    exc
                )[
                    :1000
                ],
        }


# ==================================================
# HEADER
# ==================================================

st.title(
    "🗣️ Talking vs Visual / Music"
)

st.caption(
    "Automatically classify sampled TikTok videos as "
    "creator/voice talking versus primarily visual/music creative."
)

st.info(
    "This analysis makes **zero EchoTik API requests**. FlipRadar first tries "
    "the cached TikTok CDN URL. If that signed URL has expired, it automatically "
    "uses the saved TikTok video ID with **yt-dlp** to obtain a fresh public "
    "video URL, then runs speech detection locally."
)

st.caption(
    "For this first version, voiceover counts as Talking. "
    "The detector is measuring meaningful human speech in the audio; "
    "it is not yet checking whether the visible creator's lips are moving."
)


# ==================================================
# LOAD PRODUCTS
# ==================================================

products, market_scan_time = (
    load_latest_scan()
)

if not products:
    st.warning(
        "No saved product scan exists yet."
    )

    st.stop()


scanned_products = []

for product in products:
    videos, scanned_at = (
        load_content_scan(
            str(
                product[
                    "id"
                ]
            )
        )
    )

    if videos:
        scanned_products.append(
            product
        )


if not scanned_products:
    st.warning(
        "No products have a cached Content Deep Scan yet."
    )

    st.stop()


product_names = [
    product[
        "name"
    ]
    for product in scanned_products
]


selected_name = st.selectbox(
    "Choose a content-scanned product",
    product_names,
)


selected_product = next(
    product
    for product in scanned_products
    if product[
        "name"
    ] == selected_name
)


product_id = str(
    selected_product[
        "id"
    ]
)


videos, content_scan_time = (
    load_content_scan(
        product_id
    )
)


# ==================================================
# CURRENT ANALYSIS
# ==================================================

saved_results = load_speech_results(
    product_id
)

video_ids = [
    str(
        video.get(
            "video_id",
            ""
        )
    )
    for video in videos
    if str(
        video.get(
            "video_id",
            ""
        )
    ).strip()
]


missing_video_ids = [
    video_id
    for video_id in video_ids
    if video_id not in saved_results
]


st.write(
    f"**Product ID:** `{product_id}`"
)

status1, status2, status3 = st.columns(
    3
)

status1.metric(
    "Sampled Videos",
    len(
        video_ids
    ),
)

status2.metric(
    "Analyzed",
    len(
        [
            video_id
            for video_id in video_ids
            if video_id in saved_results
        ]
    ),
)

status3.metric(
    "Not Yet Analyzed",
    len(
        missing_video_ids
    ),
)


# ==================================================
# ANALYZE BUTTONS
# ==================================================

button1, button2 = st.columns(
    2
)

with button1:
    analyze_missing = st.button(
        "🗣️ Analyze Missing Videos",
        type="primary",
        width="stretch",
        disabled=(
            len(
                missing_video_ids
            )
            == 0
        ),
    )

with button2:
    reanalyze_all = st.button(
        "🔄 Re-analyze All Videos",
        width="stretch",
    )


if analyze_missing:
    videos_to_analyze = [
        video
        for video in videos
        if str(
            video.get(
                "video_id",
                ""
            )
        ) in missing_video_ids
    ]

elif reanalyze_all:
    videos_to_analyze = list(
        videos
    )

else:
    videos_to_analyze = []


if videos_to_analyze:
    st.warning(
        f"Local speech analysis will download "
        f"{len(videos_to_analyze)} cached TikTok video file(s). "
        "This uses **0 EchoTik API requests**."
    )

    progress = st.progress(
        0
    )

    status = st.empty()

    total_to_analyze = len(
        videos_to_analyze
    )

    for index, video in enumerate(
        videos_to_analyze,
        start=1,
    ):
        video_id = str(
            video.get(
                "video_id",
                ""
            )
        ).strip()

        video_url = clean_video_url(
            video
        )

        status.write(
            f"Analyzing {index}/{total_to_analyze}: "
            f"`{video_id}`"
        )

        result = analyze_video_speech(
            video_url=video_url,
            video_id=video_id,
        )

        save_speech_result(
            product_id=
                product_id,
            video_id=
                video_id,
            result=
                result,
            source_url=
                video_url,
        )

        progress.progress(
            index
            / total_to_analyze
        )

    status.success(
        "Speech analysis complete."
    )

    st.rerun()


# ==================================================
# RESULTS
# ==================================================

saved_results = load_speech_results(
    product_id
)

result_rows = []

for video in videos:
    video_id = str(
        video.get(
            "video_id",
            ""
        )
    ).strip()

    if not video_id:
        continue

    result = saved_results.get(
        video_id
    )

    if not result:
        classification = (
            "⏳ Not analyzed"
        )

        speech_seconds = 0.0
        audio_seconds = 0.0
        speech_share = 0.0
        error_message = ""

    else:
        classification = result[
            "classification"
        ]

        speech_seconds = result[
            "speech_seconds"
        ]

        audio_seconds = result[
            "audio_seconds"
        ]

        speech_share = result[
            "speech_share"
        ]

        error_message = result[
            "error_message"
        ]

    result_rows.append(
        {
            "Classification":
                classification,

            "Creator":
                creator_label(
                    video
                ),

            "Caption":
                str(
                    video.get(
                        "caption",
                        ""
                    )
                    or ""
                ),

            "Views":
                safe_int(
                    video.get(
                        "views",
                        0
                    )
                ),

            "Attributed Sales":
                safe_int(
                    video.get(
                        "video_sales",
                        0
                    )
                ),

            "Attributed GMV":
                safe_float(
                    video.get(
                        "video_gmv",
                        0
                    )
                ),

            "Speech Seconds":
                speech_seconds,

            "Audio Seconds":
                audio_seconds,

            "Speech Share":
                speech_share,

            "Video ID":
                video_id,

            "Source URL Present":
                bool(
                    clean_video_url(
                        video
                    )
                ),

            "Analysis Error":
                error_message,
        }
    )


result_df = pd.DataFrame(
    result_rows
)


analyzed_df = result_df[
    result_df[
        "Classification"
    ].isin(
        [
            "🗣️ Talking",
            "🎵 Visual / Music",
        ]
    )
].copy()


talking_df = analyzed_df[
    analyzed_df[
        "Classification"
    ] == "🗣️ Talking"
].copy()


visual_df = analyzed_df[
    analyzed_df[
        "Classification"
    ] == "🎵 Visual / Music"
].copy()


talking_sales = int(
    talking_df[
        "Attributed Sales"
    ].sum()
) if not talking_df.empty else 0


visual_sales = int(
    visual_df[
        "Attributed Sales"
    ].sum()
) if not visual_df.empty else 0


analyzed_sales = (
    talking_sales
    + visual_sales
)


talking_sales_share = (
    (
        talking_sales
        / analyzed_sales
    ) * 100
    if analyzed_sales > 0
    else 0
)


visual_sales_share = (
    (
        visual_sales
        / analyzed_sales
    ) * 100
    if analyzed_sales > 0
    else 0
)


talking_video_share = (
    (
        len(
            talking_df
        )
        / len(
            analyzed_df
        )
    ) * 100
    if len(
        analyzed_df
    ) > 0
    else 0
)


# ==================================================
# SUMMARY
# ==================================================

st.divider()

st.subheader(
    "📊 Product Speech Mix"
)


unclear_count = int(
    (
        result_df[
            "Classification"
        ] == "❓ Unclear"
    ).sum()
)

s1, s2, s3, s4 = st.columns(
    4
)

s1.metric(
    "🗣️ Talking Videos",
    (
        f"{len(talking_df)} / "
        f"{len(analyzed_df)}"
    ),
)

s2.metric(
    "Talking Video Share",
    f"{talking_video_share:.1f}%",
)

s3.metric(
    "💰 Sales from Talking Videos",
    f"{talking_sales_share:.1f}%",
    help=(
        f"{talking_sales:,} of {analyzed_sales:,} attributed sales "
        "in the analyzed video sample came from Talking videos."
    ),
)

s4.metric(
    "❓ Unclear",
    unclear_count,
)


v1, v2 = st.columns(
    2
)

v1.metric(
    "🎵 Visual / Music Videos",
    (
        f"{len(visual_df)} / "
        f"{len(analyzed_df)}"
    ),
)

v2.metric(
    "Sales from Visual / Music Videos",
    f"{visual_sales_share:.1f}%",
    help=(
        f"{visual_sales:,} of {analyzed_sales:,} attributed sales "
        "in the analyzed video sample came from Visual / Music videos."
    ),
)


st.caption(
    f"Analyzed attributed sales: {analyzed_sales:,} • "
    f"Talking-video sales: {talking_sales:,} • "
    f"Visual/music-video sales: {visual_sales:,}"
)


if len(
    analyzed_df
) == 0:
    st.info(
        "Run the local speech analyzer to classify the cached videos."
    )

elif talking_sales_share >= 65:
    st.success(
        "Most analyzed attributed sales are coming from videos with "
        "meaningful spoken audio."
    )

elif talking_sales_share >= 35:
    st.info(
        "The product has a mixed creative pattern: both talking and "
        "visual/music videos contribute meaningful attributed sales."
    )

else:
    st.info(
        "Most analyzed attributed sales are currently coming from "
        "primarily visual/music creative."
    )


st.caption(
    "**Sales from Talking Videos** = the percentage of attributed sales "
    "in this analyzed video sample that came from videos classified as Talking. "
    "It does not mean verified total product sales."
)


# ==================================================
# RESULTS TABLE
# ==================================================

st.subheader(
    "🎬 Video Classifications"
)


display_df = result_df.copy()

display_df[
    "Speech Seconds"
] = display_df[
    "Speech Seconds"
].map(
    lambda value:
        round(
            value,
            1,
        )
)

display_df[
    "Audio Seconds"
] = display_df[
    "Audio Seconds"
].map(
    lambda value:
        round(
            value,
            1,
        )
)

display_df[
    "Speech Share"
] = display_df[
    "Speech Share"
].map(
    lambda value:
        f"{value * 100:.1f}%"
)

display_df[
    "Attributed GMV"
] = display_df[
    "Attributed GMV"
].map(
    lambda value:
        f"${value:,.0f}"
)

st.dataframe(
    display_df[
        [
            "Classification",
            "Creator",
            "Caption",
            "Views",
            "Attributed Sales",
            "Attributed GMV",
            "Speech Seconds",
            "Audio Seconds",
            "Speech Share",
            "Video ID",
        ]
    ],
    width="stretch",
    hide_index=True,
)


# ==================================================
# ERRORS / DIAGNOSTICS
# ==================================================

error_df = result_df[
    result_df[
        "Analysis Error"
    ].astype(
        str
    ).str.strip() != ""
].copy()


if not error_df.empty:
    st.subheader(
        "⚠️ Analysis Diagnostics"
    )

    st.error(
        f"{len(error_df)} video(s) could not be classified. "
        "The exact errors are shown below so we can diagnose the pipeline."
    )

    visible_errors = (
        error_df
        .head(
            5
        )
        .copy()
    )

    for _, error_row in visible_errors.iterrows():
        st.write(
            f"**Video {error_row['Video ID']}**"
        )

        st.caption(
            f"Creator: {error_row['Creator']} • "
            f"Cached video URL present: "
            f"{'Yes' if error_row['Source URL Present'] else 'No'}"
        )

        st.code(
            str(
                error_row[
                    "Analysis Error"
                ]
                or "Unknown analysis error."
            )
        )

    if len(
        error_df
    ) > 5:
        st.caption(
            f"Showing the first 5 of {len(error_df)} errors."
        )

    with st.expander(
        "View full diagnostics table"
    ):
        st.dataframe(
            error_df[
                [
                    "Video ID",
                    "Creator",
                    "Source URL Present",
                    "Classification",
                    "Analysis Error",
                ]
            ],
            width="stretch",
            hide_index=True,
        )


# ==================================================
# METHODOLOGY
# ==================================================

with st.expander(
    "How this classifier works"
):
    st.write(
        "1. FlipRadar first tries the cached TikTok CDN URL stored by the "
        "Content Deep Scan. If that signed URL has expired, FlipRadar uses "
        "the saved video ID with yt-dlp to resolve a fresh public TikTok "
        "media URL."
    )

    st.write(
        "2. The video's audio is converted locally to 16 kHz mono PCM."
    )

    st.write(
        "3. WebRTC Voice Activity Detection checks the audio in 30 ms frames "
        "for human speech."
    )

    st.write(
        f"4. A video is classified as **🗣️ Talking** when at least "
        f"{MIN_SPEECH_SECONDS:.1f} seconds of speech are detected and speech "
        f"covers at least {MIN_SPEECH_SHARE * 100:.0f}% of the analyzed audio."
    )

    st.write(
        "5. Otherwise it is classified as **🎵 Visual / Music**."
    )

    st.caption(
        "This is intentionally a simple first-pass classifier. "
        "Voiceover counts as Talking. Songs with clearly detected vocals can "
        "occasionally be mistaken for speech, so this should be treated as a "
        "creative-structure signal rather than a perfect semantic judgment."
    )


st.divider()

st.caption(
    "Talking vs Visual / Music analysis uses zero EchoTik API requests. "
    "It uses the cached video data first and can refresh an expired TikTok "
    "media URL directly from TikTok using the saved video ID."
)

if content_scan_time:
    st.caption(
        f"Content dataset cached: {content_scan_time}"
    )
