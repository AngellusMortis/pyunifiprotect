import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

UFP_SAMPLE_DIR = os.environ.get("UFP_SAMPLE_DIR")
if UFP_SAMPLE_DIR:
    DATA_FILE = Path(UFP_SAMPLE_DIR) / "sample_constants.json"
else:
    DATA_FILE = Path(__file__).parent / "sample_constants.json"


class ConstantData:
    _data: Optional[Dict[str, Any]] = None

    def __getitem__(self, key):
        return self.data().__getitem__(key)

    def __contains__(self, key):
        return self.data().__contains__(key)

    def get(self, key, default=None):
        return self.data().get(key, default)

    def data(self):
        if self._data is None:
            with open(DATA_FILE) as f:
                self._data = json.load(f)
        return self._data


CONSTANTS = ConstantData()
