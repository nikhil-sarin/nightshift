"""
File Tracker - Monitors file system changes during task execution
Tracks which files were created, modified, or deleted
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, asdict


@dataclass
class FileChange:
    """Represents a file system change"""
    path: str
    change_type: str  # 'created', 'modified', 'deleted'
    timestamp: str
    size: Optional[int] = None


class FileTracker:
    """Tracks file changes during task execution"""

    def __init__(self, watch_dir: str = "."):
        self.watch_dir = Path(watch_dir).resolve()
        self.snapshot_before: Dict[str, float] = {}
        self.snapshot_after: Dict[str, float] = {}

    def take_snapshot(self) -> Dict[str, float]:
        """
        Take a snapshot of all files in the watch directory
        Returns dict of {filepath: mtime}
        """
        snapshot = {}

        for root, dirs, files in os.walk(self.watch_dir):
            # Skip hidden directories and common ignore patterns
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]

            for file in files:
                if file.startswith('.'):
                    continue

                filepath = Path(root) / file
                try:
                    stat = filepath.stat()
                    # Store relative path and mtime
                    rel_path = str(filepath.relative_to(self.watch_dir))
                    snapshot[rel_path] = stat.st_mtime
                except (OSError, ValueError):
                    continue

        return snapshot

    def start_tracking(self):
        """Start tracking - take initial snapshot"""
        self.snapshot_before = self.take_snapshot()

    def stop_tracking(self) -> List[FileChange]:
        """
        Stop tracking and return list of changes
        """
        self.snapshot_after = self.take_snapshot()
        return self.get_changes()

    def get_changes(self) -> List[FileChange]:
        """Compare snapshots and return list of changes"""
        changes = []
        now = datetime.now().isoformat()

        # Find created and modified files
        for path, mtime in self.snapshot_after.items():
            if path not in self.snapshot_before:
                # New file
                filepath = self.watch_dir / path
                size = filepath.stat().st_size if filepath.exists() else None
                changes.append(FileChange(
                    path=path,
                    change_type='created',
                    timestamp=now,
                    size=size
                ))
            elif mtime > self.snapshot_before[path]:
                # Modified file
                filepath = self.watch_dir / path
                size = filepath.stat().st_size if filepath.exists() else None
                changes.append(FileChange(
                    path=path,
                    change_type='modified',
                    timestamp=now,
                    size=size
                ))

        # Find deleted files
        for path in self.snapshot_before:
            if path not in self.snapshot_after:
                changes.append(FileChange(
                    path=path,
                    change_type='deleted',
                    timestamp=now,
                    size=None
                ))

        return changes

    def save_changes(self, task_id: str, changes: List[FileChange], output_dir: str = "output"):
        """Save file changes to a JSON file"""
        output_path = Path(output_dir) / f"{task_id}_files.json"

        data = {
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "changes": [asdict(change) for change in changes]
        }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        return str(output_path)
