import pytest

from app.engines.waterlogging_risk import waterlogging_risk

# excess 100 mm, drainage 1*10 => 10 h => MEDIUM
BASE = dict(excess_mm=100.0, ksat_mm_h=10.0, scs_group="B")


def test_no_wetness_unchanged():
    assert waterlogging_risk(**BASE).risk_level == "MEDIUM"
    assert waterlogging_risk(**BASE, wetness_class=None).risk_level == "MEDIUM"
    assert waterlogging_risk(**BASE, wetness_class="balanced").risk_level == "MEDIUM"


def test_wet_raises_one_level():
    r = waterlogging_risk(**BASE, wetness_class="wet")
    assert r.risk_level == "HIGH"
    assert r.condition == "saturated_prolonged"


def test_drained_lowers_one_level():
    r = waterlogging_risk(**BASE, wetness_class="drained")
    assert r.risk_level == "LOW"
    assert r.condition == "normal"


def test_caps_and_floors():
    crit = waterlogging_risk(excess_mm=1000.0, ksat_mm_h=1.0, scs_group="B", wetness_class="wet")
    assert crit.risk_level == "CRITICAL"
    low = waterlogging_risk(excess_mm=1.0, ksat_mm_h=10.0, scs_group="B", wetness_class="drained")
    assert low.risk_level == "LOW"


@pytest.mark.parametrize("wc", ["wet", "drained"])
def test_no_excess_no_change(wc):
    r = waterlogging_risk(excess_mm=0.0, ksat_mm_h=10.0, scs_group="B", wetness_class=wc)
    assert r.risk_level == "LOW" and r.condition == "normal"
