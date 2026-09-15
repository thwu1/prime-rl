#!/usr/bin/env python3

"""
Simulated Cisco DNA Center REST API.
Provides device inventory, compliance assessments, assurance issues,
site hierarchy, and network health data for a 5-device managed network.
"""

import base64
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

VALID_TOKEN = "eyJhbGciOiJIUzI1NiJ9.ewogICJzdWIiOiAiYWRtaW4iLAogICJhdXRoU291cmNlIjogImludGVybmFsIiwKICAidGVuYW50TmFtZSI6ICJUbkFCQ0RFRiIKfQ.sim_dnac_v1"
CREDENTIALS = "admin:Cisco123!"

DEVICES = [
    {
        "id": "3a1fb7e2-4d5c-8a90-1234-567890abcd01",
        "hostname": "R1-CORE",
        "managementIpAddress": "10.0.0.1",
        "platformId": "C8000V",
        "softwareVersion": "17.9.5",
        "role": "CORE",
        "series": "Cisco Catalyst 8000V Edge Software",
        "serialNumber": "9ABCDEF001",
        "macAddress": "52:54:00:01:00:01",
        "upTime": "45 days, 12:34:56",
        "reachabilityStatus": "Reachable",
        "lastUpdated": "2025-06-09T14:30:00.000Z",
        "family": "Routers"
    },
    {
        "id": "3a1fb7e2-4d5c-8a90-1234-567890abcd02",
        "hostname": "R2-DIST-W",
        "managementIpAddress": "10.0.0.2",
        "platformId": "C8000V",
        "softwareVersion": "17.9.5",
        "role": "DISTRIBUTION",
        "series": "Cisco Catalyst 8000V Edge Software",
        "serialNumber": "9ABCDEF002",
        "macAddress": "52:54:00:02:00:01",
        "upTime": "45 days, 12:34:56",
        "reachabilityStatus": "Reachable",
        "lastUpdated": "2025-06-09T14:30:00.000Z",
        "family": "Routers"
    },
    {
        "id": "3a1fb7e2-4d5c-8a90-1234-567890abcd03",
        "hostname": "R3-DIST-E",
        "managementIpAddress": "10.0.0.3",
        "platformId": "C8000V",
        "softwareVersion": "17.9.5",
        "role": "DISTRIBUTION",
        "series": "Cisco Catalyst 8000V Edge Software",
        "serialNumber": "9ABCDEF003",
        "macAddress": "52:54:00:03:00:01",
        "upTime": "45 days, 12:34:56",
        "reachabilityStatus": "Reachable",
        "lastUpdated": "2025-06-09T14:30:00.000Z",
        "family": "Routers"
    },
    {
        "id": "3a1fb7e2-4d5c-8a90-1234-567890abcd04",
        "hostname": "R4-BRANCH-W",
        "managementIpAddress": "10.0.0.4",
        "platformId": "C8000V",
        "softwareVersion": "17.9.5",
        "role": "ACCESS",
        "series": "Cisco Catalyst 8000V Edge Software",
        "serialNumber": "9ABCDEF004",
        "macAddress": "52:54:00:04:00:01",
        "upTime": "30 days, 08:22:11",
        "reachabilityStatus": "Reachable",
        "lastUpdated": "2025-06-09T14:30:00.000Z",
        "family": "Routers"
    },
    {
        "id": "3a1fb7e2-4d5c-8a90-1234-567890abcd05",
        "hostname": "R5-BRANCH-E",
        "managementIpAddress": "10.0.0.5",
        "platformId": "C8000V",
        "softwareVersion": "17.9.5",
        "role": "ACCESS",
        "series": "Cisco Catalyst 8000V Edge Software",
        "serialNumber": "9ABCDEF005",
        "macAddress": "52:54:00:05:00:01",
        "upTime": "30 days, 08:22:11",
        "reachabilityStatus": "Reachable",
        "lastUpdated": "2025-06-09T14:30:00.000Z",
        "family": "Routers"
    }
]

COMPLIANCE = [
    {
        "deviceUuid": "3a1fb7e2-4d5c-8a90-1234-567890abcd01",
        "complianceStatus": "COMPLIANT",
        "lastUpdateTime": 1717940400000,
        "categories": [
            {"complianceType": "RUNNING_CONFIG", "status": "COMPLIANT"},
            {"complianceType": "SOFTWARE_IMAGE", "status": "COMPLIANT"},
            {"complianceType": "PSIRT", "status": "NOT_APPLICABLE"}
        ]
    },
    {
        "deviceUuid": "3a1fb7e2-4d5c-8a90-1234-567890abcd02",
        "complianceStatus": "COMPLIANT",
        "lastUpdateTime": 1717940400000,
        "categories": [
            {"complianceType": "RUNNING_CONFIG", "status": "COMPLIANT"},
            {"complianceType": "SOFTWARE_IMAGE", "status": "COMPLIANT"},
            {"complianceType": "PSIRT", "status": "NOT_APPLICABLE"}
        ]
    },
    {
        "deviceUuid": "3a1fb7e2-4d5c-8a90-1234-567890abcd03",
        "complianceStatus": "NON_COMPLIANT",
        "lastUpdateTime": 1717940400000,
        "categories": [
            {
                "complianceType": "RUNNING_CONFIG",
                "status": "NON_COMPLIANT",
                "details": [
                    {
                        "name": "Interface MTU Configuration",
                        "status": "NON_COMPLIANT",
                        "configElement": "interface GigabitEthernet0/2",
                        "remediationAction": "Set ip mtu to 1500",
                        "description": "IP MTU on GigabitEthernet0/2 is 9000, design template specifies 1500"
                    }
                ]
            },
            {"complianceType": "SOFTWARE_IMAGE", "status": "COMPLIANT"},
            {"complianceType": "PSIRT", "status": "NOT_APPLICABLE"}
        ]
    },
    {
        "deviceUuid": "3a1fb7e2-4d5c-8a90-1234-567890abcd04",
        "complianceStatus": "COMPLIANT",
        "lastUpdateTime": 1717940400000,
        "categories": [
            {"complianceType": "RUNNING_CONFIG", "status": "COMPLIANT"},
            {"complianceType": "SOFTWARE_IMAGE", "status": "COMPLIANT"},
            {"complianceType": "PSIRT", "status": "NOT_APPLICABLE"}
        ]
    },
    {
        "deviceUuid": "3a1fb7e2-4d5c-8a90-1234-567890abcd05",
        "complianceStatus": "NON_COMPLIANT",
        "lastUpdateTime": 1717940400000,
        "categories": [
            {
                "complianceType": "RUNNING_CONFIG",
                "status": "NON_COMPLIANT",
                "details": [
                    {
                        "name": "OSPF Area Type",
                        "status": "NON_COMPLIANT",
                        "configElement": "router ospf 1",
                        "remediationAction": "Change area 20 from stub to nssa",
                        "description": "OSPF area 20 is configured as stub, design intent requires NSSA"
                    }
                ]
            },
            {"complianceType": "SOFTWARE_IMAGE", "status": "COMPLIANT"},
            {"complianceType": "PSIRT", "status": "NOT_APPLICABLE"}
        ]
    }
]

ISSUES = [
    {
        "issueId": "AI-001",
        "name": "Interface MTU Mismatch Detected",
        "deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd03",
        "deviceName": "R3-DIST-E",
        "issueSource": "Assurance",
        "issuePriority": "P2",
        "issueSeverity": "HIGH",
        "issueCategory": "Connectivity",
        "issueDescription": "Interface GigabitEthernet0/2 on R3-DIST-E has IP MTU 9000 which differs from the peer R2-DIST-W (MTU 1500). This will prevent OSPF adjacency from forming on this link.",
        "suggestedActions": ["Set ip mtu 1500 on R3-DIST-E GigabitEthernet0/2"],
        "status": "active",
        "lastOccurrence": "2025-06-09T13:00:00.000Z"
    },
    {
        "issueId": "AI-002",
        "name": "OSPF Area Type Mismatch",
        "deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd05",
        "deviceName": "R5-BRANCH-E",
        "issueSource": "Assurance",
        "issuePriority": "P1",
        "issueSeverity": "CRITICAL",
        "issueCategory": "Connectivity",
        "issueDescription": "OSPF area 20 on R5-BRANCH-E is configured as stub, but peer R3-DIST-E has it as NSSA. The N-bit mismatch in Hello packets will prevent adjacency formation.",
        "suggestedActions": ["Change area 20 stub to area 20 nssa on R5-BRANCH-E under router ospf 1"],
        "status": "active",
        "lastOccurrence": "2025-06-09T13:00:00.000Z"
    },
    {
        "issueId": "AI-003",
        "name": "DHCP Relay Configuration Missing",
        "deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd02",
        "deviceName": "R2-DIST-W",
        "issueSource": "Assurance",
        "issuePriority": "P3",
        "issueSeverity": "MEDIUM",
        "issueCategory": "Application",
        "issueDescription": "Interface GigabitEthernet0/1 on R2-DIST-W does not have ip helper-address configured. Clients on the connected branch segment may not receive DHCP addresses.",
        "suggestedActions": ["Configure ip helper-address on GigabitEthernet0/1 pointing to DHCP server"],
        "status": "active",
        "lastOccurrence": "2025-06-09T12:00:00.000Z"
    }
]

SITES = [
    {
        "id": "site-global-001",
        "siteNameHierarchy": "Global",
        "siteType": "area",
        "additionalInfo": [{"nameSpace": "Location", "attributes": {"type": "area"}}]
    },
    {
        "id": "site-campus-001",
        "siteNameHierarchy": "Global/Enterprise-Campus",
        "siteType": "area",
        "parentId": "site-global-001",
        "additionalInfo": [{"nameSpace": "Location", "attributes": {"type": "area"}}]
    },
    {
        "id": "site-bldg-core-001",
        "siteNameHierarchy": "Global/Enterprise-Campus/Core-DC",
        "siteType": "building",
        "parentId": "site-campus-001",
        "additionalInfo": [{"nameSpace": "Location", "attributes": {"type": "building"}}]
    },
    {
        "id": "site-floor-core-001",
        "siteNameHierarchy": "Global/Enterprise-Campus/Core-DC/Floor-1",
        "siteType": "floor",
        "parentId": "site-bldg-core-001",
        "additionalInfo": [{"nameSpace": "mapsSummary", "attributes": {"rfModel": "Cubes And Walled Offices"}}]
    },
    {
        "id": "site-bldg-west-001",
        "siteNameHierarchy": "Global/Enterprise-Campus/Branch-West",
        "siteType": "building",
        "parentId": "site-campus-001",
        "additionalInfo": [{"nameSpace": "Location", "attributes": {"type": "building"}}]
    },
    {
        "id": "site-bldg-east-001",
        "siteNameHierarchy": "Global/Enterprise-Campus/Branch-East",
        "siteType": "building",
        "parentId": "site-campus-001",
        "additionalInfo": [{"nameSpace": "Location", "attributes": {"type": "building"}}]
    }
]

HEALTH = {
    "healthDistir498": {
        "totalCount": 5,
        "healthScore": [
            {"healthType": "POOR", "percentage": 20, "count": 1},
            {"healthType": "FAIR", "percentage": 20, "count": 1},
            {"healthType": "GOOD", "percentage": 60, "count": 3}
        ]
    },
    "latestHealthScore": [
        {"category": "NETWORK_DEVICE", "score": 72},
        {"category": "CLIENT", "score": 85},
        {"category": "APPLICATION", "score": 90}
    ],
    "deviceHealthDetails": [
        {"deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd01", "name": "R1-CORE", "overallHealth": 90, "issueCount": 0, "interfaceLinkErrHealth": 100, "cpuUlitilization": 12, "memoryUtilization": 34},
        {"deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd02", "name": "R2-DIST-W", "overallHealth": 80, "issueCount": 1, "interfaceLinkErrHealth": 100, "cpuUlitilization": 8, "memoryUtilization": 28},
        {"deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd03", "name": "R3-DIST-E", "overallHealth": 55, "issueCount": 1, "interfaceLinkErrHealth": 70, "cpuUlitilization": 15, "memoryUtilization": 31},
        {"deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd04", "name": "R4-BRANCH-W", "overallHealth": 85, "issueCount": 0, "interfaceLinkErrHealth": 100, "cpuUlitilization": 6, "memoryUtilization": 22},
        {"deviceId": "3a1fb7e2-4d5c-8a90-1234-567890abcd05", "name": "R5-BRANCH-E", "overallHealth": 45, "issueCount": 1, "interfaceLinkErrHealth": 60, "cpuUlitilization": 9, "memoryUtilization": 25}
    ]
}

# Map device IDs to router names for quick lookup
_DEV_ID_TO_ROUTER = {d["id"]: d["hostname"].split("-")[0] for d in DEVICES}
_DEV_ID_TO_SITE = {
    "3a1fb7e2-4d5c-8a90-1234-567890abcd01": "site-bldg-core-001",
    "3a1fb7e2-4d5c-8a90-1234-567890abcd02": "site-bldg-west-001",
    "3a1fb7e2-4d5c-8a90-1234-567890abcd03": "site-bldg-east-001",
    "3a1fb7e2-4d5c-8a90-1234-567890abcd04": "site-bldg-west-001",
    "3a1fb7e2-4d5c-8a90-1234-567890abcd05": "site-bldg-east-001",
}


class DNACHandler(BaseHTTPRequestHandler):
    """HTTP request handler for simulated DNA Center API."""

    def log_message(self, format, *args):
        pass  # suppress default logging

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_token(self):
        token = self.headers.get("X-Auth-Token", "")
        return token == VALID_TOKEN

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "":
            self._send_json({"status": "ready", "version": "2.3.7.6"})
            return

        if not self._check_token():
            self._send_json({"response": {"errorCode": "UNAUTHORIZED", "message": "Token required"}}, 401)
            return

        if path == "/dna/intent/api/v1/network-device":
            self._send_json({"response": DEVICES, "version": "1.0"})

        elif path == "/dna/intent/api/v1/compliance":
            device_uuid = params.get("deviceUuid", [None])[0]
            if device_uuid:
                filtered = [c for c in COMPLIANCE if c["deviceUuid"] == device_uuid]
                self._send_json({"response": filtered, "version": "1.0"})
            else:
                self._send_json({"response": COMPLIANCE, "version": "1.0"})

        elif path == "/dna/intent/api/v1/issue":
            self._send_json({"response": ISSUES, "version": "1.0"})

        elif path == "/dna/intent/api/v1/site":
            self._send_json({"response": SITES, "version": "1.0"})

        elif path == "/dna/intent/api/v1/network-health":
            self._send_json({"response": HEALTH, "version": "1.0"})

        elif path.startswith("/dna/intent/api/v1/network-device/") and path.endswith("/config"):
            device_id = path.split("/")[-2]
            router = _DEV_ID_TO_ROUTER.get(device_id)
            if router:
                try:
                    with open(f"/app/network/configs/{router}.cfg") as f:
                        config_text = f.read()
                    self._send_json({"response": config_text, "version": "1.0"})
                except FileNotFoundError:
                    self._send_json({"response": {"errorCode": "NOT_FOUND"}}, 404)
            else:
                self._send_json({"response": {"errorCode": "NOT_FOUND"}}, 404)

        elif path == "/dna/intent/api/v1/membership":
            site_id = params.get("siteId", [None])[0]
            members = []
            for dev_id, sid in _DEV_ID_TO_SITE.items():
                if site_id is None or sid == site_id:
                    dev = next((d for d in DEVICES if d["id"] == dev_id), None)
                    if dev:
                        members.append({"instanceUuid": dev_id, "hostname": dev["hostname"]})
            self._send_json({"response": {"device": members}, "version": "1.0"})

        else:
            self._send_json({"response": {"errorCode": "NOT_FOUND", "message": f"Unknown endpoint: {path}"}}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/dna/system/api/v1/auth/token":
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Basic "):
                self._send_json({"response": {"errorCode": "UNAUTHORIZED", "message": "Basic auth required"}}, 401)
                return
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            except Exception:
                self._send_json({"response": {"errorCode": "UNAUTHORIZED", "message": "Invalid encoding"}}, 401)
                return
            if decoded != CREDENTIALS:
                self._send_json({"response": {"errorCode": "UNAUTHORIZED", "message": "Invalid credentials"}}, 401)
                return
            self._send_json({"Token": VALID_TOKEN})
        else:
            self._send_json({"response": {"errorCode": "NOT_FOUND"}}, 404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9443
    server = HTTPServer(("0.0.0.0", port), DNACHandler)
    print(f"DNA Center API simulator listening on port {port}")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
