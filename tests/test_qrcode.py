import os
import tempfile
import unittest
from typing import cast

import png  # type: ignore[import-untyped]
import qrcode  # type: ignore[import-untyped]
from qrcode.image.pure import PyPNGImage  # type: ignore[import-untyped]
from wox_plugin import ActionContext, Context, GetThemeColorsResult, LogLevel, PublicAPI, WoxImage

from src.qrcode_main import BORDER, BOX_SIZE, QRCodePlugin, decode_qr_image, image_preview_data
from tests.fakes import FakeAPI, make_query

# A module pixel and a quiet-zone pixel of a generated QR Code. The quiet zone is
# BORDER modules wide, so anything before BORDER * BOX_SIZE belongs to it.
MODULE_PIXEL = BORDER * BOX_SIZE + BOX_SIZE // 2
QUIET_PIXEL = BOX_SIZE // 2

DARK_THEME = GetThemeColorsResult(background="#1e1e1e", text="#e6e6e6", dark=True)
LIGHT_THEME = GetThemeColorsResult(background="#ffffff", text="#101010", dark=False)


def _rgba_at(path: str, x: int, y: int) -> tuple[int, int, int, int]:
    """Read one pixel from a PNG as RGBA."""
    with open(path, "rb") as f:
        _width, _height, rows, _info = png.Reader(file=f).asRGBA8()
        row = list(rows)[y]
    offset = x * 4
    return (row[offset], row[offset + 1], row[offset + 2], row[offset + 3])


def _copied_image_path(api: FakeAPI) -> str:
    """Path of the image the plugin copied, asserting it copied exactly one."""
    assert len(api.copied) == 1
    wox_image = api.copied[0].wox_image
    assert wox_image is not None
    return str(wox_image["ImageData"])


class PluginTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class wiring a QRCodePlugin to a FakeAPI in a throwaway cache dir."""

    def make_plugin(
        self,
        theme_colors: GetThemeColorsResult | None = None,
        settings: dict[str, str] | None = None,
    ) -> tuple[QRCodePlugin, FakeAPI]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        plugin = QRCodePlugin()
        api = FakeAPI(tmp.name, settings=settings, theme_colors=theme_colors)
        plugin.api = cast(PublicAPI, api)
        return plugin, api


class TestQRCodeRoundtrip(unittest.TestCase):
    def test_generate_then_decode(self):
        text = "https://example.com/中文测试?q=1"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "qr.png")
            img = qrcode.make(text, image_factory=PyPNGImage)
            with open(path, "wb") as f:
                img.save(f)
            self.assertEqual(decode_qr_image(path), [text])

    def test_no_qr_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "blank.png")
            with open(path, "wb") as f:
                # pypng's Writer defaults to greyscale: one sample per pixel.
                png.Writer(100, 100).write(f, [[255] * 100 for _ in range(100)])
            self.assertEqual(decode_qr_image(path), [])


class TestImagePreviewData(unittest.TestCase):
    def test_absolute_image_serializes_as_type_data(self):
        # The host parses "type:data"; str(WoxImage) is wrong on Python 3.12+.
        data = image_preview_data(WoxImage.new_absolute(r"C:\tmp\qr.png"))
        self.assertEqual(data, r"absolute:C:\tmp\qr.png")


class TestMakeQrPngCache(unittest.IsolatedAsyncioTestCase):
    """Generated PNGs must live in the Wox-managed plugin cache folder.

    Wox deletes that folder on uninstall, so the plugin no longer needs its own
    temp directory. get_cache_folder() returns "" on failure, and joining ""
    would write the PNG into the process working directory instead.
    """

    async def test_uses_plugin_cache_folder(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            plugin = QRCodePlugin()
            api = FakeAPI(cache_dir)
            plugin.api = cast(PublicAPI, api)
            path = await plugin._make_qr_png(Context.new(), "hello")
            self.assertEqual(os.path.dirname(path), cache_dir)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(api.logs, [])

    async def test_reuses_existing_png_for_same_text(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            plugin = QRCodePlugin()
            plugin.api = cast(PublicAPI, FakeAPI(cache_dir))
            first = await plugin._make_qr_png(Context.new(), "same text")
            mtime = os.path.getmtime(first)
            second = await plugin._make_qr_png(Context.new(), "same text")
            self.assertEqual(first, second)
            self.assertEqual(os.path.getmtime(second), mtime)

    async def test_falls_back_to_temp_dir_when_cache_folder_is_empty(self):
        plugin = QRCodePlugin()
        api = FakeAPI("")
        plugin.api = cast(PublicAPI, api)
        path = await plugin._make_qr_png(Context.new(), "fallback text")
        self.assertEqual(os.path.dirname(path), os.path.join(tempfile.gettempdir(), "wox-qrcode"))
        self.assertTrue(os.path.exists(path))
        self.assertEqual([level for level, _ in api.logs], [LogLevel.WARNING])


class TestThemeColors(PluginTestCase):
    """The QR palette follows the Wox theme, but only when it stays scannable."""

    async def test_dark_theme_uses_light_modules_on_a_dark_background(self):
        plugin, _ = self.make_plugin(DARK_THEME)
        colors = await plugin._theme_colors(Context.new())
        self.assertEqual(colors, ((0xE6, 0xE6, 0xE6), (0x1E, 0x1E, 0x1E)))

        path = await plugin._make_qr_png(Context.new(), "hello", colors)
        self.assertEqual(_rgba_at(path, MODULE_PIXEL, MODULE_PIXEL)[:3], (0xE6, 0xE6, 0xE6))
        self.assertEqual(_rgba_at(path, QUIET_PIXEL, QUIET_PIXEL)[:3], (0x1E, 0x1E, 0x1E))

    async def test_light_theme_keeps_dark_modules_on_a_light_background(self):
        plugin, _ = self.make_plugin(LIGHT_THEME)
        colors = await plugin._theme_colors(Context.new())

        path = await plugin._make_qr_png(Context.new(), "hello", colors)
        self.assertEqual(_rgba_at(path, MODULE_PIXEL, MODULE_PIXEL)[:3], (0x10, 0x10, 0x10))
        self.assertEqual(_rgba_at(path, QUIET_PIXEL, QUIET_PIXEL)[:3], (0xFF, 0xFF, 0xFF))

    async def test_low_contrast_theme_falls_back_to_black_and_white(self):
        plugin, _ = self.make_plugin(GetThemeColorsResult(background="#808080", text="#909090"))
        self.assertIsNone(await plugin._theme_colors(Context.new()))

    async def test_missing_palette_falls_back_to_black_and_white(self):
        plugin, _ = self.make_plugin(GetThemeColorsResult())
        self.assertIsNone(await plugin._theme_colors(Context.new()))

    async def test_setting_turns_theme_colors_off(self):
        plugin, _ = self.make_plugin(DARK_THEME, settings={"theme_colors": "false"})
        self.assertIsNone(await plugin._theme_colors(Context.new()))

    async def test_query_result_icon_uses_the_theme_palette(self):
        plugin, _ = self.make_plugin(DARK_THEME)
        results = await plugin.query(Context.new(), make_query(trigger_keyword="qr", search="hello"))

        path = results[0].icon.image_data
        self.assertEqual(_rgba_at(path, MODULE_PIXEL, MODULE_PIXEL)[:3], (0xE6, 0xE6, 0xE6))

    async def test_theme_lookup_failure_falls_back_to_black_and_white(self):
        class BrokenAPI(FakeAPI):
            async def get_theme_colors(self, ctx, option=None):
                raise RuntimeError("host too old")

        plugin, _ = self.make_plugin()
        api = BrokenAPI()
        plugin.api = cast(PublicAPI, api)
        self.assertIsNone(await plugin._theme_colors(Context.new()))
        self.assertEqual([level for level, _ in api.logs], [LogLevel.WARNING])


class TestThemeColorCache(PluginTestCase):
    """Differently colored PNGs must not share a cache file."""

    async def test_each_palette_gets_its_own_cached_file(self):
        plugin, api = self.make_plugin(DARK_THEME)
        dark = await plugin._make_qr_png(Context.new(), "same text", await plugin._theme_colors(Context.new()))
        api.theme_colors = LIGHT_THEME
        light = await plugin._make_qr_png(Context.new(), "same text", await plugin._theme_colors(Context.new()))
        plain = await plugin._make_qr_png(Context.new(), "same text", None)
        self.assertEqual(len({dark, light, plain}), 3)

    async def test_same_palette_reuses_the_cached_file(self):
        plugin, _ = self.make_plugin(DARK_THEME)
        colors = await plugin._theme_colors(Context.new())
        first = await plugin._make_qr_png(Context.new(), "same text", colors)
        mtime = os.path.getmtime(first)
        second = await plugin._make_qr_png(Context.new(), "same text", colors)
        self.assertEqual(first, second)
        self.assertEqual(os.path.getmtime(second), mtime)


class TestExportColors(PluginTestCase):
    """Copied and saved images stay black and white unless the user opts in."""

    async def test_exports_are_black_and_white_by_default(self):
        plugin, api = self.make_plugin(DARK_THEME)
        await plugin._action_copy_image(Context.new(), ActionContext(context_data={"text": "hello"}))

        path = _copied_image_path(api)
        self.assertEqual(_rgba_at(path, MODULE_PIXEL, MODULE_PIXEL)[:3], (0, 0, 0))
        self.assertEqual(_rgba_at(path, QUIET_PIXEL, QUIET_PIXEL)[:3], (255, 255, 255))

    async def test_exports_follow_the_theme_when_enabled(self):
        plugin, api = self.make_plugin(DARK_THEME, settings={"theme_colors_export": "true"})
        await plugin._action_copy_image(Context.new(), ActionContext(context_data={"text": "hello"}))

        path = _copied_image_path(api)
        self.assertEqual(_rgba_at(path, MODULE_PIXEL, MODULE_PIXEL)[:3], (0xE6, 0xE6, 0xE6))

    async def test_export_ignores_theme_when_theme_colors_are_off(self):
        plugin, api = self.make_plugin(DARK_THEME, settings={"theme_colors": "false", "theme_colors_export": "true"})
        await plugin._action_copy_image(Context.new(), ActionContext(context_data={"text": "hello"}))

        path = _copied_image_path(api)
        self.assertEqual(_rgba_at(path, MODULE_PIXEL, MODULE_PIXEL)[:3], (0, 0, 0))


class TestThemedQrDecodes(PluginTestCase):
    """A theme-colored QR Code must still be readable by the scanner."""

    async def test_dark_theme_qr_round_trips(self):
        text = "https://example.com/夜间模式"
        plugin, _ = self.make_plugin(DARK_THEME)
        path = await plugin._make_qr_png(Context.new(), text, await plugin._theme_colors(Context.new()))
        self.assertEqual(decode_qr_image(path), [text])


if __name__ == "__main__":
    unittest.main()
