"""
LegiScan API client — structured bill tracking for US state legislatures.

Free tier: 30,000 queries/month, 100 calls per 60 seconds.
API docs: https://api.legiscan.com/dl/LegiScan_API_User_Manual.pdf

Provides:
  - Keyword search across all states or specific states
  - Full bill details (status, sponsors, history, committee, text)
  - Change detection via change_hash
  - Monitor list management (GAITS)
"""
from __future__ import annotations
import logging
import time
from typing import Any, Optional

import requests

from config.settings import Config

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.legiscan.com/"
_TIMEOUT = 20

# LegiScan status codes → human-readable labels
STATUS_LABELS = {
    0: "N/A",
    1: "Introduced",
    2: "Engrossed",
    3: "Enrolled",
    4: "Passed",
    5: "Vetoed",
    6: "Failed",
}

# LegiScan progress event codes
PROGRESS_EVENTS = {
    0: "Pre-filed",
    1: "Introduced",
    2: "Engrossed",
    3: "Enrolled",
    4: "Passed",
    5: "Vetoed",
    6: "Failed/Dead",
    7: "Veto Override",
    8: "Chaptered",
    9: "Refer",
    10: "Report Pass",
    11: "Report DNP",
    12: "Draft",
}


class LegiScanError(Exception):
    """Raised when the LegiScan API returns an error."""
    pass


class LegiScanClient:
    """Thin wrapper around the LegiScan REST API."""

    def __init__(self, api_key: str = ""):
        self._key = api_key or Config.legiscan_api_key()
        if not self._key:
            raise LegiScanError(
                "LEGISCAN_API_KEY not set. Register at https://legiscan.com/user/register "
                "and add LEGISCAN_API_KEY to your .env file."
            )
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "ComplianceMonitor/1.0 (compliance intelligence tool)"
        )
        self._last_call = 0.0
        self._call_count = 0

    def _throttle(self):
        """Enforce rate limit: max 100 calls per 60 seconds."""
        now = time.time()
        if now - self._last_call < 0.6:  # ~100/60s = 1 per 0.6s
            time.sleep(0.6 - (now - self._last_call))
        self._last_call = time.time()
        self._call_count += 1

    def _call(self, op: str, **params) -> dict:
        """Make an API call and return the parsed JSON response."""
        self._throttle()
        params["key"] = self._key
        params["op"] = op

        try:
            resp = self._session.get(_BASE_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise LegiScanError(f"API request failed: {e}") from e

        if data.get("status") == "ERROR":
            raise LegiScanError(f"LegiScan API error: {data}")

        return data

    # ── Search ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        state: str = "ALL",
        year: int = 2,  # 2 = current session
        page: int = 1,
    ) -> dict:
        """
        Full-text bill search. Returns up to 50 results per page.

        Args:
            query: Search string. Supports AND, OR, NOT, +, -.
            state: Two-letter abbreviation or "ALL".
            year: 1=all, 2=current (default), 3=recent, 4=prior, or exact year.
            page: Page number for pagination.

        Returns:
            Dict with 'summary' and 'results' keys.
        """
        data = self._call("getSearch", query=query, state=state, year=year, page=page)
        search_result = data.get("searchresult", {})

        # LegiScan returns results with numeric string keys plus 'summary'
        summary = search_result.get("summary", {})
        results = []
        for key, val in search_result.items():
            if key == "summary":
                continue
            if isinstance(val, dict) and "bill_id" in val:
                results.append(val)

        return {"summary": summary, "results": results}

    def search_all_pages(
        self,
        query: str,
        state: str = "ALL",
        year: int = 2,
        max_pages: int = 10,
    ) -> list[dict]:
        """Search and automatically paginate through all results."""
        all_results = []
        page = 1
        while page <= max_pages:
            data = self.search(query=query, state=state, year=year, page=page)
            results = data["results"]
            if not results:
                break
            all_results.extend(results)
            total_pages = int(data["summary"].get("page_total", 1))
            if page >= total_pages:
                break
            page += 1
        return all_results

    # ── Bill Details ───────────────────────────────────────────────────────

    def get_bill(self, bill_id: int) -> dict:
        """
        Fetch full bill details including status, sponsors, history,
        committee, texts, votes, and amendments.
        """
        data = self._call("getBill", id=bill_id)
        return data.get("bill", {})

    def get_bill_text(self, doc_id: int) -> dict:
        """Fetch bill text document (base64-encoded)."""
        data = self._call("getBillText", id=doc_id)
        return data.get("text", {})

    # ── Session & Master List ──────────────────────────────────────────────

    def get_session_list(self, state: str) -> list[dict]:
        """List available legislative sessions for a state."""
        data = self._call("getSessionList", state=state)
        sessions = data.get("sessions", [])
        if isinstance(sessions, dict):
            sessions = list(sessions.values())
        return sessions

    def get_master_list(self, state: str, session_id: int = 0) -> list[dict]:
        """
        Get all bills in a state's current (or specified) session.
        Lightweight: returns bill_id, number, change_hash, last_action.
        """
        params = {"state": state}
        if session_id:
            params["id"] = session_id
        data = self._call("getMasterListRaw", **params)
        master = data.get("masterlist", {})
        if isinstance(master, dict):
            bills = []
            for key, val in master.items():
                if key == "session" or not isinstance(val, dict):
                    continue
                bills.append(val)
            return bills
        return []

    # ── Monitor List (GAITS) ──────────────────────────────────────────────

    def set_monitor(self, bill_ids: list[int], stance: str = "watch") -> dict:
        """
        Add bills to your GAITS monitor list.
        stance: 'watch', 'support', or 'oppose'
        """
        id_str = ",".join(str(b) for b in bill_ids)
        return self._call("setMonitor", action="monitor", list=id_str, stance=stance)

    def get_monitor_list(self, record: str = "current") -> list[dict]:
        """Get monitored bills with full details. record: 'current' or 'all'."""
        data = self._call("getMonitorList", record=record)
        return data.get("monitorlist", [])

    def get_monitor_list_raw(self) -> list[dict]:
        """Get monitored bills — lightweight (bill_id + change_hash only)."""
        data = self._call("getMonitorListRaw", record="current")
        monitor = data.get("monitorlist", {})
        if isinstance(monitor, dict):
            bills = []
            for key, val in monitor.items():
                if not isinstance(val, dict):
                    continue
                bills.append(val)
            return bills
        return []

    # ── People ─────────────────────────────────────────────────────────────

    def get_person(self, people_id: int) -> dict:
        """Get legislator details."""
        data = self._call("getPerson", id=people_id)
        return data.get("person", {})

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def status_label(status_code: int) -> str:
        return STATUS_LABELS.get(status_code, f"Unknown ({status_code})")

    @property
    def call_count(self) -> int:
        return self._call_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        client = LegiScanClient()
        print(f"API key loaded. Testing search...")
        results = client.search("PFAS", state="ALL", year=2)
        print(f"Found {results['summary'].get('count', 0)} PFAS bills in current sessions")
        for r in results["results"][:5]:
            print(f"  [{r['state']}] {r['bill_number']}: {r['title'][:80]}")
            print(f"    Last action: {r['last_action_date']} — {r['last_action'][:60]}")
        print(f"\nAPI calls used: {client.call_count}")
    except LegiScanError as e:
        print(f"Error: {e}")
