import logging
import os
import re
import time
from typing import Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

logger = logging.getLogger("monday_client")


class MondayClient:
    """Production-grade, read-only Monday.com GraphQL API Client.
    
    Provides:
    - Cursor-based full pagination (items_page)
    - In-memory caching with configurable TTL
    - Dynamic schema introspection
    - Robust error and rate-limiting resilience
    """
    API_URL = "https://api.monday.com/v2"

    def __init__(self, api_token: Optional[str] = None, cache_ttl_seconds: int = 120) -> None:
        load_dotenv()
        self.api_token = api_token or os.getenv("MONDAY_API_TOKEN")
        if not self.api_token or self.api_token.startswith("your_"):
            raise ValueError("Set MONDAY_API_TOKEN in .env or pass valid api_token before running.")
        
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        retry_policy = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=retry_policy, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def query(self, query_str: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Execute a GraphQL query against Monday.com API v2 with error handling."""
        operation_match = re.search(r"(?:query|mutation)\s+(\w+)", query_str)
        operation = operation_match.group(1) if operation_match else "anonymous"
        logger.info(
            "Monday request: POST %s | operation=%s | variables=%s",
            self.API_URL,
            operation,
            variables or {},
        )
        headers = {
            "Authorization": self.api_token,
            "Content-Type": "application/json",
            "API-Version": "2024-01",
        }
        try:
            response = self.session.post(
                self.API_URL,
                json={"query": query_str, "variables": variables or {}},
                headers=headers,
                timeout=45,
            )
            response.raise_for_status()
            logger.info(
                "Monday response: operation=%s | status=%s | bytes=%s",
                operation,
                response.status_code,
                len(response.content),
            )
        except requests.RequestException as exc:
            logger.error("Failed to connect to Monday API: %s", exc)
            raise RuntimeError(f"Monday API connection error: {exc}") from exc

        payload = response.json()
        if payload.get("errors"):
            err_msg = payload.get("errors")
            logger.error("Monday API returned GraphQL errors: %s", err_msg)
            raise RuntimeError(f"Monday API error: {err_msg}")
        
        if "data" not in payload:
            raise RuntimeError("Monday API returned malformed response with no 'data' key.")
        return payload["data"]

    def close(self) -> None:
        """Close pooled HTTP connections during application shutdown."""
        self.session.close()

    def who_am_i(self) -> dict[str, Any]:
        """Verify authentication and retrieve current user context."""
        data = self.query("query { me { id name email is_guest is_admin } }")
        return data["me"]

    def get_board(self, board_id: str, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch all items from a board with pagination and in-memory TTL caching."""
        cache_key = f"board_{board_id}"
        now = time.time()
        if not force_refresh and cache_key in self._cache:
            cached_time, cached_board = self._cache[cache_key]
            if now - cached_time < self.cache_ttl_seconds:
                logger.info("Monday board cache hit: board_id=%s", board_id)
                return cached_board

        logger.info("Fetching Monday board: board_id=%s", board_id)

        query_board = """
        query GetBoard($board_id: ID!) {
            boards(ids: [$board_id]) {
                id
                name
                description
                columns {
                    id
                    title
                    type
                    settings_str
                }
                items_page(limit: 500) {
                    cursor
                    items {
                        id
                        name
                        updated_at
                        column_values {
                            id
                            text
                            value
                            type
                        }
                    }
                }
            }
        }
        """
        data = self.query(query_board, {"board_id": board_id})
        boards = data.get("boards", [])
        if not boards:
            raise ValueError(f"No board found for ID '{board_id}'.")

        board = boards[0]
        items_page = board.get("items_page") or {}
        items = list(items_page.get("items", []))
        cursor = items_page.get("cursor")

        query_next = """
        query GetNextItems($board_id: ID!, $cursor: String!) {
            boards(ids: [$board_id]) {
                items_page(limit: 500, cursor: $cursor) {
                    cursor
                    items {
                        id
                        name
                        updated_at
                        column_values {
                            id
                            text
                            value
                            type
                        }
                    }
                }
            }
        }
        """
        while cursor:
            next_data = self.query(query_next, {"board_id": board_id, "cursor": cursor})
            next_boards = next_data.get("boards", [])
            if not next_boards:
                break
            page = next_boards[0].get("items_page") or {}
            next_items = page.get("items", [])
            items.extend(next_items)
            cursor = page.get("cursor")

        board_result = {
            "id": board.get("id"),
            "name": board.get("name"),
            "description": board.get("description"),
            "columns": board.get("columns", []),
            "items_count": len(items),
            "items_page": {
                "items": items,
                "cursor": None,
            },
        }
        self._cache[cache_key] = (now, board_result)
        logger.info(
            "Monday board fetched: name=%s | board_id=%s | columns=%s | items=%s",
            board_result["name"],
            board_id,
            len(board_result["columns"]),
            board_result["items_count"],
        )
        return board_result

    def clear_cache(self) -> None:
        """Manually flush internal cache."""
        self._cache.clear()


def required_board_id(environment_name: str) -> str:
    """Retrieve board ID from environment with strict validation."""
    board_id = os.getenv(environment_name)
    if not board_id or board_id.startswith("your_"):
        raise ValueError(f"Set {environment_name} in .env before running the application.")
    return board_id

