import os
import sys
import tempfile
from pathlib import Path

# isolate the app database and data folder used by tests
os.environ.setdefault("FIRESYNC_DATA", tempfile.mkdtemp(prefix="firesync-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
