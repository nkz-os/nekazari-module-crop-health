"""Shade-aware water stress under agrivoltaic panels."""

# Global horizontal irradiance (W/m2) to open-sky PAR (umol/m2/s):
# ~0.45 PAR fraction x 4.57 umol/J (general-knowledge conversion factor).
PAR_PER_GHI = 2.02
# Below this GHI (night, dawn, dusk) the open-sky reference is meaningless.
MIN_GHI_WM2 = 50.0
