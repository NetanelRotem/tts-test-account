"""
TextOps transcription script.
Usage:
  python transcribe.py --file <path_or_url> [--diarization true|false]
                       [--output-format json|text] [--output-path <path>]
  python transcribe.py --job-id <id> [--output-format json|text] [--output-path <path>]
"""

import argparse
import json
import os
import sys
import time
import requests

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── API config ───────────────────────────────────────────────────────────────

API_KEY = os.environ.get("TEXTOPS_API_KEY", "")

GET_UPLOAD_URL   = "https://get-upload-signed-url-hjqzix372q-uc.a.run.app"
SUBMIT_MODAL_URL = "https://us-central1-whisper-cloud-functions.cloudfunctions.net/submit_modal_job"
CHECK_JOB_URL    = "https://us-central1-whisper-cloud-functions.cloudfunctions.net/check_modal_job"

SECS_PER_MIN     = 4      # 1 min of audio ≈ 4s processing
DIARIZATION_MULT = 1.6    # +60% for speaker separation
POLL_INTERVAL    = 5      # seconds between polls
MAX_POLLS        = 120    # ~10 minutes max



def log(msg):
    """Print with immediate flush so output streams in real time."""
    print(msg, flush=True)


# ── duration detection ───────────────────────────────────────────────────────

def _try_ffprobe(file_path):
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", file_path],
        capture_output=True, text=True, timeout=10
    )
    info = json.loads(result.stdout)
    for stream in info["streams"]:
        if "duration" in stream:
            return float(stream["duration"])
    return None


def _try_moviepy(file_path):
    from moviepy.editor import VideoFileClip
    clip = VideoFileClip(file_path)
    duration = clip.duration
    clip.close()
    return float(duration) if duration else None


def get_duration_seconds(file_path):
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return None
    for _, fn in [("ffprobe", _try_ffprobe), ("moviepy", _try_moviepy)]:
        try:
            result = fn(file_path)
            if result and result > 0:
                return result
        except Exception:
            pass
    return None


def calc_initial_wait(duration_sec, has_diarization):
    if duration_sec is None:
        return None
    wait = (duration_sec / 60) * SECS_PER_MIN
    if has_diarization:
        wait *= DIARIZATION_MULT
    return wait * 0.8  # start checking 20% before estimated finish


# ── upload (for local files) ─────────────────────────────────────────────────

def get_signed_urls(filename):
    log(f"[1/4] מקבל signed URL עבור: {filename}")
    res = requests.post(GET_UPLOAD_URL, json={"filename": filename},
                        headers={"textops-api-key": API_KEY})
    res.raise_for_status()
    return res.json()


def upload_file(upload_url, file_path, filename):
    log(f"[2/4] מעלה קובץ: {filename}...")
    with open(file_path, "rb") as f:
        res = requests.put(upload_url, data=f)
    if res.status_code == 403:
        log("❌ שגיאת 403 בהעלאה — ייתכן שה-signed URL פג תוקף, נסה שוב")
        sys.exit(1)
    res.raise_for_status()
    log("  העלאה הושלמה.")


# ── submit + poll ─────────────────────────────────────────────────────────────

def submit_job(download_url, has_diarization, word_timestamps=False, min_speakers=1, max_speakers=10):
    params = {
        "enable_diarization": has_diarization,
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
        "word_timestamps": word_timestamps,
    }
    log("[3/4] שולח job לעיבוד...")
    res = requests.post(SUBMIT_MODAL_URL,
                        json={"download_url": download_url, "params": params},
                        headers={"textops-api-key": API_KEY})
    res.raise_for_status()
    job_id = res.json()["textopsJobId"]
    log(f"  Job ID: {job_id}")
    log(f"  שמור את ה-Job ID! אם התהליך נקטע, תוכל לשחזר עם: --job-id {job_id}")
    return job_id


def poll_job(job_id, initial_wait):
    if initial_wait is not None:
        log(f"[4/4] ממתין {initial_wait:.0f} שניות לפני בדיקה ראשונה...")
        time.sleep(initial_wait)
        interval = POLL_INTERVAL
    else:
        log("[4/4] אורך לא ידוע — ממתין 10 שניות ומתחיל לפול...")
        time.sleep(10)
        interval = 4

    for attempt in range(1, MAX_POLLS + 1):
        res = requests.post(CHECK_JOB_URL,
                            json={"textopsJobId": job_id},
                            headers={"textops-api-key": API_KEY})
        res.raise_for_status()
        data = res.json()

        status   = data.get("status", "?")
        progress = data.get("progress", 0)
        log(f"  [{attempt}] status: {status} | {progress}%")

        if data.get("has_error"):
            log("\n❌ שגיאה בעיבוד:")
            log(str(data.get("user_messages") or data))
            sys.exit(1)

        if status == "done":
            log("\n✅ הושלם!")
            return data

        time.sleep(interval)

    log("⚠️ תם הזמן המקסימלי ללא תוצאה")
    log(f"  ניתן לנסות שוב: python transcribe.py --job-id {job_id} ...")
    sys.exit(1)


def extract_segments(data):
    """
    API response structure can vary:
      - data["result"]["segments"]      (most common)
      - data["result"]["result"]["segments"]  (nested)
    Returns segments list and prints the actual structure if not found.
    """
    result = data.get("result", {})

    # try flat structure first
    segments = result.get("segments")
    if segments is not None:
        return segments

    # try nested structure
    inner = result.get("result", {})
    segments = inner.get("segments")
    if segments is not None:
        return segments

    # not found — print actual structure to help debug
    log("\n⚠️ לא נמצאו segments בתשובה. מבנה התשובה בפועל:")
    log(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    log("\n  עצה: בדוק את המפתח שמכיל את הטקסט ושלח issue עם המבנה הזה")
    return []


# ── output writers ────────────────────────────────────────────────────────────

def write_json(data, output_path):
    result = data.get("result", data)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(output_path)
    if size < 10:
        log(f"⚠️ קובץ JSON ריק ({size} bytes) — תשובת ה-API לא הכילה תוכן")
    return size


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TextOps transcription")
    parser.add_argument("--file", default=None, help="Local file path or URL")
    parser.add_argument("--job-id", default=None,
                        help="Resume from existing Job ID (skip upload/submit)")
    parser.add_argument("--diarization", default="false",
                        help="Enable speaker separation: true/false")
    parser.add_argument("--min-speakers", type=int, default=1,
                        help="Minimum number of speakers (used with diarization)")
    parser.add_argument("--max-speakers", type=int, default=10,
                        help="Maximum number of speakers (used with diarization)")
    parser.add_argument("--word-timestamps", default="false",
                        help="Word-level timestamps (slower): true/false")
    parser.add_argument("--output-format", default="json",
                        choices=["json", "text"], help="Output format")
    parser.add_argument("--output-path", default=None,
                        help="Where to save the result (optional)")
    args = parser.parse_args()

    if not API_KEY:
        log("❌ חסר TEXTOPS_API_KEY — הגדר את המשתנה בסביבה ונסה שוב.")
        log("  Windows: set TEXTOPS_API_KEY=your_key")
        log("  Mac/Linux: export TEXTOPS_API_KEY=your_key")
        sys.exit(1)

    if not args.file and not args.job_id:
        log("❌ נדרש --file או --job-id")
        sys.exit(1)

    has_diarize      = args.diarization.lower() in ("true", "1", "yes")
    has_word_ts      = args.word_timestamps.lower() in ("true", "1", "yes")
    min_speakers     = args.min_speakers
    max_speakers     = args.max_speakers
    output_format = args.output_format

    # ── determine output path ─────────────────────────────────────────────────
    if args.output_path:
        output_path = args.output_path
    elif args.job_id:
        ext = ".json" if output_format == "json" else ".txt"
        output_path = os.path.join(os.getcwd(), f"{args.job_id}_transcript{ext}")
    elif args.file.startswith("http://") or args.file.startswith("https://"):
        ext = ".json" if output_format == "json" else ".txt"
        output_path = os.path.join(os.getcwd(), "transcript" + ext)
    else:
        base = os.path.splitext(args.file)[0]
        ext  = ".json" if output_format == "json" else ".txt"
        output_path = base + "_transcript" + ext

    # ── resume from existing job ID ───────────────────────────────────────────
    if args.job_id:
        log(f"🔄 ממשיך עם Job ID קיים: {args.job_id}")
        data = poll_job(args.job_id, initial_wait=None)
    else:
        file_arg = args.file
        is_url   = file_arg.startswith("http://") or file_arg.startswith("https://")

        if is_url:
            log(f"URL זוהה: {file_arg}")
            download_url = file_arg
            duration_sec = None
        else:
            filename     = os.path.basename(file_arg)
            duration_sec = get_duration_seconds(file_arg)
            urls         = get_signed_urls(filename)
            upload_file(urls["upload_url"], file_arg, filename)
            download_url = urls["download_url"]

        initial_wait = calc_initial_wait(duration_sec, has_diarize)
        if initial_wait:
            log(f"  זמן המתנה משוער: {initial_wait:.0f} שניות")

        job_id = submit_job(download_url, has_diarize, has_word_ts, min_speakers, max_speakers)
        data   = poll_job(job_id, initial_wait)

    # ── always save JSON first ────────────────────────────────────────────────
    json_path = os.path.splitext(output_path)[0] + ".json"
    size = write_json(data, json_path)
    log(f"📦 JSON: {json_path} ({size:,} bytes)")

    # ── convert to text if requested ──────────────────────────────────────────
    if output_format == "text":
        import subprocess
        script_dir = os.path.dirname(os.path.abspath(__file__))
        txt_path = os.path.splitext(output_path)[0] + ".txt"
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "json_to_text.py"),
             json_path, "--output", txt_path,
             "--diarization", "true" if has_diarize else "false"],
            capture_output=True, text=True
        )
        if result.stdout:
            log(result.stdout.strip())
        if result.returncode != 0 and result.stderr:
            log(f"⚠️ {result.stderr.strip()}")
        output_path = txt_path

    log(f"\n✔ סיום. קובץ הפלט: {output_path}")


if __name__ == "__main__":
    main()
