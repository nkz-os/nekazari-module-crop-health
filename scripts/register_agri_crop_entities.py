#!/usr/bin/env python3
"""Register AgriCrop placeholder entities for all existing AgriParcels.

Creates one AgriCrop per parcel with inputMethod='pending' and all
crop-specific fields set to null. Safe to re-run — uses upsert.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

ORION_URL = os.getenv("ORION_URL", "http://orion:1026")
TENANT_ID = os.getenv("TENANT_ID", "")


def _make_headers(tenant_id: str) -> dict:
    headers = {
        "Accept": "application/ld+json",
    }
    if tenant_id:
        headers["NGSILD-Tenant"] = tenant_id
        headers["Fiware-Service"] = tenant_id
        headers["Fiware-ServicePath"] = "/"
    ctx_url = os.getenv("CONTEXT_URL", "")
    if ctx_url:
        headers["Link"] = (
            f'<{ctx_url}>; rel="http://www.w3.org/ns/json-ld#context";'
            f' type="application/ld+json"'
        )
    return headers


async def main() -> None:
    tenant = TENANT_ID
    headers = _make_headers(tenant)
    base = ORION_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Get all AgriParcels
        resp = await client.get(
            f"{base}/ngsi-ld/v1/entities",
            params={"type": "AgriParcel", "limit": 1000, "options": "keyValues"},
            headers=headers,
        )
        if resp.status_code != 200:
            print(f"ERROR: Orion returned {resp.status_code}: {resp.text[:200]}")
            sys.exit(1)

        parcels = resp.json()
        if not isinstance(parcels, list):
            print("ERROR: Unexpected response format")
            sys.exit(1)

        print(f"Found {len(parcels)} AgriParcel entities")

        # 2. For each parcel, upsert an AgriCrop placeholder
        created = 0
        for p in parcels:
            pid = p.get("id", "").replace("urn:ngsi-ld:AgriParcel:", "")
            if not pid:
                continue

            agri_crop = {
                "id": f"urn:ngsi-ld:AgriCrop:{pid}-pending",
                "type": "AgriCrop",
                "hasAgriParcel": {
                    "type": "Relationship",
                    "object": f"urn:ngsi-ld:AgriParcel:{pid}",
                },
                "category": {"type": "Property", "value": "sowing"},
                "inputMethod": {"type": "Property", "value": "pending"},
            }

            ctx_url = os.getenv("CONTEXT_URL", "")
            if ctx_url:
                agri_crop["@context"] = ctx_url

            upsert_headers = {**headers, "Content-Type": "application/ld+json"}
            resp2 = await client.post(
                f"{base}/ngsi-ld/v1/entityOperations/upsert",
                json=[agri_crop],
                headers=upsert_headers,
            )
            if resp2.status_code in (200, 201, 204):
                created += 1
            else:
                print(f"  WARN: Failed to upsert AgriCrop for {pid}: {resp2.status_code}")

        print(f"Created/updated {created}/{len(parcels)} AgriCrop placeholders")


if __name__ == "__main__":
    asyncio.run(main())
