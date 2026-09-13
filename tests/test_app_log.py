import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest

import app_log


class TestAppLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_log_")
        self.stdout, self.stderr = sys.stdout, sys.stderr
        self.buffer = app_log.install(os.path.join(self.tmp, "logs"), max_lines=50)

    def tearDown(self):
        app_log.uninstall()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uninstall_restores_streams(self):
        app_log.uninstall()
        self.assertIs(sys.stdout, self.stdout)
        self.assertIs(sys.stderr, self.stderr)
        self.buffer = app_log.install(os.path.join(self.tmp, "logs"))

    def test_logger_messages_are_kept_and_drained(self):
        logging.getLogger("dynamix.test").warning("careful %d", 3)
        records = self.buffer.drain()
        self.assertEqual([(r.levelno, r.getMessage()) for r in records], [(logging.WARNING, "careful 3")])
        self.assertEqual(self.buffer.drain(), [])
        self.assertEqual(len(self.buffer.records()), 1)
        self.buffer.clear()
        self.assertEqual(self.buffer.records(), [])

    def test_buffer_is_bounded(self):
        log = logging.getLogger("dynamix.test")
        for i in range(80):
            log.info("line %d", i)
        records = self.buffer.records()
        self.assertEqual(len(records), 50)
        self.assertEqual(records[-1].getMessage(), "line 79")

    def test_print_and_stderr_are_captured(self):
        print("hello from print")
        sys.stderr.write("broken thing\npartial")
        messages = [(r.levelno, r.getMessage()) for r in self.buffer.drain()]
        self.assertIn((logging.INFO, "hello from print"), messages)
        self.assertIn((logging.ERROR, "broken thing"), messages)
        self.assertNotIn((logging.ERROR, "partial"), messages)  # no newline yet

    def test_thread_exception_is_logged_with_traceback(self):
        def boom():
            raise ZeroDivisionError("nope")
        t = threading.Thread(target=boom, name="worker-1")
        t.start()
        t.join()
        errors = self.buffer.records(logging.ERROR)
        self.assertEqual(len(errors), 1)
        text = app_log.format_record(errors[0])
        self.assertIn("Error in thread worker-1: nope", text)
        self.assertIn("Traceback", text)
        self.assertIn("ZeroDivisionError", text)

    def test_python_warnings_are_warnings(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn("old api", DeprecationWarning)
        records = self.buffer.drain()
        self.assertTrue(any(r.levelno == logging.WARNING and "old api" in r.getMessage() for r in records))
        self.assertEqual(self.buffer.records(logging.ERROR), [])

    def test_file_is_written(self):
        logging.getLogger("dynamix.test").error("to the file")
        app_log._STATE["file_handler"].flush()
        with open(os.path.join(self.tmp, "logs", "dynamix.log"), encoding="utf-8") as f:
            self.assertIn("to the file", f.read())


if __name__ == "__main__":
    unittest.main()
