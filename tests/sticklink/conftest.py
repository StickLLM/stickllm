import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "overlay/usr/local/lib"))
os.environ.setdefault("STICKLINK_TESTING", "1")
os.environ.setdefault("STICKLINK_FAST_KDF", "1")

# Prefer lab-vendored vectors, then sibling recoveries, then container path.
_candidates = [
    Path(os.environ["SL_SERVER_VECTORS"]) if os.environ.get("SL_SERVER_VECTORS") else None,
    REPO / "sticklink-server" / "vectors",
    REPO.parent / "sticklink-inventory-20261107" / "sticklink-server" / "vectors",
    REPO.parent / "vectors-v2",
    Path("/workspace/sticklink/server/vectors"),
]
VECTORS = next((p for p in _candidates if p is not None and (p / "ikpsk2-v2.json").exists()), Path("/workspace/sticklink/server/vectors"))
QR_VECTORS = VECTORS / "qr-v1.json"
