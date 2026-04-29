import datetime as dt
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests


ACCOUNTS_BASE = "https://accounts.zohocloud.ca"
DESK_BASE = "https://desk.zohocloud.ca/api/v1"


class ZohoDeskClient:
    # Serialize OAuth refresh when parallel HTTP workers hit 401 together.
    _refresh_lock = threading.Lock()

    def __init__(self) -> None:
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
        self.org_id = os.getenv("ZOHO_ORG_ID", "").strip()
        self.access_token: str | None = None

        missing = [
            k
            for k, v in {
                "ZOHO_CLIENT_ID": self.client_id,
                "ZOHO_CLIENT_SECRET": self.client_secret,
                "ZOHO_REFRESH_TOKEN": self.refresh_token,
                "ZOHO_ORG_ID": self.org_id,
            }.items()
            if not v
        ]
        if missing:
            raise RuntimeError(f"Missing Zoho env vars: {', '.join(missing)}")

    def _log(self, method: str, url: str, status: int | str) -> None:
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        print(f"[{ts}] {method} {url} -> {status}")

    def _zoho_dt(self, value: str) -> str:
        """
        Zoho list filters are strict: use UTC without microseconds, e.g. 2026-04-09T13:50:00Z
        """
        d = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        d = d.replace(microsecond=0)
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")

    def refresh_access_token(self) -> str:
        with ZohoDeskClient._refresh_lock:
            url = f"{ACCOUNTS_BASE}/oauth/v2/token"
            payload = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            }
            resp = requests.post(url, data=payload, timeout=30)
            self._log("POST", url, resp.status_code)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token")
            if not token:
                raise RuntimeError(f"Zoho token refresh failed: {data}")
            self.access_token = token
            return token

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.access_token:
            self.refresh_access_token()

        url = f"{DESK_BASE}{path}"
        headers = {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "orgId": self.org_id,
        }
        for i in range(8):
            try:
                resp = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=60)
            except requests.RequestException as exc:
                if i >= 7:
                    raise
                wait = min(60, 2 ** min(i, 5))
                self._log(method, url, f"network_error_retry_{wait}s: {exc}")
                time.sleep(wait)
                continue

            self._log(method, resp.url, resp.status_code)

            # Refresh on any 401: network retries advance `i`, so a late 401 must still refresh
            # (otherwise the first HTTP response after DNS blips can be 401 with i>0 and we fail).
            if resp.status_code == 401:
                self.refresh_access_token()
                headers["Authorization"] = f"Zoho-oauthtoken {self.access_token}"
                continue

            if resp.status_code in {429, 500, 502, 503, 504} and i < 3:
                wait = 2 ** i
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json() if resp.text else {}

        raise RuntimeError(f"Failed after retries: {method} {url}")

    def _spawn_peer(self) -> "ZohoDeskClient":
        """Share the same access token so parallel workers do not each cold-refresh OAuth."""
        peer = ZohoDeskClient()
        peer.access_token = self.access_token
        return peer

    def fetch_ticket_activity_parallel(self, ticket_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Fetch threads, comments, and history concurrently (three HTTP pipelines per ticket).
        Rebuild/sync spend most wall time here; this typically cuts that segment ~3x vs sequential.
        Zoho rate limits still apply; we only run three workers per ticket, not N tickets at once.
        """
        if not self.access_token:
            self.refresh_access_token()
        p1, p2, p3 = self._spawn_peer(), self._spawn_peer(), self._spawn_peer()
        with ThreadPoolExecutor(max_workers=3) as ex:
            ft = ex.submit(p1.list_threads, ticket_id)
            fc = ex.submit(p2.list_comments, ticket_id)
            fh = ex.submit(p3.list_history, ticket_id)
            return ft.result(), fc.result(), fh.result()

    def fetch_ticket_activity(self, ticket_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Parallel by default; set ZOHO_PARALLEL_FETCH=0 to force sequential (debug / rate-limit issues)."""
        off = os.getenv("ZOHO_PARALLEL_FETCH", "1").strip().lower()
        if off in ("0", "false", "no", "off"):
            return self.list_threads(ticket_id), self.list_comments(ticket_id), self.list_history(ticket_id)
        return self.fetch_ticket_activity_parallel(ticket_id)

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        return self._request("GET", f"/tickets/{ticket_id}")

    def list_modified_tickets(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        # Many portals reject modifiedTimeRange on /tickets with 422.
        # Use stable fallback fetch/filter path directly.
        return self._list_modified_tickets_fallback(start_iso, end_iso, limit=100)

    def _list_modified_tickets_fallback(self, start_iso: str, end_iso: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        Fallback when modifiedTimeRange isn't accepted:
        page /tickets/search (sorted by modifiedTime desc) and filter by modifiedTime locally.
        """
        start_dt = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        end_dt = dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            try:
                data = self._request(
                    "GET",
                    "/tickets/search",
                    params={
                        "limit": limit,
                        "from": offset,
                        "sortBy": "-modifiedTime",
                    },
                )
            except requests.exceptions.HTTPError as exc:
                # Some portals may reject high offsets with 422; treat as pagination end.
                if exc.response is not None and exc.response.status_code == 422 and offset > 0:
                    break
                if "422 Client Error" in str(exc) and offset > 0:
                    break
                raise
            rows = data.get("data", [])
            if not rows:
                break
            seen_in_window = False
            for t in rows:
                mt_raw = t.get("modifiedTime")
                if not mt_raw:
                    continue
                try:
                    mt = dt.datetime.fromisoformat(str(mt_raw).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
                except Exception:
                    continue
                if start_dt <= mt <= end_dt:
                    out.append(t)
                    seen_in_window = True
            oldest_raw = rows[-1].get("modifiedTime")
            if oldest_raw:
                try:
                    oldest_dt = dt.datetime.fromisoformat(str(oldest_raw).replace("Z", "+00:00")).astimezone(
                        dt.timezone.utc
                    )
                    if oldest_dt < start_dt:
                        break
                except Exception:
                    pass
            if len(rows) < limit and not seen_in_window:
                break
            if len(rows) < limit:
                break
            offset += limit
        return out

    def list_threads(self, ticket_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            data = self._request("GET", f"/tickets/{ticket_id}/threads", params={"from": offset, "limit": limit})
            rows = data if isinstance(data, list) else data.get("data", [])
            if not rows:
                break
            out.extend(rows)
            if len(rows) < limit:
                break
            offset += limit
        return out

    def list_comments(self, ticket_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            data = self._request("GET", f"/tickets/{ticket_id}/comments", params={"from": offset, "limit": limit})
            rows = data if isinstance(data, list) else data.get("data", [])
            if not rows:
                break
            out.extend(rows)
            if len(rows) < limit:
                break
            offset += limit
        return out

    def list_history(self, ticket_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            data = self._request("GET", f"/tickets/{ticket_id}/history", params={"from": offset, "limit": limit})
            rows = data if isinstance(data, list) else data.get("data", [])
            if not rows:
                break
            out.extend(rows)
            if len(rows) < limit:
                break
            offset += limit
        return out
