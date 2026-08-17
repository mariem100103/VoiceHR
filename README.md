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
3. Render reads `render.yaml`, creates the web service, and attaches persistent storage at `/var/data`.
4. Add the environment variables marked `sync: false`. Set `BASE_URL` to the public Render URL.
5. Deploy, then open `/admin` on the deployed URL.

Persistent storage is required for the SQLite database, recordings, and transcripts. Never commit `.env` or production secrets.

Copy `.env.example` to `.env` and add the ElevenLabs agent IDs and API key before starting a live interview. The Gemini and Resend credentials are reserved for the reporting milestone.
