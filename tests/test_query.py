import unittest

from wox_plugin import Context, Query, QueryEnv, QueryType, Selection

from src.qrcode_main import QRCodePlugin


def _query(trigger_keyword: str = "", command: str = "", search: str = "") -> Query:
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


class TestQueryRouting(unittest.IsolatedAsyncioTestCase):
    """Mode selection must not depend on the trigger keyword value.

    Users can rename or delete trigger keywords in Wox settings, so an empty
    search is the signal that routes to the screenshot scan.
    """

    async def test_empty_search_offers_scan_for_any_trigger_keyword(self):
        plugin = QRCodePlugin()
        for keyword in ("qr", "qrs", "renamed-in-settings"):
            results = await plugin.query(Context.new(), _query(trigger_keyword=keyword))
            self.assertEqual(results[0].sub_title, "i18n:scan_subtitle")
            self.assertEqual(results[1].title, "i18n:input_text_title")

    async def test_scan_command_returns_only_scan_results(self):
        plugin = QRCodePlugin()
        results = await plugin.query(Context.new(), _query(trigger_keyword="qr", command="scan"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].sub_title, "i18n:scan_subtitle")

    async def test_search_text_generates_qr_code(self):
        plugin = QRCodePlugin()
        results = await plugin.query(Context.new(), _query(trigger_keyword="qr", search="hello"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].sub_title, "i18n:qr_generated")


if __name__ == "__main__":
    unittest.main()
