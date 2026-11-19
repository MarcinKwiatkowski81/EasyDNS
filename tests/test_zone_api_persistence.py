import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from dns_server.api import ApiError, ApiServer
from dns_server.zone import ZoneStore


def dispatch(api, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    try:
        return api._dispatch(method, path, {}, body)
    except ApiError as exc:
        return exc.status, {"message": exc.message}


class ZoneApiPersistenceTests(unittest.TestCase):
    def make_api(self, zones, state_file):
        return ApiServer(
            host="127.0.0.1",
            port=0,
            resolver=Mock(),
            zones=zones,
            acl=Mock(),
            cache=Mock(),
            state_file=str(state_file) if state_file is not None else None,
        )

    def test_api_record_changes_are_persisted_and_identical_adds_are_idempotent(self):
        config_zones = [{
            "name": "example.test",
            "records": [{
                "name": "@", "type": "A", "ttl": 300, "value": "192.0.2.1",
            }],
        }]

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.yaml"
            zones = ZoneStore("test")
            zones.load_from_config(config_zones)
            api = self.make_api(zones, state_file)
            record = {
                "name": "www",
                "type": "A",
                "ttl": 300,
                "rdata": {"value": "192.0.2.2"},
            }

            first_status, first = dispatch(
                api, "POST", "/api/v1/zones/example.test/records", record
            )
            duplicate_status, duplicate = dispatch(
                api, "POST", "/api/v1/zones/example.test/records", record
            )

            self.assertEqual(first_status, 201)
            self.assertEqual(duplicate_status, 200)
            self.assertEqual(first["uid"], duplicate["uid"])
            self.assertTrue(state_file.is_file())

            updated_status, updated = dispatch(
                api,
                "PUT",
                "/api/v1/zones/example.test/records",
                {
                    "uid": first["uid"],
                    "name": "www",
                    "type": "A",
                    "ttl": 600,
                    "rdata": {"value": "192.0.2.3"},
                },
            )
            self.assertEqual(updated_status, 200)
            self.assertEqual(updated["rdata"]["value"], "192.0.2.3")

            apex_uid = next(
                rr.uid for rr in zones.zones["example.test."].all_active()
                if rr.name == ""
            )
            self.assertEqual(
                dispatch(
                    api,
                    "PUT",
                    "/api/v1/zones/example.test/records",
                    {
                        "uid": apex_uid,
                        "name": "@",
                        "type": "A",
                        "ttl": 300,
                        "rdata": {"value": "192.0.2.9"},
                    },
                )[0],
                200,
            )

            restored = ZoneStore("test")
            restored.load_from_config(config_zones)
            restored.load_state(str(state_file))
            active = restored.zones["example.test."].all_active()
            self.assertEqual(len(active), 2)
            self.assertEqual(
                next(rr for rr in active if rr.name == "www").rdata["value"],
                "192.0.2.3",
            )
            self.assertEqual(
                next(rr for rr in active if rr.name == "").rdata["value"],
                "192.0.2.9",
            )

            restored_api = self.make_api(restored, state_file)
            self.assertEqual(
                dispatch(
                    restored_api,
                    "DELETE",
                    "/api/v1/zones/example.test/records",
                    {"uid": first["uid"]},
                )[0],
                200,
            )
            restored_again = ZoneStore("test")
            restored_again.load_from_config(config_zones)
            restored_again.load_state(str(state_file))
            remaining = restored_again.zones["example.test."].all_active()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].rdata["value"], "192.0.2.9")

    def test_zone_add_rename_and_delete_persist_across_restart(self):
        config_zones = [{"name": "example.test", "records": []}]

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.yaml"
            zones = ZoneStore("test")
            zones.load_from_config(config_zones)
            api = self.make_api(zones, state_file)

            self.assertEqual(
                dispatch(api, "POST", "/api/v1/zones", {"name": "new.test"})[0],
                201,
            )
            self.assertEqual(
                dispatch(
                    api, "PUT", "/api/v1/zones/example.test",
                    {"name": "moved.test"},
                )[0],
                200,
            )

            restored = ZoneStore("test")
            restored.load_from_config(config_zones)
            restored.load_state(str(state_file))
            self.assertEqual(set(restored.zones), {"new.test.", "moved.test."})

            api = self.make_api(restored, state_file)
            self.assertEqual(
                dispatch(api, "DELETE", "/api/v1/zones/moved.test")[0],
                200,
            )
            restored_again = ZoneStore("test")
            restored_again.load_from_config(config_zones)
            restored_again.load_state(str(state_file))
            self.assertEqual(set(restored_again.zones), {"new.test."})

    def test_recreated_configured_zone_stays_empty_after_restart(self):
        config_zones = [{
            "name": "example.test",
            "records": [{
                "name": "@", "type": "A", "ttl": 300, "value": "192.0.2.1",
            }],
        }]

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.yaml"
            zones = ZoneStore("test")
            zones.load_from_config(config_zones)
            api = self.make_api(zones, state_file)
            self.assertEqual(
                dispatch(api, "DELETE", "/api/v1/zones/example.test")[0],
                200,
            )
            self.assertEqual(
                dispatch(api, "POST", "/api/v1/zones", {"name": "example.test"})[0],
                201,
            )

            restored = ZoneStore("test")
            restored.load_from_config(config_zones)
            restored.load_state(str(state_file))
            self.assertEqual(restored.zones["example.test."].all_active(), [])

    def test_invalid_and_duplicate_zone_operations_return_client_errors(self):
        zones = ZoneStore("test")
        zones.add_zone("example.test")
        api = self.make_api(zones, None)

        self.assertEqual(
            dispatch(api, "POST", "/api/v1/zones", {"name": "bad..test"})[0],
            400,
        )
        self.assertEqual(
            dispatch(api, "POST", "/api/v1/zones", {"name": "example.test"})[0],
            409,
        )
        self.assertEqual(
            dispatch(
                api, "PUT", "/api/v1/zones/example.test",
                {"name": "example.test"},
            )[0],
            200,
        )
        self.assertEqual(
            dispatch(api, "DELETE", "/api/v1/zones/missing.test")[0],
            404,
        )


if __name__ == "__main__":
    unittest.main()
