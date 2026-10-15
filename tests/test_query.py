import tempfile
import unittest
from typing import cast

from wox_plugin import Context, PublicAPI

from src.qrcode_main import QRCodePlugin
from tests.fakes import FakeAPI, make_query


class TestQueryRouting(unittest.IsolatedAsyncioTestCase):
    """Mode selection must not depend on the trigger keyword value.

    Users can rename or delete trigger keywords in Wox settings, so an empty
    search is the signal that routes to the screenshot scan.
    """

    def setUp(self):
        # Generating a QR code resolves the plugin cache folder through the API,
        # so the plugin needs an api instance even when init() was never called.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.plugin = QRCodePlugin()
        self.api = FakeAPI(tmp.name)
        self.plugin.api = cast(PublicAPI, self.api)

    async def test_empty_search_offers_scan_for_any_trigger_keyword(self):
        for keyword in ("qr", "qrs", "renamed-in-settings"):
            results = await self.plugin.query(Context.new(), make_query(trigger_keyword=keyword))
            self.assertEqual(results[0].sub_title, "i18n:scan_subtitle")
            self.assertEqual(results[1].title, "i18n:input_text_title")

    async def test_scan_command_returns_only_scan_results(self):
        results = await self.plugin.query(Context.new(), make_query(trigger_keyword="qr", command="scan"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].sub_title, "i18n:scan_subtitle")

    async def test_search_text_generates_qr_code(self):
        results = await self.plugin.query(Context.new(), make_query(trigger_keyword="qr", search="hello"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].sub_title, "i18n:qr_generated")


if __name__ == "__main__":
    unittest.main()
