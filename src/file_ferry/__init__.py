"""ferry — Zero-cost CLI for post-production media ops."""

__version__ = "0.3.0"

# The version stamped into operation receipts (ADR-0003 §6.5). It lives
# here rather than beside one of its writers: receipts are written by the
# project service *and* by the job runners, and a runner should not have
# to import from the project service to name the application it is part of.
APP_VERSION = __version__

__all__ = ["APP_VERSION", "__version__"]
