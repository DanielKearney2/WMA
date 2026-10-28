"""
Re-export models from mapper app for compatibility.
"""
from mapper.models import CityBoundary, SafetyPin

__all__ = ["CityBoundary", "SafetyPin"]
