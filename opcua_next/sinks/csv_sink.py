import csv
import os
from pathlib import Path
from typing import List, Dict


class CSVSink:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file_exists = self.path.exists()

    def write_records(self, records: List[Dict]):
        if not records:
            return
        
        # Get fieldnames from first record
        fieldnames = records[0].keys()
        
        mode = 'a' if self._file_exists else 'w'
        with open(self.path, mode, newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header only if file is new
            if not self._file_exists:
                writer.writeheader()
                self._file_exists = True
            
            writer.writerows(records)
