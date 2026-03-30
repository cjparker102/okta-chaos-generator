"""
src/okta/client.py

Wraps the Okta SDK client with rate limit handling and retry logic.

Okta's API has rate limits — if you fire too many requests too fast,
it returns HTTP 429 (Too Many Requests) and you have to back off.
With 150+ users, each needing groups, apps, and admin roles, we'll
make hundreds of API calls. This wrapper makes sure we don't get
throttled and automatically retries on transient failures.
"""

import asyncio
import os
import time
import yaml
from dotenv import load_dotenv
from okta.client import Client as OktaClient
from rich.console import Console


console = Console()

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _load_settings() -> dict:
    """
    Loads settings.yaml.

    Returns:
        The settings dict.
    """
    with open(os.path.join(_CONFIG_DIR, "settings.yaml")) as f:
        return yaml.safe_load(f)


def build_client() -> OktaClient:
    """
    Creates and returns an authenticated Okta API client.

    Reads OKTA_DOMAIN and OKTA_API_TOKEN from the .env file.
    The token needs SUPER_ADMIN level to create users, groups,
    and assign admin roles.

    Returns:
        An authenticated OktaClient instance ready to use.
    """
    load_dotenv()

    domain = os.environ.get("OKTA_DOMAIN")
    token  = os.environ.get("OKTA_API_TOKEN")

    if not domain or not token:
        raise EnvironmentError(
            "Missing OKTA_DOMAIN or OKTA_API_TOKEN in .env file. "
            "Copy .env.example to .env and fill in your credentials."
        )

    config = {
        "orgUrl": f"https://{domain}",
        "token":  token,
    }
    return OktaClient(config)


async def safe_api_call(coro_factory, description: str = "", retries: int = 3):
    """
    Executes an Okta API call with automatic retry on failure.

    If Okta returns an error (rate limit, transient failure), we wait
    briefly and try again up to `retries` times before giving up.

    The delay between retries doubles each time (exponential backoff):
      Attempt 1 fails → wait 1s → retry
      Attempt 2 fails → wait 2s → retry
      Attempt 3 fails → wait 4s → give up

    Args:
        coro_factory: A callable (lambda) that returns a fresh awaitable
                      coroutine each time. Coroutines can only be awaited
                      once, so we need a new one for each retry attempt.
        description:  Human-readable name for logging (e.g. "create user john.doe").
        retries:      Maximum number of retry attempts.

    Returns:
        The tuple returned by the Okta SDK (result, response, error).
    """
    settings = _load_settings()
    delay    = settings["okta"]["rate_limit_delay"]

    for attempt in range(retries):
        result = await coro_factory()

        # Okta SDK returns a 3-tuple: (data, response, error)
        # We check the last element for errors
        if isinstance(result, tuple) and len(result) >= 3:
            _, _, err = result[0], result[1], result[2]
            if err is None:
                # Success — add a small delay to avoid rate limits
                await asyncio.sleep(delay)
                return result

            error_msg = str(err)

            # Rate limit hit — wait longer and retry
            if "429" in error_msg or "rate limit" in error_msg.lower():
                wait_time = delay * (2 ** attempt) * 5
                console.print(
                    f"   [yellow]Rate limit hit. Waiting {wait_time:.1f}s...[/yellow]"
                )
                await asyncio.sleep(wait_time)
                continue

            # 400 validation errors will never succeed on retry — return immediately
            # so the caller can handle them (e.g. "already exists")
            if "400" in error_msg or "validation" in error_msg.lower():
                return result

            # Other error on last attempt — raise it
            if attempt == retries - 1:
                raise RuntimeError(
                    f"Okta API call failed after {retries} attempts"
                    + (f" ({description})" if description else "")
                    + f": {err}"
                )

            # Other error, retry with backoff
            await asyncio.sleep(delay * (2 ** attempt))

        else:
            # Unexpected return shape — return as-is
            return result

    return result
