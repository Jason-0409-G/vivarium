from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "docs" / "site.css").read_text(encoding="utf-8")
INSTALLER = (ROOT / "install.sh").read_text(encoding="utf-8")


class PublicSiteContractTests(unittest.TestCase):
    def test_public_chinese_uses_event_log_terminology(self):
        self.assertNotIn("账本", HTML)
        self.assertIn("事件日志", HTML)

    def test_skill_cards_link_to_each_skill_contract(self):
        for skill in (
            "vivarium",
            "vivarium-prep",
            "vivarium-compare",
            "vivarium-phylo",
            "vivarium-search",
            "vivarium-report",
        ):
            expected = f"/skills/{skill}/SKILL.md"
            self.assertIn(expected, HTML)
        self.assertEqual(HTML.count('class="skill-card'), 6)

    def test_installation_tabs_cover_declared_agent_platforms(self):
        for platform in ("claude", "codex", "opencode", "openclaw", "hermes"):
            self.assertIn(f'id="tab-{platform}"', HTML)
            self.assertIn(f'id="panel-{platform}"', HTML)

    def test_local_installer_supports_declared_agent_platforms(self):
        for target in ("claude", "codex", "opencode", "openclaw", "hermes", "all"):
            self.assertRegex(INSTALLER, rf"\b{target}\b")

    def test_images_preserve_intrinsic_aspect_ratio(self):
        for selector in (".hero-visual img", ".benchmark-figure img", ".mechanism-image img"):
            rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS, re.DOTALL)
            self.assertIsNotNone(rule, selector)
            self.assertIn("height: auto", rule.group(1), selector)
            self.assertIn("object-fit: contain", rule.group(1), selector)

    def test_desktop_layout_uses_wide_viewport(self):
        width = re.search(r"--max-width:\s*(\d+)px", CSS)
        self.assertIsNotNone(width)
        self.assertGreaterEqual(int(width.group(1)), 1600)

    def test_figure_captions_are_not_overlaid_on_images(self):
        hero_caption = re.search(r"\.hero-visual figcaption\s*\{([^}]*)\}", CSS, re.DOTALL)
        self.assertIsNotNone(hero_caption)
        self.assertNotIn("position: absolute", hero_caption.group(1))
        self.assertNotIn(".mechanism-image > span", CSS)

    def test_china_friendly_cli_onboarding_is_present(self):
        self.assertIn('id="cli-setup"', HTML)
        for term in ("macOS", "Windows", "CC Switch", "DeepSeek"):
            self.assertIn(term, HTML)
        self.assertIn("registry.npmmirror.com", HTML)
        self.assertIn("DeepSeek 仅作为配置示例", HTML)


if __name__ == "__main__":
    unittest.main()
