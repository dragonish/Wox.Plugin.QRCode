"""Shared test doubles for the Wox plugin API."""

from wox_plugin import Context, LogLevel


class FakeAPI:
    """Minimal PublicAPI stand-in covering only what QRCodePlugin calls.

    Implementing the whole PublicAPI protocol is unnecessary for these tests,
    so cast the instance to PublicAPI at the injection site.
    """

    def __init__(self, cache_dir: str = "") -> None:
        self.cache_dir = cache_dir
        self.logs: list[tuple[LogLevel, str]] = []

    async def get_cache_folder(self, ctx: Context) -> str:
        return self.cache_dir

    async def log(self, ctx: Context, level: LogLevel, message: str) -> None:
        self.logs.append((level, message))
