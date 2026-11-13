import asyncio
import logging
from logging.handlers import SysLogHandler
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

from dns_server.__main__ import main, run, setup_logging


class SystemIntegrationTests(unittest.TestCase):
    def test_default_configuration_path(self):
        result = Mock()
        with patch("sys.argv", ["easydns"]), \
                patch("os.path.exists", return_value=True), \
                patch("dns_server.__main__.run", new=Mock(return_value=result)) as run, \
                patch("asyncio.run") as execute:
            main()
        run.assert_called_once_with("/etc/easydns/easydns.yaml")
        execute.assert_called_once_with(result)

    def test_explicit_configuration_path(self):
        with patch("sys.argv", ["easydns", "-c", "/tmp/custom.yaml"]), \
                patch("os.path.exists", return_value=True), \
                patch("dns_server.__main__.run", new=Mock()) as run, \
                patch("asyncio.run"):
            main()
        run.assert_called_once_with("/tmp/custom.yaml")

    def test_syslog_handler(self):
        with patch("os.path.exists", return_value=True), \
                patch("dns_server.__main__.SysLogHandler") as handler, \
                patch("logging.basicConfig") as configure:
            setup_logging({"syslog": True})
        handler.assert_called_once_with(address="/dev/log", facility=handler.LOG_DAEMON)
        self.assertEqual(configure.call_args.kwargs["handlers"], [handler.return_value])
        self.assertEqual(handler.return_value.ident, "easydns: ")

    def test_syslog_falls_back_to_stdout(self):
        with patch("os.path.exists", return_value=False), \
                patch("logging.basicConfig") as configure:
            setup_logging({"syslog": True})
        handlers = configure.call_args.kwargs["handlers"]
        self.assertEqual(len(handlers), 1)
        self.assertIsInstance(handlers[0], logging.StreamHandler)
        self.assertNotIsInstance(handlers[0], SysLogHandler)

    def test_file_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            logfile = Path(directory) / "logs" / "easydns.log"
            with patch("logging.basicConfig") as configure:
                setup_logging({"file": str(logfile)})
            handlers = configure.call_args.kwargs["handlers"]
            self.assertTrue(logfile.is_file())
            handlers[-1].close()


class StatePathTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_state_path(self):
        stopped = asyncio.Event()
        stopped.set()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("server: {id: test}\npeer_listen: {port: 0}\n")
            with patch("dns_server.__main__.setup_logging"), \
                    patch("dns_server.__main__.ZoneStore") as store, \
                    patch("dns_server.__main__.PeerManager") as peers, \
                    patch("dns_server.__main__.DnsServer") as server, \
                    patch("asyncio.Event", return_value=stopped):
                peers.return_value.start = AsyncMock()
                server.return_value.start = AsyncMock()
                server.return_value.stop = AsyncMock()
                await run(str(config))
            store.return_value.load_state.assert_called_once_with(
                "/var/cache/easydns/state.yaml"
            )
            store.return_value.save_state.assert_called_once_with(
                "/var/cache/easydns/state.yaml"
            )


if __name__ == "__main__":
    unittest.main()