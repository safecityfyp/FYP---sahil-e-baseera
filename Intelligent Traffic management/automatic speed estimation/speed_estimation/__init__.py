"""Automatic CCTV speed estimation from calibrated ground motion.

Neural inference is loaded separately; saved-measurement calibration/speed runs
need only the CPU dependencies.
"""
from .calibration import calibrate
from .speed import calculate

__all__ = ['calibrate', 'calculate']
