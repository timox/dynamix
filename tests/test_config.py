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

    def test_library_folder(self):
        from config import Config
        c = Config()
        self.assertEqual(c.get("library_folder"), "")
        c.set("library_folder", os.path.join(self.tmp, "Mixes"))
        c.save()
        self.assertEqual(Config().get("library_folder"), os.path.join(self.tmp, "Mixes"))

    def test_fx_samples_folder(self):
        from config import Config
        c = Config()
        self.assertEqual(c.get("fx_samples_folder"), "")
        c.set("fx_samples_folder", os.path.join(self.tmp, "FX"))
        c.save()
        self.assertEqual(Config().get("fx_samples_folder"), os.path.join(self.tmp, "FX"))

    def test_several_fx_sample_folders(self):
        from config import Config
        c = Config()
        self.assertEqual(c.fx_sample_folders(), [])
        one, two = os.path.join(self.tmp, "Vengeance"), os.path.join(self.tmp, "Splice")
        c.set("fx_samples_folders", [one, "", two, "  "])
        c.save()
        self.assertEqual(Config().fx_sample_folders(), [one, two])      # blanks dropped, order kept

    def test_the_single_folder_of_an_older_config_is_still_used(self):
        """A user who set one folder before must find it there, without doing anything."""
        from config import Config
        c = Config()
        c.set("fx_samples_folder", os.path.join(self.tmp, "FX"))
        c.save()
        self.assertEqual(Config().fx_sample_folders(), [os.path.join(self.tmp, "FX")])
        c.set("fx_samples_folders", [os.path.join(self.tmp, "Other")])  # the list wins once it has something
        c.save()
        self.assertEqual(Config().fx_sample_folders(), [os.path.join(self.tmp, "Other")])


if __name__ == "__main__":
    unittest.main()
