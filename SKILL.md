---
name: transcribe
description: Transcribe audio or video files using the TextOps/Modal API. Use this skill whenever the user wants to transcribe a video or audio file, mentions an mp4/mp3/wav/m4a file and wants text out of it, asks for transcription or תמלול, or wants to convert spoken audio to text. Always trigger this skill even if the user just says "תמלל את זה" or "I want to transcribe this file".
---

# Transcription Skill

Transcribe audio/video files using the TextOps API.

## Step 1: Gather info from the user

Ask the user **one question only**:

1. **קובץ / File**: What is the file path or URL?
   - Local path (e.g. `C:\videos\interview.mp4`)
   - Any HTTP/HTTPS URL pointing directly to the file
   - Or: they can upload the file directly here in the chat

**Then ask about diarization** (speaker separation) — in the same message:
- Default: **no diarization** (single block of text)
- If the user mentions multiple speakers or wants speaker labels → diarization = true
  - Ask: **כמה דוברים בערך?** — e.g. "2", "3–4", "לא יודע"
  - Map: exact number → `--min-speakers N --max-speakers N`; range "3–4" → min=3 max=4; unknown → leave defaults (min=1 max=10)

**Skip questions the user already answered.** Read their message carefully:
- "דובר אחד", "one speaker", "no diarization" → diarization = false
- "שני דוברים", "two speakers", "with speakers" → diarization = true, min=2 max=2
- "timestamps פר מילה", "word level", "כתוביות מדויקות", "word timestamps" → `--word-timestamps true` (slower, no diarization)
- URL or file path already in the message → don't ask for the file again

If the user said "תמלל את זה" with a file attached/linked — just run immediately.

## Step 1.5: Validate URL (if input is a URL)

If the user provided a URL (not a local file path), **call `probe_url` before transcribing** to verify access and get metadata.

```bash
curl -s -X POST https://us-central1-whisper-cloud-functions.cloudfunctions.net/probe_url \
  -H "Content-Type: application/json" \
  -H "textops-api-key: $TEXTOPS_API_KEY" \
  -d '{"url": "<url>"}'
```

Response fields:
- `accessible` — can the file be reached without special permissions
- `transcribable` — is the extension supported (mp3/mp4/wav/m4a/ogg/flac/aac/wma/opus/webm/mkv/avi/mov/wmv/3gp/ts)
- `duration_seconds` — length in seconds (or `null` if unknown)
- `source_type` — `"gdrive"` for Google Drive, `"direct"` for everything else
- `error` — error message or `null`

**Decision tree:**
- `accessible: false` → Stop. Tell the user: the file is not publicly accessible. If it's a Google Drive link, they need to set sharing to "Anyone with the link".
- `transcribable: false` → Stop. Tell the user the file extension is not supported for transcription.
- Both `true` → Proceed to Step 2. If `duration_seconds` is available, mention the estimated file length to the user.

---

## Step 2: Run the transcription script

Use `scripts/transcribe.py` (relative to this skill directory).

```bash
python scripts/transcribe.py \
  --file "<path_or_url>" \
  --diarization <true|false> \
  --min-speakers <N> \
  --max-speakers <N> \
  --output-format text
```

`--file` accepts both local file paths and HTTP/HTTPS URLs.
`--min-speakers` / `--max-speakers` — only relevant when `--diarization true`. Default: min=1, max=10.
`--output-format text` — always use this. The script saves **both** a `.json` file and a `.txt` file every time.

**Environment variable required**: `TEXTOPS_API_KEY`
If missing: tell the user to set it (`set TEXTOPS_API_KEY=...` on Windows, `export` on Mac/Linux).

## Step 3: Monitor the process

The script handles polling automatically — no need to re-run anything. Watch the terminal output:

1. **After submission**, you'll see:
   - `[4/4] Waiting X seconds before first check...` — estimated wait based on file duration. Just wait.
   - Or: `[4/4] Unknown duration — waiting 10 seconds before polling...` — if duration couldn't be detected.

2. **During polling**, the script checks every 5 seconds and prints:
   ```
   [1] status: running | 45%
   [2] status: running | 72%
   ```
   No action needed — just wait.

3. **When done**, you'll see:
   - `✅ Done!` → proceed to Step 4
   - `❌ Processing error:` → go to Troubleshooting
   - `⚠️ Maximum wait time exceeded` → use `--job-id` to resume (see Troubleshooting)

## Step 3.5: Convert existing JSON (optional)

If the user already has a JSON file from a previous transcription and wants to convert it:

```bash
python scripts/json_to_text.py <file.json> [--output <file.txt>] [--diarization auto|true|false]
```

`--diarization auto` detects speaker info automatically from the data.

## Step 4: Show the result

After the script finishes, report both output files:
```
📦 transcript.json → <path>
📄 transcript.txt  → <path>
```

Don't dump the file contents into the chat. If the user wants to see the content, read the file and show a relevant excerpt.

**Validate**: if you see "empty" or "0 bytes" in the output, go to Troubleshooting immediately.

---

## Troubleshooting

### Empty output file (0 chars)

This usually means the API response had a different structure than expected.

1. Re-run with JSON format to see the raw response:
   ```bash
   python scripts/transcribe.py --job-id <JOB_ID> --output-format json
   ```
2. Open the JSON file and look for where the text segments actually are
3. Check the structure: is it `result.segments` or `result.result.segments`?

### 403 error on upload

The signed URL likely expired. Re-run from the beginning.

### Recover transcription with existing Job ID

If the process was interrupted or the output file was lost, you can recover using the Job ID that was printed during the run:

```bash
python scripts/transcribe.py \
  --job-id <JOB_ID> \
  --diarization <true|false> \
  --output-format text
```

To query a job directly (raw API):
```bash
curl -X POST https://us-central1-whisper-cloud-functions.cloudfunctions.net/check_modal_job \
  -H "Content-Type: application/json" \
  -H "textops-api-key: $TEXTOPS_API_KEY" \
  -d '{"textopsJobId": "<JOB_ID>"}'
```

### Process took too long / timeout

- The script polls for up to ~10 minutes (120 polls × 5s)
- For files longer than 60 minutes with diarization, this may not be enough
- Use `--job-id` to resume polling after a timeout

### Script printed "Done!" but the file is empty

Run with `--job-id` to re-fetch and inspect the raw `.json` output for where the content actually lives.

---

## Notes

- The API handles Hebrew and other languages automatically
- Diarization adds ~60% more processing time
- The Job ID is printed at submission — save it in case you need to recover
