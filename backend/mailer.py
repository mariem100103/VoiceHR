import os
import httpx

def send_report_email(candidate_name: str, candidate_email: str, overall_score: int, cefr_level: str, report_token: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    admin_email = os.getenv("ADMIN_EMAIL")
    base_url = os.getenv("BASE_URL", "http://localhost:8000")

    if not api_key or not admin_email:
        print("[WARNING] Resend API key or Admin Email missing. Email not sent.")
        return False

    report_link = f"{base_url}/report?token={report_token}"

    html_content = f"""
    <h2>VoiceHR Interview Report Available</h2>
    <p><strong>Candidate:</strong> {candidate_name} ({candidate_email})</p>
    <p><strong>Overall Score:</strong> {overall_score}/100</p>
    <p><strong>CEFR Estimate:</strong> {cefr_level}</p>
    <br/>
    <p><a href="{report_link}" style="background: #2457d6; color: white; padding: 10px 18px; text-decoration: none; border-radius: 6px; font-weight: bold;">View Recruiter Report</a></p>
    <p>Or open directly: <a href="{report_link}">{report_link}</a></p>
    """

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": "VoiceHR <onboarding@resend.dev>",
                "to": [admin_email],
                "subject": f"Interview Report: {candidate_name} - {cefr_level} ({overall_score}/100)",
                "html": html_content
            },
            timeout=10.0
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send report email via Resend: {e}")
        return False

