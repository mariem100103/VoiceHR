from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import json
import os
import base64

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .database import get_connection, init_db
from .evaluator import evaluate_transcript
from .mailer import send_report_email

FRONTEND = ROOT / "frontend"
DATA_DIR = Path(os.getenv("VOICEHR_DATA_DIR", ROOT))
RECORDINGS = DATA_DIR / "recordings"
TRANSCRIPTS = DATA_DIR / "transcripts"

app = FastAPI(title="VoiceHR")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


class InviteRequest(BaseModel):
    candidate_name: str
    candidate_email: str
    language: str


class TranscriptPayload(BaseModel):
    transcript: list
    duration_seconds: int = 0
    audio_base64: str | None = None


@app.on_event("startup")
def startup() -> None:
    RECORDINGS.mkdir(exist_ok=True)
    TRANSCRIPTS.mkdir(exist_ok=True)
    init_db()


@app.get("/")
def root():
    return RedirectResponse(url="/admin")


@app.get("/admin", response_class=FileResponse)
def admin_page() -> Path:
    return FRONTEND / "admin.html"


@app.get("/interview", response_class=FileResponse)
def interview_page() -> Path:
    return FRONTEND / "interview.html"


@app.get("/report", response_class=FileResponse)
def report_page() -> Path:
    return FRONTEND / "report.html"


def _get_interview(token: str):
    with get_connection() as connection:
        interview = connection.execute("SELECT * FROM interviews WHERE token = ?", (token,)).fetchone()
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview link not found")
    return interview


def _validate_interview(interview):
    if datetime.fromisoformat(interview["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This interview link has expired")
    if interview["status"] in {"active", "completed"}:
        raise HTTPException(status_code=409, detail="This interview link has already been used")


@app.post("/api/invite")
def create_invite(request: InviteRequest) -> dict:
    name = request.candidate_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Candidate name is required")
    if "@" not in request.candidate_email:
        raise HTTPException(status_code=422, detail="A valid candidate email is required")
    if request.language not in {"en", "fr"}:
        raise HTTPException(status_code=422, detail="Language must be en or fr")

    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(days=7)
    token = str(uuid4())
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO interviews
            (token, candidate_name, candidate_email, language, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (token, name, str(request.candidate_email), request.language,
             created_at.isoformat(), expires_at.isoformat()),
        )

    return {
        "token": token,
        "candidate_name": name,
        "language": request.language,
        "expires_at": expires_at.isoformat(),
        "interview_url": f"/interview?token={token}",
    }


@app.get("/api/interview/{token}")
def interview_details(token: str) -> dict:
    interview = _get_interview(token)
    _validate_interview(interview)
    return {"candidate_name": interview["candidate_name"], "language": interview["language"], "expires_at": interview["expires_at"]}


@app.post("/api/interview/{token}/start")
async def start_interview(token: str) -> dict:
    load_dotenv(ROOT / ".env", override=True)
    interview = _get_interview(token)
    _validate_interview(interview)
    agent_id = os.getenv(f"ELEVENLABS_AGENT_ID_{interview['language'].upper()}")
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not agent_id or not api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs is not configured in .env")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
                params={"agent_id": agent_id},
                headers={"xi-api-key": api_key}
            )
            if response.status_code != 200:
                print(f"[ElevenLabs API Error] Status: {response.status_code}, Body: {response.text}")
                try:
                    err_msg = response.json().get("detail", response.text)
                except Exception:
                    err_msg = response.text
                raise HTTPException(status_code=502, detail=f"ElevenLabs error ({response.status_code}): {err_msg}")
            
            signed_url = response.json().get("signed_url")
    except HTTPException:
        raise
    except Exception as error:
        print(f"[ElevenLabs Connection Error]: {error}")
        raise HTTPException(status_code=502, detail=f"Failed to connect to ElevenLabs: {str(error)}") from error

    if not signed_url:
        raise HTTPException(status_code=502, detail="ElevenLabs returned no signed URL")

    with get_connection() as connection:
        connection.execute("UPDATE interviews SET status = 'active' WHERE id = ?", (interview["id"],))
    return {"signed_url": signed_url, "agent_id": agent_id}


@app.post("/api/interview/{token}/complete")
async def complete_interview(token: str, payload: TranscriptPayload, background_tasks: BackgroundTasks):
    """Receives transcript directly from the browser — no webhook/ngrok needed."""
    interview = _get_interview(token)
    if interview["status"] in {"completed", "processing"}:
        return {"status": "skipped", "reason": "interview already completed"}

    interview_id = interview["id"]
    language = interview["language"]
    name = interview["candidate_name"]
    email = interview["candidate_email"]

    print(f"[COMPLETE] Interview {interview_id} received {len(payload.transcript)} transcript messages, duration={payload.duration_seconds}s")
    if payload.transcript:
        print(f"[COMPLETE] First message sample: {payload.transcript[0]}")

    with get_connection() as connection:
        connection.execute("UPDATE interviews SET status = 'processing' WHERE id = ?", (interview_id,))

    background_tasks.add_task(
        _process_completed_interview,
        interview_id,
        interview["conversation_id"] or "",
        payload.transcript,
        language,
        name,
        email,
        payload.duration_seconds,
        payload.audio_base64,
    )
    return {"status": "processing"}


class ConversationPayload(BaseModel):
    conversation_id: str


@app.post("/api/interview/{token}/conversation")
def save_conversation(token: str, payload: ConversationPayload):
    interview = _get_interview(token)
    with get_connection() as connection:
        connection.execute("UPDATE interviews SET conversation_id = ? WHERE id = ?", (payload.conversation_id, interview["id"]))
    return {"status": "saved"}


async def _process_completed_interview(interview_id: int, conversation_id: str, transcript: list, language: str, candidate_name: str, candidate_email: str, duration_seconds: int = 0, audio_base64: str | None = None):
    # 1. Attempt to download Audio from ElevenLabs (best-effort)
    api_key = os.getenv("ELEVENLABS_API_KEY")
    audio_path = RECORDINGS / f"{interview_id}.webm"
    if audio_base64:
        try:
            audio_path.write_bytes(base64.b64decode(audio_base64))
        except (ValueError, base64.binascii.Error) as error:
            print(f"[WARNING] Invalid browser audio: {error}")
    elif api_key and conversation_id:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.get(f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}/audio", headers={"xi-api-key": api_key})
                if res.status_code == 200:
                    audio_path = RECORDINGS / f"{interview_id}.mp3"
                    audio_path.write_bytes(res.content)
        except Exception as e:
            print(f"[WARNING] Could not fetch audio for {conversation_id}: {e}")

    # Save Transcript JSON
    transcript_file = TRANSCRIPTS / f"{interview_id}.json"
    transcript_file.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

    word_count = sum(len(item.get("message", "").split()) for item in transcript if item.get("role") == "user")
    candidate_secs = sum(item.get("time_in_call_secs", 0) for item in transcript if item.get("role") == "user")

    with get_connection() as conn:
        conn.execute("DELETE FROM recordings WHERE interview_id = ?", (interview_id,))
        conn.execute(
            """INSERT INTO recordings (interview_id, file_path, duration_seconds, candidate_speaking_seconds, word_count, transcript_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (interview_id, str(audio_path), int(duration_seconds), int(candidate_secs), word_count, json.dumps(transcript))
        )

    # 2. Run Gemini Evaluation
    if _is_not_qualified(transcript):
        report_data = {
            "overall_score": 0, "result": "Not qualified", "confidence": "High",
            "interaction_score": 0, "fluency_score": 0, "grammar_score": 0,
            "vocabulary_score": 0, "pronunciation_score": 0,
            "strengths": [],
            "concerns": ["The candidate did not provide sufficient substantive answers."],
            "evidence": [],
        }
    else:
        try:
            report_data = evaluate_transcript(transcript, language)
        except Exception as error:
            print(f"[WARNING] Gemini evaluation failed: {error}")
            score = min(100, max(0, 40 + min(word_count, 60)))
            level = "C1" if score >= 85 else "B2" if score >= 65 else "B1" if score >= 50 else "A2"
            report_data = {"overall_score": score, "result": level, "confidence": "Low", "interaction_score": score, "fluency_score": score, "grammar_score": score, "vocabulary_score": score, "pronunciation_score": score, "strengths": ["Interview response captured"], "concerns": ["Detailed automated evaluation was unavailable"], "evidence": []}

    report_token = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO reports 
               (interview_id, report_token, overall_score, confidence, result, interaction_score, fluency_score, grammar_score, vocabulary_score, pronunciation_score, strengths_json, concerns_json, evidence_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                interview_id,
                report_token,
                report_data.get("overall_score"),
                report_data.get("confidence", "Medium"),
                report_data.get("result", "B1"),
                report_data.get("interaction_score", 0),
                report_data.get("fluency_score", 0),
                report_data.get("grammar_score", 0),
                report_data.get("vocabulary_score", 0),
                report_data.get("pronunciation_score", 0),
                json.dumps(report_data.get("strengths", [])),
                json.dumps(report_data.get("concerns", [])),
                json.dumps(report_data.get("evidence", [])),
                created_at
            )
        )
        conn.execute("UPDATE interviews SET status = 'completed' WHERE id = ?", (interview_id,))

    # 3. Send Email Notification
    send_report_email(candidate_name, candidate_email, report_data.get("overall_score", 0), report_data.get("result", "N/A"), report_token)


def _is_not_qualified(transcript: list) -> bool:
    responses = [str(item.get("message", "")).strip() for item in transcript if item.get("role") == "user"]
    substantive = [response for response in responses if len(response.split()) >= 4]
    refusals = {"no", "nope", "nah", "nothing", "not interested", "i don't know", "idk", "non"}
    refusal_count = sum(response.lower().strip(".!?") in refusals for response in responses)
    return len(substantive) < 3 or (responses and refusal_count / len(responses) >= 0.6)


@app.post("/api/webhook/elevenlabs")
async def elevenlabs_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    conversation_id = body.get("conversation_id")
    transcript = body.get("transcript", [])

    if not conversation_id:
        return JSONResponse({"status": "ignored", "reason": "No conversation_id provided"})

    with get_connection() as conn:
        interview = conn.execute("SELECT * FROM interviews WHERE conversation_id = ? OR status = 'active' ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()

    if not interview:
        return JSONResponse({"status": "ignored", "reason": "Interview session not found"})

    interview_id = interview["id"]
    language = interview["language"]
    name = interview["candidate_name"]
    email = interview["candidate_email"]

    with get_connection() as conn:
        conn.execute("UPDATE interviews SET conversation_id = ? WHERE id = ?", (conversation_id, interview_id))

    background_tasks.add_task(_process_completed_interview, interview_id, conversation_id, transcript, language, name, email)
    return {"status": "processing"}


@app.get("/api/report/{report_token}")
def get_report(report_token: str):
    with get_connection() as conn:
        report = conn.execute("SELECT * FROM reports WHERE report_token = ?", (report_token,)).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        interview = conn.execute("SELECT * FROM interviews WHERE id = ?", (report["interview_id"],)).fetchone()
        recording = conn.execute("SELECT * FROM recordings WHERE interview_id = ?", (report["interview_id"],)).fetchone()

    return {
        "candidate_name": interview["candidate_name"],
        "candidate_email": interview["candidate_email"],
        "language": interview["language"],
        "overall_score": report["overall_score"],
        "confidence": report["confidence"],
        "result": report["result"],
        "dimension_scores": {
            "interaction": report["interaction_score"],
            "fluency": report["fluency_score"],
            "grammar": report["grammar_score"],
            "vocabulary": report["vocabulary_score"],
            "pronunciation": report["pronunciation_score"],
        },
        "strengths": json.loads(report["strengths_json"] or "[]"),
        "concerns": json.loads(report["concerns_json"] or "[]"),
        "evidence": json.loads(report["evidence_json"] or "[]"),
        "transcript": json.loads(recording["transcript_json"] if recording else "[]"),
        "recording_url": f"/recordings/{Path(recording['file_path']).name}" if recording and recording["file_path"] else None,
        "created_at": report["created_at"],
    }


@app.get("/recordings/{filename}")
def serve_recording(filename: str):
    file_path = RECORDINGS / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    media_type = "audio/webm" if file_path.suffix.lower() == ".webm" else "audio/mpeg"
    return FileResponse(file_path, media_type=media_type)


@app.get("/admin/reports")
def list_reports():
    with get_connection() as conn:
        reports = conn.execute(
            """SELECT r.report_token, r.overall_score, r.result, i.candidate_name, i.language, r.created_at
               FROM reports r JOIN interviews i ON r.interview_id = i.id ORDER BY r.id DESC"""
        ).fetchall()

    return {"reports": [dict(r) for r in reports]}
