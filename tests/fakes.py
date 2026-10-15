"""Shared test doubles for the Wox plugin API."""

from wox_plugin import (
    Context,
    CopyParams,
    GetThemeColorsOption,
    GetThemeColorsResult,
    LogLevel,
    Query,
    QueryEnv,
    QueryType,
    Selection,
)


def make_query(trigger_keyword: str = "", command: str = "", search: str = "") -> Query:
    """Build a Query the way Wox delivers it to the plugin."""
    return Query(
        id="test",
        type=QueryType.INPUT,
        raw_query=trigger_keyword,
        selection=Selection(),
        env=QueryEnv(),
        trigger_keyword=trigger_keyword,
        command=command,
        search=search,
    )


class FakeAPI:
    """Minimal PublicAPI stand-in covering only what QRCodePlugin calls.

    Implementing the whole PublicAPI protocol is unnecessary for these tests,
    so cast the instance to PublicAPI at the injection site.
    """

    def __init__(
        self,
        cache_dir: str = "",
        settings: dict[str, str] | None = None,
        theme_colors: GetThemeColorsResult | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.settings = settings or {}
        self.theme_colors = theme_colors or GetThemeColorsResult()
        self.logs: list[tuple[LogLevel, str]] = []
        self.copied: list[CopyParams] = []
        self.notifications: list[str] = []

    async def get_cache_folder(self, ctx: Context) -> str:
        return self.cache_dir

    async def get_setting(self, ctx: Context, key: str) -> str:
        return self.settings.get(key, "")

    async def get_theme_colors(self, ctx: Context, option: GetThemeColorsOption | None = None) -> GetThemeColorsResult:
        return self.theme_colors

    async def copy(self, ctx: Context, params: CopyParams) -> None:
        self.copied.append(params)

    async def get_translation(self, ctx: Context, key: str) -> str:
        return key

    async def notify(self, ctx: Context, message: str) -> None:
        self.notifications.append(message)

    async def log(self, ctx: Context, level: LogLevel, message: str) -> None:
        self.logs.append((level, message))
