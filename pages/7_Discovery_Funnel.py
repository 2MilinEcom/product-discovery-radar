import inspect
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import wave
from datetime import datetime, timedelta
from pathlib import Path

import imageio_ffmpeg
import pandas as pd
import requests
import streamlit as st
import webrtcvad

import content_database
from fastmoss_content_scanner import (
    FASTMOSS_API_KEY,
    scan_product_content_fastmoss,
)
from scanner import normalize_echotik_product


# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="FlipRadar Discovery Funnel",
    page_icon="🔭",
    layout="wide",
)

DB_NAME = "flipradar.db"

DEFAULT_POOL_TARGET = 100
DEFAULT_SHORTLIST_SIZE = 30

# Stage 1 FastMoss discovery intentionally uses a fixed request count so the
# user knows the exact provider cost before clicking the button. The reliable
# v2 search paginates one broad documented query instead of experimental lanes.
FASTMOSS_DISCOVERY_REQUESTS = 3
FASTMOSS_DISCOVERY_PAGE_SIZE = 100
FASTMOSS_DISCOVERY_CACHE_HOURS = 48
FASTMOSS_PRODUCT_SEARCH_URL = (
    "https://openapi.fastmoss.com/product/v1/search"
)

CONTENT_SCAN_REQUESTS_PER_PRODUCT = 1
CONTENT_SCAN_DAYS = 30
CONTENT_SCAN_PAGE_SIZE = 10


# Talking-vs-Visual settings.
#
# v3 uses WebRTC VAD as a cheap pre-filter, separates speech from
# music/noise with inaSpeechSegmenter, then confirms intelligible
# spoken words with local faster-whisper transcription.
SPEECH_ANALYSIS_VERSION = "speech_music_v3"
WHISPER_MODEL_SIZE = "base"
UNAVAILABLE_CLASSIFICATION = "🚫 Unavailable / Restricted"

# Final-stage Runability Gate.
# A product can remain visible in the comparison table without passing,
# but it cannot enter the serious Top Opportunities cards unless all
# of these minimums are met.
RUNABILITY_MIN_CONCEPT_FIT = 65.0
RUNABILITY_MAX_AD_SATURATION = 80.0
RUNABILITY_MIN_MARKET_OPPORTUNITY = 55.0
RUNABILITY_MIN_TALKING_SALES_SHARE = 60.0
RUNABILITY_MIN_STRONG_VIDEOS = 1

VAD_MODE = 2
FRAME_MS = 30
VAD_PREFILTER_MIN_SECONDS = 0.75
VAD_PREFILTER_MIN_SHARE = 0.03

MIN_FOREGROUND_SPEECH_SECONDS = 1.5
MIN_FOREGROUND_SPEECH_SHARE = 0.08

MIN_TRANSCRIPT_WORDS = 5
MIN_TRANSCRIPT_SECONDS = 1.5
MIN_TRANSCRIPT_SHARE = 0.08
MAX_WHISPER_NO_SPEECH_PROB = 0.50
MIN_WHISPER_AVG_LOGPROB = -0.85

MAX_VIDEO_BYTES = 80 * 1024 * 1024
REQUEST_TIMEOUT = 40


# ==================================================
# DATABASE
# ==================================================

def initialize_discovery_funnel_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_funnel_runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 0,
            raw_slot_count INTEGER NOT NULL DEFAULT 0,
            unique_raw_count INTEGER NOT NULL DEFAULT 0,
            qualified_count INTEGER NOT NULL DEFAULT 0,
            shortlist_count INTEGER NOT NULL DEFAULT 0,
            settings_json TEXT NOT NULL,
            rejection_counts_json TEXT NOT NULL,
            products_json TEXT NOT NULL,
            shortlist_json TEXT NOT NULL
        )
        """
    )

    # Fallback cache. Normally Discovery Funnel writes through
    # content_database.save_content_scan(), so the rest of FlipRadar
    # can see the scans too. This table prevents scan results from being
    # lost if a local content_database version has a different save API.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_funnel_content_cache (
            product_id TEXT PRIMARY KEY,
            videos_json TEXT NOT NULL,
            scanned_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fastmoss_discovery_page_cache (
            cache_key TEXT PRIMARY KEY,
            page_number INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            products_json TEXT NOT NULL,
            total_results INTEGER NOT NULL DEFAULT 0,
            cached_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def save_discovery_funnel_run(
    request_count,
    raw_slot_count,
    unique_raw_count,
    settings,
    rejection_counts,
    products,
    shortlist,
):
    run_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO discovery_funnel_runs (
            run_id,
            created_at,
            request_count,
            raw_slot_count,
            unique_raw_count,
            qualified_count,
            shortlist_count,
            settings_json,
            rejection_counts_json,
            products_json,
            shortlist_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            created_at,
            int(request_count),
            int(raw_slot_count),
            int(unique_raw_count),
            len(products),
            len(shortlist),
            json.dumps(settings),
            json.dumps(rejection_counts),
            json.dumps(products),
            json.dumps(shortlist),
        ),
    )

    conn.commit()
    conn.close()

    return run_id, created_at


def load_latest_discovery_funnel_run():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            run_id,
            created_at,
            request_count,
            raw_slot_count,
            unique_raw_count,
            qualified_count,
            shortlist_count,
            settings_json,
            rejection_counts_json,
            products_json,
            shortlist_json
        FROM discovery_funnel_runs
        WHERE qualified_count > 0
        ORDER BY created_at DESC
        LIMIT 1
        """
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "run_id": row[0],
        "created_at": row[1],
        "request_count": int(row[2] or 0),
        "raw_slot_count": int(row[3] or 0),
        "unique_raw_count": int(row[4] or 0),
        "qualified_count": int(row[5] or 0),
        "shortlist_count": int(row[6] or 0),
        "settings": json.loads(row[7] or "{}"),
        "rejection_counts": json.loads(row[8] or "{}"),
        "products": json.loads(row[9] or "[]"),
        "shortlist": json.loads(row[10] or "[]"),
    }


def save_fallback_content_scan(product_id, videos):
    scanned_at = datetime.now().isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO discovery_funnel_content_cache (
            product_id,
            videos_json,
            scanned_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(product_id)
        DO UPDATE SET
            videos_json = excluded.videos_json,
            scanned_at = excluded.scanned_at
        """,
        (
            str(product_id),
            json.dumps(videos),
            scanned_at,
        ),
    )

    conn.commit()
    conn.close()

    return scanned_at


def load_fallback_content_scan(product_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT videos_json, scanned_at
        FROM discovery_funnel_content_cache
        WHERE product_id = ?
        """,
        (str(product_id),),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return [], None

    try:
        videos = json.loads(row[0] or "[]")
    except Exception:
        videos = []

    return videos, row[1]


initialize_discovery_funnel_database()

try:
    content_database.initialize_content_database()
except Exception:
    # The funnel still has its own fallback cache.
    pass


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


# ==================================================
# CONTENT DATABASE COMPATIBILITY
# ==================================================

def load_content_scan_compat(product_id):
    """
    Prefer FlipRadar's normal content_database so Content Scan,
    Creative Playbook, etc. can share the same cached videos.

    Fall back to the Discovery Funnel cache only if necessary.
    """

    try:
        videos, scanned_at = content_database.load_content_scan(
            str(product_id)
        )

        if videos:
            return videos, scanned_at, "content_database"
    except Exception:
        pass

    videos, scanned_at = load_fallback_content_scan(product_id)

    if videos:
        return videos, scanned_at, "funnel_fallback"

    return [], None, "none"


def save_content_scan_compat(product_id, videos):
    """
    Current FlipRadar versions are expected to expose
    content_database.save_content_scan(). This wrapper adapts to
    common signatures so Discovery Funnel can work without guessing
    one exact local signature.

    A fallback copy is always saved in the funnel cache.
    """

    fallback_scanned_at = save_fallback_content_scan(
        product_id,
        videos,
    )

    save_function = getattr(
        content_database,
        "save_content_scan",
        None,
    )

    if save_function is None:
        return fallback_scanned_at, "funnel_fallback"

    scanned_at = datetime.now().isoformat(timespec="seconds")

    try:
        signature = inspect.signature(save_function)
        parameter_names = list(signature.parameters.keys())

        kwargs = {}

        for name in parameter_names:
            lower = name.lower()

            if lower in {
                "product_id",
                "productid",
                "id",
            }:
                kwargs[name] = str(product_id)

            elif lower in {
                "videos",
                "video_list",
                "items",
                "records",
                "content",
            }:
                kwargs[name] = videos

            elif lower in {
                "scanned_at",
                "scan_time",
                "scan_timestamp",
                "created_at",
                "timestamp",
            }:
                kwargs[name] = scanned_at

        required_names = [
            name
            for name, parameter in signature.parameters.items()
            if (
                parameter.default is inspect.Parameter.empty
                and parameter.kind
                in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                }
            )
        ]

        if all(name in kwargs for name in required_names):
            save_function(**kwargs)
            return scanned_at, "content_database"

    except Exception:
        pass

    # Common positional signatures.
    for args in [
        (str(product_id), videos),
        (str(product_id), videos, scanned_at),
    ]:
        try:
            save_function(*args)
            return scanned_at, "content_database"
        except TypeError:
            continue
        except Exception:
            break

    return fallback_scanned_at, "funnel_fallback"


# ==================================================
# TALKING VS VISUAL — LOCAL SPEECH ENGINE
# ==================================================

def is_terminal_video_access_error(
    error_message,
):
    """
    Return True when TikTok/yt-dlp is telling us the post itself cannot
    be downloaded in the current FlipRadar environment.

    These are not speech-model failures, so repeatedly retrying them is
    not useful. They are resolved as Unavailable / Restricted instead.
    """
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
    """
    Reinterpret an already-saved TikTok access restriction as a terminal,
    non-retryable result. This also upgrades the existing LUCKMEEY row
    immediately without making the user download/retry that video again.
    """
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
            "download access. FlipRadar treats it as unavailable, excludes "
            "it from Talking-vs-Visual percentages and attributed-sales "
            "splits, and does not retry it."
        )

    return normalized


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
            analysis_version TEXT DEFAULT '',
            transcript TEXT DEFAULT '',
            transcript_word_count INTEGER NOT NULL DEFAULT 0,
            transcript_seconds REAL NOT NULL DEFAULT 0,
            transcript_share REAL NOT NULL DEFAULT 0,
            whisper_avg_logprob REAL NOT NULL DEFAULT -99,
            classification_reason TEXT DEFAULT '',
            model_name TEXT DEFAULT '',
            PRIMARY KEY (
                product_id,
                video_id
            )
        )
        """
    )

    cursor.execute(
        "PRAGMA table_info(video_speech_analysis)"
    )

    existing_columns = {
        row[1]
        for row in cursor.fetchall()
    }

    migrations = {
        "analysis_version":
            "TEXT DEFAULT ''",

        "transcript":
            "TEXT DEFAULT ''",

        "transcript_word_count":
            "INTEGER NOT NULL DEFAULT 0",

        "transcript_seconds":
            "REAL NOT NULL DEFAULT 0",

        "transcript_share":
            "REAL NOT NULL DEFAULT 0",

        "whisper_avg_logprob":
            "REAL NOT NULL DEFAULT -99",

        "classification_reason":
            "TEXT DEFAULT ''",

        "model_name":
            "TEXT DEFAULT ''",

        "foreground_speech_seconds":
            "REAL NOT NULL DEFAULT 0",

        "foreground_speech_share":
            "REAL NOT NULL DEFAULT 0",

        "music_seconds":
            "REAL NOT NULL DEFAULT 0",

        "music_share":
            "REAL NOT NULL DEFAULT 0",

        "noise_seconds":
            "REAL NOT NULL DEFAULT 0",

        "segmenter_name":
            "TEXT DEFAULT ''",
    }

    for column_name, column_sql in migrations.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"""
                ALTER TABLE video_speech_analysis
                ADD COLUMN {column_name} {column_sql}
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
            analyzed_at,
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

    conn.close()

    results = {}

    for row in rows:
        result = {
            "classification":
                row[1]
                or "❓ Unclear",

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

            "analysis_version":
                row[8]
                or "",

            "transcript":
                row[9]
                or "",

            "transcript_word_count":
                int(
                    row[10]
                    or 0
                ),

            "transcript_seconds":
                float(
                    row[11]
                    or 0
                ),

            "transcript_share":
                float(
                    row[12]
                    or 0
                ),

            "whisper_avg_logprob":
                float(
                    row[13]
                    if row[13] is not None
                    else -99
                ),

            "classification_reason":
                row[14]
                or "",

            "model_name":
                row[15]
                or "",

            "foreground_speech_seconds":
                float(
                    row[16]
                    or 0
                ),

            "foreground_speech_share":
                float(
                    row[17]
                    or 0
                ),

            "music_seconds":
                float(
                    row[18]
                    or 0
                ),

            "music_share":
                float(
                    row[19]
                    or 0
                ),

            "noise_seconds":
                float(
                    row[20]
                    or 0
                ),

            "segmenter_name":
                row[21]
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
            analyzed_at,
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
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(product_id, video_id)
        DO UPDATE SET
            classification = excluded.classification,
            speech_seconds = excluded.speech_seconds,
            audio_seconds = excluded.audio_seconds,
            speech_share = excluded.speech_share,
            source_url = excluded.source_url,
            error_message = excluded.error_message,
            analyzed_at = excluded.analyzed_at,
            analysis_version = excluded.analysis_version,
            transcript = excluded.transcript,
            transcript_word_count = excluded.transcript_word_count,
            transcript_seconds = excluded.transcript_seconds,
            transcript_share = excluded.transcript_share,
            whisper_avg_logprob = excluded.whisper_avg_logprob,
            classification_reason = excluded.classification_reason,
            model_name = excluded.model_name,
            foreground_speech_seconds = excluded.foreground_speech_seconds,
            foreground_speech_share = excluded.foreground_speech_share,
            music_seconds = excluded.music_seconds,
            music_share = excluded.music_share,
            noise_seconds = excluded.noise_seconds,
            segmenter_name = excluded.segmenter_name
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
                or ""
            ),
            datetime.now().isoformat(
                timespec="seconds"
            ),
            str(
                result.get(
                    "analysis_version",
                    SPEECH_ANALYSIS_VERSION,
                )
            ),
            str(
                result.get(
                    "transcript",
                    "",
                )
                or ""
            ),
            int(
                result.get(
                    "transcript_word_count",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "transcript_seconds",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "transcript_share",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "whisper_avg_logprob",
                    -99,
                )
                if result.get(
                    "whisper_avg_logprob",
                    None,
                ) is not None
                else -99
            ),
            str(
                result.get(
                    "classification_reason",
                    "",
                )
                or ""
            ),
            str(
                result.get(
                    "model_name",
                    "",
                )
                or ""
            ),
            float(
                result.get(
                    "foreground_speech_seconds",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "foreground_speech_share",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "music_seconds",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "music_share",
                    0,
                )
                or 0
            ),
            float(
                result.get(
                    "noise_seconds",
                    0,
                )
                or 0
            ),
            str(
                result.get(
                    "segmenter_name",
                    "",
                )
                or ""
            ),
        ),
    )

    conn.commit()
    conn.close()


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
        "Accept":
            "*/*",
        "Referer":
            "https://www.tiktok.com/",
        "Origin":
            "https://www.tiktok.com",
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
            "yt-dlp is not installed. Run: "
            "python -m pip install -U yt-dlp"
        ) from exc

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
        "quiet":
            True,

        "no_warnings":
            True,

        "noplaylist":
            True,

        "outtmpl":
            output_template,

        "format":
            "best",

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Referer":
                "https://www.tiktok.com/",
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
            "Fresh TikTok download failed: "
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
        "yt-dlp reported success but no "
        "downloaded video file was found."
    )


def download_video_for_speech(
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


@st.cache_resource(
    show_spinner=False
)
def get_speech_music_segmenter():
    # inaSpeechSegmenter (or one of its audio dependencies) may still call
    # numpy.lib.pad. NumPy 2.x removed that old alias, while numpy.pad
    # remains the supported function. Restore the alias locally so we do
    # not have to downgrade NumPy for the rest of FlipRadar.
    try:
        import numpy as np

        # Compatibility bridge for older audio-feature code used inside
        # inaSpeechSegmenter and its dependencies when running on newer
        # NumPy releases.
        if not hasattr(
            np.lib,
            "pad",
        ):
            np.lib.pad = np.pad

        # Newer NumPy requires stack-family inputs to be true sequences
        # (list/tuple) rather than generators. Some older audio code still
        # passes generators, so materialize only those inputs locally.
        if not getattr(
            np,
            "_flipradar_stack_compat",
            False,
        ):
            def _as_stack_sequence(
                arrays,
            ):
                if hasattr(
                    arrays,
                    "__getitem__",
                ):
                    return arrays

                return list(
                    arrays
                )

            original_stack = np.stack
            original_vstack = np.vstack
            original_hstack = np.hstack
            original_dstack = np.dstack
            original_column_stack = np.column_stack

            def _stack_compat(
                arrays,
                *args,
                **kwargs,
            ):
                return original_stack(
                    _as_stack_sequence(
                        arrays
                    ),
                    *args,
                    **kwargs,
                )

            def _vstack_compat(
                arrays,
                *args,
                **kwargs,
            ):
                return original_vstack(
                    _as_stack_sequence(
                        arrays
                    ),
                    *args,
                    **kwargs,
                )

            def _hstack_compat(
                arrays,
                *args,
                **kwargs,
            ):
                return original_hstack(
                    _as_stack_sequence(
                        arrays
                    ),
                    *args,
                    **kwargs,
                )

            def _dstack_compat(
                arrays,
                *args,
                **kwargs,
            ):
                return original_dstack(
                    _as_stack_sequence(
                        arrays
                    ),
                    *args,
                    **kwargs,
                )

            def _column_stack_compat(
                arrays,
                *args,
                **kwargs,
            ):
                return original_column_stack(
                    _as_stack_sequence(
                        arrays
                    ),
                    *args,
                    **kwargs,
                )

            np.stack = _stack_compat
            np.vstack = _vstack_compat
            np.hstack = _hstack_compat
            np.dstack = _dstack_compat
            np.column_stack = (
                _column_stack_compat
            )

            if hasattr(
                np,
                "row_stack",
            ):
                np.row_stack = (
                    _vstack_compat
                )

            np._flipradar_stack_compat = True

    except Exception as exc:
        raise RuntimeError(
            f"NumPy compatibility setup failed: {exc}"
        ) from exc

    try:
        from inaSpeechSegmenter import Segmenter
    except ImportError as exc:
        raise RuntimeError(
            "inaSpeechSegmenter is not installed. "
            "Run: python -m pip install inaSpeechSegmenter"
        ) from exc

    segmenter = Segmenter(
        vad_engine="smn",
        detect_gender=False,
    )

    # Some TensorFlow/Keras combinations deserialize INA's legacy HDF5
    # CNN with a 4-D input shape while an installed inaSpeechSegmenter
    # build can still hand predict() a 3-D batch. Adapt only the model
    # input at prediction time, choosing the singleton-axis placement
    # that matches the model's declared input shape.
    vad_model = segmenter.vad.nn

    if not getattr(
        vad_model,
        "_flipradar_input_compat",
        False,
    ):
        original_predict = (
            vad_model.predict
        )

        def _shape_matches(
            candidate_shape,
            expected_shape,
        ):
            if (
                not expected_shape
                or len(
                    candidate_shape
                )
                != len(
                    expected_shape
                )
            ):
                return False

            for actual_dim, expected_dim in zip(
                candidate_shape,
                expected_shape,
            ):
                if expected_dim is None:
                    continue

                try:
                    expected_value = int(
                        expected_dim
                    )
                except Exception:
                    continue

                if (
                    int(
                        actual_dim
                    )
                    != expected_value
                ):
                    return False

            return True

        def _predict_with_shape_compat(
            batch,
            *args,
            **kwargs,
        ):
            batch_array = np.asarray(
                batch
            )

            expected_shape = getattr(
                vad_model,
                "input_shape",
                None,
            )

            if (
                isinstance(
                    expected_shape,
                    list,
                )
                and expected_shape
            ):
                expected_shape = (
                    expected_shape[0]
                )

            if (
                expected_shape
                and batch_array.ndim
                < len(
                    expected_shape
                )
            ):
                candidates = []

                # Common legacy layouts:
                # N x 68 x 21 x 1
                candidates.append(
                    np.expand_dims(
                        batch_array,
                        axis=-1,
                    )
                )

                # Keras 3 can deserialize some old HDF5 inputs as:
                # N x 1 x 68 x 21
                candidates.append(
                    np.expand_dims(
                        batch_array,
                        axis=1,
                    )
                )

                for candidate in candidates:
                    if _shape_matches(
                        candidate.shape,
                        expected_shape,
                    ):
                        batch_array = (
                            candidate
                        )
                        break

            return original_predict(
                batch_array,
                *args,
                **kwargs,
            )

        vad_model.predict = (
            _predict_with_shape_compat
        )

        vad_model._flipradar_input_compat = (
            True
        )

    return segmenter


def analyze_speech_music_segments(
    wav_path,
    audio_seconds,
):
    segmenter = get_speech_music_segmenter()

    raw_segments = segmenter(
        str(
            wav_path
        )
    )

    speech_segments = []
    music_segments = []
    noise_segments = []

    for raw_segment in raw_segments:
        if len(
            raw_segment
        ) < 3:
            continue

        label = str(
            raw_segment[0]
            or ""
        ).strip().lower()

        start = max(
            0.0,
            float(
                raw_segment[1]
                or 0
            ),
        )

        end = max(
            start,
            float(
                raw_segment[2]
                or start
            ),
        )

        segment = {
            "label":
                label,

            "start":
                start,

            "end":
                end,

            "duration":
                max(
                    0.0,
                    end
                    - start,
                ),
        }

        if label in {
            "speech",
            "male",
            "female",
        }:
            speech_segments.append(
                segment
            )

        elif label == "music":
            music_segments.append(
                segment
            )

        else:
            noise_segments.append(
                segment
            )

    speech_seconds = sum(
        item[
            "duration"
        ]
        for item in speech_segments
    )

    music_seconds = sum(
        item[
            "duration"
        ]
        for item in music_segments
    )

    noise_seconds = sum(
        item[
            "duration"
        ]
        for item in noise_segments
    )

    return {
        "speech_segments":
            speech_segments,

        "foreground_speech_seconds":
            speech_seconds,

        "foreground_speech_share":
            (
                speech_seconds
                / audio_seconds
                if audio_seconds > 0
                else 0.0
            ),

        "music_seconds":
            music_seconds,

        "music_share":
            (
                music_seconds
                / audio_seconds
                if audio_seconds > 0
                else 0.0
            ),

        "noise_seconds":
            noise_seconds,

        "segmenter_name":
            "inaSpeechSegmenter-smn",
    }


def write_speech_only_wav(
    source_wav,
    target_wav,
    speech_segments,
):
    with wave.open(
        str(
            source_wav
        ),
        "rb",
    ) as source:
        params = source.getparams()
        frame_rate = source.getframerate()
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        frame_count = source.getnframes()

        raw_audio = source.readframes(
            frame_count
        )

    bytes_per_frame = (
        channels
        * sample_width
    )

    with wave.open(
        str(
            target_wav
        ),
        "wb",
    ) as target:
        target.setparams(
            params
        )

        for segment in speech_segments:
            start_frame = max(
                0,
                min(
                    frame_count,
                    int(
                        segment[
                            "start"
                        ]
                        * frame_rate
                    ),
                ),
            )

            end_frame = max(
                start_frame,
                min(
                    frame_count,
                    int(
                        segment[
                            "end"
                        ]
                        * frame_rate
                    ),
                ),
            )

            start_byte = (
                start_frame
                * bytes_per_frame
            )

            end_byte = (
                end_frame
                * bytes_per_frame
            )

            target.writeframes(
                raw_audio[
                    start_byte:
                    end_byte
                ]
            )


@st.cache_resource(
    show_spinner=False
)
def get_whisper_model():
    try:
        from faster_whisper import WhisperModel

    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. "
            "Run: python -m pip install faster-whisper"
        ) from exc

    return WhisperModel(
        WHISPER_MODEL_SIZE,
        device="cpu",
        compute_type="int8",
    )


def run_speech_pipeline_preflight():
    """
    Validate the shared local speech stack ONCE before touching any
    queued product videos.

    This catches global setup failures such as:
    - missing ffmpeg
    - inaSpeechSegmenter import/model-download failures
    - SSL/certificate failures while fetching the INA model
    - faster-whisper import/model-load failures
    - PyAV / faster-whisper decoder incompatibilities

    No FastMoss or EchoTik requests are made here.
    """
    checks = []

    def add_check(
        name,
        ok,
        detail,
    ):
        checks.append(
            {
                "name":
                    name,

                "ok":
                    bool(
                        ok
                    ),

                "detail":
                    str(
                        detail
                        or ""
                    ),
            }
        )

    # inaSpeechSegmenter invokes a command named "ffmpeg" itself,
    # so checking only imageio_ffmpeg's bundled binary is not enough.
    system_ffmpeg = shutil.which(
        "ffmpeg"
    )

    if not system_ffmpeg:
        add_check(
            "FFmpeg",
            False,
            (
                "The system ffmpeg executable is not available on PATH. "
                "inaSpeechSegmenter needs a command named `ffmpeg`."
            ),
        )

        return {
            "ok":
                False,

            "checks":
                checks,

            "error":
                (
                    "FFmpeg preflight failed before any videos were processed."
                ),

            "hint":
                (
                    "Install or expose ffmpeg on PATH, restart Streamlit, "
                    "then run the preflight again."
                ),
        }

    add_check(
        "FFmpeg",
        True,
        system_ffmpeg,
    )

    try:
        with tempfile.TemporaryDirectory(
            prefix="flipradar_preflight_"
        ) as temp_dir:
            temp_dir = Path(
                temp_dir
            )

            test_wav = (
                temp_dir
                / "preflight.wav"
            )

            # Use energetic synthetic audio rather than silence.
            # Silence can bypass INA's neural speech/music classifier and
            # make preflight look healthy even when the CNN predict path is
            # broken. This tone forces the actual model path to run.
            import numpy as np

            sample_rate = 16000
            test_seconds = 3.0
            sample_count = int(
                sample_rate
                * test_seconds
            )

            timeline = (
                np.arange(
                    sample_count,
                    dtype=np.float32,
                )
                / sample_rate
            )

            signal = (
                0.22
                * np.sin(
                    2
                    * np.pi
                    * 220.0
                    * timeline
                )
            )

            # Add amplitude modulation so the test is not perfectly
            # stationary while remaining deterministic and local.
            envelope = (
                0.65
                + 0.35
                * np.sin(
                    2
                    * np.pi
                    * 2.0
                    * timeline
                )
            )

            pcm = np.clip(
                signal
                * envelope
                * 32767.0,
                -32768,
                32767,
            ).astype(
                np.int16
            )

            with wave.open(
                str(
                    test_wav
                ),
                "wb",
            ) as wav_file:
                wav_file.setnchannels(
                    1
                )
                wav_file.setsampwidth(
                    2
                )
                wav_file.setframerate(
                    sample_rate
                )
                wav_file.writeframes(
                    pcm.tobytes()
                )

            try:
                segmenter = (
                    get_speech_music_segmenter()
                )

                # Calling the model on a real WAV catches both model
                # initialization/download issues and ffmpeg execution issues.
                segmenter(
                    str(
                        test_wav
                    )
                )

                add_check(
                    "Speech / music model",
                    True,
                    (
                        "inaSpeechSegmenter initialized and its neural "
                        "speech/music CNN processed energetic local test audio."
                    ),
                )

            except Exception as exc:
                error_text = str(
                    exc
                )

                add_check(
                    "Speech / music model",
                    False,
                    error_text,
                )

                hint = (
                    "Fix the inaSpeechSegmenter setup error, restart "
                    "Streamlit, then try again."
                )

                if (
                    "CERTIFICATE_VERIFY_FAILED"
                    in error_text
                    or "certificate verify failed"
                    in error_text.lower()
                ):
                    hint = (
                        "Python could not verify the certificate while "
                        "downloading the inaSpeechSegmenter model. Fix the "
                        "Python certificate bundle first; no queued videos "
                        "were processed."
                    )

                elif (
                    "ffmpeg program not found"
                    in error_text.lower()
                ):
                    hint = (
                        "inaSpeechSegmenter still cannot execute ffmpeg. "
                        "Make sure `ffmpeg` is on PATH for the same Terminal "
                        "session that launches Streamlit."
                    )

                return {
                    "ok":
                        False,

                    "checks":
                        checks,

                    "error":
                        (
                            "Speech/music model preflight failed before "
                            "any videos were processed."
                        ),

                    "hint":
                        hint,
                }

            try:
                whisper_model = (
                    get_whisper_model()
                )

                # faster-whisper decodes lazily, so force one tiny local
                # transcription. This catches PyAV compatibility problems
                # before the 74-video loop starts.
                test_segments, _ = (
                    whisper_model.transcribe(
                        str(
                            test_wav
                        ),
                        beam_size=1,
                        best_of=1,
                        temperature=0,
                        condition_on_previous_text=False,
                        vad_filter=False,
                        language="en",
                    )
                )

                list(
                    test_segments
                )

                add_check(
                    "Whisper",
                    True,
                    (
                        f"faster-whisper `{WHISPER_MODEL_SIZE}` loaded "
                        "and decoded the local test audio."
                    ),
                )

            except Exception as exc:
                error_text = str(
                    exc
                )

                add_check(
                    "Whisper",
                    False,
                    error_text,
                )

                hint = (
                    "Fix the faster-whisper setup error, restart "
                    "Streamlit, then try again."
                )

                if (
                    "metadata_errors"
                    in error_text
                ):
                    hint = (
                        "The installed PyAV version is incompatible with "
                        "this faster-whisper build. Keep the working "
                        "PyAV 18.1.0 pin, restart Streamlit, then retry."
                    )

                return {
                    "ok":
                        False,

                    "checks":
                        checks,

                    "error":
                        (
                            "Whisper preflight failed before any videos "
                            "were processed."
                        ),

                    "hint":
                        hint,
                }

    except Exception as exc:
        return {
            "ok":
                False,

            "checks":
                checks,

            "error":
                (
                    "Speech/Music v3 preflight could not complete."
                ),

            "hint":
                str(
                    exc
                ),
        }

    return {
        "ok":
            True,

        "checks":
            checks,

        "error":
            "",

        "hint":
            (
                "Local speech stack is ready."
            ),
    }


def transcribe_wav_with_whisper(
    wav_path,
    audio_seconds,
):
    model = get_whisper_model()

    segments, info = model.transcribe(
        str(
            wav_path
        ),
        beam_size=1,
        best_of=1,
        temperature=0,
        condition_on_previous_text=False,
        vad_filter=True,
        language=None,
    )

    reliable_segments = []
    all_segment_text = []

    weighted_logprob_total = 0.0
    weighted_logprob_seconds = 0.0

    for segment in segments:
        text_value = str(
            getattr(
                segment,
                "text",
                "",
            )
            or ""
        ).strip()

        if not text_value:
            continue

        all_segment_text.append(
            text_value
        )

        no_speech_prob = float(
            getattr(
                segment,
                "no_speech_prob",
                1.0,
            )
            or 0
        )

        avg_logprob = float(
            getattr(
                segment,
                "avg_logprob",
                -99,
            )
            if getattr(
                segment,
                "avg_logprob",
                None,
            ) is not None
            else -99
        )

        start = float(
            getattr(
                segment,
                "start",
                0,
            )
            or 0
        )

        end = float(
            getattr(
                segment,
                "end",
                start,
            )
            or start
        )

        duration = max(
            0.0,
            end
            - start,
        )

        if (
            no_speech_prob
            <= MAX_WHISPER_NO_SPEECH_PROB
            and avg_logprob
            >= MIN_WHISPER_AVG_LOGPROB
        ):
            reliable_segments.append(
                {
                    "text":
                        text_value,

                    "start":
                        start,

                    "end":
                        end,

                    "duration":
                        duration,

                    "no_speech_prob":
                        no_speech_prob,

                    "avg_logprob":
                        avg_logprob,
                }
            )

            if duration > 0:
                weighted_logprob_total += (
                    avg_logprob
                    * duration
                )

                weighted_logprob_seconds += (
                    duration
                )

    transcript = " ".join(
        segment[
            "text"
        ]
        for segment in reliable_segments
    ).strip()

    transcript_words = re.findall(
        r"[A-Za-z0-9']+",
        transcript,
    )

    transcript_word_count = len(
        transcript_words
    )

    transcript_seconds = sum(
        segment[
            "duration"
        ]
        for segment in reliable_segments
    )

    transcript_share = (
        transcript_seconds
        / audio_seconds
        if audio_seconds > 0
        else 0.0
    )

    if weighted_logprob_seconds > 0:
        average_logprob = (
            weighted_logprob_total
            / weighted_logprob_seconds
        )

    else:
        average_logprob = -99.0

    detected_language = str(
        getattr(
            info,
            "language",
            "",
        )
        or ""
    )

    return {
        "transcript":
            transcript,

        "transcript_word_count":
            transcript_word_count,

        "transcript_seconds":
            transcript_seconds,

        "transcript_share":
            transcript_share,

        "whisper_avg_logprob":
            average_logprob,

        "detected_language":
            detected_language,

        "raw_segment_text":
            " ".join(
                all_segment_text
            ).strip(),
    }


def classify_speech_v3(
    vad_result,
    segment_result,
    whisper_result,
):
    audio_seconds = float(
        vad_result.get(
            "audio_seconds",
            0,
        )
        or 0
    )

    vad_seconds = float(
        vad_result.get(
            "speech_seconds",
            0,
        )
        or 0
    )

    vad_share = float(
        vad_result.get(
            "speech_share",
            0,
        )
        or 0
    )

    if audio_seconds <= 0:
        return (
            "🎵 Visual / Music",
            "No usable audio track was detected.",
        )

    if (
        vad_seconds
        < VAD_PREFILTER_MIN_SECONDS
        or vad_share
        < VAD_PREFILTER_MIN_SHARE
    ):
        return (
            "🎵 Visual / Music",
            (
                "WebRTC VAD found too little speech-like audio "
                "to justify deeper speech analysis."
            ),
        )

    foreground_seconds = float(
        segment_result.get(
            "foreground_speech_seconds",
            0,
        )
        or 0
    )

    foreground_share = float(
        segment_result.get(
            "foreground_speech_share",
            0,
        )
        or 0
    )

    if (
        foreground_seconds
        < MIN_FOREGROUND_SPEECH_SECONDS
        or foreground_share
        < MIN_FOREGROUND_SPEECH_SHARE
    ):
        return (
            "🎵 Visual / Music",
            (
                "The speech-vs-music model found too little actual "
                "foreground speech. Most voice-like audio was music, "
                "singing, or non-speech."
            ),
        )

    word_count = int(
        whisper_result.get(
            "transcript_word_count",
            0,
        )
        or 0
    )

    transcript_seconds = float(
        whisper_result.get(
            "transcript_seconds",
            0,
        )
        or 0
    )

    transcript_share = float(
        whisper_result.get(
            "transcript_share",
            0,
        )
        or 0
    )

    if (
        word_count
        >= MIN_TRANSCRIPT_WORDS
        and transcript_seconds
        >= MIN_TRANSCRIPT_SECONDS
        and transcript_share
        >= MIN_TRANSCRIPT_SHARE
    ):
        return (
            "🗣️ Talking",
            (
                "The speech-vs-music model found real speech segments, "
                "and Whisper confirmed sustained intelligible words "
                "inside those speech-only segments."
            ),
        )

    return (
        "🎵 Visual / Music",
        (
            "Some foreground speech-like segments were detected, but "
            "Whisper did not confirm enough intelligible spoken words "
            "inside those segments. This helps reject sung lyrics and "
            "music vocals."
        ),
    )


def analyze_video_speech(
    video_url,
    video_id,
):
    empty_result = {
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
            "",

        "analysis_version":
            SPEECH_ANALYSIS_VERSION,

        "transcript":
            "",

        "transcript_word_count":
            0,

        "transcript_seconds":
            0.0,

        "transcript_share":
            0.0,

        "whisper_avg_logprob":
            -99.0,

        "classification_reason":
            "",

        "model_name":
            WHISPER_MODEL_SIZE,

        "foreground_speech_seconds":
            0.0,

        "foreground_speech_share":
            0.0,

        "music_seconds":
            0.0,

        "music_share":
            0.0,

        "noise_seconds":
            0.0,

        "segmenter_name":
            "inaSpeechSegmenter-smn",
    }

    if not video_id:
        empty_result[
            "error_message"
        ] = (
            "No video ID is available."
        )
        return empty_result

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

            speech_only_wav = (
                temp_dir
                / "speech_only.wav"
            )

            (
                video_path,
                download_method,
            ) = download_video_for_speech(
                url=video_url,
                video_id=video_id,
                temp_dir=temp_dir,
            )

            extract_audio_to_wav(
                video_path,
                wav_path,
            )

            vad_result = analyze_wav_speech(
                wav_path
            )

            result = dict(
                empty_result
            )

            result[
                "speech_seconds"
            ] = vad_result[
                "speech_seconds"
            ]

            result[
                "audio_seconds"
            ] = vad_result[
                "audio_seconds"
            ]

            result[
                "speech_share"
            ] = vad_result[
                "speech_share"
            ]

            result[
                "download_method"
            ] = download_method

            if (
                vad_result[
                    "speech_seconds"
                ]
                < VAD_PREFILTER_MIN_SECONDS
                or vad_result[
                    "speech_share"
                ]
                < VAD_PREFILTER_MIN_SHARE
            ):
                (
                    classification,
                    reason,
                ) = classify_speech_v3(
                    vad_result,
                    {},
                    {},
                )

                result[
                    "classification"
                ] = classification

                result[
                    "classification_reason"
                ] = reason

                return result

            segment_result = (
                analyze_speech_music_segments(
                    wav_path=
                        wav_path,

                    audio_seconds=
                        vad_result[
                            "audio_seconds"
                        ],
                )
            )

            result.update(
                {
                    key:
                        segment_result[
                            key
                        ]
                    for key in [
                        "foreground_speech_seconds",
                        "foreground_speech_share",
                        "music_seconds",
                        "music_share",
                        "noise_seconds",
                        "segmenter_name",
                    ]
                }
            )

            if (
                segment_result[
                    "foreground_speech_seconds"
                ]
                < MIN_FOREGROUND_SPEECH_SECONDS
                or segment_result[
                    "foreground_speech_share"
                ]
                < MIN_FOREGROUND_SPEECH_SHARE
            ):
                (
                    classification,
                    reason,
                ) = classify_speech_v3(
                    vad_result,
                    segment_result,
                    {},
                )

                result[
                    "classification"
                ] = classification

                result[
                    "classification_reason"
                ] = reason

                return result

            write_speech_only_wav(
                source_wav=
                    wav_path,

                target_wav=
                    speech_only_wav,

                speech_segments=
                    segment_result[
                        "speech_segments"
                    ],
            )

            whisper_result = (
                transcribe_wav_with_whisper(
                    wav_path=
                        speech_only_wav,

                    audio_seconds=
                        vad_result[
                            "audio_seconds"
                        ],
                )
            )

            (
                classification,
                reason,
            ) = classify_speech_v3(
                vad_result,
                segment_result,
                whisper_result,
            )

            result.update(
                whisper_result
            )

            result[
                "classification"
            ] = classification

            result[
                "classification_reason"
            ] = reason

            return result

    except Exception as exc:
        result = dict(
            empty_result
        )

        error_text = str(
            exc
        )[
            :1000
        ]

        result[
            "error_message"
        ] = error_text

        if is_terminal_video_access_error(
            error_text
        ):
            result[
                "classification"
            ] = UNAVAILABLE_CLASSIFICATION

            result[
                "classification_reason"
            ] = (
                "TikTok restricted or withheld this post from unauthenticated "
                "download access. FlipRadar treats it as unavailable, excludes "
                "it from Talking-vs-Visual percentages and attributed-sales "
                "splits, and does not retry it."
            )

        else:
            result[
                "classification_reason"
            ] = (
                "The video could not be fully analyzed."
            )

        return result


def speech_result_is_successful(
    result,
):
    if not result:
        return False

    if (
        result.get(
            "analysis_version",
            "",
        )
        != SPEECH_ANALYSIS_VERSION
    ):
        return False

    classification = str(
        result.get(
            "classification",
            "",
        )
        or ""
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
        return True

    if error_message:
        return False

    return classification in {
        "🗣️ Talking",
        "🎵 Visual / Music",
    }


def speech_result_needs_retry(
    result,
):
    return not speech_result_is_successful(
        result
    )


def summarize_product_speech(
    videos,
    saved_results,
):
    sampled_ids = []

    talking_count = 0
    visual_count = 0
    unavailable_count = 0
    unclear_count = 0
    stale_or_missing_count = 0

    talking_sales = 0
    visual_sales = 0

    successful_count = 0

    for video in videos:
        video_id = str(
            video.get(
                "video_id",
                "",
            )
            or ""
        ).strip()

        if not video_id:
            continue

        sampled_ids.append(
            video_id
        )

        result = saved_results.get(
            video_id
        )

        if not result:
            stale_or_missing_count += 1
            continue

        if (
            result.get(
                "analysis_version",
                "",
            )
            != SPEECH_ANALYSIS_VERSION
        ):
            stale_or_missing_count += 1
            continue

        classification = str(
            result.get(
                "classification",
                "",
            )
            or ""
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
            unavailable_count += 1
            continue

        if (
            error_message
            or classification
            not in {
                "🗣️ Talking",
                "🎵 Visual / Music",
            }
        ):
            unclear_count += 1
            continue

        successful_count += 1

        sales = safe_int(
            video.get(
                "video_sales",
                0,
            )
        )

        if classification == "🗣️ Talking":
            talking_count += 1
            talking_sales += sales

        elif classification == "🎵 Visual / Music":
            visual_count += 1
            visual_sales += sales

    pending_count = (
        unclear_count
        + stale_or_missing_count
    )

    clear_count = (
        talking_count
        + visual_count
    )

    analyzed_sales = (
        talking_sales
        + visual_sales
    )

    talking_video_share = (
        (
            talking_count
            / clear_count
        )
        * 100
        if clear_count > 0
        else 0.0
    )

    talking_sales_share = (
        (
            talking_sales
            / analyzed_sales
        )
        * 100
        if analyzed_sales > 0
        else 0.0
    )

    return {
        "sampled":
            len(
                sampled_ids
            ),

        "analyzed":
            successful_count,

        "successful":
            successful_count,

        "missing":
            pending_count,

        "stale_or_missing":
            stale_or_missing_count,

        "talking_count":
            talking_count,

        "visual_count":
            visual_count,

        "unavailable_count":
            unavailable_count,

        "unclear_count":
            unclear_count,

        "talking_video_share":
            talking_video_share,

        "talking_sales":
            talking_sales,

        "visual_sales":
            visual_sales,

        "analyzed_sales":
            analyzed_sales,

        "talking_sales_share":
            talking_sales_share,
    }


def build_speech_status_rows(
    shortlist,
):
    rows = []
    jobs = []

    for rank, product in enumerate(
        shortlist,
        start=1,
    ):
        product_id = str(
            product.get(
                "id",
                "",
            )
        ).strip()

        videos, scanned_at, source = (
            load_content_scan_compat(
                product_id
            )
        )

        if not videos:
            continue

        saved_results = (
            load_speech_results(
                product_id
            )
        )

        summary = (
            summarize_product_speech(
                videos,
                saved_results,
            )
        )

        retry_videos = []

        for video in videos:
            video_id = str(
                video.get(
                    "video_id",
                    "",
                )
                or ""
            ).strip()

            if not video_id:
                continue

            saved_result = saved_results.get(
                video_id
            )

            if speech_result_needs_retry(
                saved_result
            ):
                retry_videos.append(
                    video
                )

        if retry_videos:
            jobs.append(
                {
                    "rank":
                        rank,

                    "product":
                        product,

                    "videos":
                        retry_videos,
                }
            )

        if summary[
            "missing"
        ] == 0:
            status = (
                "✅ Complete"
            )

        elif (
            summary[
                "unclear_count"
            ] > 0
        ):
            status = (
                "⚠️ Retry needed"
            )

        elif summary[
            "analyzed"
        ] > 0:
            status = (
                "🟡 Partial"
            )

        else:
            status = (
                "⏳ Not analyzed"
            )

        last_errors = []

        for video in retry_videos:
            video_id = str(
                video.get(
                    "video_id",
                    "",
                )
                or ""
            ).strip()

            saved_result = saved_results.get(
                video_id,
                {},
            )

            error_message = str(
                saved_result.get(
                    "error_message",
                    "",
                )
                or ""
            ).strip()

            if error_message:
                last_errors.append(
                    error_message
                )

        rows.append(
            {
                "Rank":
                    rank,

                "Product":
                    product.get(
                        "name",
                        "Unknown Product",
                    ),

                "Speech Status":
                    status,

                "Sampled Videos":
                    summary[
                        "sampled"
                    ],

                "Classified":
                    summary[
                        "successful"
                    ],

                "Retry / Unclear":
                    summary[
                        "missing"
                    ],

                "Talking Videos":
                    summary[
                        "talking_count"
                    ],

                "Visual / Music":
                    summary[
                        "visual_count"
                    ],

                "Unavailable":
                    summary[
                        "unavailable_count"
                    ],

                "Talking Video Share":
                    summary[
                        "talking_video_share"
                    ],

                "Sales from Talking Videos":
                    summary[
                        "talking_sales_share"
                    ],

                "Talking Attributed Sales":
                    summary[
                        "talking_sales"
                    ],

                "Visual Attributed Sales":
                    summary[
                        "visual_sales"
                    ],

                "Last Error":
                    (
                        last_errors[0][
                            :220
                        ]
                        if last_errors
                        else ""
                    ),

                "Product ID":
                    product_id,

                "_scanned_at":
                    scanned_at
                    or "",

                "_cache_source":
                    source,
            }
        )

    return (
        rows,
        jobs,
    )


initialize_speech_database()


# ==================================================
# HARD QUALIFICATION RULES
# ==================================================

def qualify_product(product, settings):
    reasons = []

    age_days = safe_int(product.get("age_days", 0))
    seven_day_sales = safe_int(product.get("seven_day_sales", 0))
    growth = safe_float(product.get("growth", 0))
    price = safe_float(product.get("price", 0))
    creators = safe_int(
        product.get(
            "creators",
            0,
        )
    )

    provider = str(
        product.get(
            "discovery_provider",
            settings.get(
                "discovery_provider",
                "echotik",
            ),
        )
        or ""
    ).lower()

    if (
        age_days <= 0
        or age_days > settings["max_age_days"]
    ):
        reasons.append("Too old / invalid age")

    if seven_day_sales < settings["min_7d_sales"]:
        reasons.append("Weak 7d sales")

    if growth < settings["min_growth"]:
        reasons.append("Momentum below minimum")

    if price <= 0 or price > settings["max_price"]:
        reasons.append("Price outside range")

    if provider == "fastmoss":
        max_creator_count = safe_int(
            settings.get(
                "max_creator_count",
                500,
            ),
            500,
        )

        if (
            max_creator_count > 0
            and creators > max_creator_count
        ):
            reasons.append("Too many associated creators")

    else:
        promotion_count_7d = safe_int(
            product.get(
                "promotion_count_7d",
                0,
            )
        )

        if (
            promotion_count_7d
            > settings.get(
                "max_promotions_7d",
                300,
            )
        ):
            reasons.append("Too many recent promotions")

    return len(reasons) == 0, reasons


# ==================================================
# DISCOVERY BUCKET MERGE
# ==================================================

def add_bucket_metadata(raw, bucket_name):
    item = dict(raw)

    buckets = item.get(
        "_flipradar_discovery_buckets",
        [],
    )

    if not isinstance(buckets, list):
        buckets = []

    if bucket_name not in buckets:
        buckets.append(bucket_name)

    item["_flipradar_discovery_buckets"] = buckets

    if not item.get("_flipradar_primary_bucket"):
        item["_flipradar_primary_bucket"] = bucket_name

    return item


def merge_raw_product(existing, incoming, bucket_name):
    incoming = add_bucket_metadata(incoming, bucket_name)

    if existing is None:
        return incoming

    merged = dict(existing)

    current_buckets = merged.get(
        "_flipradar_discovery_buckets",
        [],
    )

    if not isinstance(current_buckets, list):
        current_buckets = []

    for bucket in incoming.get(
        "_flipradar_discovery_buckets",
        [],
    ):
        if bucket not in current_buckets:
            current_buckets.append(bucket)

    merged["_flipradar_discovery_buckets"] = current_buckets

    if not merged.get("_flipradar_primary_bucket"):
        merged["_flipradar_primary_bucket"] = bucket_name

    return merged


def classify_product_fit(
    product,
):
    title = str(
        product.get(
            "name",
            "",
        )
        or ""
    ).lower()

    category = str(
        product.get(
            "category",
            "",
        )
        or ""
    ).lower()

    haystack = (
        title
        + " "
        + category
    )

    hard_exclude_rules = [
        (
            "Gadget / phone / car tech",
            [
                "phone holder",
                "cell phone holder",
                "phone mount",
                "car mount",
                "dashboard mount",
                "magnetic mount",
                "mobile mount",
                "car accessory",
                "vehicle accessory",
                "charger",
                "charging station",
                "power bank",
                "bluetooth",
                "earbuds",
                "headphones",
                "speaker",
                "smart watch",
                "smartwatch",
                "selfie stick",
            ],
        ),
        (
            "Novelty / toy / seasonal",
            [
                "advent calendar",
                "countdown calendar",
                "squishy",
                "squishies",
                "fidget",
                "plush toy",
                "toy countdown",
                "christmas mini",
                "holiday countdown",
            ],
        ),
        (
            "Commodity carry accessory",
            [
                "wallet",
                "bifold",
                "card holder",
                "money clip",
                "keychain",
                "key chain",
                "key ring",
                "key holder",
            ],
        ),
        (
            "Utility tool / commodity home item",
            [
                "cleaning tool",
                "gap cleaning",
                "cleaning brush",
                "scrubber",
                "tool set",
                "drill bit",
                "wrench",
                "screwdriver",
                "storage rack",
                "organizer rack",
            ],
        ),
    ]

    for label, terms in hard_exclude_rules:
        matched = [
            term
            for term in terms
            if term in haystack
        ]

        if matched:
            return {
                "eligible":
                    False,

                "score":
                    0.0,

                "segment":
                    label,

                "reason":
                    (
                        "Hard filtered because it looks like "
                        f"{label.lower()}."
                    ),

                "matched_terms":
                    ", ".join(
                        matched[
                            :3
                        ]
                    ),
            }

    preferred_rules = [
        (
            "Beauty / Personal Care",
            95.0,
            [
                "perfume",
                "fragrance",
                "body wash",
                "exfoliating",
                "exfoliant",
                "serum",
                "cleanser",
                "moisturizer",
                "skincare",
                "skin care",
                "body lotion",
                "lip gloss",
                "lip oil",
                "shampoo",
                "conditioner",
                "hair oil",
                "scalp",
                "deodorant",
                "beauty",
                "soap",
                "body care",
            ],
        ),
        (
            "Wellness / Consumable",
            92.0,
            [
                "protein coffee",
                "protein",
                "coffee",
                "collagen",
                "electrolyte",
                "hydration",
                "drink mix",
                "wellness",
                "tea",
                "gummies",
                "gummy",
            ],
        ),
        (
            "Fashion / Identity",
            86.0,
            [
                "bra",
                "shapewear",
                "dress",
                "bodysuit",
                "jacket",
                "coat",
                "jeans",
                "leggings",
                "hoodie",
                "sweatpants",
                "matching set",
                "activewear",
                "swimsuit",
                "swimwear",
                "skirt",
                "blouse",
                "crop top",
                "shorts",
            ],
        ),
    ]

    best_match = None

    for segment, score, terms in preferred_rules:
        matched = [
            term
            for term in terms
            if term in haystack
        ]

        if matched:
            candidate = {
                "eligible":
                    True,

                "score":
                    score,

                "segment":
                    segment,

                "reason":
                    (
                        "Fits the preferred product profile: "
                        f"{segment.lower()}."
                    ),

                "matched_terms":
                    ", ".join(
                        matched[
                            :3
                        ]
                    ),
            }

            if (
                best_match is None
                or candidate[
                    "score"
                ]
                > best_match[
                    "score"
                ]
            ):
                best_match = candidate

    if best_match:
        return best_match

    return {
        "eligible":
            True,

        "score":
            70.0,

        "segment":
            "Neutral / Needs Review",

        "reason":
            (
                "No obvious gadget/novelty/commodity exclusion was found, "
                "but it also did not match a preferred beauty, wellness, "
                "consumable, or fashion profile."
            ),

        "matched_terms":
            "",
    }



# ==================================================
# MARKETING CONCEPT FIT — LOCAL / 0 API REQUESTS
# ==================================================

def classify_marketing_concept(
    product,
    videos=None,
):
    """
    Marketing Concept Fit v2.

    This is deliberately stricter than v1. Generic product benefits can
    create a decent score, but only products with a genuinely built-in
    premise — relationship/intimacy, personalization, caregiving tied to a
    specific need, or another unusually clear use case — can reach the very
    top of the scale.

    Cached captions VALIDATE an angle. A single stray caption keyword is not
    allowed to manufacture a major concept.
    """
    title = str(
        product.get(
            "name",
            "",
        )
        or ""
    ).lower()

    category = str(
        product.get(
            "category",
            "",
        )
        or ""
    ).lower()

    product_text = (
        title
        + " "
        + category
    )

    caption_texts = []

    for video in (
        videos
        or []
    ):
        caption = str(
            video.get(
                "caption",
                "",
            )
            or video.get(
                "title",
                "",
            )
            or video.get(
                "description",
                "",
            )
            or ""
        ).strip().lower()

        if caption:
            caption_texts.append(
                caption
            )

    def find_matches(
        terms,
        text_value,
    ):
        return [
            term
            for term in terms
            if term in text_value
        ]

    def caption_count(
        terms,
    ):
        return sum(
            1
            for caption in caption_texts
            if any(
                term in caption
                for term in terms
            )
        )

    def caption_cooccurrence_count(
        terms_a,
        terms_b,
    ):
        return sum(
            1
            for caption in caption_texts
            if (
                any(
                    term in caption
                    for term in terms_a
                )
                and any(
                    term in caption
                    for term in terms_b
                )
            )
        )

    relationship_terms = [
        "boyfriend",
        "girlfriend",
        "husband",
        "wife",
        "partner",
        "couple",
        "couples",
        "date night",
        "bedroom",
        "intimate",
        "intimacy",
        "spicy",
        "sexy",
        "lingerie",
        "thong",
        "easy access",
        "romantic",
        "for him",
        "for her",
    ]

    personalization_terms = [
        "custom",
        "personalized",
        "personalised",
        "custom name",
        "name on",
        "monogram",
        "initial",
        "engraved",
        "engraving",
        "custom text",
        "custom photo",
        "photo gift",
    ]

    # Strong caregiving anchors are reserved for an actual child/baby
    # plus a specific need. Adult postpartum/maternity products are useful
    # angles, but they should not receive the same near-perfect concept
    # treatment as a baby-bedtime or child-specific problem product.
    child_caregiving_terms = [
        "baby",
        "newborn",
        "toddler",
        "kids",
        "kid",
        "child",
        "children",
    ]

    child_need_terms = [
        "sleep",
        "bedtime",
        "calm",
        "soothe",
        "soothing",
        "teething",
        "colic",
        "cramp",
        "tension",
    ]

    adult_recovery_terms = [
        "postpartum",
        "maternity",
        "post-pregnancy",
        "post pregnancy",
        "recovery",
    ]

    specific_problem_terms = [
        "sleep",
        "bedtime",
        "insomnia",
        "pain",
        "sore",
        "cramp",
        "tension",
        "recovery",
        "postpartum",
        "back support",
        "non slip",
        "anti-slip",
        "anti slip",
        "front closure",
        "tummy control",
        "odor",
        "odour",
        "sweat",
        "acne",
        "dark spot",
        "dark spots",
        "hyperpigmentation",
        "hair loss",
        "thinning",
        "frizz",
        "dry scalp",
        "dandruff",
        "eczema",
        "sensitive skin",
        "stretch mark",
        "under eye",
        "color-correcting",
        "colour-correcting",
        "color correcting",
        "colour correcting",
        "strapless",
    ]

    transformation_terms = [
        "brightening",
        "brighten",
        "exfoliating",
        "exfoliant",
        "push up",
        "push-up",
        "lift",
        "lifter",
        "lifting",
        "tummy control",
        "shapewear",
        "shaper",
        "slimming",
        "firming",
        "smoothing",
        "color-correcting",
        "colour-correcting",
        "color correcting",
        "colour correcting",
        "growth",
        "hair growth",
        "repair",
        "restore",
        "volumizing",
        "volume",
        "whitening",
        "glow",
        "glowing",
        "plump",
        "curl",
        "butt lifter",
        "body shaper",
    ]

    demonstration_terms = [
        "easy-off",
        "easy off",
        "easy access",
        "open design",
        "front closure",
        "removable straps",
        "zipper front",
        "roll on",
        "roll-on",
        "rub",
        "spray",
        "peel",
        "color changing",
        "colour changing",
        "before and after",
        "before & after",
        "custom",
        "personalized",
        "personalised",
    ]

    identity_terms = [
        "strapless",
        "date night",
        "going out",
        "outfit",
        "everyday wear",
        "wedding",
        "bridal",
        "maternity",
        "postpartum",
        "gym",
        "activewear",
        "shapewear",
        "lingerie",
        "swimwear",
    ]

    sensual_product_terms = [
        "body oil",
        "massage oil",
        "massage serum",
        "body serum",
    ]

    story_friendly_terms = [
        "hair serum",
        "hair oil",
        "scalp serum",
        "body oil",
        "massage oil",
        "body serum",
        "magnesium rub",
        "body rub",
        "serum",
        "body wash",
        "bra",
        "shapewear",
        "bodysuit",
    ]

    generic_terms = [
        "serum",
        "body wash",
        "cleanser",
        "moisturizer",
        "moisturiser",
        "lotion",
        "jacket",
        "coat",
        "sweatpants",
        "clogs",
        "dress",
        "hoodie",
        "leggings",
        "shorts",
    ]

    score = 35.0
    signals = []
    matched_terms = []

    relationship_product = find_matches(
        relationship_terms,
        product_text,
    )

    personalization_product = find_matches(
        personalization_terms,
        product_text,
    )

    child_caregiving_product = find_matches(
        child_caregiving_terms,
        product_text,
    )

    child_need_product = find_matches(
        child_need_terms,
        product_text,
    )

    adult_recovery_product = find_matches(
        adult_recovery_terms,
        product_text,
    )

    problem_product = find_matches(
        specific_problem_terms,
        product_text,
    )

    transformation_product = find_matches(
        transformation_terms,
        product_text,
    )

    demonstration_product = find_matches(
        demonstration_terms,
        product_text,
    )

    identity_product = find_matches(
        identity_terms,
        product_text,
    )

    sensual_product = find_matches(
        sensual_product_terms,
        product_text,
    )

    # --------------------------------------------------
    # MAJOR CONCEPT ANCHORS
    # --------------------------------------------------
    # These are the only signals that can naturally push a product into
    # the 85–100 range.
    # --------------------------------------------------

    relationship_caption_count = (
        caption_count(
            relationship_terms
        )
    )

    personalization_caption_count = (
        caption_count(
            personalization_terms
        )
    )

    child_caregiving_caption_count = (
        caption_cooccurrence_count(
            child_caregiving_terms,
            child_need_terms,
        )
    )

    major_anchor = False
    strong_anchor = False

    if relationship_product:
        score += 35.0
        major_anchor = True
        strong_anchor = True
        signals.append(
            "Relationship / Intimacy"
        )
        matched_terms.extend(
            relationship_product[
                :3
            ]
        )

    elif relationship_caption_count >= 2:
        score += 26.0
        major_anchor = True
        signals.append(
            "Relationship / Intimacy"
        )

    if personalization_product:
        score += 35.0
        major_anchor = True
        strong_anchor = True
        signals.append(
            "Personalized / Giftable"
        )
        matched_terms.extend(
            personalization_product[
                :3
            ]
        )

    elif personalization_caption_count >= 2:
        score += 26.0
        major_anchor = True
        signals.append(
            "Personalized / Giftable"
        )

    child_caregiving_is_specific = bool(
        child_caregiving_product
        and child_need_product
    )

    if child_caregiving_is_specific:
        score += 30.0
        major_anchor = True
        strong_anchor = True
        signals.append(
            "Parent / Child Specific Need"
        )
        matched_terms.extend(
            (
                child_caregiving_product[
                    :2
                ]
                + child_need_product[
                    :2
                ]
            )
        )

    elif child_caregiving_caption_count >= 2:
        score += 22.0
        major_anchor = True
        signals.append(
            "Parent / Child Specific Need"
        )

    # Adult postpartum/maternity/recovery is a useful functional angle,
    # but deliberately NOT a major anchor. It therefore remains subject
    # to the stricter no-major-anchor score caps below.
    if adult_recovery_product:
        score += 10.0
        signals.append(
            "Adult Recovery / Maternity"
        )
        matched_terms.extend(
            adult_recovery_product[
                :3
            ]
        )

    # Body/massage oils are naturally capable of intimacy positioning,
    # but do not get a top score unless the product/captions actually
    # support a relationship/intimacy angle.
    if sensual_product:
        score += 10.0
        matched_terms.extend(
            sensual_product[
                :2
            ]
        )

        if relationship_caption_count >= 2:
            score += 8.0
            major_anchor = True

    # --------------------------------------------------
    # FUNCTIONAL CREATIVE SIGNALS
    # --------------------------------------------------

    functional_signal_count = 0

    if problem_product:
        score += 15.0
        functional_signal_count += 1
        signals.append(
            "Specific Pain Point / Use Case"
        )
        matched_terms.extend(
            problem_product[
                :3
            ]
        )

    elif caption_count(
        specific_problem_terms
    ) >= 2:
        score += 8.0
        functional_signal_count += 1
        signals.append(
            "Specific Pain Point / Use Case"
        )

    if transformation_product:
        score += 14.0
        functional_signal_count += 1
        signals.append(
            "Transformation / Outcome"
        )
        matched_terms.extend(
            transformation_product[
                :3
            ]
        )

    elif caption_count(
        transformation_terms
    ) >= 2:
        score += 7.0
        functional_signal_count += 1
        signals.append(
            "Transformation / Outcome"
        )

    if demonstration_product:
        score += 10.0
        functional_signal_count += 1
        signals.append(
            "Demonstration / Mechanism"
        )
        matched_terms.extend(
            demonstration_product[
                :3
            ]
        )

    elif caption_count(
        demonstration_terms
    ) >= 2:
        score += 5.0
        functional_signal_count += 1
        signals.append(
            "Demonstration / Mechanism"
        )

    if identity_product:
        score += 5.0
        signals.append(
            "Identity / Occasion"
        )
        matched_terms.extend(
            identity_product[
                :2
            ]
        )

    story_matches = find_matches(
        story_friendly_terms,
        product_text,
    )

    if story_matches:
        score += 4.0
        matched_terms.extend(
            story_matches[
                :2
            ]
        )

    # --------------------------------------------------
    # CAPTION VALIDATION
    # --------------------------------------------------
    # Repeated creator language can validate an existing angle, but it
    # cannot manufacture a 90+ score from one stray keyword.
    # --------------------------------------------------

    validation_terms = (
        relationship_terms
        + personalization_terms
        + child_caregiving_terms
        + child_need_terms
        + adult_recovery_terms
        + specific_problem_terms
        + transformation_terms
        + demonstration_terms
    )

    caption_angle_hits = sum(
        1
        for caption in caption_texts
        if any(
            term in caption
            for term in validation_terms
        )
    )

    if caption_angle_hits >= 5:
        score += 5.0

    elif caption_angle_hits >= 3:
        score += 3.0

    # --------------------------------------------------
    # GENERIC-PRODUCT PENALTY + STRICT CAPS
    # --------------------------------------------------

    generic_matches = find_matches(
        generic_terms,
        product_text,
    )

    if (
        generic_matches
        and not major_anchor
    ):
        score -= 10.0

    # Without a major built-in premise, functional benefits alone should
    # not produce a near-perfect Marketing Concept Fit.
    if not major_anchor:
        if functional_signal_count <= 0:
            score = min(
                score,
                55.0,
            )

        elif functional_signal_count == 1:
            score = min(
                score,
                65.0,
            )

        elif functional_signal_count == 2:
            score = min(
                score,
                72.0,
            )

        else:
            score = min(
                score,
                78.0,
            )

    # Caption-derived major anchors are useful but still less certain than
    # a premise that is inherent in the product itself.
    elif (
        major_anchor
        and not strong_anchor
    ):
        score = min(
            score,
            90.0,
        )

    score = max(
        20.0,
        min(
            100.0,
            score,
        ),
    )

    signal_priority = [
        "Relationship / Intimacy",
        "Personalized / Giftable",
        "Parent / Child Specific Need",
        "Adult Recovery / Maternity",
        "Specific Pain Point / Use Case",
        "Transformation / Outcome",
        "Demonstration / Mechanism",
        "Identity / Occasion",
    ]

    ordered_signals = [
        label
        for label in signal_priority
        if label in signals
    ]

    if (
        "Relationship / Intimacy"
        in ordered_signals
    ):
        profile = (
            "Relationship / Intimacy Hook"
        )

    elif (
        "Personalized / Giftable"
        in ordered_signals
    ):
        profile = (
            "Personalized / Gift Hook"
        )

    elif (
        "Parent / Child Specific Need"
        in ordered_signals
    ):
        profile = (
            "Parent / Child Specific Need"
        )

    elif (
        "Adult Recovery / Maternity"
        in ordered_signals
    ):
        profile = (
            "Adult Recovery / Maternity"
        )

    elif (
        "Specific Pain Point / Use Case"
        in ordered_signals
        and "Transformation / Outcome"
        in ordered_signals
    ):
        profile = (
            "Problem → Transformation"
        )

    elif (
        "Specific Pain Point / Use Case"
        in ordered_signals
    ):
        profile = (
            "Specific Problem / Use Case"
        )

    elif (
        "Transformation / Outcome"
        in ordered_signals
    ):
        profile = (
            "Transformation-Led"
        )

    elif (
        "Demonstration / Mechanism"
        in ordered_signals
    ):
        profile = (
            "Demo / Mechanism-Led"
        )

    else:
        profile = (
            "Generic / Angle Needed"
        )

    if ordered_signals:
        reason = (
            "Built-in creative signals: "
            + ", ".join(
                ordered_signals[
                    :3
                ]
            )
            + "."
        )

    else:
        reason = (
            "No unusually strong built-in relationship, personalization, "
            "caregiving, problem, transformation, or demonstration premise "
            "was found."
        )

    if (
        caption_angle_hits >= 3
    ):
        reason += (
            f" Repeated sampled-caption evidence supports an angle in "
            f"{caption_angle_hits} video(s)."
        )

    if (
        not major_anchor
        and functional_signal_count >= 1
    ):
        reason += (
            " Functional benefits help, but v2 caps products without a "
            "major built-in premise so generic benefit stacking cannot "
            "create a 90–100 Concept Fit."
        )

    unique_terms = []

    for term in matched_terms:
        if (
            term
            and term
            not in unique_terms
        ):
            unique_terms.append(
                term
            )

    return {
        "score":
            round(
                score,
                1,
            ),

        "profile":
            profile,

        "reason":
            reason,

        "signals":
            ordered_signals,

        "matched_terms":
            ", ".join(
                unique_terms[
                    :6
                ]
            ),

        "caption_angle_hits":
            caption_angle_hits,
    }


def estimate_ad_saturation_risk(
    product,
):
    """
    Local Ad Saturation Risk v1.

    IMPORTANT: this is a heuristic proxy only. It does NOT query Meta Ad
    Library and does not claim to know the real current ad count.

    Higher score = more likely to be a crowded/commodity ad market.
    Lower score = more likely to have creative white space.

    The purpose is to stop extremely crowded product archetypes from
    winning purely because their TikTok metrics are strong.
    """
    title = str(
        product.get(
            "name",
            "",
        )
        or ""
    ).lower()

    category = str(
        product.get(
            "category",
            "",
        )
        or ""
    ).lower()

    haystack = (
        title
        + " "
        + category
    )

    def matched(
        terms,
    ):
        return [
            term
            for term in terms
            if term in haystack
        ]

    # Start from a neutral-medium risk.
    risk = 45.0
    reasons = []
    matched_terms = []

    # --------------------------------------------------
    # VERY HIGH SATURATION ARCHETYPES
    # --------------------------------------------------

    shapewear_terms = [
        "shapewear",
        "faja",
        "fajas",
        "waist trainer",
        "waist trimmer",
        "tummy control",
        "body shaper",
        "full body shaper",
        "butt lifter",
        "scrunch butt",
        "compression bodysuit",
        "shaping bodysuit",
    ]

    shapewear_hits = matched(
        shapewear_terms
    )

    if shapewear_hits:
        risk = max(
            risk,
            94.0,
        )

        reasons.append(
            "Very crowded shapewear/faja archetype"
        )

        matched_terms.extend(
            shapewear_hits[
                :4
            ]
        )

    # --------------------------------------------------
    # HIGH SATURATION ARCHETYPES
    # --------------------------------------------------

    bra_terms = [
        "push up bra",
        "push-up bra",
        "strapless bra",
        "wireless bra",
        "seamless bra",
        "front closure bra",
        "padded bra",
    ]

    bra_hits = matched(
        bra_terms
    )

    if bra_hits:
        risk = max(
            risk,
            72.0,
        )

        reasons.append(
            "Crowded generic bra/apparel archetype"
        )

        matched_terms.extend(
            bra_hits[
                :3
            ]
        )

    commodity_apparel_terms = [
        "leggings",
        "sweatpants",
        "hoodie",
        "jacket",
        "coat",
        "clogs",
        "wide-leg pants",
        "wide leg pants",
        "matching set",
    ]

    apparel_hits = matched(
        commodity_apparel_terms
    )

    if apparel_hits:
        risk = max(
            risk,
            74.0,
        )

        reasons.append(
            "Crowded commodity apparel archetype"
        )

        matched_terms.extend(
            apparel_hits[
                :3
            ]
        )

    # --------------------------------------------------
    # MODERATE-HIGH SATURATION ARCHETYPES
    # --------------------------------------------------

    generic_beauty_terms = [
        "body wash",
        "cleanser",
        "moisturizer",
        "moisturiser",
        "tinted serum",
        "face serum",
        "facial serum",
        "brightening serum",
        "exfoliating body wash",
        "lip gloss",
        "lip oil",
    ]

    beauty_hits = matched(
        generic_beauty_terms
    )

    if beauty_hits:
        risk = max(
            risk,
            60.0,
        )

        reasons.append(
            "Competitive generic beauty/personal-care archetype"
        )

        matched_terms.extend(
            beauty_hits[
                :3
            ]
        )

    hair_terms = [
        "hair serum",
        "hair oil",
        "scalp serum",
        "hair growth",
        "hair repair",
    ]

    hair_hits = matched(
        hair_terms
    )

    if hair_hits:
        risk = max(
            risk,
            55.0,
        )

        reasons.append(
            "Competitive hair-care archetype"
        )

        matched_terms.extend(
            hair_hits[
                :3
            ]
        )

    # --------------------------------------------------
    # WHITE-SPACE REDUCERS
    # --------------------------------------------------
    # These do not guarantee low competition. They simply indicate a more
    # differentiated premise than a generic commodity version.

    personalization_terms = [
        "custom",
        "personalized",
        "personalised",
        "custom name",
        "monogram",
        "engraved",
        "custom text",
    ]

    relationship_terms = [
        "boyfriend",
        "girlfriend",
        "husband",
        "wife",
        "couples",
        "couple",
        "date night",
        "spicy",
        "intimate",
        "intimacy",
        "easy access",
        "thong",
    ]

    parent_specific_terms = [
        "baby",
        "newborn",
        "toddler",
        "bedtime",
        "sleep rub",
        "magnesium rub",
        "teething",
        "colic",
    ]

    unusual_mechanism_terms = [
        "color changing",
        "colour changing",
        "custom name",
        "easy access",
        "open design",
        "before and after",
    ]

    personalization_hits = matched(
        personalization_terms
    )

    if personalization_hits:
        risk -= 28.0
        reasons.append(
            "Personalization creates differentiation"
        )
        matched_terms.extend(
            personalization_hits[
                :3
            ]
        )

    relationship_hits = matched(
        relationship_terms
    )

    if relationship_hits:
        risk -= 18.0
        reasons.append(
            "Relationship/intimacy angle creates differentiation"
        )
        matched_terms.extend(
            relationship_hits[
                :3
            ]
        )

    parent_hits = matched(
        parent_specific_terms
    )

    if (
        len(
            parent_hits
        ) >= 2
    ):
        risk -= 18.0
        reasons.append(
            "Specific parent/child use case creates differentiation"
        )
        matched_terms.extend(
            parent_hits[
                :3
            ]
        )

    mechanism_hits = matched(
        unusual_mechanism_terms
    )

    if mechanism_hits:
        risk -= 12.0
        reasons.append(
            "Distinctive mechanism/use case creates differentiation"
        )
        matched_terms.extend(
            mechanism_hits[
                :3
            ]
        )

    risk = max(
        10.0,
        min(
            100.0,
            risk,
        ),
    )

    if risk >= 85:
        level = (
            "🚫 Very High"
        )

    elif risk >= 70:
        level = (
            "⚠️ High"
        )

    elif risk >= 50:
        level = (
            "🟠 Moderate"
        )

    elif risk >= 30:
        level = (
            "🟡 Low-Moderate"
        )

    else:
        level = (
            "🌱 Lower / More White Space"
        )

    white_space_score = (
        100.0
        - risk
    )

    unique_terms = []

    for term in matched_terms:
        if (
            term
            and term
            not in unique_terms
        ):
            unique_terms.append(
                term
            )

    if reasons:
        reason = (
            "; ".join(
                reasons
            )
            + "."
        )

    else:
        reason = (
            "No strong local saturation or white-space signal was found. "
            "This remains a heuristic until Meta Ad Library validation is added."
        )

    return {
        "risk":
            round(
                risk,
                1,
            ),

        "white_space_score":
            round(
                white_space_score,
                1,
            ),

        "level":
            level,

        "reason":
            reason,

        "matched_terms":
            ", ".join(
                unique_terms[
                    :6
                ]
            ),
    }


def evaluate_runability_gate(
    row,
    market_score,
):
    """
    Decide whether a fully analyzed product is strong enough to enter the
    serious Top Opportunities section.

    This is a gate, not a deletion rule: failed products stay visible in
    the full ranking so the user can inspect why they failed.
    """
    failures = []

    concept_fit = safe_float(
        row.get(
            "concept_fit_score",
            0,
        )
    )

    saturation_risk = safe_float(
        row.get(
            "ad_saturation_risk",
            100,
        )
    )

    talking_sales_share = safe_float(
        row.get(
            "talking_sales_share",
            0,
        )
    )

    strong_videos = safe_int(
        row.get(
            "strong_videos",
            0,
        )
    )

    if not row.get(
        "product_fit_eligible",
        False,
    ):
        failures.append(
            "Product Fit excluded"
        )

    if (
        concept_fit
        < RUNABILITY_MIN_CONCEPT_FIT
    ):
        failures.append(
            (
                "Weak Marketing Premise "
                f"({concept_fit:.0f} < {RUNABILITY_MIN_CONCEPT_FIT:.0f})"
            )
        )

    if (
        saturation_risk
        > RUNABILITY_MAX_AD_SATURATION
    ):
        failures.append(
            (
                "Saturated Market "
                f"({saturation_risk:.0f} > {RUNABILITY_MAX_AD_SATURATION:.0f})"
            )
        )

    if (
        market_score
        < RUNABILITY_MIN_MARKET_OPPORTUNITY
    ):
        failures.append(
            (
                "Insufficient Market Proof "
                f"({market_score:.0f} < {RUNABILITY_MIN_MARKET_OPPORTUNITY:.0f})"
            )
        )

    if (
        talking_sales_share
        < RUNABILITY_MIN_TALKING_SALES_SHARE
    ):
        failures.append(
            (
                "Weak Talking-Sales Proof "
                f"({talking_sales_share:.0f}% < "
                f"{RUNABILITY_MIN_TALKING_SALES_SHARE:.0f}%)"
            )
        )

    if (
        strong_videos
        < RUNABILITY_MIN_STRONG_VIDEOS
    ):
        failures.append(
            (
                "No Strong-Video Proof "
                f"({strong_videos} < {RUNABILITY_MIN_STRONG_VIDEOS})"
            )
        )

    passed = (
        len(
            failures
        )
        == 0
    )

    if passed:
        status = (
            "✅ Launch Candidate"
        )

    else:
        status = (
            "🚫 Fails Runability Gate"
        )

    return {
        "passed":
            passed,

        "status":
            status,

        "failures":
            failures,

        "reason":
            (
                "Passes all Runability Gate minimums."
                if passed
                else "; ".join(
                    failures
                )
            ),
    }


def pre_content_opportunity_score(
    product,
):
    """
    Keep market proof dominant before we have content, while allowing
    obvious built-in concepts to move products up the scan queue.
    """
    concept = (
        classify_marketing_concept(
            product
        )
    )

    saturation = (
        estimate_ad_saturation_risk(
            product
        )
    )

    return (
        (
            max(
                0.0,
                min(
                    100.0,
                    safe_float(
                        product.get(
                            "score",
                            0,
                        )
                    ),
                ),
            )
            * 0.65
        )
        + (
            concept[
                "score"
            ]
            * 0.25
        )
        + (
            saturation[
                "white_space_score"
            ]
            * 0.10
        )
    )


# ==================================================
# SHORTLIST RANKING
# ==================================================

def shortlist_sort_key(product):
    concept = (
        classify_marketing_concept(
            product
        )
    )

    saturation = (
        estimate_ad_saturation_risk(
            product
        )
    )

    return (
        pre_content_opportunity_score(
            product
        ),
        saturation[
            "white_space_score"
        ],
        concept[
            "score"
        ],
        safe_float(
            product.get(
                "growth",
                0,
            )
        ),
        safe_float(
            product.get(
                "sales_per_promo",
                0,
            )
        ),
        safe_int(
            product.get(
                "seven_day_sales",
                0,
            )
        ),
    )


def build_shortlist(products, shortlist_size):
    eligible_products = [
        product
        for product in products
        if classify_product_fit(
            product
        )[
            "eligible"
        ]
    ]

    return sorted(
        eligible_products,
        key=shortlist_sort_key,
        reverse=True,
    )[:shortlist_size]


# ==================================================
# FASTMOSS DISCOVERY PAGE CACHE
# ==================================================

def fastmoss_discovery_cache_key(
    payload,
):
    stable_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    return hashlib.sha256(
        stable_payload.encode(
            "utf-8"
        )
    ).hexdigest()


def save_fastmoss_discovery_page_cache(
    payload,
    products,
    total_results,
):
    page_number = safe_int(
        payload.get(
            "page",
            1,
        ),
        1,
    )

    cache_key = (
        fastmoss_discovery_cache_key(
            payload
        )
    )

    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO fastmoss_discovery_page_cache (
            cache_key,
            page_number,
            payload_json,
            products_json,
            total_results,
            cached_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            page_number,
            json.dumps(
                payload
            ),
            json.dumps(
                products
            ),
            safe_int(
                total_results,
                0,
            ),
            datetime.now().isoformat(
                timespec="seconds"
            ),
        ),
    )

    conn.commit()
    conn.close()


def load_fastmoss_discovery_page_cache(
    payload,
    max_age_hours=FASTMOSS_DISCOVERY_CACHE_HOURS,
):
    cache_key = (
        fastmoss_discovery_cache_key(
            payload
        )
    )

    conn = sqlite3.connect(
        DB_NAME
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            products_json,
            total_results,
            cached_at
        FROM fastmoss_discovery_page_cache
        WHERE cache_key = ?
        LIMIT 1
        """,
        (
            cache_key,
        ),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    products_json, total_results, cached_at = row

    try:
        cached_dt = datetime.fromisoformat(
            cached_at
        )

    except Exception:
        return None

    age = (
        datetime.now()
        - cached_dt
    )

    if age > timedelta(
        hours=max_age_hours
    ):
        return None

    try:
        products = json.loads(
            products_json
        )

    except Exception:
        return None

    if not isinstance(
        products,
        list,
    ):
        return None

    return {
        "products":
            products,

        "total":
            safe_int(
                total_results,
                0,
            ),

        "cached_at":
            cached_at,

        "age_hours":
            round(
                age.total_seconds()
                / 3600.0,
                1,
            ),
    }


def count_missing_fastmoss_discovery_pages(
    settings,
):
    discovery_pages = (
        build_fastmoss_discovery_requests(
            settings
        )
    )

    cached_pages = []
    missing_pages = []

    for (
        bucket_name,
        payload,
    ) in discovery_pages:
        cached = (
            load_fastmoss_discovery_page_cache(
                payload
            )
        )

        page_number = safe_int(
            payload.get(
                "page",
                1,
            ),
            1,
        )

        if cached:
            cached_pages.append(
                {
                    "page":
                        page_number,

                    "cached_at":
                        cached[
                            "cached_at"
                        ],

                    "products":
                        len(
                            cached[
                                "products"
                            ]
                        ),
                }
            )

        else:
            missing_pages.append(
                page_number
            )

    return (
        cached_pages,
        missing_pages,
    )


# ==================================================
# FASTMOSS STAGE 1 DISCOVERY
# ==================================================

def parse_fastmoss_percent(
    value,
):
    text_value = str(
        value
        or ""
    ).strip().replace(
        "%",
        "",
    )

    return safe_float(
        text_value,
        0.0,
    )


def fastmoss_ctime_to_yyyymmdd(
    value,
):
    text_value = str(
        value
        or ""
    ).strip()

    if not text_value:
        return ""

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(
                text_value[
                    :19
                ],
                fmt,
            )

            return parsed.strftime(
                "%Y%m%d"
            )

        except Exception:
            continue

    try:
        timestamp = int(
            float(
                text_value
            )
        )

        return datetime.fromtimestamp(
            timestamp
        ).strftime(
            "%Y%m%d"
        )

    except Exception:
        return ""


def fastmoss_category_text(
    raw,
):
    category = raw.get(
        "category",
        {},
    )

    if not isinstance(
        category,
        dict,
    ):
        return str(
            category
            or ""
        )

    names = []

    for level in [
        "l1",
        "l2",
        "l3",
    ]:
        item = category.get(
            level,
            {},
        )

        if isinstance(
            item,
            dict,
        ):
            name = str(
                item.get(
                    "name",
                    "",
                )
                or ""
            ).strip()

            if (
                name
                and name not in names
            ):
                names.append(
                    name
                )

    return " > ".join(
        names
    )


def adapt_fastmoss_raw_for_flipradar(
    raw,
):
    """
    Convert FastMoss Product Search data into the mature normalized product
    shape FlipRadar already understands.

    FastMoss Product Search does not expose EchoTik's 7-day video/live promo
    count. For the existing FlipScore efficiency slot we use associated
    creator count as a transparent proxy:
        7d sales / associated creators.
    """
    if not isinstance(
        raw,
        dict,
    ):
        raw = {}

    shop = raw.get(
        "shop",
        {},
    )

    if not isinstance(
        shop,
        dict,
    ):
        shop = {}

    creators = safe_int(
        raw.get(
            "creator_count",
            0,
        )
    )

    day7_units = safe_int(
        raw.get(
            "day7_units_sold",
            0,
        )
    )

    day28_units = safe_int(
        raw.get(
            "day28_units_sold",
            0,
        )
    )

    yday_units = safe_int(
        raw.get(
            "yday_sold_count",
            0,
        )
    )

    mapped = {
        "product_id":
            str(
                raw.get(
                    "product_id",
                    "",
                )
                or ""
            ).strip(),

        "product_name":
            raw.get(
                "title",
                "Unknown Product",
            ),

        "spu_avg_price":
            safe_float(
                raw.get(
                    "floor_price",
                    0,
                )
            )
            or safe_float(
                raw.get(
                    "price",
                    0,
                )
            ),

        "total_sale_1d_cnt":
            yday_units,

        "total_sale_7d_cnt":
            day7_units,

        # FastMoss commonly returns 28-day rather than 30-day sales.
        # We preserve it as the longer-window momentum fallback.
        "total_sale_15d_cnt":
            0,

        "total_sale_30d_cnt":
            day28_units,

        "total_sale_cnt":
            safe_int(
                raw.get(
                    "total_units_sold",
                    0,
                )
            ),

        "total_ifl_cnt":
            creators,

        # Transparent FastMoss creator-efficiency proxy used by the existing
        # score slot. This is NOT claimed to be a real 7-day promo count.
        "total_video_7d_cnt":
            creators,

        "total_video_cnt":
            safe_int(
                raw.get(
                    "video_count",
                    0,
                )
            ),

        "total_live_7d_cnt":
            0,

        "total_live_cnt":
            0,

        "first_crawl_dt":
            fastmoss_ctime_to_yyyymmdd(
                raw.get(
                    "ctime",
                    "",
                )
            ),

        "cover_url":
            raw.get(
                "cover",
                "",
            ),

        "seller_name":
            shop.get(
                "name",
                "",
            ),

        "total_sale_gmv_amt":
            safe_float(
                raw.get(
                    "total_gmv",
                    0,
                )
            ),

        "total_sale_gmv_7d_amt":
            safe_float(
                raw.get(
                    "day7_gmv",
                    0,
                )
            ),

        "total_sale_gmv_30d_amt":
            safe_float(
                raw.get(
                    "day28_gmv",
                    0,
                )
            ),

        "product_rating":
            safe_float(
                raw.get(
                    "product_rating",
                    0,
                )
            ),

        "review_count":
            safe_int(
                raw.get(
                    "review_count",
                    0,
                )
            ),

        "product_commission_rate":
            parse_fastmoss_percent(
                raw.get(
                    "commission_rate",
                    0,
                )
            ),

        "_flipradar_discovery_buckets":
            raw.get(
                "_flipradar_discovery_buckets",
                [],
            ),

        "_flipradar_primary_bucket":
            raw.get(
                "_flipradar_primary_bucket",
                "",
            ),
    }

    return mapped


def normalize_fastmoss_discovery_product(
    raw,
):
    mapped = (
        adapt_fastmoss_raw_for_flipradar(
            raw
        )
    )

    product = (
        normalize_echotik_product(
            mapped
        )
    )

    category_text = (
        fastmoss_category_text(
            raw
        )
    )

    creators = safe_int(
        raw.get(
            "creator_count",
            0,
        )
    )

    seven_day_sales = safe_int(
        raw.get(
            "day7_units_sold",
            0,
        )
    )

    product[
        "category"
    ] = category_text

    product[
        "discovery_provider"
    ] = "fastmoss"

    product[
        "region"
    ] = str(
        raw.get(
            "region",
            "US",
        )
        or "US"
    )

    product[
        "creator_order_rate"
    ] = parse_fastmoss_percent(
        raw.get(
            "creator_order_rate",
            0,
        )
    )

    product[
        "commission_rate"
    ] = parse_fastmoss_percent(
        raw.get(
            "commission_rate",
            0,
        )
    )

    product[
        "sales_per_creator"
    ] = round(
        (
            seven_day_sales
            / creators
        )
        if creators > 0
        else 0.0,
        2,
    )

    product[
        "efficiency_basis"
    ] = (
        "FastMoss 7d sales / associated creator"
    )

    product[
        "fastmoss_url"
    ] = str(
        raw.get(
            "fastmoss_url",
            "",
        )
        or ""
    )

    product[
        "url"
    ] = str(
        raw.get(
            "tiktok_url",
            "",
        )
        or product.get(
            "url",
            "",
        )
        or ""
    )

    # Product Search provides total associated video count, not a clean
    # 7-day promo count. Keep the real total separately for display.
    product[
        "associated_video_count"
    ] = safe_int(
        raw.get(
            "video_count",
            0,
        )
    )

    return product


def build_fastmoss_discovery_requests(
    settings,
):
    """
    Reliable FastMoss discovery v2.

    Use the same broad, documented Product Search shape that already worked
    in FlipRadar's FastMoss diagnostic, then paginate it across three pages.

    Provider-side filters:
    - US
    - on-sale products
    - user's max price
    - user's minimum 7-day sales

    Everything else — product age, momentum, creator saturation, Product Fit,
    Marketing Concept Fit, local Ad Saturation and Runability — is applied
    locally after retrieval.

    This deliberately avoids putting launch_time_range or creator filters into
    every provider request. Those are useful later, but they should not be
    capable of making the entire candidate universe disappear.
    """
    min_sales = max(
        0,
        safe_int(
            settings.get(
                "min_7d_sales",
                500,
            )
        ),
    )

    max_price = max(
        1.0,
        safe_float(
            settings.get(
                "max_price",
                100,
            )
        ),
    )

    base_payload = {
        "filter":
            {
                "region":
                    "US",

                "off_shelves":
                    0,

                "price_range":
                    {
                        "min":
                            1,

                        "max":
                            max_price,
                    },

                "day7_units_sold_range":
                    {
                        "min":
                            min_sales,
                    },
            },

        "orderby":
            [
                {
                    "field":
                        "day7_units_sold",

                    "order":
                        "desc",
                }
            ],

        "pagesize":
            FASTMOSS_DISCOVERY_PAGE_SIZE,
    }

    requests_to_make = []

    for page_number in range(
        1,
        FASTMOSS_DISCOVERY_REQUESTS + 1,
    ):
        payload = {
            "filter":
                dict(
                    base_payload[
                        "filter"
                    ]
                ),

            "orderby":
                list(
                    base_payload[
                        "orderby"
                    ]
                ),

            "page":
                page_number,

            "pagesize":
                FASTMOSS_DISCOVERY_PAGE_SIZE,
        }

        requests_to_make.append(
            (
                f"7D Sales Page {page_number}",
                payload,
            )
        )

    return requests_to_make


def build_fastmoss_test_payload(
    settings,
):
    """
    One-request no-save diagnostic using the exact same provider-side
    filters as the real pool build.
    """
    return build_fastmoss_discovery_requests(
        settings
    )[0][1]


def request_fastmoss_discovery_products(
    payload,
    bucket_name,
):
    if not FASTMOSS_API_KEY:
        raise RuntimeError(
            "FASTMOSS_API_KEY was not found in .env."
        )

    headers = {
        "Content-Type":
            "application/json",

        "Authorization":
            f"Bearer {FASTMOSS_API_KEY}",
    }

    response = requests.post(
        FASTMOSS_PRODUCT_SEARCH_URL,
        headers=headers,
        json=payload,
        timeout=40,
    )

    if response.status_code == 401:
        raise RuntimeError(
            "FastMoss authentication failed."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "FastMoss denied access to Product Search."
        )

    if response.status_code == 429:
        raise RuntimeError(
            "FastMoss rate limit reached."
        )

    if response.status_code != 200:
        body_text = (
            response.text[
                :1000
            ]
            if response.text
            else "No response body."
        )

        raise RuntimeError(
            f"FastMoss Product Search failed for {bucket_name}. "
            f"HTTP {response.status_code}. Response: {body_text}"
        )

    try:
        body = response.json()

    except ValueError as exc:
        raise RuntimeError(
            "FastMoss Product Search returned non-JSON data."
        ) from exc

    if body.get(
        "code"
    ) not in {
        0,
        "0",
        None,
    }:
        raise RuntimeError(
            "FastMoss API error for "
            f"{bucket_name}: "
            + str(
                body.get(
                    "message",
                    body.get(
                        "msg",
                        body,
                    ),
                )
            )
        )

    data = body.get(
        "data",
        {},
    )

    if not isinstance(
        data,
        dict,
    ):
        return []

    products = data.get(
        "list",
        [],
    )

    if not isinstance(
        products,
        list,
    ):
        products = []

    total_results = safe_int(
        data.get(
            "total",
            0,
        )
    )

    # Save every successful discovery page immediately. This means a later
    # quota error cannot destroy provider calls that already succeeded.
    save_fastmoss_discovery_page_cache(
        payload=payload,
        products=products,
        total_results=total_results,
    )

    return {
        "products":
            products,

        "total":
            total_results,

        "cached":
            False,

        "cached_at":
            "",
    }


# ==================================================
# COLLECT QUALIFIED PRODUCTS
# ==================================================

def collect_candidate_pool(
    settings,
    progress_bar,
    status_box,
):
    discovery_pages = (
        build_fastmoss_discovery_requests(
            settings
        )
    )

    raw_by_id = {}
    request_count = 0
    cache_pages_used = 0
    raw_slot_count = 0
    pages_used = 0

    target_pool_size = int(
        settings[
            "pool_target"
        ]
    )

    quota_hit = False

    for (
        bucket_name,
        payload,
    ) in discovery_pages:
        page_number = safe_int(
            payload.get(
                "page",
                1,
            ),
            1,
        )

        cached = (
            load_fastmoss_discovery_page_cache(
                payload
            )
        )

        if cached:
            result = {
                "products":
                    cached[
                        "products"
                    ],

                "total":
                    cached[
                        "total"
                    ],

                "cached":
                    True,

                "cached_at":
                    cached[
                        "cached_at"
                    ],
            }

            cache_pages_used += 1

            status_box.write(
                f"Using cached FastMoss page {page_number} "
                f"({len(cached['products'])} products, "
                f"cached {cached['age_hours']:.1f}h ago) — "
                "**0 provider requests**."
            )

        else:
            status_box.write(
                f"Requesting missing FastMoss page {page_number}/"
                f"{FASTMOSS_DISCOVERY_REQUESTS}..."
            )

            try:
                result = (
                    request_fastmoss_discovery_products(
                        payload=payload,
                        bucket_name=bucket_name,
                    )
                )

                request_count += 1

            except Exception as exc:
                error_text = str(
                    exc
                ).lower()

                quota_hit = (
                    "quota"
                    in error_text
                    or "limit"
                    in error_text
                )

                if quota_hit:
                    if raw_by_id:
                        status_box.warning(
                            "FastMoss quota was reached, but FlipRadar is "
                            "keeping every cached/successful page collected "
                            "so far and will build the best partial pool it can."
                        )

                        break

                    raise RuntimeError(
                        "FastMoss request quota is currently exhausted and "
                        "there are no cached discovery pages yet. No pool was "
                        "changed. Once FastMoss allows requests again, the "
                        "first successful page will be cached automatically "
                        "and future retries will resume from the next missing "
                        "page."
                    ) from exc

                raise

        bucket_products = result[
            "products"
        ]

        pages_used += 1
        raw_slot_count += len(
            bucket_products
        )

        if pages_used == 1:
            status_box.write(
                f"FastMoss reports about {result['total']:,} matching "
                "products before local qualification."
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
                or ""
            ).strip()

            if not product_id:
                continue

            raw_by_id[
                product_id
            ] = merge_raw_product(
                raw_by_id.get(
                    product_id
                ),
                raw,
                bucket_name,
            )

        progress_bar.progress(
            min(
                pages_used
                / FASTMOSS_DISCOVERY_REQUESTS,
                1.0,
            )
        )

        # Count local qualifiers after every page. If we already have the
        # requested pool target, stop before spending another provider call.
        qualified_so_far = 0

        for raw in raw_by_id.values():
            product = (
                normalize_fastmoss_discovery_product(
                    raw
                )
            )

            qualifies, _ = (
                qualify_product(
                    product,
                    settings,
                )
            )

            if qualifies:
                qualified_so_far += 1

        status_box.write(
            f"Collected {len(raw_by_id)} unique raw products; "
            f"{qualified_so_far} currently pass Stage 1 local rules."
        )

        if (
            qualified_so_far
            >= target_pool_size
        ):
            status_box.success(
                f"Reached the {target_pool_size}-product qualified target. "
                "Stopping early to avoid unnecessary FastMoss requests."
            )

            break

    if not raw_by_id:
        raise RuntimeError(
            "No usable raw products were available from either FastMoss "
            "or the local discovery-page cache. The previous usable pool "
            "was left unchanged."
        )

    products = []

    rejection_counts = {
        "Too old / invalid age":
            0,

        "Weak 7d sales":
            0,

        "Momentum below minimum":
            0,

        "Price outside range":
            0,

        "Too many associated creators":
            0,
    }

    for raw in raw_by_id.values():
        product = (
            normalize_fastmoss_discovery_product(
                raw
            )
        )

        qualifies, reasons = (
            qualify_product(
                product,
                settings,
            )
        )

        if qualifies:
            products.append(
                product
            )

        else:
            for reason in set(
                reasons
            ):
                rejection_counts[
                    reason
                ] = (
                    rejection_counts.get(
                        reason,
                        0,
                    )
                    + 1
                )

    products = sorted(
        products,
        key=shortlist_sort_key,
        reverse=True,
    )

    if not products:
        raise RuntimeError(
            "Raw products were available, but 0 survived the local "
            "qualification rules. The previous usable pool was left "
            "unchanged. Loosen Stage 1 age/momentum/creator settings."
        )

    if (
        len(
            products
        )
        > target_pool_size
    ):
        products = products[
            :target_pool_size
        ]

    return {
        "products":
            products,

        # Actual successful provider requests made THIS build.
        "request_count":
            request_count,

        "cache_pages_used":
            cache_pages_used,

        "pages_used":
            pages_used,

        "raw_slot_count":
            raw_slot_count,

        "unique_raw_count":
            len(
                raw_by_id
            ),

        "rejection_counts":
            rejection_counts,

        "quota_hit":
            quota_hit,
    }


# ==================================================
# PRODUCT DISPLAY
# ==================================================

def build_product_rows(products):
    rows = []

    for rank, product in enumerate(products, start=1):
        buckets = product.get(
            "discovery_buckets",
            [],
        )

        concept = (
            classify_marketing_concept(
                product
            )
        )

        saturation = (
            estimate_ad_saturation_risk(
                product
            )
        )

        if not isinstance(buckets, list):
            buckets = []

        rows.append(
            {
                "Rank": rank,
                "Product": product.get(
                    "name",
                    "Unknown Product",
                ),
                "FlipScore": round(
                    safe_float(
                        product.get("score", 0)
                    ),
                    1,
                ),
                "Concept Fit": concept[
                    "score"
                ],
                "Concept Profile": concept[
                    "profile"
                ],
                "Ad Saturation Risk": saturation[
                    "risk"
                ],
                "Saturation Level": saturation[
                    "level"
                ],
                "White Space": saturation[
                    "white_space_score"
                ],
                "Pre-Content Score": round(
                    pre_content_opportunity_score(
                        product
                    ),
                    1,
                ),
                "Status": product.get("status", ""),
                "7d Sales": safe_int(
                    product.get("seven_day_sales", 0)
                ),
                "Momentum %": safe_float(
                    product.get("growth", 0)
                ),
                "Sales / Creator": round(
                    (
                        safe_int(
                            product.get(
                                "seven_day_sales",
                                0,
                            )
                        )
                        / safe_int(
                            product.get(
                                "creators",
                                0,
                            )
                        )
                    )
                    if safe_int(
                        product.get(
                            "creators",
                            0,
                        )
                    ) > 0
                    else 0.0,
                    1,
                ),
                "Associated Videos": safe_int(
                    product.get(
                        "associated_video_count",
                        product.get(
                            "video_count_total",
                            0,
                        ),
                    )
                ),
                "Age Days": safe_int(
                    product.get("age_days", 0)
                ),
                "Price": safe_float(
                    product.get("price", 0)
                ),
                "Creators": safe_int(
                    product.get("creators", 0)
                ),
                "Discovery Lane": " + ".join(buckets),
                "Product ID": str(
                    product.get("id", "")
                ),
            }
        )

    return rows


def show_product_table(products):
    if not products:
        st.info("No products to display.")
        return

    df = pd.DataFrame(
        build_product_rows(products)
    )

    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn(
                "Price",
                format="$%.2f",
            ),
            "Momentum %": st.column_config.NumberColumn(
                "Momentum %",
                format="%.1f%%",
            ),
            "FlipScore": st.column_config.NumberColumn(
                "FlipScore",
                format="%.1f",
            ),
            "Concept Fit": st.column_config.NumberColumn(
                "Concept Fit",
                format="%.1f",
            ),
            "Ad Saturation Risk": st.column_config.NumberColumn(
                "Ad Saturation Risk",
                format="%.1f",
            ),
            "White Space": st.column_config.NumberColumn(
                "White Space",
                format="%.1f",
            ),
            "Pre-Content Score": st.column_config.NumberColumn(
                "Pre-Content Score",
                format="%.1f",
            ),
            "Sales / Creator": st.column_config.NumberColumn(
                "Sales / Creator",
                format="%.1f",
            ),
        },
    )


# ==================================================
# CONTENT SCAN HELPERS
# ==================================================

def detect_content_provider(
    videos,
):
    if not videos:
        return ""

    providers = {
        str(
            video.get(
                "data_provider",
                "",
            )
            or ""
        ).strip()
        for video in videos
        if isinstance(
            video,
            dict,
        )
    }

    providers.discard(
        ""
    )

    if "FastMoss" in providers:
        return "FastMoss"

    if providers:
        return " + ".join(
            sorted(
                providers
            )
        )

    # Older cached scans pre-date provider tagging.
    return "Legacy / EchoTik"


def summarize_content(
    videos,
):
    if not videos:
        return {
            "video_count":
                0,

            "views":
                0,

            "sales":
                0,

            "gmv":
                0.0,

            "provider":
                "",
        }

    views = sum(
        safe_int(
            video.get(
                "views",
                0,
            )
        )
        for video in videos
    )

    sales = sum(
        safe_int(
            video.get(
                "video_sales",
                0,
            )
        )
        for video in videos
    )

    gmv = sum(
        safe_float(
            video.get(
                "video_gmv",
                0,
            )
        )
        for video in videos
    )

    return {
        "video_count":
            len(
                videos
            ),

        "views":
            views,

        "sales":
            sales,

        "gmv":
            gmv,

        "provider":
            detect_content_provider(
                videos
            ),
    }


def build_content_status_rows(
    shortlist,
):
    rows = []
    missing_products = []

    for rank, product in enumerate(
        shortlist,
        start=1,
    ):
        product_id = str(
            product.get(
                "id",
                "",
            )
        )

        videos, scanned_at, source = (
            load_content_scan_compat(
                product_id
            )
        )

        summary = summarize_content(
            videos
        )

        cached = bool(
            videos
        )

        if not cached:
            missing_products.append(
                product
            )

        rows.append(
            {
                "Rank":
                    rank,

                "Product":
                    product.get(
                        "name",
                        "Unknown Product",
                    ),

                "Content Status":
                    (
                        "✅ Cached"
                        if cached
                        else "⏳ Needs FastMoss Scan"
                    ),

                "Provider":
                    summary[
                        "provider"
                    ],

                "Videos":
                    summary[
                        "video_count"
                    ],

                "Sample Views":
                    summary[
                        "views"
                    ],

                "Attributed Sales":
                    summary[
                        "sales"
                    ],

                "Attributed GMV":
                    summary[
                        "gmv"
                    ],

                "Scanned At":
                    scanned_at
                    or "",

                "Product ID":
                    product_id,

                "_cache_source":
                    source,
            }
        )

    return (
        rows,
        missing_products,
    )


def show_content_status_table(
    rows,
):
    if not rows:
        return

    df = pd.DataFrame(
        rows
    )

    display_columns = [
        "Rank",
        "Product",
        "Content Status",
        "Provider",
        "Videos",
        "Sample Views",
        "Attributed Sales",
        "Attributed GMV",
        "Scanned At",
        "Product ID",
    ]

    st.dataframe(
        df[
            display_columns
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Attributed GMV":
                st.column_config.NumberColumn(
                    "Attributed GMV",
                    format="$%.0f",
                ),
        },
    )


# ==================================================
# HEADER
# ==================================================

st.title("🔭 Discovery Funnel")

st.caption(
    "Build a targeted product universe, narrow it locally, "
    "then analyze shortlisted product content with FastMoss."
)

st.info(
    "Stage 1 can now build a **fresh FastMoss candidate pool** instead of "
    "depending on the exhausted EchoTik discovery source. One pool build "
    "uses **up to 3 FastMoss Product Search requests**, paginated across "
    "up to 300 raw product slots. Successful discovery pages are cached locally "
    "for 48 hours, so retries only request missing pages. Stage 2 filters/ranks "
    "locally. Stage 3 still "
    "uses **1 additional FastMoss request per uncached shortlisted product** "
    "only if you separately choose to run content scans."
)


# ==================================================
# STAGE 1 — POOL SETTINGS
# ==================================================

st.subheader("1️⃣ Candidate Pool Rules")

st.caption(
    "These are first-pass qualification rules. "
    "The FastMoss search itself is broad; Product Fit, Concept Fit, "
    "Ad Saturation and the Runability Gate do the harder filtering later."
)

c1, c2, c3 = st.columns(
    3
)

with c1:
    pool_target = st.number_input(
        "Qualified pool target",
        min_value=20,
        max_value=200,
        value=DEFAULT_POOL_TARGET,
        step=10,
    )

    shortlist_size = st.number_input(
        "Shortlist size",
        min_value=5,
        max_value=100,
        value=DEFAULT_SHORTLIST_SIZE,
        step=5,
    )

with c2:
    max_age_days = st.number_input(
        "Maximum product age (days)",
        min_value=30,
        max_value=730,
        value=365,
        step=30,
    )

    min_7d_sales = st.number_input(
        "Minimum 7-day sales",
        min_value=0,
        max_value=100000,
        value=500,
        step=100,
    )

with c3:
    min_growth = st.number_input(
        "Minimum momentum (%)",
        min_value=-100.0,
        max_value=1000.0,
        value=0.0,
        step=5.0,
        help=(
            "Uses FastMoss yesterday-vs-prior-6-day momentum when "
            "available, with the longer FastMoss sales window as fallback."
        ),
    )

    max_creator_count = st.number_input(
        "Maximum associated creator count",
        min_value=1,
        max_value=10000,
        value=500,
        step=50,
        help=(
            "FastMoss Product Search exposes associated creator count but "
            "not EchoTik's old 7-day video+live promotion count. This is "
            "the Stage 1 saturation guard for new FastMoss pools."
        ),
    )

max_price = st.number_input(
    "Maximum product price",
    min_value=5.0,
    max_value=500.0,
    value=100.0,
    step=5.0,
)

shortlist_size = min(
    int(
        shortlist_size
    ),
    int(
        pool_target
    ),
)

settings = {
    "discovery_provider":
        "fastmoss",

    "pool_target":
        int(
            pool_target
        ),

    "shortlist_size":
        int(
            shortlist_size
        ),

    # Retained in saved settings for backward compatibility with the
    # existing discovery-run table.
    "max_requests":
        FASTMOSS_DISCOVERY_REQUESTS,

    "max_age_days":
        int(
            max_age_days
        ),

    "min_7d_sales":
        int(
            min_7d_sales
        ),

    "min_growth":
        float(
            min_growth
        ),

    "max_creator_count":
        int(
            max_creator_count
        ),

    "max_price":
        float(
            max_price
        ),
}

cached_discovery_pages, missing_discovery_pages = (
    count_missing_fastmoss_discovery_pages(
        settings
    )
)

max_build_requests = len(
    missing_discovery_pages
)

cached_page_numbers = [
    item[
        "page"
    ]
    for item in cached_discovery_pages
]

if cached_discovery_pages:
    st.success(
        f"Local discovery cache: {len(cached_discovery_pages)} of "
        f"{FASTMOSS_DISCOVERY_REQUESTS} page(s) available "
        f"(pages {', '.join(str(page) for page in cached_page_numbers)}). "
        "Cached pages cost 0 provider requests."
    )

if max_build_requests > 0:
    st.warning(
        f"**Maximum provider cost for the next pool build: "
        f"{max_build_requests} FastMoss Product Search request(s).** "
        f"Only missing pages {', '.join(str(page) for page in missing_discovery_pages)} "
        "will be requested. Every successful page is saved immediately for "
        f"{FASTMOSS_DISCOVERY_CACHE_HOURS} hours. The build can also stop early "
        "if the qualified-pool target is reached. This does **not** run "
        "Product Associated Videos/content scans."
    )

else:
    st.success(
        "**Next pool build costs 0 FastMoss requests.** All three discovery "
        "pages are already cached locally, so FlipRadar can rebuild the pool "
        "entirely from cache."
    )

st.caption(
    "FastMoss is currently returning `request quota limit` on page 1, which "
    "means the provider quota is exhausted before FlipRadar receives any new "
    "data. Do not keep clicking the test/build while that is happening. "
    "With this version, once a future request succeeds it is cached immediately, "
    "so progress survives later quota errors."
)

test_fastmoss_search = st.button(
    "🧪 Test + Cache Page 1 — 1 Request",
    width="stretch",
)

if test_fastmoss_search:
    test_payload = (
        build_fastmoss_test_payload(
            settings
        )
    )

    existing_test_cache = (
        load_fastmoss_discovery_page_cache(
            test_payload
        )
    )

    test_status = st.empty()

    if existing_test_cache:
        test_result = existing_test_cache

        test_status.success(
            f"Page 1 is already cached with "
            f"{len(test_result['products'])} products. "
            "**0 FastMoss requests used.**"
        )

    else:
        try:
            test_status.write(
                "Testing and caching FastMoss page 1..."
            )

            test_result = (
                request_fastmoss_discovery_products(
                    payload=test_payload,
                    bucket_name="Broad Search Test",
                )
            )

            if test_result[
                "products"
            ]:
                test_status.success(
                    f"Test worked: FastMoss reports "
                    f"{test_result['total']:,} matching products and returned "
                    f"{len(test_result['products'])} on page 1. "
                    "Page 1 is now cached locally, so the next full build "
                    "will not pay for page 1 again."
                )

            else:
                test_status.error(
                    "FastMoss accepted the request but returned 0 products."
                )

        except Exception as exc:
            test_status.error(
                f"FastMoss test failed: {exc}"
            )

    test_products = (
        test_result.get(
            "products",
            [],
        )
        if "test_result"
        in locals()
        else []
    )

    if test_products:
        preview_rows = []

        for raw in test_products[
            :10
        ]:
            preview_rows.append(
                {
                    "Product":
                        raw.get(
                            "title",
                            "Unknown Product",
                        ),

                    "7d Sales":
                        safe_int(
                            raw.get(
                                "day7_units_sold",
                                0,
                            )
                        ),

                    "Creators":
                        safe_int(
                            raw.get(
                                "creator_count",
                                0,
                            )
                        ),

                    "Price":
                        safe_float(
                            raw.get(
                                "floor_price",
                                raw.get(
                                    "price",
                                    0,
                                ),
                            )
                        ),

                    "Product ID":
                        str(
                            raw.get(
                                "product_id",
                                "",
                            )
                        ),
                }
            )

        st.dataframe(
            pd.DataFrame(
                preview_rows
            ),
            width="stretch",
            hide_index=True,
        )

build_pool = st.button(
    (
        "🚀 Build / Resume FastMoss Candidate Pool — "
        f"Up to {max_build_requests} Request(s)"
    ),
    type="primary",
    width="stretch",
)

if build_pool:
    progress_bar = st.progress(
        0
    )

    status_box = st.empty()

    try:
        result = (
            collect_candidate_pool(
                settings=settings,
                progress_bar=progress_bar,
                status_box=status_box,
            )
        )

        products = result[
            "products"
        ]

        shortlist = (
            build_shortlist(
                products,
                settings[
                    "shortlist_size"
                ],
            )
        )

        save_discovery_funnel_run(
            request_count=result[
                "request_count"
            ],
            raw_slot_count=result[
                "raw_slot_count"
            ],
            unique_raw_count=result[
                "unique_raw_count"
            ],
            settings=settings,
            rejection_counts=result[
                "rejection_counts"
            ],
            products=products,
            shortlist=shortlist,
        )

        progress_bar.progress(
            1.0
        )

        status_box.success(
            f"FastMoss discovery saved. "
            f"{result['unique_raw_count']} unique raw products → "
            f"{len(products)} qualified products → "
            f"{len(shortlist)} shortlisted. "
            f"Provider requests used this build: {result['request_count']}. "
            f"Cached pages reused: {result['cache_pages_used']}."
        )

        st.rerun()

    except Exception as exc:
        status_box.error(
            f"FastMoss Discovery Funnel failed: {exc}"
        )


# ==================================================
# STAGE 2 — LATEST POOL + SHORTLIST
# ==================================================

latest_run = load_latest_discovery_funnel_run()

st.divider()
st.subheader("2️⃣ Latest Candidate Pool")

if latest_run is None:
    st.info(
        "No Discovery Funnel run has been saved yet."
    )
    st.stop()


saved_shortlist_size = int(
    latest_run[
        "settings"
    ].get(
        "shortlist_size",
        DEFAULT_SHORTLIST_SIZE,
    )
)

effective_shortlist = build_shortlist(
    latest_run[
        "products"
    ],
    saved_shortlist_size,
)

fit_excluded_products = []

for product in latest_run[
    "products"
]:
    fit_result = classify_product_fit(
        product
    )

    if not fit_result[
        "eligible"
    ]:
        fit_excluded_products.append(
            {
                "product":
                    product,

                "fit":
                    fit_result,
            }
        )

m1, m2, m3, m4, m5, m6 = st.columns(6)

latest_discovery_provider = str(
    latest_run[
        "settings"
    ].get(
        "discovery_provider",
        "echotik",
    )
    or "echotik"
).lower()

m1.metric(
    (
        "FastMoss Requests"
        if latest_discovery_provider
        == "fastmoss"
        else "EchoTik Requests"
    ),
    latest_run[
        "request_count"
    ],
)

m2.metric(
    "Raw Product Slots",
    latest_run["raw_slot_count"],
)

m3.metric(
    "Unique Raw Products",
    latest_run["unique_raw_count"],
)

m4.metric(
    "Qualified Pool",
    latest_run["qualified_count"],
)

m5.metric(
    "Product Fit Removed",
    len(
        fit_excluded_products
    ),
)

m6.metric(
    "Fit Shortlist",
    len(
        effective_shortlist
    ),
)

st.caption(
    f"Saved: {latest_run['created_at']} • "
    f"Run ID: {latest_run['run_id']}"
)

saved_target = latest_run["settings"].get(
    "pool_target",
    DEFAULT_POOL_TARGET,
)

if latest_run["qualified_count"] < saved_target:
    st.warning(
        "The discovery batch finished before FlipRadar reached "
        "the full qualified pool target. This can happen because "
        "the discovery lanes overlap or products fail the local filters."
    )

st.subheader("🎯 Product Fit Gate — Before Content Scan")

st.caption(
    "FlipRadar now removes obvious gadgets, novelty/seasonal products, "
    "commodity wallets/key accessories, and utility tools BEFORE choosing "
    "the content-scan shortlist. This uses 0 API requests."
)

if fit_excluded_products:
    with st.expander(
        f"🚫 Product Fit removed {len(fit_excluded_products)} qualified product(s)"
    ):
        for item in fit_excluded_products:
            product = item[
                "product"
            ]

            fit = item[
                "fit"
            ]

            st.write(
                f"**{product.get('name', 'Unknown Product')}** — "
                f"{fit['segment']}. {fit['reason']}"
            )

st.subheader("💡 Marketing Concept Fit v2 — Before Content Scan")

st.caption(
    "Concept Fit estimates whether the product naturally gives you a story "
    "to market: relationship/intimacy, personalization, a specific pain point, "
    "caregiving, transformation, or a clear demonstration. It uses only local "
    "rules here, costs **0 API requests**, and does not hard-exclude products. "
    "The shortlist score below combines market proof, Concept Fit and the "
    "local White Space signal."
)

concept_preview_rows = []

for product in effective_shortlist:
    concept = (
        classify_marketing_concept(
            product
        )
    )

    concept_preview_rows.append(
        {
            "Product":
                product.get(
                    "name",
                    "Unknown Product",
                ),

            "Concept Fit":
                concept[
                    "score"
                ],

            "Concept Profile":
                concept[
                    "profile"
                ],

            "Why":
                concept[
                    "reason"
                ],

            "Matched":
                concept[
                    "matched_terms"
                ],

            "Pre-Content Score":
                round(
                    pre_content_opportunity_score(
                        product
                    ),
                    1,
                ),
        }
    )

if concept_preview_rows:
    with st.expander(
        "View Marketing Concept Fit details",
        expanded=False,
    ):
        st.dataframe(
            pd.DataFrame(
                concept_preview_rows
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Concept Fit":
                    st.column_config.NumberColumn(
                        "Concept Fit",
                        format="%.1f",
                    ),

                "Pre-Content Score":
                    st.column_config.NumberColumn(
                        "Pre-Content Score",
                        format="%.1f",
                    ),
            },
        )

st.subheader("📣 Local Ad Saturation Risk v1")

st.caption(
    "This is a **local heuristic proxy**, not live Meta Ad Library data. "
    "It penalizes archetypes that are commonly crowded/commodity-like "
    "(especially shapewear/fajas) and gives some white-space credit to "
    "personalization, relationship/intimacy, specific parent/child use cases, "
    "and distinctive mechanisms. Higher Saturation Risk is worse. This uses "
    "**0 API requests**."
)

saturation_preview_rows = []

for product in effective_shortlist:
    saturation = (
        estimate_ad_saturation_risk(
            product
        )
    )

    saturation_preview_rows.append(
        {
            "Product":
                product.get(
                    "name",
                    "Unknown Product",
                ),

            "Ad Saturation Risk":
                saturation[
                    "risk"
                ],

            "Level":
                saturation[
                    "level"
                ],

            "White Space":
                saturation[
                    "white_space_score"
                ],

            "Why":
                saturation[
                    "reason"
                ],

            "Matched":
                saturation[
                    "matched_terms"
                ],
        }
    )

if saturation_preview_rows:
    with st.expander(
        "View local Ad Saturation Risk details",
        expanded=False,
    ):
        st.dataframe(
            pd.DataFrame(
                saturation_preview_rows
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Ad Saturation Risk":
                    st.column_config.NumberColumn(
                        "Ad Saturation Risk",
                        format="%.1f",
                    ),

                "White Space":
                    st.column_config.NumberColumn(
                        "White Space",
                        format="%.1f",
                    ),
            },
        )

st.subheader("🏆 Product-Fit Shortlist")

st.caption(
    "Only products that pass Product Fit can enter this shortlist. "
    "Within that eligible set, the Pre-Content Score is now **65% FlipScore "
    "+ 25% Marketing Concept Fit + 10% local White Space**, then momentum, "
    "sales-per-promotion and 7-day sales are tie-breakers."
)

show_product_table(
    effective_shortlist
)

with st.expander(
    "View full qualified candidate pool"
):
    show_product_table(
        latest_run["products"]
    )

st.subheader("🧹 Qualification Rejections")

rejection_rows = [
    {
        "Reason": reason,
        "Rule Hits": count,
    }
    for reason, count
    in latest_run["rejection_counts"].items()
]

if rejection_rows:
    rejection_df = pd.DataFrame(
        rejection_rows
    ).sort_values(
        "Rule Hits",
        ascending=False,
    )

    st.dataframe(
        rejection_df,
        width="stretch",
        hide_index=True,
    )


# ==================================================
# STAGE 3 — CONTENT DEEP SCAN SHORTLIST
# ==================================================

st.divider()
st.subheader("3️⃣ FastMoss Content Scan Shortlist")

st.write(
    "This stage now uses FastMoss instead of EchoTik for new content scans. "
    "Each newly scanned product uses exactly **1 FastMoss request** and "
    "pulls the top associated videos sorted by FastMoss-attributed units sold."
)

st.caption(
    "Existing cached EchoTik/legacy scans are kept and labeled rather than "
    "discarded. FastMoss-attributed sales are provider estimates, so this page "
    "does not calculate Sales / 1K from FastMoss play counts."
)

content_rows, missing_products = (
    build_content_status_rows(
        effective_shortlist
    )
)

cached_count = (
    len(effective_shortlist)
    - len(missing_products)
)

s1, s2, s3 = st.columns(3)

s1.metric(
    "Shortlisted Products",
    len(effective_shortlist),
)

s2.metric(
    "Content Scans Cached",
    cached_count,
)

s3.metric(
    "Need FastMoss Scan",
    len(missing_products),
)

show_content_status_table(
    content_rows
)

if not missing_products:
    st.success(
        "Every shortlisted product already has cached "
        "content data."
    )

else:
    request_cost = (
        len(missing_products)
        * CONTENT_SCAN_REQUESTS_PER_PRODUCT
    )

    st.warning(
        f"**Scan all {len(missing_products)} missing products:** "
        f"this will use exactly **{request_cost} FastMoss request(s)**. "
        "Each product is scanned once. Products that already have cached "
        "content are skipped automatically."
    )

    with st.expander(
        "Products that will be scanned"
    ):
        for index, product in enumerate(
            missing_products,
            start=1,
        ):
            st.write(
                f"{index}. "
                f"{product.get('name', 'Unknown Product')} "
                f"— `{product.get('id', '')}`"
            )

    run_deep_scan = st.button(
        f"🎬 Scan All {len(missing_products)} Missing Products",
        type="primary",
        width="stretch",
    )

    if run_deep_scan:
        selected_products = list(
            missing_products
        )

        progress = st.progress(0)
        status = st.empty()

        successes = 0
        failures = []

        total = len(selected_products)

        for index, product in enumerate(
            selected_products,
            start=1,
        ):
            product_id = str(
                product.get("id", "")
            )

            product_name = product.get(
                "name",
                "Unknown Product",
            )

            status.write(
                f"FastMoss scanning {index}/{total}: "
                f"{product_name}"
            )

            try:
                videos = scan_product_content_fastmoss(
                    product_id=product_id,
                    days=CONTENT_SCAN_DAYS,
                    page_size=CONTENT_SCAN_PAGE_SIZE,
                )

                save_content_scan_compat(
                    product_id,
                    videos,
                )

                successes += 1

            except Exception as exc:
                failures.append(
                    {
                        "product": product_name,
                        "product_id": product_id,
                        "error": str(exc),
                    }
                )

            progress.progress(
                index / total
            )

        if failures:
            status.error(
                f"Finished with {successes} successful scan(s) "
                f"and {len(failures)} failure(s)."
            )

            for failure in failures:
                st.error(
                    f"{failure['product']} "
                    f"({failure['product_id']}): "
                    f"{failure['error']}"
                )

        else:
            status.success(
                f"FastMoss content scan complete for "
                f"all {successes} missing product(s)."
            )

        if successes > 0:
            st.rerun()


# ==================================================
# STAGE 4 — TALKING VS VISUAL
# ==================================================

st.divider()
st.subheader("4️⃣ Talking vs Visual")

st.write(
    "FlipRadar now uses a two-step local detector: WebRTC VAD is only a "
    "cheap pre-filter, and faster-whisper must confirm actual intelligible "
    "speech before a video counts as Talking."
)

st.info(
    "This stage uses **0 FastMoss requests** and **0 EchoTik requests**. "
    "Old VAD-only results are automatically treated as stale and will be "
    "rechecked with Speech/Music v3. Voiceover counts as Talking. Music that "
    "sounds voice-like to VAD should now be rejected when Whisper cannot "
    "confirm enough reliable spoken words."
)

speech_rows, speech_jobs = (
    build_speech_status_rows(
        effective_shortlist
    )
)

cached_content_products = len(
    speech_rows
)

products_needing_speech = len(
    speech_jobs
)

videos_needing_speech = sum(
    len(
        job[
            "videos"
        ]
    )
    for job in speech_jobs
)

speech_complete_products = (
    cached_content_products
    - products_needing_speech
)

t1, t2, t3, t4 = st.columns(
    4
)

t1.metric(
    "Cached-content Products",
    cached_content_products,
)

t2.metric(
    "Speech/Music v3 Complete",
    speech_complete_products,
)

t3.metric(
    "Need Speech/Music Recheck",
    products_needing_speech,
)

t4.metric(
    "Videos to Recheck",
    videos_needing_speech,
)

if speech_rows:
    speech_df = pd.DataFrame(
        speech_rows
    )

    st.dataframe(
        speech_df[
            [
                "Rank",
                "Product",
                "Speech Status",
                "Sampled Videos",
                "Classified",
                "Retry / Unclear",
                "Talking Videos",
                "Visual / Music",
                "Unavailable",
                "Talking Video Share",
                "Sales from Talking Videos",
                "Talking Attributed Sales",
                "Visual Attributed Sales",
                "Last Error",
                "Product ID",
            ]
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Talking Video Share":
                st.column_config.NumberColumn(
                    "Talking Video Share",
                    format="%.1f%%",
                ),

            "Sales from Talking Videos":
                st.column_config.NumberColumn(
                    "Sales from Talking Videos",
                    format="%.1f%%",
                ),
        },
    )

    st.markdown(
        "#### 🎬 Review cached videos"
    )

    st.caption(
        "Open the exact cached video sample for any product below. "
        "This works even when Whisper failed or the product is still pending. "
        "Opening a review uses 0 FastMoss requests and 0 EchoTik requests."
    )

    for row in speech_rows:
        product_id = str(
            row.get(
                "Product ID",
                "",
            )
            or ""
        ).strip()

        product_name = str(
            row.get(
                "Product",
                "Unknown Product",
            )
            or "Unknown Product"
        )

        status_label = str(
            row.get(
                "Speech Status",
                "",
            )
            or ""
        )

        classified_count = safe_int(
            row.get(
                "Classified",
                0,
            )
        )

        retry_count = safe_int(
            row.get(
                "Retry / Unclear",
                0,
            )
        )

        review_col, status_col = st.columns(
            [
                3,
                2,
            ]
        )

        with review_col:
            if st.button(
                f"🎬 {product_name}",
                key=(
                    "stage4_review_cached_"
                    + product_id
                ),
                width="stretch",
            ):
                st.session_state[
                    "video_review_product_id"
                ] = product_id

                st.session_state[
                    "video_review_product_name"
                ] = product_name

                st.switch_page(
                    "pages/8_Product_Videos.py"
                )

        with status_col:
            st.caption(
                f"{status_label} • "
                f"{classified_count} classified • "
                f"{retry_count} retry/unclear"
            )

else:
    st.warning(
        "None of the shortlisted products has cached content yet."
    )


if speech_jobs:
    st.warning(
        f"Clicking the button below will analyze "
        f"**{videos_needing_speech} video(s)** across "
        f"**{products_needing_speech} cached-content product(s)**. "
        "This uses **0 FastMoss requests**. The first run may download "
        f"the local Whisper `{WHISPER_MODEL_SIZE}` model once. "
        "Before touching any queued videos, FlipRadar now runs one "
        "local preflight check for FFmpeg, inaSpeechSegmenter and Whisper. "
        "If setup is broken, it stops immediately instead of waiting through "
        "all queued videos. Only missing, stale, Unclear, or true analysis "
        "failures are retried. TikTok-restricted/unavailable posts are resolved "
        "once, excluded from the Talking/Visual split, and skipped thereafter."
    )

    with st.expander(
        "Products that need Speech/Music v3 recheck"
    ):
        for job in speech_jobs:
            product = job[
                "product"
            ]

            st.write(
                f"#{job['rank']} "
                f"{product.get('name', 'Unknown Product')} "
                f"— {len(job['videos'])} video(s) need retry/recheck"
            )

    run_speech_analysis = st.button(
        "🧪 Preflight + Retry Failed / Missing Videos",
        type="primary",
        width="stretch",
    )

    if run_speech_analysis:
        preflight_status = st.empty()

        with st.spinner(
            "Running one local Speech/Music v3 preflight check..."
        ):
            preflight = (
                run_speech_pipeline_preflight()
            )

        if not preflight[
            "ok"
        ]:
            preflight_status.error(
                "Preflight failed — **0 queued videos were processed**."
            )

            st.error(
                preflight.get(
                    "error",
                    "Local speech setup failed.",
                )
            )

            for check in preflight.get(
                "checks",
                [],
            ):
                icon = (
                    "✅"
                    if check.get(
                        "ok"
                    )
                    else "❌"
                )

                st.write(
                    f"{icon} **{check.get('name', 'Check')}** — "
                    f"{check.get('detail', '')}"
                )

            hint = str(
                preflight.get(
                    "hint",
                    "",
                )
                or ""
            ).strip()

            if hint:
                st.info(
                    hint
                )

            st.caption(
                "No FastMoss requests and no EchoTik requests were used."
            )

        else:
            preflight_status.success(
                "Preflight passed. Starting only the queued videos."
            )

            with st.expander(
                "✅ Local speech preflight passed",
                expanded=False,
            ):
                for check in preflight.get(
                    "checks",
                    [],
                ):
                    st.write(
                        f"✅ **{check.get('name', 'Check')}** — "
                        f"{check.get('detail', '')}"
                    )

            progress = st.progress(
                0
            )

            status = st.empty()

            total_videos = (
                videos_needing_speech
            )

            completed = 0
            unclear_or_failed = 0

            for job in speech_jobs:
                product = job[
                    "product"
                ]

                product_id = str(
                    product.get(
                        "id",
                        "",
                    )
                )

                product_name = (
                    product.get(
                        "name",
                        "Unknown Product",
                    )
                )

                for video in job[
                    "videos"
                ]:
                    video_id = str(
                        video.get(
                            "video_id",
                            "",
                        )
                        or ""
                    ).strip()

                    if not video_id:
                        continue

                    completed += 1

                    status.write(
                        f"Analyzing {completed}/{total_videos}: "
                        f"{product_name} • video `{video_id}`"
                    )

                    video_url = (
                        clean_video_url(
                            video
                        )
                    )

                    result = (
                        analyze_video_speech(
                            video_url=
                                video_url,

                            video_id=
                                video_id,
                        )
                    )

                    if (
                        result.get(
                            "classification"
                        )
                        == "❓ Unclear"
                    ):
                        unclear_or_failed += 1

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
                        completed
                        / total_videos
                    )

            if unclear_or_failed:
                status.warning(
                    "Speech/Music v3 retry finished, but "
                    f"{unclear_or_failed} video(s) are still Unclear/failed. "
                    "Only those failed videos will remain in the retry queue. "
                    "Successful classifications will be skipped next time."
                )

            else:
                status.success(
                    "Speech/Music v3 analysis complete."
                )

            st.rerun()

elif speech_rows:
    st.success(
        "All cached shortlist videos are resolved for Speech/Music v3. "
        "Restricted/unavailable posts are excluded from the Talking/Visual split."
    )


st.caption(
    "**Talking** now requires speech/music-separated, Whisper-confirmed intelligible speech. "
    "**Sales from Talking Videos** uses only attributed sales from videos "
    "classified as Talking or Visual / Music. Unclear and "
    "Unavailable / Restricted videos are excluded."
)


# ==================================================
# STAGE 5 — FINAL OPPORTUNITIES
# ==================================================

def min_max_score(
    value,
    values,
    invert=False,
):
    cleaned = [
        safe_float(
            item,
            0,
        )
        for item in values
    ]

    if not cleaned:
        return 50.0

    low = min(
        cleaned
    )

    high = max(
        cleaned
    )

    current = safe_float(
        value,
        0,
    )

    if high <= low:
        score = 50.0

    else:
        score = (
            (
                current
                - low
            )
            / (
                high
                - low
            )
        ) * 100

    if invert:
        score = (
            100
            - score
        )

    return max(
        0.0,
        min(
            100.0,
            score,
        ),
    )


def product_shop_url(
    product_id,
):
    product_id = str(
        product_id
        or ""
    ).strip()

    if not product_id:
        return ""

    return (
        "https://shop.tiktok.com/view/product/"
        f"{product_id}"
        "?region=US&local=en"
    )


def build_final_opportunity_rows(
    shortlist,
):
    base_rows = []

    for product in shortlist:
        product_id = str(
            product.get(
                "id",
                "",
            )
            or ""
        ).strip()

        videos, scanned_at, cache_source = (
            load_content_scan_compat(
                product_id
            )
        )

        saved_speech = (
            load_speech_results(
                product_id
            )
        )

        speech_summary = (
            summarize_product_speech(
                videos,
                saved_speech,
            )
        )

        sampled_videos = len(
            videos
        )

        total_views = sum(
            safe_int(
                video.get(
                    "views",
                    0,
                )
            )
            for video in videos
        )

        attributed_sales = sum(
            safe_int(
                video.get(
                    "video_sales",
                    0,
                )
            )
            for video in videos
        )

        attributed_gmv = sum(
            safe_float(
                video.get(
                    "video_gmv",
                    0,
                )
            )
            for video in videos
        )

        strong_videos = [
            video
            for video in videos
            if safe_int(
                video.get(
                    "views",
                    0,
                )
            ) >= 100000
        ]

        strong_video_count = len(
            strong_videos
        )

        strong_video_share = (
            (
                strong_video_count
                / sampled_videos
            )
            * 100
            if sampled_videos > 0
            else 0.0
        )

        creator_ids = set()

        for video in videos:
            creator_id = str(
                video.get(
                    "creator_user_id",
                    "",
                )
                or video.get(
                    "creator",
                    "",
                )
                or video.get(
                    "creator_username",
                    "",
                )
                or ""
            ).strip()

            if creator_id:
                creator_ids.add(
                    creator_id
                )

        strong_creator_ids = set()

        for video in strong_videos:
            creator_id = str(
                video.get(
                    "creator_user_id",
                    "",
                )
                or video.get(
                    "creator",
                    "",
                )
                or video.get(
                    "creator_username",
                    "",
                )
                or ""
            ).strip()

            if creator_id:
                strong_creator_ids.add(
                    creator_id
                )

        repeatability_score = min(
            100.0,
            (
                len(
                    strong_creator_ids
                )
                / 3
            )
            * 100,
        )

        provider = detect_content_provider(
            videos
        )

        product_fit = (
            classify_product_fit(
                product
            )
        )

        marketing_concept = (
            classify_marketing_concept(
                product,
                videos=videos,
            )
        )

        ad_saturation = (
            estimate_ad_saturation_risk(
                product
            )
        )

        base_rows.append(
            {
                "product":
                    product,

                "product_id":
                    product_id,

                "product_name":
                    product.get(
                        "name",
                        "Unknown Product",
                    ),

                "cover":
                    str(
                        product.get(
                            "cover",
                            "",
                        )
                        or ""
                    ),

                "shop_url":
                    product_shop_url(
                        product_id
                    ),

                "provider":
                    provider,

                "flipscore":
                    safe_float(
                        product.get(
                            "score",
                            0,
                        )
                    ),

                "momentum":
                    safe_float(
                        product.get(
                            "growth",
                            0,
                        )
                    ),

                "seven_day_sales":
                    safe_int(
                        product.get(
                            "seven_day_sales",
                            0,
                        )
                    ),

                "age_days":
                    safe_int(
                        product.get(
                            "age_days",
                            0,
                        )
                    ),

                "price":
                    safe_float(
                        product.get(
                            "price",
                            0,
                        )
                    ),

                "promotions_7d":
                    safe_int(
                        product.get(
                            "promotion_count_7d",
                            0,
                        )
                    ),

                "sales_per_promo":
                    safe_float(
                        product.get(
                            "sales_per_promo",
                            0,
                        )
                    ),

                "creator_saturation":
                    safe_int(
                        product.get(
                            "creators",
                            0,
                        )
                    ),

                "sampled_videos":
                    sampled_videos,

                "sample_views":
                    total_views,

                "attributed_sales":
                    attributed_sales,

                "attributed_gmv":
                    attributed_gmv,

                "strong_videos":
                    strong_video_count,

                "strong_video_share":
                    strong_video_share,

                "unique_sample_creators":
                    len(
                        creator_ids
                    ),

                "strong_creators":
                    len(
                        strong_creator_ids
                    ),

                "repeatability_score":
                    repeatability_score,

                "talking_video_share":
                    safe_float(
                        speech_summary.get(
                            "talking_video_share",
                            0,
                        )
                    ),

                "talking_sales_share":
                    safe_float(
                        speech_summary.get(
                            "talking_sales_share",
                            0,
                        )
                    ),

                "talking_sales":
                    safe_int(
                        speech_summary.get(
                            "talking_sales",
                            0,
                        )
                    ),

                "visual_sales":
                    safe_int(
                        speech_summary.get(
                            "visual_sales",
                            0,
                        )
                    ),

                "unclear_videos":
                    safe_int(
                        speech_summary.get(
                            "unclear_count",
                            0,
                        )
                    ),

                "unavailable_videos":
                    safe_int(
                        speech_summary.get(
                            "unavailable_count",
                            0,
                        )
                    ),

                "speech_missing":
                    safe_int(
                        speech_summary.get(
                            "missing",
                            0,
                        )
                    ),

                "product_fit_eligible":
                    bool(
                        product_fit[
                            "eligible"
                        ]
                    ),

                "product_fit_score":
                    safe_float(
                        product_fit[
                            "score"
                        ]
                    ),

                "product_fit_segment":
                    product_fit[
                        "segment"
                    ],

                "product_fit_reason":
                    product_fit[
                        "reason"
                    ],

                "product_fit_terms":
                    product_fit[
                        "matched_terms"
                    ],

                "concept_fit_score":
                    safe_float(
                        marketing_concept[
                            "score"
                        ]
                    ),

                "concept_fit_profile":
                    marketing_concept[
                        "profile"
                    ],

                "concept_fit_reason":
                    marketing_concept[
                        "reason"
                    ],

                "concept_fit_terms":
                    marketing_concept[
                        "matched_terms"
                    ],

                "concept_caption_angle_hits":
                    safe_int(
                        marketing_concept[
                            "caption_angle_hits"
                        ]
                    ),

                "ad_saturation_risk":
                    safe_float(
                        ad_saturation[
                            "risk"
                        ]
                    ),

                "ad_white_space_score":
                    safe_float(
                        ad_saturation[
                            "white_space_score"
                        ]
                    ),

                "ad_saturation_level":
                    ad_saturation[
                        "level"
                    ],

                "ad_saturation_reason":
                    ad_saturation[
                        "reason"
                    ],

                "ad_saturation_terms":
                    ad_saturation[
                        "matched_terms"
                    ],

                "scanned_at":
                    scanned_at
                    or "",

                "cache_source":
                    cache_source,
            }
        )

    creator_values = [
        row[
            "creator_saturation"
        ]
        for row in base_rows
    ]

    promo_efficiency_values = [
        row[
            "sales_per_promo"
        ]
        for row in base_rows
    ]

    scored_rows = []

    for row in base_rows:
        creator_opportunity_score = (
            min_max_score(
                row[
                    "creator_saturation"
                ],
                creator_values,
                invert=True,
            )
        )

        promo_efficiency_score = (
            min_max_score(
                row[
                    "sales_per_promo"
                ],
                promo_efficiency_values,
            )
        )

        # ------------------------------------------
        # MARKET OPPORTUNITY SCORE
        # ------------------------------------------
        #
        # This is the previous numerical opportunity score.
        # Product Fit is deliberately kept separate so a strong
        # gadget cannot automatically become a final recommendation.
        # ------------------------------------------

        market_score = (
            (
                max(
                    0.0,
                    min(
                        100.0,
                        row[
                            "flipscore"
                        ],
                    ),
                )
                * 0.40
            )
            + (
                max(
                    0.0,
                    min(
                        100.0,
                        row[
                            "talking_sales_share"
                        ],
                    ),
                )
                * 0.20
            )
            + (
                max(
                    0.0,
                    min(
                        100.0,
                        row[
                            "talking_video_share"
                        ],
                    ),
                )
                * 0.10
            )
            + (
                max(
                    0.0,
                    min(
                        100.0,
                        row[
                            "strong_video_share"
                        ],
                    ),
                )
                * 0.10
            )
            + (
                row[
                    "repeatability_score"
                ]
                * 0.10
            )
            + (
                creator_opportunity_score
                * 0.05
            )
            + (
                promo_efficiency_score
                * 0.05
            )
        )

        # ------------------------------------------
        # FINAL OPPORTUNITY SCORE
        # ------------------------------------------
        #
        # Market proof still matters most, but Marketing Concept Fit now
        # has substantial weight because a product can be "good" while
        # still being difficult to build distinctive talking-led ads around.
        #
        # Final Opportunity =
        #   (60% Market Opportunity + 40% Marketing Concept Fit)
        #   × Product Fit factor
        #   × Local Saturation multiplier
        #
        # Local Saturation Risk is a heuristic proxy only until we add
        # actual Meta Ad Library validation. At 100 risk it can reduce
        # the score by up to 35%; at 0 risk there is no penalty.
        # ------------------------------------------

        concept_market_blend = (
            (
                market_score
                * 0.60
            )
            + (
                row[
                    "concept_fit_score"
                ]
                * 0.40
            )
        )

        saturation_multiplier = (
            1.0
            - (
                (
                    row[
                        "ad_saturation_risk"
                    ]
                    / 100.0
                )
                * 0.35
            )
        )

        saturation_multiplier = max(
            0.65,
            min(
                1.0,
                saturation_multiplier,
            ),
        )

        if row[
            "product_fit_eligible"
        ]:
            final_score = (
                concept_market_blend
                * (
                    row[
                        "product_fit_score"
                    ]
                    / 100.0
                )
                * saturation_multiplier
            )

        else:
            final_score = 0.0

        runability = (
            evaluate_runability_gate(
                row,
                market_score,
            )
        )

        if not row[
            "product_fit_eligible"
        ]:
            verdict = (
                "🚫 Product Fit Excluded"
            )

        elif not runability[
            "passed"
        ]:
            # Keep the specific gate failures visible rather than pretending
            # the highest mathematical score is automatically launchable.
            if any(
                "Saturated Market"
                in failure
                for failure in runability[
                    "failures"
                ]
            ):
                verdict = (
                    "🚫 Saturated Market"
                )

            elif any(
                "Weak Marketing Premise"
                in failure
                for failure in runability[
                    "failures"
                ]
            ):
                verdict = (
                    "🚫 Weak Marketing Premise"
                )

            else:
                verdict = (
                    "👀 Fails Runability Gate"
                )

        elif final_score >= 75:
            verdict = (
                "🔥 Strong Launch Candidate"
            )

        else:
            verdict = (
                "✅ Launch Candidate"
            )

        completed = dict(
            row
        )

        completed[
            "creator_opportunity_score"
        ] = creator_opportunity_score

        completed[
            "promo_efficiency_score"
        ] = promo_efficiency_score

        completed[
            "market_score"
        ] = round(
            market_score,
            1,
        )

        completed[
            "concept_market_blend"
        ] = round(
            concept_market_blend,
            1,
        )

        completed[
            "saturation_multiplier"
        ] = round(
            saturation_multiplier,
            3,
        )

        completed[
            "runability_pass"
        ] = bool(
            runability[
                "passed"
            ]
        )

        completed[
            "runability_status"
        ] = runability[
            "status"
        ]

        completed[
            "runability_reason"
        ] = runability[
            "reason"
        ]

        completed[
            "final_score"
        ] = round(
            final_score,
            1,
        )

        completed[
            "verdict"
        ] = verdict

        scored_rows.append(
            completed
        )

    eligible_rows = [
        row
        for row in scored_rows
        if row[
            "product_fit_eligible"
        ]
    ]

    eligible_rows = sorted(
        eligible_rows,
        key=lambda item: (
            1
            if item.get(
                "runability_pass",
                False,
            )
            else 0,
            item[
                "final_score"
            ],
            item[
                "concept_fit_score"
            ],
            item[
                "market_score"
            ],
            item[
                "talking_sales_share"
            ],
            item[
                "flipscore"
            ],
        ),
        reverse=True,
    )

    for rank, row in enumerate(
        eligible_rows,
        start=1,
    ):
        row[
            "final_rank"
        ] = rank

    excluded_rows = [
        row
        for row in scored_rows
        if not row[
            "product_fit_eligible"
        ]
    ]

    excluded_rows = sorted(
        excluded_rows,
        key=lambda item: item[
            "market_score"
        ],
        reverse=True,
    )

    return (
        eligible_rows,
        excluded_rows,
    )


def product_fit_dataframe(
    eligible_rows,
    excluded_rows,
):
    combined = (
        eligible_rows
        + excluded_rows
    )

    rows = []

    for row in combined:
        rows.append(
            {
                "Product":
                    row[
                        "product_name"
                    ],

                "Gate":
                    (
                        "✅ Keep"
                        if row[
                            "product_fit_eligible"
                        ]
                        else "🚫 Exclude"
                    ),

                "Product Fit":
                    row[
                        "product_fit_score"
                    ],

                "Profile":
                    row[
                        "product_fit_segment"
                    ],

                "Why":
                    row[
                        "product_fit_reason"
                    ],

                "Matched":
                    row[
                        "product_fit_terms"
                    ],

                "Market Opportunity":
                    row[
                        "market_score"
                    ],

                "Product ID":
                    row[
                        "product_id"
                    ],
            }
        )

    return pd.DataFrame(
        rows
    )


def final_opportunity_dataframe(
    final_rows,
):
    rows = []

    for row in final_rows:
        rows.append(
            {
                "Rank":
                    row[
                        "final_rank"
                    ],

                "Product":
                    row[
                        "product_name"
                    ],

                "Runability Gate":
                    row[
                        "runability_status"
                    ],

                "Gate Reason":
                    row[
                        "runability_reason"
                    ],

                "Final Opportunity":
                    row[
                        "final_score"
                    ],

                "Market Opportunity":
                    row[
                        "market_score"
                    ],

                "Marketing Concept Fit":
                    row[
                        "concept_fit_score"
                    ],

                "Concept Profile":
                    row[
                        "concept_fit_profile"
                    ],

                "Ad Saturation Risk":
                    row[
                        "ad_saturation_risk"
                    ],

                "Saturation Level":
                    row[
                        "ad_saturation_level"
                    ],

                "White Space":
                    row[
                        "ad_white_space_score"
                    ],

                "Product Fit":
                    row[
                        "product_fit_score"
                    ],

                "Profile":
                    row[
                        "product_fit_segment"
                    ],

                "Verdict":
                    row[
                        "verdict"
                    ],

                "FlipScore":
                    round(
                        row[
                            "flipscore"
                        ],
                        1,
                    ),

                "Momentum %":
                    row[
                        "momentum"
                    ],

                "7d Sales":
                    row[
                        "seven_day_sales"
                    ],

                "Age Days":
                    row[
                        "age_days"
                    ],

                "7d Promotions":
                    row[
                        "promotions_7d"
                    ],

                "Creators":
                    row[
                        "creator_saturation"
                    ],

                "Videos Sampled":
                    row[
                        "sampled_videos"
                    ],

                "Strong Videos ≥100K":
                    row[
                        "strong_videos"
                    ],

                "Strong Creators":
                    row[
                        "strong_creators"
                    ],

                "Talking Video Share":
                    row[
                        "talking_video_share"
                    ],

                "Sales from Talking Videos":
                    row[
                        "talking_sales_share"
                    ],

                "Talking Attributed Sales":
                    row[
                        "talking_sales"
                    ],

                "Provider":
                    row[
                        "provider"
                    ],

                "TikTok Shop":
                    row[
                        "shop_url"
                    ],

                "Product ID":
                    row[
                        "product_id"
                    ],
            }
        )

    return pd.DataFrame(
        rows
    )

st.divider()
st.subheader("5️⃣ Final Opportunities")

st.write(
    "FlipRadar now ranks every Product-Fit shortlist product that has "
    "complete content + successful Speech/Music v3 classifications. "
    "Marketing Concept Fit now measures whether the product naturally creates "
    "a compelling talking-led story instead of rewarding market performance "
    "alone. Products still waiting for analysis stay visible as Pending."
)

st.info(
    "Stage 5 uses **0 FastMoss requests** and **0 EchoTik requests**. "
    "The final score combines **60% Market Opportunity + 40% Marketing "
    "Concept Fit**, applies Product Fit, then applies a **local Ad Saturation "
    "Risk penalty of up to 35%**. This saturation layer is only a heuristic "
    "proxy until live Meta Ad Library validation is added. Cached video captions "
    "can strengthen Concept Fit when they repeatedly reveal a relationship, "
    "problem, transformation, personalization, caregiving, or demonstration "
    "angle. A product only enters **Top Opportunities** if it also passes the "
    "Runability Gate: Concept Fit ≥ 65, Ad Saturation Risk ≤ 80, Market "
    "Opportunity ≥ 55, Sales from Talking ≥ 60%, and at least 1 Strong Video. "
    "Products that fail remain visible in the full comparison. If only part of "
    "the shortlist is fully analyzed, the ranking is labeled **Provisional**."
)

complete_product_ids = {
    str(
        row.get(
            "Product ID",
            "",
        )
    ).strip()
    for row in speech_rows
    if row.get(
        "Speech Status"
    ) == "✅ Complete"
}

completed_products = [
    product
    for product in effective_shortlist
    if str(
        product.get(
            "id",
            "",
        )
    ).strip()
    in complete_product_ids
]

pending_products = [
    product
    for product in effective_shortlist
    if str(
        product.get(
            "id",
            "",
        )
    ).strip()
    not in complete_product_ids
]

pending_rows = []

for product in pending_products:
    product_id = str(
        product.get(
            "id",
            "",
        )
    ).strip()

    videos, scanned_at, cache_source = (
        load_content_scan_compat(
            product_id
        )
    )

    if not videos:
        pending_reason = (
            "Needs FastMoss content scan"
        )

    else:
        saved_speech = (
            load_speech_results(
                product_id
            )
        )

        summary = (
            summarize_product_speech(
                videos,
                saved_speech,
            )
        )

        if summary[
            "missing"
        ] > 0:
            pending_reason = (
                "Needs Talking vs Visual"
            )

        else:
            pending_reason = (
                "Waiting for complete analysis"
            )

    fit = classify_product_fit(
        product
    )

    concept = (
        classify_marketing_concept(
            product,
            videos=videos,
        )
    )

    saturation = (
        estimate_ad_saturation_risk(
            product
        )
    )

    pending_rows.append(
        {
            "Product":
                product.get(
                    "name",
                    "Unknown Product",
                ),

            "Status":
                pending_reason,

            "Product Fit":
                safe_float(
                    fit.get(
                        "score",
                        0,
                    )
                ),

            "Profile":
                fit.get(
                    "segment",
                    "",
                ),

            "Concept Fit":
                safe_float(
                    concept.get(
                        "score",
                        0,
                    )
                ),

            "Concept Profile":
                concept.get(
                    "profile",
                    "",
                ),

            "Ad Saturation Risk":
                safe_float(
                    saturation.get(
                        "risk",
                        0,
                    )
                ),

            "Saturation Level":
                saturation.get(
                    "level",
                    "",
                ),

            "FlipScore":
                safe_float(
                    product.get(
                        "score",
                        0,
                    )
                ),

            "7d Sales":
                safe_int(
                    product.get(
                        "seven_day_sales",
                        0,
                    )
                ),

            "Momentum %":
                safe_float(
                    product.get(
                        "growth",
                        0,
                    )
                ),

            "Product ID":
                product_id,
        }
    )

if not effective_shortlist:
    st.warning(
        "No products from the current qualified pool passed Product Fit."
    )

else:
    status1, status2, status3 = st.columns(
        3
    )

    status1.metric(
        "Product-Fit Shortlist",
        len(
            effective_shortlist
        ),
    )

    status2.metric(
        "Fully Analyzed",
        len(
            completed_products
        ),
    )

    status3.metric(
        "Pending Analysis",
        len(
            pending_products
        ),
    )

    if pending_products:
        st.warning(
            f"**Provisional ranking:** "
            f"{len(completed_products)} of "
            f"{len(effective_shortlist)} Product-Fit shortlist products "
            "are fully analyzed. Pending products are shown below and "
            "do not block the completed recommendations."
        )

    else:
        st.success(
            "All Product-Fit shortlist products are fully analyzed. "
            "This is the complete final ranking."
        )

    if completed_products:
        (
            final_rows,
            excluded_rows,
        ) = build_final_opportunity_rows(
            completed_products
        )

        if excluded_rows:
            st.warning(
                "A completed product was excluded by Product Fit after "
                "reaching Stage 5. This should normally be zero because "
                "Product Fit now runs before the content scan."
            )

        if final_rows:
            f1, f2, f3, f4 = st.columns(
                4
            )

            f1.metric(
                (
                    "Products Ranked"
                    if not pending_products
                    else "Products Ranked So Far"
                ),
                len(
                    final_rows
                ),
            )

            f2.metric(
                "Launch Candidates",
                sum(
                    1
                    for row in final_rows
                    if row.get(
                        "runability_pass",
                        False,
                    )
                ),
            )

            f3.metric(
                "Talking-led Products",
                sum(
                    1
                    for row in final_rows
                    if row[
                        "talking_sales_share"
                    ] >= 70
                ),
            )

            f4.metric(
                "Multi-Creator Strong Proof",
                sum(
                    1
                    for row in final_rows
                    if row[
                        "strong_creators"
                    ] >= 3
                ),
            )

            st.markdown(
                (
                    "#### 🏆 Provisional opportunity comparison"
                    if pending_products
                    else "#### 🏆 Final opportunity comparison"
                )
            )

            final_df = (
                final_opportunity_dataframe(
                    final_rows
                )
            )

            st.dataframe(
                final_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Final Opportunity":
                        st.column_config.NumberColumn(
                            "Final Opportunity",
                            format="%.1f",
                        ),

                    "Market Opportunity":
                        st.column_config.NumberColumn(
                            "Market Opportunity",
                            format="%.1f",
                        ),

                    "Marketing Concept Fit":
                        st.column_config.NumberColumn(
                            "Marketing Concept Fit",
                            format="%.1f",
                        ),

                    "Ad Saturation Risk":
                        st.column_config.NumberColumn(
                            "Ad Saturation Risk",
                            format="%.1f",
                        ),

                    "White Space":
                        st.column_config.NumberColumn(
                            "White Space",
                            format="%.1f",
                        ),

                    "Product Fit":
                        st.column_config.NumberColumn(
                            "Product Fit",
                            format="%.0f",
                        ),

                    "FlipScore":
                        st.column_config.NumberColumn(
                            "FlipScore",
                            format="%.1f",
                        ),

                    "Momentum %":
                        st.column_config.NumberColumn(
                            "Momentum %",
                            format="%.1f%%",
                        ),

                    "Talking Video Share":
                        st.column_config.NumberColumn(
                            "Talking Video Share",
                            format="%.1f%%",
                        ),

                    "Sales from Talking Videos":
                        st.column_config.NumberColumn(
                            "Sales from Talking Videos",
                            format="%.1f%%",
                        ),

                    "TikTok Shop":
                        st.column_config.LinkColumn(
                            "TikTok Shop",
                            display_text="Open product",
                        ),
                },
            )

            st.caption(
                "Pending products are not scored with incomplete data. "
                "As they finish Stage 3 and Stage 4, they automatically "
                "join this comparison."
            )

            st.markdown(
                (
                    "#### 🔎 Top opportunities so far"
                    if pending_products
                    else "#### 🔎 Top opportunities"
                )
            )

            launch_candidate_rows = [
                row
                for row in final_rows
                if row.get(
                    "runability_pass",
                    False,
                )
            ]

            top_cards = launch_candidate_rows[
                :min(
                    3,
                    len(
                        launch_candidate_rows
                    ),
                )
            ]

            if not top_cards:
                st.warning(
                    "No product currently clears the Runability Gate. "
                    "The full comparison above still shows the strongest "
                    "products and exactly why each one failed."
                )

            card_columns = (
                st.columns(
                    len(
                        top_cards
                    )
                )
                if top_cards
                else []
            )

            for column, row in zip(
                card_columns,
                top_cards,
            ):
                with column:
                    cover = str(
                        row.get(
                            "cover",
                            "",
                        )
                        or ""
                    ).strip()

                    if cover:
                        try:
                            st.image(
                                cover,
                                width="stretch",
                            )

                        except Exception:
                            pass

                    st.markdown(
                        f"### #{row['final_rank']} "
                        f"{row['product_name']}"
                    )

                    st.metric(
                        "Final Opportunity",
                        f"{row['final_score']:.1f}",
                    )

                    st.success(
                        row[
                            "runability_status"
                        ]
                    )

                    st.caption(
                        row[
                            "runability_reason"
                        ]
                    )

                    st.write(
                        f"**Market Opportunity:** "
                        f"{row['market_score']:.1f}"
                    )

                    st.write(
                        f"**Product Fit:** "
                        f"{row['product_fit_score']:.0f}/100 "
                        f"— {row['product_fit_segment']}"
                    )

                    st.write(
                        f"**Marketing Concept Fit:** "
                        f"{row['concept_fit_score']:.0f}/100 "
                        f"— {row['concept_fit_profile']}"
                    )

                    st.caption(
                        row[
                            "concept_fit_reason"
                        ]
                    )

                    st.write(
                        f"**Ad Saturation Risk:** "
                        f"{row['ad_saturation_risk']:.0f}/100 "
                        f"— {row['ad_saturation_level']}"
                    )

                    st.caption(
                        "Local proxy only — not live Meta Ad Library data. "
                        + row[
                            "ad_saturation_reason"
                        ]
                    )

                    st.write(
                        f"**Momentum:** "
                        f"{row['momentum']:.1f}%"
                    )

                    st.write(
                        f"**7d Sales:** "
                        f"{row['seven_day_sales']:,}"
                    )

                    st.write(
                        f"**Talking Video Share:** "
                        f"{row['talking_video_share']:.1f}%"
                    )

                    st.write(
                        f"**Sales from Talking:** "
                        f"{row['talking_sales_share']:.1f}%"
                    )

                    st.write(
                        f"**Strong Videos:** "
                        f"{row['strong_videos']} / "
                        f"{row['sampled_videos']}"
                    )

                    st.write(
                        f"**Strong Creators:** "
                        f"{row['strong_creators']}"
                    )

                    if row[
                        "shop_url"
                    ]:
                        st.link_button(
                            "Open TikTok Shop",
                            row[
                                "shop_url"
                            ],
                            width="stretch",
                        )

                    review_key = (
                        "review_top_videos_"
                        + str(
                            row[
                                "product_id"
                            ]
                        )
                    )

                    if st.button(
                        "🎬 Review Sampled Videos",
                        key=review_key,
                        width="stretch",
                    ):
                        st.session_state[
                            "video_review_product_id"
                        ] = str(
                            row[
                                "product_id"
                            ]
                        )

                        st.session_state[
                            "video_review_product_name"
                        ] = row[
                            "product_name"
                        ]

                        st.switch_page(
                            "pages/8_Product_Videos.py"
                        )

            failed_gate_rows = [
                row
                for row in final_rows
                if not row.get(
                    "runability_pass",
                    False,
                )
            ]

            if failed_gate_rows:
                with st.expander(
                    f"🚫 Products that failed Runability Gate "
                    f"({len(failed_gate_rows)})",
                    expanded=False,
                ):
                    for row in failed_gate_rows:
                        st.write(
                            f"**#{row['final_rank']} {row['product_name']}**"
                        )
                        st.caption(
                            row[
                                "runability_reason"
                            ]
                        )

            with st.expander(
                "🎬 Review sampled videos for any ranked product"
            ):
                st.caption(
                    "This opens a separate Product Videos page using only "
                    "the cached videos already used by Discovery Funnel."
                )

                for row in final_rows:
                    product_id = str(
                        row[
                            "product_id"
                        ]
                    )

                    button_label = (
                        f"#{row['final_rank']} "
                        f"{row['product_name']}"
                    )

                    if st.button(
                        button_label,
                        key=(
                            "review_ranked_videos_"
                            + product_id
                        ),
                        width="stretch",
                    ):
                        st.session_state[
                            "video_review_product_id"
                        ] = product_id

                        st.session_state[
                            "video_review_product_name"
                        ] = row[
                            "product_name"
                        ]

                        st.switch_page(
                            "pages/8_Product_Videos.py"
                        )

        else:
            st.warning(
                "No completed products could be scored."
            )

    else:
        st.warning(
            "No Product-Fit shortlist product has complete content + "
            "Talking-vs-Visual data yet."
        )

    if pending_rows:
        st.markdown(
            "#### ⏳ Pending analysis"
        )

        st.write(
            "These products passed Product Fit, but they are not included "
            "in the ranking until their required analysis is complete."
        )

        pending_df = pd.DataFrame(
            pending_rows
        )

        st.dataframe(
            pending_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Product Fit":
                    st.column_config.NumberColumn(
                        "Product Fit",
                        format="%.0f",
                    ),

                "Concept Fit":
                    st.column_config.NumberColumn(
                        "Concept Fit",
                        format="%.1f",
                    ),

                "Ad Saturation Risk":
                    st.column_config.NumberColumn(
                        "Ad Saturation Risk",
                        format="%.1f",
                    ),

                "FlipScore":
                    st.column_config.NumberColumn(
                        "FlipScore",
                        format="%.1f",
                    ),

                "Momentum %":
                    st.column_config.NumberColumn(
                        "Momentum %",
                        format="%.1f%%",
                    ),
            },
        )

        content_pending_count = sum(
            1
            for row in pending_rows
            if row[
                "Status"
            ] == "Needs FastMoss content scan"
        )

        speech_pending_count = sum(
            1
            for row in pending_rows
            if row[
                "Status"
            ] == "Needs Talking vs Visual"
        )

        if content_pending_count:
            st.caption(
                f"{content_pending_count} pending product(s) still need "
                f"FastMoss content scans. Cost if you choose to scan all "
                f"of them: **{content_pending_count} FastMoss request(s)**."
            )

        if speech_pending_count:
            st.caption(
                f"{speech_pending_count} pending product(s) need only "
                "Talking-vs-Visual analysis, which uses **0 API requests**."
            )

