"""Python client for the Simvex paper-trading API (MIT). Paper trading only: real fills may differ.

Your bot needs an API key (`dr_...`), never a private key or seed phrase.
"""
__version__ = "0.1.0"

from ._base import DEFAULT_BASE_URL, RateInfo, RetryPolicy  # noqa: E402
from .aio import AsyncClient, AsyncReplay  # noqa: E402
from .client import Client, Replay  # noqa: E402
from .errors import (Conflict, FuelRequired, InvalidRequest, Lookahead, NetworkError, NotFound, NotYet,  # noqa: E402
                     OrderRejected, PlanLimit, RateLimited, SecretRejected, ServerError, SimvexError, Unauthorized)

DISCLAIMER = "Paper trading result. Real fills may differ."

__all__ = ["Client", "AsyncClient", "Replay", "AsyncReplay", "RetryPolicy", "RateInfo", "DEFAULT_BASE_URL",
           "DISCLAIMER", "SimvexError", "Unauthorized", "NotYet", "PlanLimit", "RateLimited", "FuelRequired",
           "SecretRejected", "NotFound", "Lookahead", "Conflict", "InvalidRequest", "OrderRejected", "ServerError",
           "NetworkError"]
