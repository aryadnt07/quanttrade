"""
Institutional Risk Analytics & Robustness Verification Package
==============================================================
- Monte Carlo Resampling & Ruin Probability (analytics.monte_carlo)
- Walk-Forward Out-Of-Sample Validation (analytics.walk_forward)
- Friction & Execution Decay Stress Testing (analytics.friction_decay)
- Parameter Sensitivity Surface & Plateau (analytics.parameter_sensitivity)
"""

from analytics.monte_carlo import run_monte_carlo, plot_monte_carlo_dashboard
from analytics.walk_forward import run_walk_forward_analysis, plot_walk_forward_dashboard
from analytics.friction_decay import run_friction_decay_sweep, plot_friction_decay_dashboard
from analytics.parameter_sensitivity import run_parameter_sensitivity_grid, plot_parameter_sensitivity_dashboard

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
