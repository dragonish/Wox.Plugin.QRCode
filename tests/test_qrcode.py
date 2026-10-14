import os
import tempfile
import unittest

import png  # type: ignore[import-untyped]
import qrcode  # type: ignore[import-untyped]
from qrcode.image.pure import PyPNGImage  # type: ignore[import-untyped]
from wox_plugin import WoxImage

from src.qrcode_main import decode_qr_image, image_preview_data


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


if __name__ == "__main__":
    unittest.main()
