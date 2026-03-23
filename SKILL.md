---
name: transcribe
description: Transcribe audio or video files using the TextOps/Modal API. Use this skill whenever the user wants to transcribe a video or audio file, mentions an mp4/mp3/wav/m4a file and wants text out of it, asks for transcription or תמלול, or wants to convert spoken audio to text. Always trigger this skill even if the user just says "תמלל את זה" or "I want to transcribe this file".
---

# Transcription Skill

Transcribe audio/video files using the TextOps API.

## Step 1: Gather info from the user

If the user didn't provide a file yet, ask for it. Once you have the file, ask **one question**:

> "יש יותר מדובר אחד בהקלטה? (הפרדת דוברים לוקחת קצת יותר זמן)"

- **No / דובר אחד** → `--diarization false`
- **Yes / כן** → ask how many: exact number → `--min-speakers N --max-speakers N`; range "3–4" → min=3 max=4; unknown → leave defaults (min=1 max=10)

**Skip the question if the user already answered:**
- "דובר אחד", "one speaker", "no diarization" → diarization = false
- "שני דוברים", "two speakers", "with speakers" → diarization = true, min=2 max=2
- "timestamps פר מילה", "word level", "כתוביות מדויקות" → `--word-timestamps true` (slower, no diarization)
- File attached/linked with "תמלל את זה" and no speaker info → ask only about speakers

**Never ask about output format** — always `--output-format text`.

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
`--output-format text` — always use this, no need to ask the user. The script always saves **both** a `.json` and a `.txt`.

**Output filenames** (set automatically, no need to specify):
- Local file: `<basename>_transcript.json` + `<basename>_transcript.txt` — saved next to the original file
- URL: `<filename-from-server>_transcript.json` + `<filename-from-server>_transcript.txt` — saved in the current directory

**For URLs**, the script automatically calls `probe_url` first (a Cloud Function that checks if the file is publicly accessible and what its duration is). You don't need to call it manually — but you need to understand what it checks so you can explain errors to the user:
- `ERROR: URL is not publicly accessible` → the file requires login/permissions. If it's Google Drive, tell the user to set sharing to "Anyone with the link".
- `ERROR: File format is not supported` → the extension isn't transcribable (e.g. `.docx`, `.zip`).
- `OK | source: gdrive | file: meeting.mp4, 45.3 MB, 342s` → probe passed, script continues.

**Environment variable required**: `TEXTOPS_API_KEY`
If missing: tell the user to set it (`set TEXTOPS_API_KEY=...` on Windows, `export` on Mac/Linux).

## Step 3: Monitor the process

The script handles polling automatically — no need to re-run anything. Watch the terminal output:

1. **After submission**, you'll see:
   - `[4/4] Waiting X seconds before first check...` — estimated wait based on file duration. Just wait.
   - Or: `[4/4] Unknown duration — waiting 10 seconds before polling...` — if duration couldn't be detected.

2. **During polling**, the script prints every few seconds:
   ```
   [1] status: running | 45%
   [2] status: running | 72%
   ```
   **Update the user every ~20% progress or every ~30 seconds** — e.g. "עדיין מעבד... 45%" or "כמעט סיים, 72%". Don't spam every poll line, just occasional updates so the user knows it's alive.

3. **When done**, you'll see:
   - `Done!` → proceed to Step 4
   - `ERROR: Processing failed:` → go to Troubleshooting
   - `WARNING: Maximum wait time exceeded` → use `--job-id` to resume (see Troubleshooting)

## Step 3.5: Convert existing JSON (optional)

If the user already has a JSON file from a previous transcription and wants to convert it:

```bash
python scripts/json_to_text.py <file.json> [--output <file.txt>] [--diarization auto|true|false]
```

`--diarization auto` detects speaker info automatically from the data.

## Step 4: Show the result

The script prints the output paths. Look for lines like:
```
[json] <path>/<name>_transcript.json (12,345 bytes)
[output] <path>/<name>_transcript.txt (4,321 chars, plain text)
```

Report both paths to the user. Don't dump the file contents into the chat. If the user wants to see the content, read the `.txt` file and show a relevant excerpt.

**Validate**: if you see `0 bytes` or `0 chars` in the output, go to Troubleshooting immediately.

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
