"""Static safety contract for passive NCL host routing.

Does not import the full ticket engine, open Chrome, or contact any site.
"""
import ast
import unittest
from pathlib import Path
from urllib.parse import urlsplit


SRC = Path(__file__).resolve().parents[1] / "src"
ROUTER = SRC / "nodriver_tixcraft.py"


class NclRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROUTER.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_router_imports_only_passive_adapter_entry(self):
        self.assertIn(
            "from platforms.ncl_openlab import nodriver_ncl_main",
            self.source,
        )
        self.assertNotIn("nodriver_ncl_booking", self.source)

    def test_exact_official_hostname_not_substring(self):
        official = "spms.ncl.edu.tw"
        self.assertEqual(urlsplit("https://spms.ncl.edu.tw/NLT/").hostname,
                         official)
        self.assertNotEqual(
            urlsplit("https://spms.ncl.edu.tw.attacker.example/").hostname,
            official)
        self.assertNotEqual(
            urlsplit("https://not-spms.ncl.edu.tw/").hostname, official)
        self.assertNotEqual(
            urlsplit("https://spms.ncl.edu.tw@evil.example/").hostname,
            official)

    def test_passive_branch_exits_before_common_refresh(self):
        nodes = [
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.If) and
            "spms.ncl.edu.tw" in ast.get_source_segment(
                self.source, n.test)
        ]
        self.assertEqual(len(nodes), 1)
        route = nodes[0]
        self.assertIsInstance(route.body[-1], ast.Continue)
        awaited = [
            n for n in ast.walk(route)
            if isinstance(n, ast.Await) and
            isinstance(n.value, ast.Call) and
            isinstance(n.value.func, ast.Name) and
            n.value.func.id == "nodriver_ncl_main"
        ]
        self.assertEqual(len(awaited), 1)
        self.assertLess(
            route.lineno,
            next(i for i, line in enumerate(self.source.splitlines(), 1)
                 if "if await check_refresh_datetime_gate(" in line))

    def test_router_does_not_call_ncl_booking_or_submit(self):
        self.assertNotIn("nodriver_ncl_booking(", self.source)
        self.assertIn("await nodriver_ncl_main(tab, url, config_dict)",
                      self.source)


if __name__ == "__main__":
    unittest.main()
