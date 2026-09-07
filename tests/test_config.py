import os
import shutil
import tempfile
import unittest


class TestConfig(unittest.TestCase):
    def setUp(self):
        import analysis_store
        self.tmp = tempfile.mkdtemp(prefix="dynamix_cfg_")
        os.environ["DYNAMIX_HOME"] = self.tmp
        analysis_store.reset_store()

    def tearDown(self):
        import analysis_store
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_and_roundtrip(self):
        from config import Config, DEFAULTS
        c = Config()
        self.assertEqual(c.get("target_lufs"), DEFAULTS["target_lufs"])
        c.set("target_lufs", -12.0)
        c.set("projects_root", os.path.join(self.tmp, "proj"))
        c.save()
        d = Config()
        self.assertEqual(d.get("target_lufs"), -12.0)
        self.assertEqual(d.projects_root, os.path.join(self.tmp, "proj"))
        self.assertEqual(set(d.project_defaults()), {"set_duration", "energy_curve", "mix_bars", "target_lufs", "tone_match", "fix_phase", "mono_bass_hz"})

    def test_environment_report(self):
        from config import environment_report, format_environment_report
        rows = environment_report()
        labels = [r[0] for r in rows]
        self.assertIn("Python", labels)
        self.assertIn("Analysis cache", labels)
        self.assertTrue(all(len(r) == 3 for r in rows))
        self.assertIn("[OK  ] Python", format_environment_report())


if __name__ == "__main__":
    unittest.main()
