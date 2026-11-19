import asyncio
import logging
from logging.handlers import SysLogHandler
import tempfile
from pathlib import Path
import struct
import unittest
from unittest.mock import AsyncMock, Mock, patch

from dnslib import DNSRecord

from dns_server.__main__ import main, run, setup_logging
from dns_server.resolver import Resolver
from dns_server.server import DnsTcpHandler, DnsUdpProtocol


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
                    patch("dns_server.__main__.os.path.exists", return_value=False), \
                    patch("dns_server.__main__.ZoneStore") as store, \
                    patch("dns_server.__main__.PeerManager") as peers, \
                    patch("dns_server.__main__.DnsServer") as server, \
                    patch("asyncio.Event", return_value=stopped):
                peers.return_value.start = AsyncMock()
                server.return_value.start = AsyncMock()
                server.return_value.stop = AsyncMock()
                await run(str(config))
            store.return_value.load_state.assert_called_once_with(
                "/var/lib/easydns/state.yaml"
            )
            store.return_value.save_state.assert_called_once_with(
                "/var/lib/easydns/state.yaml"
            )

    async def test_migrates_legacy_cache_state_to_persistent_directory(self):
        stopped = asyncio.Event()
        stopped.set()
        legacy_path = "/var/cache/easydns/state.yaml"
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("server: {id: test}\npeer_listen: {port: 0}\n")

            def state_exists(path):
                return path == legacy_path

            with patch("dns_server.__main__.setup_logging"), \
                    patch("dns_server.__main__.os.path.exists", side_effect=state_exists), \
                    patch("dns_server.__main__.ZoneStore") as store, \
                    patch("dns_server.__main__.PeerManager") as peers, \
                    patch("dns_server.__main__.DnsServer") as server, \
                    patch("asyncio.Event", return_value=stopped):
                peers.return_value.start = AsyncMock()
                server.return_value.start = AsyncMock()
                server.return_value.stop = AsyncMock()
                await run(str(config))

            store.return_value.load_state.assert_called_once_with(legacy_path)
            store.return_value.save_state.assert_called_with(
                "/var/lib/easydns/state.yaml"
            )
            self.assertEqual(store.return_value.save_state.call_count, 2)

    async def test_migrates_explicit_state_file_from_cache_directory(self):
        stopped = asyncio.Event()
        stopped.set()
        legacy_path = "/var/cache/easydns/custom-state.yaml"
        persistent_path = "/var/lib/easydns/custom-state.yaml"
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "server: {id: test}\n"
                "peer_listen: {port: 0}\n"
                f"state_file: {legacy_path}\n"
            )

            def state_exists(path):
                return path == legacy_path

            with patch("dns_server.__main__.setup_logging"), \
                    patch("dns_server.__main__.os.path.exists", side_effect=state_exists), \
                    patch("dns_server.__main__.ZoneStore") as store, \
                    patch("dns_server.__main__.PeerManager") as peers, \
                    patch("dns_server.__main__.DnsServer") as server, \
                    patch("asyncio.Event", return_value=stopped):
                peers.return_value.start = AsyncMock()
                server.return_value.start = AsyncMock()
                server.return_value.stop = AsyncMock()
                await run(str(config))

            store.return_value.load_state.assert_called_once_with(legacy_path)
            store.return_value.save_state.assert_called_with(persistent_path)
            self.assertEqual(store.return_value.save_state.call_count, 2)


class DnsMessageTests(unittest.IsolatedAsyncioTestCase):
    QR1_PACKET = (
        b"\x12\x34\x81\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        b"\x01a\x03krk\x03mkw\x00\x00\x01\x00\x01"
    )

    def setUp(self):
        self.query = DNSRecord.parse(self.QR1_PACKET)
        self.query.header.qr = 0
        self.response = self.query.reply()
        self.resolver = Resolver(
            zones=Mock(get_zone=Mock(return_value=None)),
            cache=Mock(get=Mock(return_value=None)),
            acl=Mock(can_read=Mock(return_value=True)),
            recursive=Mock(resolve=AsyncMock(return_value=self.response)),
        )

    async def test_qr1_is_discarded_before_resolution(self):
        packets = (
            self.QR1_PACKET,
            bytes.fromhex(
                "1234858300010000000100000161036b726b036d6b770000010001"
                "c00e0006000100000e100022036e7330c00e0561646d696ec012"
                "78a3f17500000e100000038400093a800000012c"
            ),
            b"\x12\x34\x80\x00" + b"\x00" * 8,
        )
        for packet in packets:
            with self.subTest(packet=packet.hex()):
                self.assertEqual(
                    await self.resolver.handle(packet, "127.0.0.1"), b""
                )
        for dependency in (
            self.resolver.acl, self.resolver.cache,
            self.resolver.zones, self.resolver.recursive,
        ):
            self.assertEqual(dependency.mock_calls, [])

    async def test_udp_ignores_response_and_answers_query(self):
        protocol = DnsUdpProtocol(self.resolver)
        transport = Mock()
        protocol.connection_made(transport)
        addr = ("127.0.0.1", 12345)

        await protocol._handle(self.QR1_PACKET, addr)
        transport.sendto.assert_not_called()
        await protocol._handle(self.query.pack(), addr)
        transport.sendto.assert_called_once_with(self.response.pack(), addr)

    async def test_tcp_ignores_response_and_keeps_connection_for_query(self):
        reader = asyncio.StreamReader()
        for packet in (self.QR1_PACKET, self.query.pack()):
            reader.feed_data(struct.pack("!H", len(packet)) + packet)
        reader.feed_eof()
        writer = Mock(
            get_extra_info=Mock(return_value=("127.0.0.1", 12345)),
            drain=AsyncMock(), wait_closed=AsyncMock(),
        )

        await DnsTcpHandler(self.resolver, reader, writer).run()

        response = self.response.pack()
        writer.write.assert_called_once_with(
            struct.pack("!H", len(response)) + response
        )


if __name__ == "__main__":
    unittest.main()