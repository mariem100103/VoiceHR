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

## Deploy on Hugging Face Spaces

1. Create a new Space and choose **Docker** as the SDK.
2. Upload or copy the project files from this repository into the Space.
3. In **Settings > Variables and secrets**, add the variables from `.env.example`.
4. Set `BASE_URL` to the public Space URL.
5. The Space automatically builds the `Dockerfile` and serves the app on port `7860`.

No Docker installation is required locally. Hugging Face builds the container remotely.

Copy `.env.example` to `.env` and add the ElevenLabs agent IDs and API key before starting a live interview. The Gemini and Resend credentials are reserved for the reporting milestone.
