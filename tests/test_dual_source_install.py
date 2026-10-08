import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DualSourceInstallTests(unittest.TestCase):
    def test_self_verify_is_pinned_to_copy_being_installed(self):
        installer = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        block = installer.split("verify_install()", 1)[1].split("\n}", 1)[0]
        self.assertIn('HERMES_WECHAT_ENHANCE_SOURCE_DIR="$SKILL_DIR"', block)
        self.assertIn('python3 "$SKILL_DIR/scripts/verify-self-install.py"', block)


if __name__ == "__main__":
    unittest.main()
