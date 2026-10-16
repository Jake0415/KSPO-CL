"""Offline regression tests for SOMA traversal and fragment content."""

import unittest
from urllib.parse import parse_qs, urlsplit

from kspo_ingest.attach.discovery import discover_attachments
from kspo_ingest.crawl.soma import detail_content, discover_urls, is_board_article, popup_content

BASE = "https://soma.kspo.or.kr"


class SomaDiscoveryTests(unittest.TestCase):
    def test_same_host_only(self):
        self.assertEqual(discover_urls("", "https://other.example/list"), [])
        urls = discover_urls(
            (
                "window.open('https://other.example/x'); window.open('/login'); wi"
                "ndow.open('/ucms/contents/1');"
            ),
            BASE + "/info",
        )
        self.assertEqual(urls, [BASE + "/ucms/contents/1"])

    def test_details(self):
        for prefix in [
            "/class/",
            "/dspy/display/",
            "/dspy/colect/",
            "/draw/notice/",
            "/draw/collection/",
            "/card/news/",
        ]:
            self.assertIn(
                BASE + prefix + "44", discover_urls("goDetail('44')", BASE + prefix + "list")
            )
        self.assertIn(
            BASE + "/customer/notice/55/C01",
            discover_urls("goDetail('55','C01')", BASE + "/customer/notice/list"),
        )
        self.assertIn(
            BASE + "/draw/writer/90/view",
            discover_urls("writerDetail('90')", BASE + "/draw/writer/list"),
        )
        self.assertIn(
            BASE + "/draw/writer/90/product/list", discover_urls("", BASE + "/draw/writer/90/view")
        )

    def test_year_options_only(self):
        urls = discover_urls(
            (
                '<select id="select_yr"><option value="2004"></option><option valu'
                'e="2026"></option><option value="all"></option></select>'
            ),
            BASE + "/dspy/display/list",
        )
        self.assertEqual(len(urls), 2)

    def test_pagination_preserves_filters(self):
        html = (
            '<form id="form"><input name="category" value="C01"><input name="i'
            'gnored" type="checkbox"><select name="sort"><option value="new" s'
            'elected></option></select></form>form_goPageIndex("116")'
        )
        url = discover_urls(html, BASE + "/customer/notice/list")[0]
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["form_page_index"], ["116"])
        self.assertEqual(query["category"], ["C01"])
        self.assertNotIn("ignored", query)
        self.assertEqual(query["sort"], ["new"])

    def test_zone_cursor_and_map(self):
        seeds = discover_urls("", BASE + "/main")
        self.assertEqual(len(seeds), 12)
        urls = discover_urls(
            "checkMoreBtn('RED','Y','100');checkMoreBtn('BLUE','N','90')",
            BASE + "/piece/product/zone/list",
        )
        self.assertEqual(len(urls), 1)
        self.assertEqual(parse_qs(urlsplit(urls[0]).query)["lastKey"], ["100"])

    def test_all_77_map_pins(self):
        html = (
            '<div class="park_pin">'
            + "".join(f'<a data-key="{i}"><span>{i}</span></a>' for i in range(1, 78))
            + '<a data-key="bad"></a></div>'
        )
        urls = discover_urls(html, BASE + "/piece/product/red/map")
        self.assertEqual(len([u for u in urls if "/pop?" in u]), 77)
        self.assertIn(BASE + "/piece/product/67/pop?number=67", urls)

    def test_popup_body_and_image(self):
        title, text = popup_content(
            '<div class="park_layer"><h3>Opening up</h3><p>Artist</p><ul><li>Y'
            "ear: 1988</li><li>Material: concrete</li><li>Size: 1009x5x7</li><"
            '/ul><img src="/image.jpg" alt="Artwork"><button>Close</button><sc'
            "ript>noise</script></div>"
        )
        self.assertEqual(title, "Opening up")
        self.assertIn("1988", text)
        self.assertIn(BASE + "/image.jpg", text)
        self.assertNotIn("noise", text)
        self.assertNotIn("Close", text)
        self.assertIsNone(popup_content("<h1>Not a popup</h1>"))
        self.assertTrue(
            popup_content('<a class="park_layer_close"></a><strong>Work</strong><p>1988</p>')
        )

    def test_bulletin_dates_not_artwork_dates(self):
        for path in ["/customer/notice/10/C01", "/customer/notice/popup/10", "/draw/notice/10"]:
            self.assertTrue(is_board_article(BASE + path))
        for path in [
            "/dspy/display/10",
            "/piece/product/10/pop",
            "/draw/writer/10/view",
            "/class/10",
        ]:
            self.assertFalse(is_board_article(BASE + path, board_source_id=1))
        self.assertTrue(is_board_article("https://example.org/bbs/view.do?nttId=1"))
        self.assertFalse(is_board_article("https://example.org/about"))

    def test_detail_tables_images_and_missing_content(self):
        self.assertIsNone(detail_content("<h1>No detail container</h1>"))
        self.assertIsNone(detail_content('<div id="sub_wrap"></div>'))
        result = detail_content(
            '<title>Fallback</title><div id="sub_wrap"><h3 class="lv_tit">Work</h3>'
            "<table><tr><th>Material</th><td>Concrete</td></tr></table>"
            '<img src="/work.jpg" alt="Sculpture"><button>Noise</button></div>'
        )
        self.assertEqual(result[0], "Work")
        self.assertIn("Material | Concrete", result[1])
        self.assertIn(BASE + "/work.jpg", result[1])
        self.assertNotIn("Noise", result[1])
        self.assertTrue(detail_content('<div class="park_layer"><strong>Work</strong></div>'))

    def test_same_domain_over_200_links_and_query_identity(self):
        from kspo_ingest.crawl.internal_links import discover_internal_links

        html = "".join(f'<a href="/ucms/contents/{i}">{i}</a>' for i in range(301))
        self.assertEqual(
            len(discover_internal_links(html, base_url=BASE, host="soma.kspo.or.kr")), 301
        )
        self.assertEqual(
            len(discover_internal_links(html, base_url=BASE, host="soma.kspo.or.kr", max_links=10)),
            10,
        )
        urls = discover_internal_links(
            '<a href="/draw/writer/10/detail?writrSeq=1"></a>'
            '<a href="/draw/writer/10/detail?writrSeq=2"></a>'
            '<a href="https://other.example/a"></a>',
            base_url=BASE,
            host="soma.kspo.or.kr",
        )
        self.assertEqual(len(urls), 2)

    def test_board_paging_and_age_boundary(self):
        from datetime import UTC, datetime, timedelta

        from kspo_ingest.crawl.board import build_page_url, classify_freshness

        url = build_page_url(BASE + "/customer/notice/list", 2, param="form_page_index")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["_form_id"], ["form"])
        self.assertEqual(query["form_page_index"], ["2"])
        now = datetime(2026, 10, 12, tzinfo=UTC)
        self.assertEqual(classify_freshness(now - timedelta(days=89), now=now), "ok")
        self.assertEqual(classify_freshness(now - timedelta(days=91), now=now), "stale")

    def test_notice_popup_and_attachments(self):
        self.assertIn(
            BASE + "/customer/notice/popup/9",
            discover_urls("""<a onclick="openPopup('9')"></a>""", BASE + "/customer/notice/list"),
        )
        items = discover_attachments(
            """<a href="javascript:fn_fileDownLoad('/files/a.pdf','a.pdf')">PDF</a>""",
            base_url=BASE + "/customer/notice/9",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].file_name, "a.pdf")
        self.assertIn("/comm/file/down?", items[0].source_url)
        onclick_items = discover_attachments(
            """<a onclick="fn_fileDownLoad('/files/a.pdf','a.pdf')">PDF</a>""",
            base_url=BASE + "/customer/notice/9",
        )
        self.assertEqual(onclick_items, items)


if __name__ == "__main__":
    unittest.main()
