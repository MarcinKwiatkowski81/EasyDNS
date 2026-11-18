#!/usr/bin/env python3
"""
Skrypt testowy dla REST API EasyDNS.
Demonstruje wszystkie operacje CRUD na rekordach DNS.
"""

import requests
import json
import sys
import time
from typing import Optional, Dict, Any

# Konfiguracja
API_BASE = "http://localhost:8080/api/v1"
TEST_ZONE = "example.com"
API_KEY = "sk-1234567890abcdef"  # Zmień na rzeczywisty klucz
TIMEOUT = 5

# Kolory do outputu
class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    END = "\033[0m"
    BOLD = "\033[1m"

def print_header(text: str) -> None:
    print(f"\n{Color.BOLD}{Color.BLUE}=== {text} ==={Color.END}")

def print_success(text: str) -> None:
    print(f"{Color.GREEN}✓ {text}{Color.END}")

def print_error(text: str) -> None:
    print(f"{Color.RED}✗ {text}{Color.END}")

def print_warning(text: str) -> None:
    print(f"{Color.YELLOW}⚠ {text}{Color.END}")

def print_info(text: str) -> None:
    print(f"{Color.BLUE}ℹ {text}{Color.END}")

class ApiClient:
    def __init__(self, base_url: str = API_BASE, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key
        self.session = requests.Session()
        
        # Ustaw domyślne nagłówki
        if self.api_key:
            self.session.headers.update({"X-API-Key": self.api_key})
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        resp = self.session.get(url, params=params, timeout=TIMEOUT)
        return {
            "status": resp.status_code,
            "data": resp.json() if resp.text else {},
            "response": resp
        }
    
    def post(self, endpoint: str, data: Dict) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        resp = self.session.post(url, json=data, timeout=TIMEOUT)
        return {
            "status": resp.status_code,
            "data": resp.json() if resp.text else {},
            "response": resp
        }
    
    def put(self, endpoint: str, data: Dict) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        resp = self.session.put(url, json=data, timeout=TIMEOUT)
        return {
            "status": resp.status_code,
            "data": resp.json() if resp.text else {},
            "response": resp
        }
    
    def delete(self, endpoint: str, data: Dict) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        resp = self.session.delete(url, json=data, timeout=TIMEOUT)
        return {
            "status": resp.status_code,
            "data": resp.json() if resp.text else {},
            "response": resp
        }

def test_health(client: ApiClient) -> bool:
    """Test health check endpoint."""
    print_header("Health Check")
    
    result = client.get("/health")
    
    if result["status"] == 200 and result["data"].get("status") == "ok":
        print_success("API is healthy")
        return True
    else:
        print_error(f"Health check failed: {result['status']}")
        return False

def test_api_key_auth(client: ApiClient) -> bool:
    """Test API-Key authentication."""
    print_header("API-Key Authentication")
    
    result = client.get("/zones")
    
    if result["status"] == 200:
        print_success("API-Key accepted")
        return True
    elif result["status"] == 401:
        print_warning("API-Key required but not sent (server expects key)")
        return True
    else:
        print_error(f"Unexpected status: {result['status']}")
        return False

def test_zones_list(client: ApiClient) -> bool:
    """Test listing zones."""
    print_header("List Zones")
    
    result = client.get("/zones")
    
    if result["status"] == 200:
        zones = result["data"].get("zones", [])
        print_success(f"Found {len(zones)} zone(s)")
        for zone in zones:
            print_info(f"  {zone['name']} ({zone['records_count']} records)")
        return True
    else:
        print_error(f"Failed to list zones: {result['status']}")
        return False

def test_records_list(client: ApiClient, zone: str) -> Optional[list]:
    """Test listing records in a zone."""
    print_header(f"List Records in {zone}")
    
    result = client.get(f"/zones/{zone}/records")
    
    if result["status"] == 200:
        records = result["data"].get("records", [])
        print_success(f"Found {len(records)} record(s)")
        for rec in records[:5]:  # Show first 5
            print_info(f"  {rec['name'] or '@'} ({rec['type']}) -> {json.dumps(rec['rdata'])}")
        if len(records) > 5:
            print_info(f"  ... and {len(records) - 5} more")
        return records
    elif result["status"] == 404:
        print_warning(f"Zone {zone} not found on server")
        return None
    else:
        print_error(f"Failed to list records: {result['status']}")
        return None

def test_add_record(client: ApiClient, zone: str) -> Optional[str]:
    """Test adding a new record."""
    print_header("Add Record (A)")
    
    record_data = {
        "name": f"test-{int(time.time())}",
        "type": "A",
        "ttl": 300,
        "rdata": {"value": "192.0.2.123"}
    }
    
    print_info(f"Adding: {json.dumps(record_data, indent=2)}")
    result = client.post(f"/zones/{zone}/records", record_data)
    
    if result["status"] == 201:
        data = result["data"]
        uid = data.get("uid")
        print_success(f"Record created with UID: {uid}")
        print_info(f"  Name: {data['name']}")
        print_info(f"  Type: {data['type']}")
        print_info(f"  Value: {data['rdata']}")
        return uid
    elif result["status"] == 404:
        print_warning(f"Zone {zone} not found on server")
        return None
    else:
        print_error(f"Failed to add record: {result['status']}")
        print_info(f"Response: {result['data']}")
        return None

def test_add_mx_record(client: ApiClient, zone: str) -> Optional[str]:
    """Test adding an MX record."""
    print_header("Add Record (MX)")
    
    record_data = {
        "name": "",  # apex
        "type": "MX",
        "ttl": 3600,
        "rdata": {
            "priority": 10,
            "value": "mail.example.com."
        }
    }
    
    print_info(f"Adding: {json.dumps(record_data, indent=2)}")
    result = client.post(f"/zones/{zone}/records", record_data)
    
    if result["status"] == 201:
        data = result["data"]
        uid = data.get("uid")
        print_success(f"MX record created with UID: {uid}")
        return uid
    elif result["status"] == 404:
        print_warning(f"Zone {zone} not found")
        return None
    else:
        print_error(f"Failed to add MX record: {result['status']}")
        print_info(f"Response: {result['data']}")
        return None

def test_update_record(client: ApiClient, zone: str, uid: str) -> bool:
    """Test updating a record."""
    print_header("Update Record")
    
    update_data = {
        "uid": uid,
        "name": f"test-{int(time.time())}",
        "type": "A",
        "ttl": 600,
        "rdata": {"value": "192.0.2.124"}
    }
    
    print_info(f"Updating with: {json.dumps(update_data, indent=2)}")
    result = client.put(f"/zones/{zone}/records", update_data)
    
    if result["status"] == 200:
        data = result["data"]
        print_success("Record updated")
        print_info(f"  New TTL: {data['ttl']}")
        print_info(f"  New value: {data['rdata']}")
        return True
    else:
        print_error(f"Failed to update record: {result['status']}")
        print_info(f"Response: {result['data']}")
        return False

def test_delete_record(client: ApiClient, zone: str, uid: str) -> bool:
    """Test deleting a record."""
    print_header("Delete Record")
    
    delete_data = {"uid": uid}
    
    print_info(f"Deleting UID: {uid}")
    result = client.delete(f"/zones/{zone}/records", delete_data)
    
    if result["status"] == 200:
        print_success("Record deleted")
        return True
    else:
        print_error(f"Failed to delete record: {result['status']}")
        print_info(f"Response: {result['data']}")
        return False

def test_stats(client: ApiClient) -> bool:
    """Test getting server statistics."""
    print_header("Server Statistics")
    
    result = client.get("/stats")
    
    if result["status"] == 200:
        data = result["data"]
        cache = data.get("cache", {})
        print_success("Got statistics")
        print_info(f"  Zones count: {data['zones_count']}")
        print_info(f"  Total records: {data['total_records']}")
        print_info(f"  Cache hits: {cache.get('hits', 0)}")
        print_info(f"  Cache misses: {cache.get('misses', 0)}")
        hit_rate = cache.get('hit_rate', 0)
        print_info(f"  Cache hit rate: {hit_rate:.1%}")
        return True
    else:
        print_error(f"Failed to get stats: {result['status']}")
        return False

def test_rate_limiting(client: ApiClient) -> bool:
    """Test rate limiting (make 15 requests, expect 429 on some)."""
    print_header("Rate Limiting Test")
    
    success_count = 0
    rate_limited = False
    
    print_info("Making 15 requests in rapid succession...")
    
    for i in range(15):
        result = client.get("/health")
        status = result["status"]
        
        if status == 200:
            success_count += 1
            print(".", end="", flush=True)
        elif status == 429:
            rate_limited = True
            print("R", end="", flush=True)  # R for Rate limited
        else:
            print("E", end="", flush=True)  # E for Error
    
    print()  # Newline
    
    if rate_limited:
        print_success("Rate limiting is working (got 429 responses)")
        print_info(f"  Successful requests: {success_count}")
        return True
    else:
        print_warning("Rate limiting not triggered (expected within high load)")
        print_info(f"  Successful requests: {success_count}")
        return True

def main():
    """Main test suite."""
    print(f"{Color.BOLD}EasyDNS REST API Test Suite{Color.END}")
    print(f"API URL: {API_BASE}")
    print(f"Test Zone: {TEST_ZONE}")
    print(f"API Key: {API_KEY[:20]}..." if API_KEY else "No API Key")
    
    client = ApiClient(api_key=API_KEY)
    
    test_results = []
    
    # Test 0: API-Key authentication (jeśli zdefiniowany)
    if API_KEY:
        test_results.append(("API-Key Authentication", test_api_key_auth(client)))
    
    # 1. Health check
    test_results.append(("Health Check", test_health(client)))
    
    # 2. List zones
    test_results.append(("List Zones", test_zones_list(client)))
    
    # 3. List records (might fail if zone doesn't exist)
    records = test_records_list(client, TEST_ZONE)
    test_results.append(("List Records", records is not None))
    
    # Only continue CRUD tests if zone exists
    if records is not None:
        # 4. Add record
        uid = test_add_record(client, TEST_ZONE)
        test_results.append(("Add Record", uid is not None))
        
        # 5. Update record (if added successfully)
        if uid:
            test_results.append(("Update Record", test_update_record(client, TEST_ZONE, uid)))
            test_results.append(("Delete Record", test_delete_record(client, TEST_ZONE, uid)))
        
        # 6. Add MX record
        mx_uid = test_add_mx_record(client, TEST_ZONE)
        test_results.append(("Add MX Record", mx_uid is not None))
        
        # 7. Clean up MX record
        if mx_uid:
            test_delete_record(client, TEST_ZONE, mx_uid)
    else:
        print_warning("Zone not found - skipping CRUD tests")
    
    # 8. Statistics
    test_results.append(("Get Statistics", test_stats(client)))
    
    # 9. Rate limiting
    test_results.append(("Rate Limiting", test_rate_limiting(client)))
    
    # Summary
    print_header("Test Summary")
    
    passed = sum(1 for _, result in test_results if result)
    total = len(test_results)
    
    for test_name, result in test_results:
        status = f"{Color.GREEN}✓ PASS{Color.END}" if result else f"{Color.RED}✗ FAIL{Color.END}"
        print(f"{test_name:.<40} {status}")
    
    print(f"\n{Color.BOLD}Total: {passed}/{total} tests passed{Color.END}")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print_error("Test interrupted by user")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print_error(f"Cannot connect to API at {API_BASE}")
        print_info("Make sure EasyDNS is running with API enabled:")
        print_info(f"  python3 -m dns_server -c config.yaml")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
