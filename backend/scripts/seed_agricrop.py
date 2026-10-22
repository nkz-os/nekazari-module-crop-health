#!/usr/bin/env python3
"""Seed AgriCrop placeholder entities for every AgriParcel in Orion-LD.

Creates per-parcel placeholder AgriCrop entities (one per AgriParcel), tenant-scoped.
This is NOT a reference catalog — the FAO-56 variety catalog belongs to bioorchestrator
(consumed via its API). --tenant is REQUIRED to avoid seeding the shared `default` store.

Creates one AgriCrop per AgriParcel with estimated plantingDate (March 1)
and harvestDate (June 30). Marked provenance="placeholder" so consumers
know dates are estimates until user assigns real crop via bioorchestrator.

Usage:
    python3 scripts/seed_agricrop.py --tenant TENANT_ID [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

import httpx

ORION_URL = os.environ.get("ORION_LD_URL", "http://orion-ld:1026")


async def main(tenant_id: str, dry_run: bool = False):
    today = date.today()
    default_planting = date(today.year, 3, 1).isoformat()
    default_harvest = date(today.year, 6, 30).isoformat()

    headers = {
        "Accept": "application/ld+json",
        "NGSILD-Tenant": tenant_id,
        "Fiware-Service": tenant_id,
        "Fiware-ServicePath": "/",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{ORION_URL}/ngsi-ld/v1/entities",
            params={"type": "AgriParcel", "limit": 1000, "options": "keyValues"},
            headers=headers,
        )
        resp.raise_for_status()
        parcels = resp.json()
        print(f"Found {len(parcels)} AgriParcel entities for tenant '{tenant_id}'")

        created = 0
        skipped = 0

        for parcel in parcels:
            parcel_id = parcel["id"]

            existing = await client.get(
                f"{ORION_URL}/ngsi-ld/v1/entities",
                params={
                    "type": "AgriCrop",
                    "q": f'hasAgriParcel=="{parcel_id}"',
                    "limit": 1,
                    "options": "keyValues",
                },
                headers=headers,
            )
            if existing.status_code == 200 and existing.json():
                skipped += 1
                continue

            crop_id = f"urn:ngsi-ld:AgriCrop:{tenant_id}:{parcel_id.split(':')[-1]}"
            body = {
                "id": crop_id,
                "type": "AgriCrop",
                "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
                "plantingDate": {
                    "type": "Property",
                    "value": {"@type": "Date", "@value": default_planting},
                },
                "harvestDate": {
                    "type": "Property",
                    "value": {"@type": "Date", "@value": default_harvest},
                },
                "provenance": {"type": "Property", "value": "placeholder"},
            }

            if dry_run:
                print(f"  [DRY-RUN] Would create {crop_id} -> {parcel_id}")
                created += 1
            else:
                create_resp = await client.post(
                    f"{ORION_URL}/ngsi-ld/v1/entities",
                    json=body,
                    headers={**headers, "Content-Type": "application/ld+json"},
                )
                if create_resp.status_code == 201:
                    created += 1
                elif create_resp.status_code == 409:
                    print(f"  Already exists: {crop_id}")
                    skipped += 1
                else:
                    print(
                        f"  FAILED {create_resp.status_code}: {crop_id} "
                        f"— {create_resp.text[:200]}"
                    )

        print(f"\nDone: {created} created, {skipped} skipped (already existed)")

        if dry_run:
            print("DRY-RUN — no entities created. Remove --dry-run to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed AgriCrop placeholders")
    parser.add_argument("--tenant", required=True, help="Tenant ID (required — never seeds shared `default` store)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be created"
    )
    args = parser.parse_args()
    asyncio.run(main(args.tenant, args.dry_run))
