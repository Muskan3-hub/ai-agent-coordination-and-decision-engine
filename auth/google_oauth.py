"""Real "Sign in with Google" OAuth 2.0 flow for the Streamlit UI.

Implements the authorization-code flow without extra dependencies:

    1. Build the Google consent URL (scope: openid email profile).
    2. Send the user to Google and receive the authorization code.
    3. Exchange the code for an access token, then fetch the user profile.

Two transports are supported. Local development uses a tiny callback
server on http://localhost:<port>/oauth2callback; once the app is exposed
at a permanent public URL, GOOGLE_REDIRECT_URI switches the flow to the
"public" mode where Google redirects the browser back to the app's own
URL (?code=...&state=...) and the app finishes the flow from its query
string - so sign-in works from any device, on Railway/Render/tunnels,
with no localhost server involved.

Configure with environment variables (in .env):

    GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
    GOOGLE_CLIENT_SECRET=xxxx
    GOOGLE_CALLBACK_PORT=8765        # localhost mode only (default 8765)
    GOOGLE_REDIRECT_URI=https://app.example.com/oauth2callback   # public mode

Create the OAuth client at https://console.cloud.google.com/apis/credentials
- Application type: "Web application"
- Local mode: add http://localhost:8765/oauth2callback to
  "Authorized redirect URIs" (use the exact value of GOOGLE_CALLBACK_PORT).
- Public mode: add the exact value of GOOGLE_REDIRECT_URI to
  "Authorized redirect URIs" as well. A mismatch is what causes
  "Error 400: redirect_uri_mismatch", so this module validates the
  configuration before the browser is ever opened and reports the exact
  URI that must be registered.

The local callback server binds to localhost only, so it is safe on a
single-user machine. The helpers return a profile dict
{email, name, picture} or raise GoogleAuthError with a friendly message.
"""
import json
import os
import secrets
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from logsys import get_logger

# Load .env at import time (same pattern as models/llm.py) so this module's
# env reads are reliable regardless of import order elsewhere. Without this,
# a caller that imports google_oauth before load_dotenv() runs would silently
# ignore GOOGLE_CLIENT_ID / GOOGLE_CALLBACK_PORT from .env - the original
# cause of the redirect_uri_mismatch bug.
load_dotenv()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
DEFAULT_CALLBACK_PORT = 8765
CALLBACK_PATH = "/oauth2callback"
SCOPES = "openid email profile"
TIMEOUT_SECONDS = 180

log = get_logger("security")

# Friendly guidance for the OAuth error codes Google can return (either as a
# callback query parameter or in the token-exchange response). The raw
# technical code is logged; the user sees the readable explanation instead.
_OAUTH_ERROR_HINTS = {
    "redirect_uri_mismatch": (
        "Google rejected the redirect URI. The app sends "
        "{redirect_uri} \u2014 add exactly that URL under \u201cAuthorized redirect "
        "URIs\u201d of your OAuth client in Google Cloud Console "
        "(https://console.cloud.google.com/apis/credentials), then try again."
    ),
    "invalid_client": (
        "Google does not recognize this OAuth client. Check that "
        "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env match a Web "
        "application client in Google Cloud Console."
    ),
    "access_denied": (
        "You declined the sign-in request \u2014 nothing was changed. "
        "You can try again whenever you like."
    ),
    "invalid_request": (
        "Google rejected the sign-in request as malformed. Please try again."
    ),
    "unauthorized_client": (
        "This OAuth client is not authorized for sign-in. In Google Cloud "
        "Console make sure the client type is \u201cWeb application\u201d and the "
        "OAuth consent screen is configured."
    ),
    "invalid_grant": (
        "Google said the authorization code is invalid or was already used. "
        "Please try again."
    ),
    "temporarily_unavailable": (
        "Google sign-in is temporarily unavailable. Please try again in a moment."
    ),
    "server_error": (
        "Google encountered an internal error. Please try again in a moment."
    ),
}


class GoogleAuthError(RuntimeError):
    """Raised when the OAuth flow cannot complete."""


# ----------------------------------------------------------------------
# Configuration (read lazily so .env is honored even when this module is
# imported before dotenv has loaded)
# ----------------------------------------------------------------------
def get_callback_port():
    """Return the configured callback port (int) or None if set-but-invalid.

    GOOGLE_CALLBACK_PORT is read on every call (not at import time), so a
    value set in .env is always picked up. Falls back to 8765 when unset.
    """
    raw = (os.getenv("GOOGLE_CALLBACK_PORT") or "").strip()
    if not raw:
        return DEFAULT_CALLBACK_PORT
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    return port


def get_client_credentials():
    """Return (client_id, client_secret) from the environment, stripped."""
    client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    return client_id, client_secret


def get_redirect_uri():
    """Canonical LOCAL redirect URI: http://localhost:<port>/oauth2callback.

    Returns None when the configured callback port is invalid.
    """
    port = get_callback_port()
    if port is None:
        return None
    return f"http://localhost:{port}{CALLBACK_PATH}"


def get_public_redirect_uri():
    """Public redirect URI for the DEPLOYED flow (GOOGLE_REDIRECT_URI).

    Returns the exact string to register in Google Cloud Console, or None
    when unset (the app then uses the localhost callback flow). The value
    must be an absolute http(s) URL without a query string.
    """
    uri = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
    if not uri:
        return None
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.query or parsed.fragment:
        return None
    return uri


def is_public_flow():
    """True when the app should use the public redirect flow (deployed mode).

    Local development keeps the localhost callback server; once
    GOOGLE_REDIRECT_URI is set the app switches to the deployed flow where
    Google redirects the browser back to the app's own public URL.
    """
    return get_public_redirect_uri() is not None


def get_effective_redirect_uri():
    """The redirect URI used for this deployment (public or localhost)."""
    return get_public_redirect_uri() or get_redirect_uri()


def validate_config():
    """Validate the Google OAuth configuration.

    Returns a dict:
        enabled: bool          - True when the flow can actually run
        problems: list[str]    - human-readable issues (empty when enabled)
        callback_port: int|None
        redirect_uri: str|None  - effective URI for this deployment
        public: bool            - True in deployed (public URI) mode
    """
    client_id, client_secret = get_client_credentials()
    port = get_callback_port()
    public_uri = get_public_redirect_uri()
    problems = []
    if not client_id:
        problems.append("GOOGLE_CLIENT_ID is missing or empty \u2014 add it to .env.")
    if not client_secret:
        problems.append("GOOGLE_CLIENT_SECRET is missing or empty \u2014 add it to .env.")
    if public_uri:
        # Deployed mode: the callback is the app's own public URL.
        if os.getenv("GOOGLE_REDIRECT_URI") and not public_uri:
            problems.append(
                "GOOGLE_REDIRECT_URI is invalid \u2014 it must be an absolute "
                "http(s) URL without a query string."
            )
    elif port is None:
        problems.append(
            "GOOGLE_CALLBACK_PORT is invalid \u2014 it must be a number between "
            "1 and 65535 (fix it in .env)."
        )
    return {
        "enabled": not problems,
        "problems": problems,
        "callback_port": port,
        "redirect_uri": get_effective_redirect_uri(),
        "public": bool(public_uri),
    }


def is_configured():
    """True when Google sign-in can actually run (keys present, valid URI)."""
    return validate_config()["enabled"]


def config_report():
    """Startup diagnostics as log lines (missing values, URI, flow mode).

    Never logs secrets (client secret or tokens).
    """
    report = validate_config()
    client_id, _ = get_client_credentials()
    lines = []
    if report["enabled"]:
        lines.append("Google Login: ENABLED")
        lines.append(
            "Google OAuth flow: PUBLIC (redirect URI: "
            f"{report['redirect_uri']})"
            if report["public"]
            else "Google OAuth flow: LOCALHOST callback "
            f"(port {report['callback_port']})"
        )
        lines.append(f"Google OAuth redirect URI: {report['redirect_uri']}")
        lines.append(f"Google OAuth client ID: {client_id}")
    else:
        lines.append("Google Login: DISABLED")
        lines.extend(f"  - {problem}" for problem in report["problems"])
        if report["redirect_uri"]:
            lines.append(
                "Register this exact URL in Google Cloud Console "
                f"(Authorized redirect URIs): {report['redirect_uri']}"
            )
    return lines


def new_state():
    """Fresh CSRF state token for a public-flow consent request."""
    return secrets.token_urlsafe(16)


def build_public_auth_url(state):
    """Google consent URL for the deployed flow (no localhost server).

    Google redirects the browser back to GOOGLE_REDIRECT_URI with the
    authorization code, which the app picks up from its own query params.
    """
    report = validate_config()
    if not report["enabled"] or not report["public"]:
        raise GoogleAuthError(
            "Google sign-in is not configured for the public flow. Set "
            "GOOGLE_REDIRECT_URI to your deployed app URL."
        )
    client_id, _ = get_client_credentials()
    return GOOGLE_AUTH_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": report["redirect_uri"],
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "prompt": "select_account",
        }
    )


def complete_public_sign_in(code, state, expected_state):
    """Finish a public-flow sign-in from the callback query params.

    Verifies the CSRF state, exchanges the code with the public redirect
    URI, fetches the profile, and returns {email, name, picture, ...}.
    Raises GoogleAuthError with a friendly message on any failure.
    """
    if not code:
        raise GoogleAuthError("Google did not return an authorization code.")
    if not expected_state or state != expected_state:
        log.error("Google OAuth: state mismatch in public callback")
        raise GoogleAuthError("OAuth state mismatch \u2014 please try again.")

    report = validate_config()
    if not report["enabled"] or not report["public"]:
        raise GoogleAuthError(
            "Google sign-in is not configured for the public flow."
        )
    client_id, client_secret = get_client_credentials()
    redirect_uri = report["redirect_uri"]
    log.debug("Google OAuth: public callback received for %s", redirect_uri)
    try:
        tokens = _exchange_code(code, client_id, client_secret, redirect_uri)
    except GoogleAuthError:
        raise
    except Exception as exc:  # network / HTTP errors talking to Google
        log.error("Google OAuth: token exchange failed: %s", exc)
        raise GoogleAuthError(
            "Could not reach Google to complete sign-in. Check your "
            "connection and try again."
        ) from exc
    access_token = tokens.get("access_token")
    if not access_token:
        raise GoogleAuthError("Google did not return an access token.")
    try:
        profile = _fetch_profile(access_token)
    except Exception as exc:
        log.error("Google OAuth: failed to fetch user profile: %s", exc)
        raise GoogleAuthError(
            "Could not fetch your Google profile. Please try again."
        ) from exc
    if not profile.get("email"):
        raise GoogleAuthError("Google did not return an email address.")
    log.info("Google OAuth: authentication succeeded for %s", profile["email"])
    return {
        "email": profile["email"],
        "name": profile.get("name") or profile["email"].split("@")[0],
        "picture": profile.get("picture"),
        "verified_email": profile.get("verified_email"),
    }


def _friendly_oauth_error(error, redirect_uri=None):
    """Map a raw Google OAuth error code to a clear user-facing message."""
    hint = _OAUTH_ERROR_HINTS.get(error)
    if hint is None:
        return f"Google sign-in failed (error: {error}). Please try again."
    if error == "redirect_uri_mismatch":
        return hint.format(redirect_uri=redirect_uri or "(unknown)")
    return hint


class _CallbackHandler(BaseHTTPRequestHandler):
    result = None  # shared capture of the callback query string
    # Set to False for HTTP/1.0-style close-after-response. The local flow
    # uses a single-threaded HTTPServer: if the browser keeps the callback
    # connection alive (default keep-alive), serve_forever() blocks reading
    # that idle socket and server.shutdown() deadlocks - the flow thread
    # never stores its result, the UI hangs on "Waiting for Google
    # sign-in..." forever, and the callback port is never released.
    protocol_version = "HTTP/1.0"
    # Read timeout as extra insurance: even a client that connects but
    # never completes a request cannot block serve_forever() indefinitely
    # (shutdown would otherwise wait for the idle socket to read).
    timeout = 30

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == CALLBACK_PATH:
            type(self).result = parse_qs(parsed.query)
            body = (
                b"<h3>Signed in with Google!</h3><p>You can close this tab "
                b"and return to the app.</p>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):  # silence stdlib logging noise
        pass


def _summarize_callback(query):
    """Non-sensitive description of the received callback for logs.

    Never includes the authorization code or tokens.
    """
    return {
        "has_code": bool(query.get("code", [""])[0]),
        "has_state": bool(query.get("state", [""])[0]),
        "error": query.get("error", [None])[0],
    }


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
    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        # Google rejects bad codes / mismatched redirect URIs with HTTP 400
        # and a JSON body like {"error": "invalid_grant"}. Parse it so the
        # user gets the friendly explanation, not a generic network error.
        err_payload = {}
        try:
            err_payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        err = err_payload.get("error") or f"http_{exc.code}"
        log.error("Google OAuth: token exchange rejected by Google (error=%r)", err)
        raise GoogleAuthError(
            _friendly_oauth_error(err, redirect_uri=redirect_uri)
        ) from exc
    if "error" in payload:
        err = payload.get("error")
        log.error("Google OAuth: token exchange rejected by Google (error=%r)", err)
        raise GoogleAuthError(_friendly_oauth_error(err, redirect_uri=redirect_uri))
    return payload


def _fetch_profile(access_token):
    req = Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ----------------------------------------------------------------------
# Background flows (Streamlit-friendly)
#
# A full Google round-trip can take tens of seconds (browser consent +
# redirect). Blocking the Streamlit script run for that long is fragile:
# if the run is interrupted (reload, disconnect, a second click) the login
# result is lost and the UI stays stuck on the spinner. Instead the app
# starts the flow and polls get_flow_status() on each rerun - the result
# survives interrupted runs.
#
# Two transport modes share the same registry:
#   * LOCAL (no GOOGLE_REDIRECT_URI): a tiny callback server on
#     localhost:<port> receives the code; the flow runs on a daemon
#     thread.
#   * PUBLIC (GOOGLE_REDIRECT_URI set, deployed app): Google redirects
#     the browser straight back to the app's own public URL with
#     ?code=...&state=...; the callback is picked up from the query
#     string (possibly in a brand-new Streamlit session) and written
#     into the registry under the flow_id identified by the CSRF state.
# ----------------------------------------------------------------------
_flow_results = {}
_state_to_flow = {}
_flow_lock = threading.Lock()


def start_sign_in(flow_id, timeout=TIMEOUT_SECONDS):
    """Start the Google sign-in flow.

    In public (deployed) mode no background thread or local server is
    needed: the flow is registered so the callback can be completed from
    the query string, and the Google consent URL is stored for the UI.
    In local mode the flow runs on a daemon thread with a localhost
    callback server.

    The result (or a friendly error) is stored under ``flow_id`` and read
    later with get_flow_status(). Returns None when the flow started, or a
    user-facing error string when it could not (bad config, callback port
    busy).
    """
    report = validate_config()
    if not report["enabled"]:
        detail = "\n".join(f"  - {p}" for p in report["problems"])
        expected = (
            report["redirect_uri"]
            or f"http://localhost:{DEFAULT_CALLBACK_PORT}{CALLBACK_PATH}"
        )
        return (
            "Google sign-in is not configured correctly.\n"
            f"{detail}\n\n"
            "Once configured, Google Cloud Console must list this exact "
            f"Authorized redirect URI: {expected}"
        )
    if is_public_flow():
        return start_public_sign_in(flow_id, timeout=timeout)
    if _callback_port_in_use(report["callback_port"]):
        return (
            f"Another Google sign-in is already in progress (callback port "
            f"{report['callback_port']} is busy). Wait for it to finish or "
            "time out, then try again."
        )

    with _flow_lock:
        _flow_results[flow_id] = {
            "status": "running", "profile": None, "error": None,
        }

    def _run():
        try:
            profile = sign_in_with_google(timeout=timeout)
            with _flow_lock:
                _flow_results[flow_id] = {
                    "status": "done", "profile": profile,
                }
        except GoogleAuthError as exc:
            with _flow_lock:
                _flow_results[flow_id] = {
                    "status": "done", "error": str(exc),
                }
        except Exception as exc:  # noqa: BLE001 - surface as friendly text
            log.error("Google OAuth: unexpected flow failure: %s", exc)
            with _flow_lock:
                _flow_results[flow_id] = {
                    "status": "done",
                    "error": "Google authentication failed. Please try again.",
                }

    threading.Thread(target=_run, daemon=True).start()
    return None


def start_public_sign_in(flow_id, timeout=TIMEOUT_SECONDS):
    """Start the deployed (public URI) Google sign-in flow.

    Google redirects the browser back to the app's own public URL
    (GOOGLE_REDIRECT_URI) with the authorization code, so no localhost
    callback server is involved. The CSRF state is registered under
    ``flow_id`` and the Google consent URL is stored (and handed to
    webbrowser.open() as a convenience on machines that have a browser).

    The UI shows the consent URL as a link; once the browser returns to
    the app with ?code=...&state=..., complete_public_callback() finishes
    the flow and the result appears in get_flow_status(). Returns None on
    success or a user-facing error string.
    """
    report = validate_config()
    if not report["enabled"]:
        detail = "\n".join(f"  - {p}" for p in report["problems"])
        return (
            "Google sign-in is not configured correctly.\n"
            f"{detail}\n\n"
            "Once configured, Google Cloud Console must list this exact "
            f"Authorized redirect URI: {report['redirect_uri']}"
        )
    if not report["public"]:
        return (
            "Google sign-in is not configured for the public flow. Set "
            "GOOGLE_REDIRECT_URI in .env to the app's public URL and "
            "register it as an Authorized redirect URI in Google Cloud "
            "Console."
        )

    state = new_state()
    auth_url = build_public_auth_url(state)
    with _flow_lock:
        _flow_results[flow_id] = {
            "status": "running",
            "state": state,
            "auth_url": auth_url,
            "deadline": time.time() + timeout,
        }
        _state_to_flow[state] = flow_id

    try:
        opened = webbrowser.open(auth_url)
        if not opened:
            log.warning(
                "Google OAuth: could not auto-open the browser; the user "
                "must click the sign-in link in the UI."
            )
    except Exception:  # noqa: BLE001 - auto-open is best-effort
        log.debug("Google OAuth: browser auto-open unavailable")
    log.info(
        "Google OAuth: public sign-in flow started (redirect_uri=%s)",
        report["redirect_uri"],
    )
    return None


def complete_public_callback(code, state, error=None):
    """Finish a public-flow sign-in from the app's own query params.

    Called when the browser comes back to the app's public URL with
    ?code=...&state=... - possibly in a fresh Streamlit session, so the
    flow is identified by the CSRF ``state`` instead of session state.
    Exchanges the code, fetches the profile, stores it under the flow so
    any polling tab sees "done", and returns the profile dict.

    Raises GoogleAuthError with a friendly message on any failure.
    """
    if error:
        raise GoogleAuthError(_friendly_oauth_error(error))
    with _flow_lock:
        flow_id = _state_to_flow.get(state or "")
        entry = _flow_results.get(flow_id) if flow_id else None
        expected_state = entry.get("state") if entry else None
    if not flow_id or not expected_state or state != expected_state:
        log.error(
            "Google OAuth: public callback for unknown or expired state "
            "(possible CSRF or expired flow)"
        )
        raise GoogleAuthError(
            "Your Google sign-in session expired. Please click \u201cContinue "
            "with Google\u201d again."
        )
    profile = complete_public_sign_in(code, state, expected_state)
    with _flow_lock:
        _flow_results[flow_id] = {"status": "done", "profile": profile}
    return profile


def get_flow_status(flow_id):
    """Return the current flow state: {status, profile, error}.

    status is "running" while the browser round-trip is in progress and
    "done" once it finished (with either profile or error populated).
    Public flows carry an extra ``auth_url`` key while running and expire
    after TIMEOUT_SECONDS.
    """
    with _flow_lock:
        entry = _flow_results.get(flow_id)
        if entry is None:
            return {
                "status": "done",
                "profile": None,
                "error": "Google sign-in flow expired. Please try again.",
            }
        if (
            entry.get("status") == "running"
            and entry.get("deadline")
            and time.time() > entry["deadline"]
        ):
            entry = dict(entry)
            entry["status"] = "done"
            entry["error"] = (
                "Google sign-in timed out \u2014 please try again."
            )
            _flow_results[flow_id] = entry
        return entry


def clear_flow(flow_id):
    """Drop the stored result for a finished flow."""
    with _flow_lock:
        entry = _flow_results.pop(flow_id, None)
        if entry and entry.get("state"):
            _state_to_flow.pop(entry["state"], None)


def _callback_port_in_use(port):
    """True when something already listens on the callback port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def sign_in_with_google(timeout=TIMEOUT_SECONDS):
    """Run the full browser-based Google sign-in flow.

    Returns a dict with keys {email, name, picture} on success.
    Raises GoogleAuthError on any failure (unconfigured, invalid config,
    timeout, rejected, network error).
    """
    report = validate_config()
    if not report["enabled"]:
        detail = "\n".join(f"  - {p}" for p in report["problems"])
        expected = report["redirect_uri"] or f"http://localhost:{DEFAULT_CALLBACK_PORT}{CALLBACK_PATH}"
        raise GoogleAuthError(
            "Google sign-in is not configured correctly.\n"
            f"{detail}\n\n"
            "Once configured, Google Cloud Console must list this exact "
            f"Authorized redirect URI: {expected}"
        )

    client_id, client_secret = get_client_credentials()
    port = report["callback_port"]
    redirect_uri = report["redirect_uri"]
    state = secrets.token_urlsafe(16)

    log.info("Google OAuth: starting sign-in flow; redirect_uri=%s", redirect_uri)

    try:
        server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as exc:
        raise GoogleAuthError(
            f"Could not start the local callback server on port {port}: {exc}"
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
    log.debug("Google OAuth: authorization URL: %s", auth_url)

    try:
        opened = webbrowser.open(auth_url)
        if not opened:
            log.warning(
                "Google OAuth: could not auto-open the browser; the user "
                "must open the authorization URL manually."
            )

        deadline = time.time() + timeout
        while time.time() < deadline and _CallbackHandler.result is None:
            time.sleep(0.25)
        query = _CallbackHandler.result
        if not query:
            raise GoogleAuthError(
                "Google sign-in timed out \u2014 no browser response received. "
                "If Google showed an \u201cError 400: redirect_uri_mismatch\u201d "
                "page, add this exact redirect URI to your OAuth client in "
                f"Google Cloud Console: {redirect_uri}"
            )
        log.debug("Google OAuth: callback received: %s", _summarize_callback(query))
        if query.get("state", [""])[0] != state:
            log.error("Google OAuth: state mismatch in callback (possible CSRF)")
            raise GoogleAuthError("OAuth state mismatch \u2014 please try again.")
        if "error" in query:
            err = query["error"][0]
            log.error(
                "Google OAuth: authorization rejected (error=%r, description=%r)",
                err,
                query.get("error_description", [None])[0],
            )
            raise GoogleAuthError(_friendly_oauth_error(err, redirect_uri=redirect_uri))
        code = query.get("code", [""])[0]
        if not code:
            raise GoogleAuthError("Google did not return an authorization code.")

        try:
            tokens = _exchange_code(code, client_id, client_secret, redirect_uri)
        except GoogleAuthError:
            raise
        except Exception as exc:  # network / HTTP errors talking to Google
            log.error("Google OAuth: token exchange failed: %s", exc)
            raise GoogleAuthError(
                "Could not reach Google to complete sign-in. Check your "
                "connection and try again."
            ) from exc
        log.debug(
            "Google OAuth: token exchange succeeded (access token received: %s)",
            bool(tokens.get("access_token")),
        )
        access_token = tokens.get("access_token")
        if not access_token:
            raise GoogleAuthError("Google did not return an access token.")

        try:
            profile = _fetch_profile(access_token)
        except Exception as exc:  # network / HTTP errors fetching userinfo
            log.error("Google OAuth: failed to fetch user profile: %s", exc)
            raise GoogleAuthError(
                "Could not fetch your Google profile. Please try again."
            ) from exc
        if not profile.get("email"):
            raise GoogleAuthError("Google did not return an email address.")

        log.info("Google OAuth: authentication succeeded for %s", profile["email"])
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
