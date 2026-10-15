import os
import tempfile
import unittest
from typing import cast

import png  # type: ignore[import-untyped]
import qrcode  # type: ignore[import-untyped]
from qrcode.image.pure import PyPNGImage  # type: ignore[import-untyped]
from wox_plugin import Context, LogLevel, PublicAPI, WoxImage

from src.qrcode_main import QRCodePlugin, decode_qr_image, image_preview_data
from tests.fakes import FakeAPI


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


if __name__ == "__main__":
    unittest.main()
