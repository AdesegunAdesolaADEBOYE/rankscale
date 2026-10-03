import base64
import hashlib
import re
from urllib.parse import parse_qs, quote, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

MAX_SHEET_DOWNLOAD_SIZE = 10 * 1024 * 1024
SHEET_ID_PATTERN = re.compile(r"^/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)")


class GoogleSheetsError(Exception):
    pass


def oauth_is_configured():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def create_oauth_flow(redirect_uri, state=None):
    if not oauth_is_configured():
        raise GoogleSheetsError(
            "Google sign-in is not configured. Add the OAuth client ID and secret to the RankScale environment."
        )
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=settings.GOOGLE_SHEETS_SCOPES,
        state=state,
    )
    flow.redirect_uri = redirect_uri
    return flow


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_refresh_token(refresh_token):
    return _fernet().encrypt(refresh_token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(encrypted_token):
    try:
        return _fernet().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise GoogleSheetsError(
            "The saved Google connection needs to be reconnected."
        ) from exc


def credentials_for_connection(connection):
    refresh_token = decrypt_refresh_token(connection.encrypted_refresh_token)
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=settings.GOOGLE_SHEETS_SCOPES,
    )


def _sheet_parts(source_url):
    parsed = urlparse(source_url)
    match = SHEET_ID_PATTERN.match(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com" or not match:
        raise GoogleSheetsError("Enter a Google Sheets share link from docs.google.com.")
    gid = parse_qs(parsed.query).get("gid", [None])[0]
    if gid is not None and not gid.isdigit():
        raise GoogleSheetsError("The sheet tab ID in this link is invalid.")
    return match.group(1), gid


def _google_host(hostname):
    return hostname == "google.com" or hostname.endswith(".google.com") or hostname.endswith(".googleusercontent.com")


def download_public_sheet_csv(source_url):
    sheet_id, gid = _sheet_parts(source_url)
    params = f"format=csv&gid={gid or '0'}"
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{params}"
    request = Request(export_url, headers={"User-Agent": "RankScale/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            final_host = urlparse(response.geturl()).hostname or ""
            if not _google_host(final_host):
                raise GoogleSheetsError("Google returned an unexpected download address.")
            if response.headers.get_content_type() == "text/html":
                raise GoogleSheetsError(
                    "This sheet is not publicly viewable. Connect a Google account that can access it."
                )
            content = response.read(MAX_SHEET_DOWNLOAD_SIZE + 1)
    except GoogleSheetsError:
        raise
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise GoogleSheetsError(
                "This sheet is not publicly viewable. Connect a Google account that can access it."
            ) from exc
        raise GoogleSheetsError(
            "Could not read this Google Sheet. Check the link and its sharing permissions."
        ) from exc
    except Exception as exc:
        raise GoogleSheetsError(
            "Could not read this Google Sheet. Check the link and its sharing permissions."
        ) from exc

    if len(content) > MAX_SHEET_DOWNLOAD_SIZE:
        raise GoogleSheetsError("The Google Sheet export is larger than 10 MB.")
    return content


def iter_private_sheet_rows(source_url, credentials):
    import requests

    sheet_id, gid = _sheet_parts(source_url)
    session = AuthorizedSession(credentials)
    api_root = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sheet_id, safe='')}"
    try:
        metadata_response = session.get(
            api_root,
            params={"fields": "sheets.properties(sheetId,title)"},
            timeout=20,
        )
        if metadata_response.status_code in (401, 403):
            raise GoogleSheetsError(
                "Google could not access this sheet with the connected account. Reconnect or check the sheet permissions."
            )
        metadata_response.raise_for_status()
        sheets = metadata_response.json().get("sheets", [])
        if not sheets:
            raise GoogleSheetsError("This Google spreadsheet has no worksheets.")

        properties = [sheet.get("properties", {}) for sheet in sheets]
        selected = next(
            (item for item in properties if gid is not None and str(item.get("sheetId")) == gid),
            properties[0] if gid is None else None,
        )
        if selected is None:
            raise GoogleSheetsError("The worksheet in this Google Sheets link was not found.")
        title = selected["title"].replace("'", "''")

        def rows():
            total_bytes = len(metadata_response.content)
            try:
                for start in range(1, 100_002, 1000):
                    end = min(start + 999, 100_001)
                    sheet_range = f"'{title}'!A{start}:AY{end}"
                    response = session.get(
                        f"{api_root}/values/{quote(sheet_range, safe='')}",
                        params={"valueRenderOption": "UNFORMATTED_VALUE"},
                        timeout=30,
                    )
                    if response.status_code in (401, 403):
                        raise GoogleSheetsError(
                            "Google could not read this worksheet. Check the connected account's access."
                        )
                    response.raise_for_status()
                    total_bytes += len(response.content)
                    if total_bytes > MAX_SHEET_DOWNLOAD_SIZE:
                        raise GoogleSheetsError("The Google Sheet data is larger than 10 MB.")
                    values = response.json().get("values", [])
                    if not values:
                        return
                    for item_index, values_row in enumerate(values):
                        actual_row = start + item_index
                        yield actual_row, values_row
                    if len(values) < (end - start + 1):
                        return
            finally:
                session.close()

        return rows()
    except GoogleSheetsError:
        session.close()
        raise
    except requests.RequestException as exc:
        session.close()
        raise GoogleSheetsError(
            "Could not read this Google Sheet. Check the connection and sheet permissions."
        ) from exc
    except Exception as exc:
        session.close()
        raise GoogleSheetsError("Could not read this Google Sheet.") from exc
