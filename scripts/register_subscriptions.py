#!/usr/bin/env python3
"""
Register FIWARE Orion-LD subscriptions for crop health sensors.

Creates subscriptions for DeviceMeasurement entities that trigger
webhook notifications to the crop-health module when sensor data
(leafTemperature, trunkDiameter, soilMoisture) is updated.

Usage:
    ORION_LD_URL=http://localhost:1026 \
    WEBHOOK_URL=http://crop-health-api-service:8000/api/crop-health \
    python register_subscriptions.py

Idempotent: checks for existing subscriptions before creating.
"""

import json
import os
import sys

import httpx

ORION_LD_URL = os.environ.get("ORION_LD_URL", "http://localhost:1026")
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL", "http://crop-health-api-service:8000/api/crop-health"
)
CONTEXT = "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context-v1.6.jsonld"

SUBSCRIPTIONS = [
    {
        "id": "urn:ngsi-ld:Subscription:crop-health-leaf-temp",
        "type": "Subscription",
        "description": "Crop Health — Leaf temperature (IR sensor) for CWSI",
        "entities": [{"type": "DeviceMeasurement"}],
        "watchedAttributes": ["leafTemperature"],
        "notification": {
            "endpoint": {
                "uri": f"{WEBHOOK_URL}/webhooks/fiware-sensors",
                "accept": "application/json",
            },
            "attributes": ["leafTemperature", "hasAgriParcel"],
        },
    },
    {
        "id": "urn:ngsi-ld:Subscription:crop-health-trunk-diam",
        "type": "Subscription",
        "description": "Crop Health — Trunk diameter (dendrómetro) for MDS",
        "entities": [{"type": "DeviceMeasurement"}],
        "watchedAttributes": ["trunkDiameter"],
        "notification": {
            "endpoint": {
                "uri": f"{WEBHOOK_URL}/webhooks/fiware-sensors",
                "accept": "application/json",
            },
            "attributes": ["trunkDiameter", "hasAgriParcel"],
        },
    },
    {
        "id": "urn:ngsi-ld:Subscription:crop-health-soil-moisture",
        "type": "Subscription",
        "description": "Crop Health — Soil moisture (TDR) for water balance",
        "entities": [{"type": "DeviceMeasurement"}],
        "watchedAttributes": ["soilMoisture"],
        "notification": {
            "endpoint": {
                "uri": f"{WEBHOOK_URL}/webhooks/fiware-sensors",
                "accept": "application/json",
            },
            "attributes": ["soilMoisture", "hasAgriParcel"],
        },
    },
]


def main():
    client = httpx.Client(timeout=10.0)
    base = f"{ORION_LD_URL}/ngsi-ld/v1/subscriptions"

    for sub in SUBSCRIPTIONS:
        sub_id = sub["id"]

        # Check if exists
        resp = client.get(
            f"{base}/{sub_id}",
            headers={"Accept": "application/ld+json"},
        )
        if resp.status_code == 200:
            print(f"✓ Subscription already exists: {sub_id}")
            continue

        # Create
        payload = {**sub, "@context": CONTEXT}
        resp = client.post(
            base,
            json=payload,
            headers={
                "Content-Type": "application/ld+json",
                "Accept": "application/ld+json",
            },
        )
        if resp.status_code in (201, 204):
            print(f"✓ Created subscription: {sub_id}")
        else:
            print(
                f"✗ Failed to create {sub_id}: {resp.status_code} {resp.text[:200]}",
                file=sys.stderr,
            )

    client.close()


if __name__ == "__main__":
    main()
