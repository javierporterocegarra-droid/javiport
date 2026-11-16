"""Autenticación y clientes de YouTube Data API v3 / YouTube Analytics API v2."""

import os
from pathlib import Path

from googleapiclient.discovery import build

from .config import env

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",   # comentarios, playlists, miniaturas
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def get_credentials(cfg: dict, interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = Path(cfg["paths"]["token"])
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        from google_auth_oauthlib.flow import InstalledAppFlow

        secret = cfg["paths"]["client_secret"]
        if not os.path.exists(secret):
            raise SystemExit(
                f"No encuentro {secret}. Descárgalo de Google Cloud Console > Credenciales > "
                "ID de cliente OAuth (tipo 'App de escritorio')."
            )
        flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, prompt="consent", access_type="offline")
    else:
        raise SystemExit("No hay sesión de YouTube. Ejecuta primero: python -m autotube auth")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def youtube_oauth(cfg: dict):
    return build("youtube", "v3", credentials=get_credentials(cfg), cache_discovery=False)


def analytics_oauth(cfg: dict):
    return build("youtubeAnalytics", "v2", credentials=get_credentials(cfg), cache_discovery=False)


def youtube_public(cfg: dict):
    """Cliente para datos públicos (tendencias). Usa API key si existe; si no, OAuth."""
    key = env("YOUTUBE_API_KEY")
    if key:
        return build("youtube", "v3", developerKey=key, cache_discovery=False)
    return youtube_oauth(cfg)
