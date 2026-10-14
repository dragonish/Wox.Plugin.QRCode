import os
import tempfile
import unittest

import qrcode  # type: ignore[import-untyped]
from qrcode.image.pil import PilImage  # type: ignore[import-untyped]

from src.qrcode_main import decode_qr_image


class TestQRCodeRoundtrip(unittest.TestCase):
    def test_generate_then_decode(self):
        text = "https://example.com/中文测试?q=1"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "qr.png")
            qrcode.make(text, image_factory=PilImage).save(path)
            self.assertEqual(decode_qr_image(path), [text])

    def test_no_qr_returns_empty(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "blank.png")
            Image.new("RGB", (100, 100), "white").save(path)
            self.assertEqual(decode_qr_image(path), [])


if __name__ == "__main__":
    unittest.main()
