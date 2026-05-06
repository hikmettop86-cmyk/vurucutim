"""YouTube video upload — videos().insert with resumable upload."""
from __future__ import annotations

import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import ResumableUploadError
from googleapiclient.http import MediaFileUpload


def build_snippet(*, header_top: str, header_bottom: str, body_paragraph: str,
                  handle: str, keywords: list[str], category_id: str) -> dict:
    title = f"{header_top} | {header_bottom}".strip()[:100]
    description = (
        f"{body_paragraph}\n\n"
        f"#shorts\n"
        f"{handle}"
    )[:5000]
    return {
        "title": title,
        "description": description,
        "tags": list(keywords)[:30],
        "categoryId": category_id,
        "defaultLanguage": "tr",
    }


def build_status(*, privacy_status: str, ai_content: bool) -> dict:
    s: dict = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": False,
    }
    if ai_content:
        s["containsSyntheticMedia"] = True
    return s


def upload_video(*, credentials: Credentials, file_path: Path,
                 snippet: dict, status: dict, max_retries: int = 5) -> str:
    """Upload mp4 with retry. Re-creates the request on each retry because
    a partial resumable session can't be safely resumed across exceptions."""
    youtube = build("youtube", "v3", credentials=credentials)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        media = MediaFileUpload(
            str(file_path), mimetype="video/mp4",
            resumable=True, chunksize=10 * 1024 * 1024,
        )
        request = youtube.videos().insert(
            part="snippet,status",
            body={"snippet": snippet, "status": status},
            media_body=media,
        )
        try:
            response = None
            while response is None:
                _status, response = request.next_chunk()
            return response["id"]
        except ResumableUploadError as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_error  # unreachable
