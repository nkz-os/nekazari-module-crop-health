from datetime import date

import pytest

from app.services import pipeline

START = date(2026, 10, 18)
END = date(2026, 10, 24)
URN = "urn:ngsi-ld:AgriParcel:p-1"


def _op(dose, ended=None, started=None):
    op = {"id": "urn:ngsi-ld:AgriParcelOperation:x", "type": "AgriParcelOperation"}
    if dose is not None:
        op["waterPerHectare"] = dose
    if ended is not None:
        op["endedAt"] = ended
    if started is not None:
        op["startedAt"] = started
    return op


def _fake(monkeypatch, pages=None, raises=False):
    calls = []
    pages = list(pages or [])

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def query_entities(self, **kw):
            calls.append(kw)
            if raises:
                raise RuntimeError("boom")
            return pages.pop(0) if pages else []

        async def close(self):
            pass

    import nkz_platform_sdk.orion as orion_mod

    monkeypatch.setattr(orion_mod, "OrionClient", _Client)
    return calls


@pytest.mark.asyncio
async def test_irrigation_sums_per_day(monkeypatch):
    calls = _fake(monkeypatch, [[
        _op(250000, ended="2026-10-20T06:00:00Z"),
        _op(50000, ended={"@type": "DateTime", "@value": "2026-10-20T18:00:00Z"}),
        _op(100000, ended="2026-10-21T06:00:00Z"),
    ]])
    out = await pipeline._fetch_irrigation("tenant-a", "p-1", START, END)
    assert out == {"2026-10-20": 30.0, "2026-10-21": 10.0}
    q = calls[0]["q"]
    assert 'operationType=="irrigation"' in q
    assert 'status=="completed"' in q
    assert URN in q
    assert calls[0]["type"] == "AgriParcelOperation"
    assert calls[0]["options"] == "keyValues"


@pytest.mark.asyncio
async def test_irrigation_urn_passthrough(monkeypatch):
    calls = _fake(monkeypatch, [[]])
    assert await pipeline._fetch_irrigation("tenant-a", URN, START, END) == {}
    assert f'hasAgriParcel=="{URN}"' in calls[0]["q"]


@pytest.mark.asyncio
async def test_irrigation_uses_started_when_no_end(monkeypatch):
    _fake(monkeypatch, [[_op({"value": 100000}, started="2026-10-19T23:30:00Z")]])
    out = await pipeline._fetch_irrigation("tenant-a", "p-1", START, END)
    assert out == {"2026-10-19": 10.0}


@pytest.mark.asyncio
async def test_irrigation_skips_bad_ops(monkeypatch):
    _fake(monkeypatch, [[
        _op(None, ended="2026-10-20T06:00:00Z"),
        _op("abc", ended="2026-10-20T06:00:00Z"),
        _op(100000),
        _op(100000, ended="2026-10-22T06:00:00Z"),
    ]])
    out = await pipeline._fetch_irrigation("tenant-a", "p-1", START, END)
    assert out == {"2026-10-22": 10.0}


@pytest.mark.asyncio
async def test_irrigation_outside_range_ignored(monkeypatch):
    _fake(monkeypatch, [[
        _op(100000, ended="2026-10-17T23:59:00Z"),
        _op(100000, ended="2026-10-25T00:00:00Z"),
        _op(100000, ended="2026-10-18T00:00:00Z"),
    ]])
    out = await pipeline._fetch_irrigation("tenant-a", "p-1", START, END)
    assert out == {"2026-10-18": 10.0}


@pytest.mark.asyncio
async def test_irrigation_orion_error_is_none(monkeypatch):
    _fake(monkeypatch, raises=True)
    assert await pipeline._fetch_irrigation("tenant-a", "p-1", START, END) is None


@pytest.mark.asyncio
async def test_irrigation_paginates(monkeypatch):
    page1 = [_op(10000, ended="2026-10-20T06:00:00Z") for _ in range(1000)]
    page2 = [_op(10000, ended="2026-10-20T07:00:00Z")]
    calls = _fake(monkeypatch, [page1, page2])
    out = await pipeline._fetch_irrigation("tenant-a", "p-1", START, END)
    assert out == {"2026-10-20": pytest.approx(1001.0)}
    assert [c["offset"] for c in calls] == [0, 1000]
    assert all(c["limit"] == 1000 for c in calls)
