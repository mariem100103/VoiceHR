from pathlib import Path
import sqlite3
import os


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("VOICEHR_DATA_DIR", ROOT))
DATABASE_PATH = DATA_DIR / "voicehr.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                candidate_name TEXT NOT NULL,
                candidate_email TEXT NOT NULL,
                language TEXT NOT NULL CHECK (language IN ('en', 'fr')),
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                conversation_id TEXT
            );

            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                file_path TEXT,
                duration_seconds INTEGER,
                candidate_speaking_seconds INTEGER,
                word_count INTEGER,
                transcript_json TEXT,
                FOREIGN KEY (interview_id) REFERENCES interviews(id)
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                report_token TEXT UNIQUE NOT NULL,
                overall_score INTEGER,
                confidence TEXT,
                result TEXT,
                interaction_score INTEGER,
                fluency_score INTEGER,
                grammar_score INTEGER,
                vocabulary_score INTEGER,
                pronunciation_score INTEGER,
                strengths_json TEXT,
                concerns_json TEXT,
                evidence_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (interview_id) REFERENCES interviews(id)
            );
            """
        )
