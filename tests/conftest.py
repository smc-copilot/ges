from __future__ import annotations

import os

# Standalone GES tests ship an official Spec Kit staging fixture. Default to
# offline so `pytest -q` does not invoke uvx / the network. Callers can still
# opt into live specify-cli by exporting GES_SOURCE_OFFLINE=0.
os.environ.setdefault("GES_SOURCE_OFFLINE", "1")
