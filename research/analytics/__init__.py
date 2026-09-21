"""
Institutional Risk Analytics & Robustness Verification Package
==============================================================
- Monte Carlo Resampling & Ruin Probability (research.analytics.monte_carlo)
- Walk-Forward Out-Of-Sample Validation (research.analytics.walk_forward)
- Friction & Execution Decay Stress Testing (research.analytics.friction_decay)
- Parameter Sensitivity Surface & Plateau (research.analytics.parameter_sensitivity)
"""

from .monte_carlo import run_monte_carlo, plot_monte_carlo_dashboard
from .walk_forward import run_walk_forward_analysis, plot_walk_forward_dashboard
from .friction_decay import run_friction_decay_sweep, plot_friction_decay_dashboard
from .parameter_sensitivity import run_parameter_sensitivity_grid, plot_parameter_sensitivity_dashboard

__all__ = [
    "run_monte_carlo",
    "plot_monte_carlo_dashboard",
    "run_walk_forward_analysis",
    "plot_walk_forward_dashboard",
    "run_friction_decay_sweep",
    "plot_friction_decay_dashboard",
    "run_parameter_sensitivity_grid",
    "plot_parameter_sensitivity_dashboard",
]
