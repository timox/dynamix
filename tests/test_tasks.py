#!/usr/bin/env python3
"""Background tasks: progress, stop between two steps, failures, history."""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks import Task, TaskCancelled, TaskManager


def wait(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestTask(unittest.TestCase):
    def test_progress_text_and_fraction(self):
        task = Task("Analyze selection", "set")
        self.assertEqual((task.fraction, task.progress_text()), (None, "working"))
        task.progress(3, 8, "b.wav")
        self.assertAlmostEqual(task.fraction, 0.375)
        self.assertEqual(task.progress_text(), "3/8 (38%) · b.wav")
        task.finish("done")
        task.finish("failed", "late")                       # a finished task keeps its state
        self.assertEqual((task.state, task.progress_text()), ("done", "done"))

    def test_cancel_raises_at_the_next_progress(self):
        task = Task("Pre-master")
        self.assertTrue(task.cancel())
        self.assertTrue(task.stopping)
        self.assertTrue(task.progress_text().startswith("stopping..."))
        with self.assertRaises(TaskCancelled):
            task.progress(1, 4)
        try:                                                # analysis code catches Exception: the stop passes through
            try:
                task.check()
            except Exception:
                self.fail("TaskCancelled must not be caught by `except Exception`")
        except TaskCancelled:
            pass

    def test_not_cancellable(self):
        task = Task("Scan library", cancellable=False)
        self.assertFalse(task.cancel())
        task.progress(1, 2)                                 # no exception


class TestTaskManager(unittest.TestCase):
    def test_run_done_stopped_failed(self):
        manager = TaskManager()
        gate = threading.Event()

        def slow(task):
            for i in range(1000):
                task.progress(i, 1000, f"step {i}")
                gate.set()
                time.sleep(0.005)

        stopped = []
        running = manager.start("Slow", "set")
        manager.run(running, slow, on_stopped=stopped.append)
        self.assertTrue(gate.wait(2.0))
        self.assertIs(manager.latest_stoppable(), running)
        self.assertEqual(manager.running(), [running])
        running.cancel()
        self.assertTrue(wait(lambda: running.state == "stopped"))
        self.assertEqual(stopped, [running])
        self.assertIsNone(manager.latest_stoppable())

        errors = []
        failing = manager.start("Failing")
        manager.run(failing, lambda task: 1 / 0, on_error=lambda task, exc: errors.append(type(exc).__name__))
        self.assertTrue(wait(lambda: failing.state == "failed"))
        self.assertEqual(errors, ["ZeroDivisionError"])
        self.assertIn("division", failing.error)

        quick = manager.start("Quick")
        manager.run(quick, lambda task: task.progress(1, 1))
        self.assertTrue(wait(lambda: quick.state == "done"))
        self.assertEqual([t.name for t in manager.tasks], ["Quick", "Failing", "Slow"])   # newest first
        self.assertEqual(manager.clear_finished(), 3)
        self.assertEqual(manager.tasks, [])

    def test_history_is_bounded(self):
        manager = TaskManager(keep=3)
        for i in range(6):
            manager.start(f"t{i}").finish("done")
        live = manager.start("live")
        self.assertEqual([t.name for t in manager.tasks], ["live", "t5", "t4", "t3"])
        self.assertEqual(manager.running(), [live])


if __name__ == "__main__":
    unittest.main()
