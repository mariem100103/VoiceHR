# VoiceHR v0 — Updated Implementation Plan (ElevenLabs)

**Stack:** ElevenLabs Conversational AI · FastAPI · SQLite · Gemini API · Resend  
**Deadline:** August 13, 2026 · Solo Build

---

## Summary of Current State

**Day 1 is complete ✅**
- Project folder structure exists: `/backend`, `/frontend`, `/recordings`, `/transcripts`
- `database.py` — full schema for `interviews`, `recordings`, `reports` tables ✅
- `main.py` — FastAPI app with `POST /api/invite` route ✅  
- `frontend/admin.html` — minimal but functional invite form ✅
- `voicehr.db` — already initialized ✅

**Switching from Vapi → ElevenLabs Conversational AI**

ElevenLabs replaces Vapi across the entire stack. The feature set is equivalent:
- Real-time voice conversation via WebRTC/WebSocket in the browser
- EN + FR bilingual support (separate agents)
- Post-call webhook with full transcript + conversation ID
- Recording stored by ElevenLabs (downloadable via API)
- `@elevenlabs/client` JavaScript SDK — CDN available

---

## What Needs to Change (Vapi → ElevenLabs)

| Vapi Concept | ElevenLabs Equivalent |
|---|---|
| `VAPI_PUBLIC_KEY` | `ELEVENLABS_API_KEY` (used backend-side for signed URL) |
| `VAPI_ASSISTANT_EN/FR` | `ELEVENLABS_AGENT_ID_EN/FR` |
| `vapi.start(assistantId)` | `Conversation.startSession({ agentId })` via `@elevenlabs/client` |
| Vapi webhook `call.id` | ElevenLabs `conversation_id` |
| Vapi `call.transcript` | ElevenLabs `transcript` array in post-call webhook |
| Vapi `call.recordingUrl` | ElevenLabs conversation audio (retrieved via API) |

> [!IMPORTANT]
> ElevenLabs requires a **signed URL** (server-generated) for private agents in production. The backend must expose a `/api/interview/{token}/signed-url` endpoint that calls the ElevenLabs API to generate a one-time auth token for the browser session.

---

## Proposed Changes

### Layer 1 — Environment & Config

#### [MODIFY] [.env.example](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/.env.example)
- Remove `VAPI_*` keys
- Add `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID_EN`, `ELEVENLABS_AGENT_ID_FR`

#### [MODIFY] [requirements.txt](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/requirements.txt)
- Add `google-generativeai`, `requests`, `aiofiles`, `httpx`

---

### Layer 2 — Backend Routes (Days 2–4)

#### [MODIFY] [main.py](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/backend/main.py)

Add the following routes:

| Route | Description |
|---|---|
| `GET /api/interview/{token}` | Validate token → return candidate info or error |
| `POST /api/interview/{token}/start` | Mark status=active, call ElevenLabs signed-URL API, return `signed_url` + `agent_id` |
| `POST /api/webhook/elevenlabs` | Receive ElevenLabs post-call webhook → save transcript + audio |
| `GET /api/report/{report_token}` | Return full report JSON |
| `GET /recordings/{filename}` | Serve local audio file |
| `GET /admin/reports` | HTML list of completed interviews (fallback) |

#### [NEW] [backend/evaluator.py](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/backend/evaluator.py)
- Build a Gemini prompt with speaker-labelled transcript
- Call the Google GenAI SDK with `GEMINI_API_KEY`
- Parse JSON response, apply PRD weights
- Return evaluation dict

#### [NEW] [backend/mailer.py](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/backend/mailer.py)
- Send report email via Resend REST API
- Include candidate name, CEFR level, score, report link

---

### Layer 3 — Frontend (Days 2–4)

#### [MODIFY] [frontend/admin.html](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/frontend/admin.html)
- Redesign with premium dark/glassmorphism aesthetic
- Add copyable link output with one-click copy button
- Add link to `/admin/reports` for report history

#### [NEW] [frontend/interview.html](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/frontend/interview.html)
5-step flow:
1. Token validation (GET /api/interview/{token})
2. Consent screen (name, language, recording notice, checkbox)
3. Mic test (getUserMedia → audio level visualizer)
4. Live interview (ElevenLabs `@elevenlabs/client` SDK, task progress, elapsed timer)
5. End screen ("Interview complete, thank you")

ElevenLabs integration pattern:
```js
import { Conversation } from 'https://cdn.jsdelivr.net/npm/@elevenlabs/client/+esm';
// Backend provides signedUrl from POST /api/interview/{token}/start
const conv = await Conversation.startSession({ signedUrl });
conv.setVolume({ volume: 1 });
conv.on('disconnect', handleEnd);
```

#### [NEW] [frontend/report.html](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/frontend/report.html)
- Fetch JSON from `/api/report/{report_token}`
- Render: overall score badge, CEFR level, 5 dimension CSS bar charts
- Strengths/concerns lists with evidence timestamps
- Audio player + full transcript

---

## ElevenLabs Setup Steps (DAY 2 Manual Steps)

1. Create account at elevenlabs.io → Conversational AI → Agents
2. Create agent "Sarah EN" → set system prompt (Section 4.1 of original plan)
3. Set first message, voice (e.g. "Rachel"), language = English
4. In agent settings: enable **Post-call webhook** → URL = `https://YOUR_NGROK_URL/api/webhook/elevenlabs`
5. Copy Agent ID → `ELEVENLABS_AGENT_ID_EN`
6. Duplicate agent → "Sarah FR" → replace prompt with French version
7. Copy Agent ID → `ELEVENLABS_AGENT_ID_FR`
8. Dashboard → API Keys → copy key → `ELEVENLABS_API_KEY`

---

## Webhook Payload (ElevenLabs → Backend)

ElevenLabs sends a `POST` after every conversation ends:
```json
{
  "type": "conversation.ended",
  "conversation_id": "conv_abc123",
  "agent_id": "agent_xyz",
  "transcript": [
    { "role": "agent", "message": "Hello...", "time_in_call_secs": 1.2 },
    { "role": "user", "message": "Hi there...", "time_in_call_secs": 3.5 }
  ],
  "metadata": {
    "call_duration_secs": 680,
    "start_time_unix_secs": 1722800000
  }
}
```

The backend matches `conversation_id` to the active interview via the `elevenlabs_conversation_id` column (rename `vapi_call_id` in DB schema).

> [!NOTE]
> Audio recording: ElevenLabs stores recordings on their platform. The backend fetches it via `GET https://api.elevenlabs.io/v1/convai/conversations/{id}/audio` using the API key and saves it locally.

---

## Database Changes

#### [MODIFY] [backend/database.py](file:///c:/Users/mariem/OneDrive/Bureau/stage-25.26/VOICEHR/backend/database.py)
- Rename column `vapi_call_id` → `conversation_id` in the `interviews` table

---

## Verification Plan

### After Day 2
- Open `/interview?token=UUID` → consent → mic test → click start → Sarah speaks in browser
- End call → check DB: `status = completed`, `conversation_id` set

### After Day 3  
- Webhook arrives → check `/transcripts/{id}.json` saved, DB updated
- Audio downloaded to `/recordings/`

### After Day 4
- Admin receives email within 3 minutes of interview end
- `/report?token=REPORT_UUID` renders all 9 required fields

### Edge Case Tests (Day 5)
- Expired link → 410 error shown
- Used link → 409 error shown  
- Invalid token → 404 error shown
- Short interview → Inconclusive in report

---

## Remaining Work by Day

| Day | Tasks |
|---|---|
| **Day 2** | ElevenLabs agents setup · Backend routes (`/interview/{token}`, `/start`, signed URL) · `interview.html` |
| **Day 3** | Webhook route · transcript + audio save · ngrok tunnel |
| **Day 4** | `evaluator.py` · `mailer.py` · `report.html` · `/api/report` route · `/admin/reports` |
| **Day 5** | Edge case tests · polish UI · README · final demo run |
