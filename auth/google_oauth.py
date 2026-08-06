"""Real "Sign in with Google" OAuth 2.0 flow for the Streamlit UI.

Implements the authorization-code flow without extra dependencies:

    1. Build the Google consent URL (scope: openid email profile).
    2. Start a tiny local callback server on http://localhost:8765/oauth2callback
    3. Open the URL in the default browser.
    4. Wait for Google to redirect back with an authorization code.
    5. Exchange the code for an access token, then fetch the user profile.

Configure with environment variables (in .env):

    GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
    GOOGLE_CLIENT_SECRET=xxxx

Create the OAuth client at https://console.cloud.google.com/apis/credentials
- Application type: "Web application"
- Authorized redirect URIs: add http://localhost:8765/oauth2callback

The callback server binds to localhost only, so this is safe on a
single-user machine. The helper returns a profile dict
{email, name, picture} or raises GoogleAuthError with a friendly message.
"""
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
CALLBACK_PORT = int(os.getenv("GOOGLE_CALLBACK_PORT", "8765"))
CALLBACK_PATH = "/oauth2callback"
SCOPES = "openid email profile"
TIMEOUT_SECONDS = 180


class GoogleAuthError(RuntimeError):
    """Raised when the OAuth flow cannot complete."""


def is_configured():
    """True when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are both set."""
    return bool(
        (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        and (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    result = None  # shared capture of the callback query string

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == CALLBACK_PATH:
            type(self).result = parse_qs(parsed.query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h3>Signed in with Google!</h3><p>You can close this tab "
                b"and return to the app.</p>"
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence stdlib logging noise
        pass


def _exchange_code(code, client_id, client_secret, redirect_uri):
    body = urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = Request(GOOGLE_TOKEN_URL, data=body)
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "error" in payload:
        raise GoogleAuthError(f"Token exchange failed: {payload.get('error')}")
    return payload


def _fetch_profile(access_token):
    req = Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sign_in_with_google(timeout=TIMEOUT_SECONDS):
    """Run the full browser-based Google sign-in flow.

    Returns a dict with keys {email, name, picture} on success.
    Raises GoogleAuthError on any failure (unconfigured, timeout,
    rejected, network error).
    """
    client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise GoogleAuthError(
            "Google sign-in is not configured. Add GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET to your .env file."
        )

    redirect_uri = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
    state = secrets.token_urlsafe(16)

    try:
        server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    except OSError as exc:
        raise GoogleAuthError(
            f"Could not start the local callback server on port "
            f"{CALLBACK_PORT}: {exc}"
        ) from exc

    _CallbackHandler.result = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    auth_url = GOOGLE_AUTH_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
    )

    try:
        webbrowser.open(auth_url)
        deadline = time.time() + timeout
        while time.time() < deadline and _CallbackHandler.result is None:
            time.sleep(0.25)
        query = _CallbackHandler.result
        if not query:
            raise GoogleAuthError(
                "Google sign-in timed out — no browser response received."
            )
        if query.get("state", [""])[0] != state:
            raise GoogleAuthError("OAuth state mismatch — please try again.")
        if "error" in query:
            raise GoogleAuthError(
                f"Google sign-in was cancelled or rejected: {query['error'][0]}"
            )
        code = query.get("code", [""])[0]
        if not code:
            raise GoogleAuthError("Google did not return an authorization code.")

        tokens = _exchange_code(code, client_id, client_secret, redirect_uri)
        access_token = tokens.get("access_token")
        if not access_token:
            raise GoogleAuthError("Google did not return an access token.")
        profile = _fetch_profile(access_token)
        if not profile.get("email"):
            raise GoogleAuthError("Google did not return an email address.")
        return {
            "email": profile["email"],
            "name": profile.get("name") or profile["email"].split("@")[0],
            "picture": profile.get("picture"),
            "verified_email": profile.get("verified_email"),
        }
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
