import os
import subprocess
import sys
import time
import unittest

from app_manager.backend import ManagerError, run
from app_manager.progress import Parser, Progress, stream


class ProgressTests(unittest.TestCase):
    def test_apt_stage_percentages_and_bad_messages(self):
        events = []
        parse = Parser(events.append)
        parse('XINGXU:running')
        parse('dlstatus:1:38.5:Retrieving file')
        parse('pmstatus:editor:62:Configuring editor')
        parse('pmstatus:editor:not-a-number:bad')
        parse('pmstatus:editor:200:bad')
        self.assertEqual(events, [Progress('授权已完成，正在准备操作'),
                                  Progress('正在下载软件包', .385), Progress('正在安装和配置', .62)])
        parse('pmstatus:editor:62:Configuring editor')
        self.assertEqual(len(events), 3)
        parse('pmstatus:editor:arm64:75:Configuring editor')
        self.assertEqual(events[-1], Progress('正在安装和配置', .75))

    def test_snap_flatpak_redraw_and_no_raw_diagnostics_in_stage(self):
        events = []
        parse = Parser(events.append)
        parse('\x1b[32mDownloading editor  23%\x1b[0m')
        parse('Installing 84.5%')
        parse('E: https://private.example failed 192.0.2.1')
        self.assertEqual(events, [Progress('正在下载', .23), Progress('正在安装和配置', .845),
                                  Progress('正在安装和配置')])
        self.assertFalse(any('https' in event.stage for event in events))

    def test_output_arrives_before_process_exit_and_preserves_diagnostics(self):
        events = []
        started = time.monotonic()
        script = "import sys,time; print('dlstatus:1:27:Download', flush=True); time.sleep(.6); print('tail', file=sys.stderr, flush=True)"
        status, output = stream([sys.executable, '-c', script], os.environ,
                                lambda event: events.append((time.monotonic() - started, event)), 5)
        self.assertEqual(status, 0)
        self.assertIn('tail', output)
        self.assertEqual(events[0][1].fraction, .27)
        self.assertLess(events[0][0], .5)

    def test_cr_only_percent_and_partial_utf8(self):
        events = []
        script = "import os; os.write(1,b'Downloading 12%\\rInstalling 50%\\r'); os.write(1,b'\\xe4'); os.write(1,b'\\xb8\\xad\\n')"
        status, output = stream([sys.executable, '-c', script], os.environ, events.append, 5)
        self.assertEqual(status, 0)
        self.assertIn('中', output)
        self.assertEqual([e.fraction for e in events[:2]], [.12, .5])

    def test_no_output_timeout_does_not_hang_and_reaps_child(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            stream([sys.executable, '-c', 'import time; time.sleep(10)'], os.environ, lambda _: None, .15)
        self.assertLess(time.monotonic() - started, 2)

    def test_nonzero_is_not_success_with_streamed_output(self):
        with self.assertRaisesRegex(ManagerError, 'command failed'):
            run([sys.executable, '-c', "import sys; print('command failed'); sys.exit(2)"], progress=lambda _: None)

    def test_diagnostic_tail_is_bounded(self):
        status, output = stream([sys.executable, '-c', "print('x' * 100000)"], os.environ, lambda _: None, 5)
        self.assertEqual(status, 0)
        self.assertLessEqual(len(output), 65536)
