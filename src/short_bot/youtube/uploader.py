"""YouTube video upload — videos().insert with resumable upload."""
from __future__ import annotations

import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import ResumableUploadError
from googleapiclient.http import MediaFileUpload


def build_snippet(*, header_top: str, header_bottom: str, body_paragraph: str,
                  handle: str, keywords: list[str], category_id: str,
                  language: str = "tr",
                  generated: dict | None = None) -> dict:
    """Build YouTube videos.insert() snippet body.

    If `generated` (from Sonnet metadata writer) is provided, use its
    title/description/tags directly. Otherwise fall back to a basic
    "{top} | {bottom}" + body_paragraph + #shorts construction.
    """
    if generated:
        title = generated.get("title", "")[:100]
        description = generated.get("description", "")[:5000]
        tags = list(generated.get("tags", []))[:30]
    else:
        title = f"{header_top} | {header_bottom}".strip()[:100]
        description = (
            f"{body_paragraph}\n\n"
            f"#shorts\n"
            f"{handle}"
        )[:5000]
        tags = list(keywords)[:30]
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "categoryId": category_id,
        "defaultLanguage": language,
    }


def build_status(*, privacy_status: str, ai_content: bool,
                 publish_at: str | None = None) -> dict:
    if publish_at:
        privacy_status = "private"  # YouTube: publishAt sadece private iken geçerli
    s: dict = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        s["publishAt"] = publish_at
    if ai_content:
        s["containsSyntheticMedia"] = True
    return s


def upload_video(*, credentials: Credentials, file_path: Path,
                 snippet: dict, status: dict, max_retries: int = 5,
                 http=None, localizations: dict | None = None) -> str:
    """Upload mp4 with retry. Re-creates the request on each retry because
    a partial resumable session can't be safely resumed across exceptions.

    http: optional proxied httplib2.Http. When given wrapped via AuthorizedHttp
    so the entire upload (including resumable chunks) goes through proxy.
    localizations: opsiyonel {"en": {"title": ..., "description": ...}} — YouTube çok-dilli
      başlık (İngilizce akışta İngilizce başlık görünür; küresel Shorts erişimi)."""
    if http is not None:
        youtube = build("youtube", "v3", http=AuthorizedHttp(credentials, http=http))
    else:
        youtube = build("youtube", "v3", credentials=credentials)
    _body = {"snippet": snippet, "status": status}
    _part = "snippet,status"
    if localizations:
        _body["localizations"] = localizations
        _part = "snippet,status,localizations"
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        media = MediaFileUpload(
            str(file_path), mimetype="video/mp4",
            resumable=True, chunksize=10 * 1024 * 1024,
        )
        request = youtube.videos().insert(
            part=_part,
            body=_body,
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
