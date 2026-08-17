# VoiceHR

Local FastAPI application for VoiceHR language interviews.

## Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

Open `http://localhost:8000/admin` to generate an interview link. The candidate opens the generated `/interview?token=...` URL.

## Deploy on Render

1. Push this project to a GitHub or GitLab repository.
2. In Render, choose **New > Blueprint** and select the repository.
3. Render reads `render.yaml` and creates the free web service.
4. Add the environment variables marked `sync: false`. Set `BASE_URL` to the public Render URL.
5. Deploy, then open `/admin` on the deployed URL.

This demo uses ephemeral storage: SQLite data, recordings, and transcripts may be lost after a restart or redeploy. Never commit `.env` or production secrets.

Copy `.env.example` to `.env` and add the ElevenLabs agent IDs and API key before starting a live interview. The Gemini and Resend credentials are reserved for the reporting milestone.
