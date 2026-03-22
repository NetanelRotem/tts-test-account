---
name: transcribe
description: Transcribe audio or video files using the TextOps/Modal API. Use this skill whenever the user wants to transcribe a video or audio file, mentions an mp4/mp3/wav/m4a file and wants text out of it, asks for transcription or תמלול, or wants to convert spoken audio to text. Always trigger this skill even if the user just says "תמלל את זה" or "I want to transcribe this file".
---

# Transcription Skill

Transcribe audio/video files using the TextOps API.

## Step 1: Gather info from the user

Ask the user these two questions **together in one message** — don't ask one at a time:

1. **קובץ / File**: What is the file path or URL?
   - Local path (e.g. `C:\videos\interview.mp4`)
   - Google Drive / network URL
   - Or: they can upload the file directly here in the chat

2. **פורמט הפלט / Output format** — ask them to choose:
   - **טקסט רגיל** — one long block of text, everything together
   - **JSON עם דוברים** — structured JSON with speaker separation (diarization), great when there are 2+ people talking

   **If they choose diarization**, ask one follow-up question in the same message:
   - **כמה דוברים בערך?** — e.g. "2", "3–4", "לא יודע"
   - Map the answer: exact number → set both `--min-speakers` and `--max-speakers` to that number; a range like "3–4" → min=3 max=4; unknown → leave defaults (min=1 max=10)

**Skip questions the user already answered.** Read their message carefully:
- "רק את הטקסט", "plain text", "clean text" → text format, no diarization
- "דובר אחד", "one speaker", "no diarization" → text format, no diarization
- "שני דוברים", "two speakers", "with speakers" → diarization = true, min=2 max=2
- "timestamps פר מילה", "word level", "כתוביות מדויקות", "word timestamps" → `--word-timestamps true` (note: slower, no diarization)
- URL or file path already in the message → don't ask for the file again

If the user said "תמלל את זה" with a file attached/linked — just confirm format and run.

## Step 2: Run the transcription script

Use `scripts/transcribe.py` (relative to this skill directory).

```bash
python scripts/transcribe.py \
  --file "<path_or_url>" \
  --diarization <true|false> \
  --min-speakers <N> \
  --max-speakers <N> \
  --output-format <json|text> \
  --output-path "<optional>"
```

`--min-speakers` / `--max-speakers` — only relevant when `--diarization true`. Default: min=1, max=10.

**The script always saves a JSON file first**, then converts to text if requested. You'll always get a `.json` backup regardless of format choice.

**Environment variable required**: `TEXTOPS_API_KEY`
If missing: tell the user to set it (`set TEXTOPS_API_KEY=...` on Windows, `export` on Mac/Linux).

## Step 3.5: Convert existing JSON (optional)

If the user already has a JSON file from a previous transcription and wants to convert it:

```bash
python scripts/json_to_text.py <file.json> [--output <file.txt>] [--diarization auto|true|false]
```

`--diarization auto` detects speaker info automatically from the data.

## Step 4: Show the result

After the script finishes, report in **one line**:
```
📄 transcript.json (X MB, Y segments) → <path>
```
Or for text: `📄 transcript.txt (X,XXX chars) → <path>`

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
  --output-format <json|text>
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

Run with `--output-format json` and `--job-id` to see the raw API response and find where the content actually lives.

---

## Notes

- The API handles Hebrew and other languages automatically
- Diarization adds ~60% more processing time
- The Job ID is printed at submission — save it in case you need to recover
