"""
Tests for TaskQueue basic operations
"""
import pytest
import json
from pathlib import Path

from nightshift.core.task_queue import TaskQueue, TaskStatus, Task


class TestTaskCreation:
    """Tests for task creation and retrieval"""

    def test_create_task_basic(self, tmp_path):
        """Create a task with minimal parameters"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        task = queue.create_task(
            task_id="task_001",
            description="Test task"
        )

        assert task.task_id == "task_001"
        assert task.description == "Test task"
        assert task.status == TaskStatus.STAGED.value
        assert task.created_at is not None
        assert task.updated_at is not None

    def test_create_task_with_all_fields(self, tmp_path):
        """Create a task with all optional fields"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        task = queue.create_task(
            task_id="task_002",
            description="Full task",
            skill_name="research",
            allowed_tools=["Read", "Write", "Bash"],
            allowed_directories=["/tmp/sandbox"],
            needs_git=True,
            system_prompt="You are a helpful assistant",
            timeout_seconds=1800
        )

        assert task.skill_name == "research"
        assert task.allowed_tools == ["Read", "Write", "Bash"]
        assert task.allowed_directories == ["/tmp/sandbox"]
        assert task.needs_git is True
        assert task.system_prompt == "You are a helpful assistant"
        assert task.timeout_seconds == 1800

    def test_allowed_tools_none_roundtrip(self, tmp_path):
        """allowed_tools None should roundtrip correctly"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_003", description="Test")
        task = queue.get_task("task_003")

        assert task.allowed_tools is None

    def test_allowed_directories_none_roundtrip(self, tmp_path):
        """allowed_directories None should roundtrip correctly"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_004", description="Test")
        task = queue.get_task("task_004")

        assert task.allowed_directories is None

    def test_needs_git_false_when_omitted(self, tmp_path):
        """needs_git should be falsy when not specified"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_005", description="Test")
        task = queue.get_task("task_005")

        # needs_git is stored as 0 when not specified, which becomes False
        assert not task.needs_git

    def test_needs_git_true_persistence(self, tmp_path):
        """needs_git=True should persist correctly"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_006", description="Test", needs_git=True)
        task = queue.get_task("task_006")

        assert task.needs_git is True

    def test_timeout_seconds_default(self, tmp_path):
        """timeout_seconds should default to 900 (15 mins)"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        task = queue.create_task(task_id="task_007", description="Test")
        assert task.timeout_seconds == 900

        # Verify it persists
        retrieved = queue.get_task("task_007")
        assert retrieved.timeout_seconds == 900

    def test_get_nonexistent_task(self, tmp_path):
        """get_task returns None for nonexistent task"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        task = queue.get_task("nonexistent")
        assert task is None


class TestWALMode:
    """Tests for WAL mode configuration"""

    def test_wal_mode_enabled(self, tmp_path):
        """WAL mode should be enabled on initialization"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()

        assert mode.lower() == "wal"


class TestStatusTransitions:
    """Tests for status update behavior"""

    def test_running_sets_started_at(self, tmp_path):
        """Transitioning to RUNNING should set started_at"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_010", description="Test")
        queue.update_status("task_010", TaskStatus.COMMITTED)
        queue.update_status("task_010", TaskStatus.RUNNING)

        task = queue.get_task("task_010")
        assert task.status == TaskStatus.RUNNING.value
        assert task.started_at is not None

    def test_completed_sets_completed_at(self, tmp_path):
        """Transitioning to COMPLETED should set completed_at"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_011", description="Test")
        queue.update_status("task_011", TaskStatus.RUNNING)
        queue.update_status("task_011", TaskStatus.COMPLETED)

        task = queue.get_task("task_011")
        assert task.status == TaskStatus.COMPLETED.value
        assert task.completed_at is not None

    def test_failed_sets_completed_at(self, tmp_path):
        """Transitioning to FAILED should set completed_at"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_012", description="Test")
        queue.update_status("task_012", TaskStatus.RUNNING)
        queue.update_status("task_012", TaskStatus.FAILED, error_message="Something went wrong")

        task = queue.get_task("task_012")
        assert task.status == TaskStatus.FAILED.value
        assert task.completed_at is not None
        assert task.error_message == "Something went wrong"

    def test_cancelled_sets_completed_at(self, tmp_path):
        """Transitioning to CANCELLED should set completed_at"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_013", description="Test")
        queue.update_status("task_013", TaskStatus.CANCELLED)

        task = queue.get_task("task_013")
        assert task.status == TaskStatus.CANCELLED.value
        assert task.completed_at is not None

    def test_update_status_with_kwargs(self, tmp_path):
        """update_status should accept additional fields via kwargs"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_014", description="Test")
        queue.update_status(
            "task_014",
            TaskStatus.COMPLETED,
            result_path="/tmp/result.json",
            token_usage=1000,
            execution_time=45.5
        )

        task = queue.get_task("task_014")
        assert task.result_path == "/tmp/result.json"
        assert task.token_usage == 1000
        assert task.execution_time == 45.5

    def test_update_status_ignores_unknown_kwargs(self, tmp_path):
        """update_status should ignore unknown kwargs"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_015", description="Test")
        # Should not raise even with unknown kwarg
        result = queue.update_status(
            "task_015",
            TaskStatus.RUNNING,
            unknown_field="should be ignored"
        )

        assert result is True


class TestUpdatePlan:
    """Tests for plan update functionality"""

    def test_update_plan_staged_task(self, tmp_path):
        """update_plan should work for STAGED tasks"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_020", description="Original")
        result = queue.update_plan(
            "task_020",
            description="Updated description",
            allowed_tools=["Read"],
            timeout_seconds=600
        )

        assert result is True
        task = queue.get_task("task_020")
        assert task.description == "Updated description"
        assert task.allowed_tools == ["Read"]
        assert task.timeout_seconds == 600

    def test_update_plan_rejected_for_non_staged(self, tmp_path):
        """update_plan should be rejected for non-STAGED tasks"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_021", description="Original")
        queue.update_status("task_021", TaskStatus.COMMITTED)

        result = queue.update_plan("task_021", description="Should fail")
        assert result is False

        # Description should be unchanged
        task = queue.get_task("task_021")
        assert task.description == "Original"


class TestLogging:
    """Tests for task logging functionality"""

    def test_add_and_get_logs(self, tmp_path):
        """add_log and get_logs should work correctly"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_030", description="Test")
        queue.add_log("task_030", "INFO", "First log")
        queue.add_log("task_030", "DEBUG", "Second log")
        queue.add_log("task_030", "ERROR", "Third log")

        logs = queue.get_logs("task_030")

        assert len(logs) == 3
        assert logs[0]["log_level"] == "INFO"
        assert logs[0]["message"] == "First log"
        assert logs[1]["log_level"] == "DEBUG"
        assert logs[2]["log_level"] == "ERROR"

    def test_logs_ordered_by_timestamp(self, tmp_path):
        """Logs should be returned in chronological order"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_031", description="Test")
        queue.add_log("task_031", "INFO", "First")
        queue.add_log("task_031", "INFO", "Second")
        queue.add_log("task_031", "INFO", "Third")

        logs = queue.get_logs("task_031")

        assert logs[0]["message"] == "First"
        assert logs[1]["message"] == "Second"
        assert logs[2]["message"] == "Third"

    def test_delete_task_removes_logs(self, tmp_path):
        """Deleting a task should also remove its logs"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_032", description="Test")
        queue.add_log("task_032", "INFO", "Log entry")

        queue.delete_task("task_032")

        # Task should be gone
        assert queue.get_task("task_032") is None
        # Logs should also be gone
        logs = queue.get_logs("task_032")
        assert len(logs) == 0


class TestListTasks:
    """Tests for listing and filtering tasks"""

    def test_list_all_tasks(self, tmp_path):
        """list_tasks without filter returns all tasks"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_040", description="Task 1")
        queue.create_task(task_id="task_041", description="Task 2")
        queue.create_task(task_id="task_042", description="Task 3")

        tasks = queue.list_tasks()
        assert len(tasks) == 3

    def test_list_tasks_filtered_by_status(self, tmp_path):
        """list_tasks with status filter returns matching tasks"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_050", description="Staged 1")
        queue.create_task(task_id="task_051", description="Staged 2")
        queue.create_task(task_id="task_052", description="Running")
        queue.update_status("task_052", TaskStatus.COMMITTED)
        queue.update_status("task_052", TaskStatus.RUNNING)

        staged = queue.list_tasks(TaskStatus.STAGED)
        running = queue.list_tasks(TaskStatus.RUNNING)

        assert len(staged) == 2
        assert len(running) == 1
        assert running[0].task_id == "task_052"

    def test_list_tasks_ordered_by_created_at_desc(self, tmp_path):
        """list_tasks should return newest first"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_060", description="First")
        queue.create_task(task_id="task_061", description="Second")
        queue.create_task(task_id="task_062", description="Third")

        tasks = queue.list_tasks()

        # Newest first
        assert tasks[0].task_id == "task_062"
        assert tasks[1].task_id == "task_061"
        assert tasks[2].task_id == "task_060"


class TestDeleteTask:
    """Tests for task deletion"""

    def test_delete_existing_task(self, tmp_path):
        """delete_task returns True for existing task"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        queue.create_task(task_id="task_070", description="To delete")
        result = queue.delete_task("task_070")

        assert result is True
        assert queue.get_task("task_070") is None

    def test_delete_nonexistent_task(self, tmp_path):
        """delete_task returns False for nonexistent task"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        result = queue.delete_task("nonexistent")
        assert result is False


class TestCountRunningTasks:
    """Tests for counting running tasks"""

    def test_count_running_tasks(self, tmp_path):
        """count_running_tasks returns correct count"""
        db_path = tmp_path / "test.db"
        queue = TaskQueue(db_path=str(db_path))

        # Initially zero
        assert queue.count_running_tasks() == 0

        # Create and run some tasks
        queue.create_task(task_id="task_080", description="Running 1")
        queue.update_status("task_080", TaskStatus.COMMITTED)
        queue.update_status("task_080", TaskStatus.RUNNING)

        queue.create_task(task_id="task_081", description="Running 2")
        queue.update_status("task_081", TaskStatus.COMMITTED)
        queue.update_status("task_081", TaskStatus.RUNNING)

        queue.create_task(task_id="task_082", description="Staged")

        assert queue.count_running_tasks() == 2


class TestTaskDataclass:
    """Tests for Task dataclass"""

    def test_to_dict(self):
        """Task.to_dict should return all fields"""
        task = Task(
            task_id="test_001",
            description="Test task",
            status="staged",
            allowed_tools=["Read"]
        )

        d = task.to_dict()

        assert d["task_id"] == "test_001"
        assert d["description"] == "Test task"
        assert d["status"] == "staged"
        assert d["allowed_tools"] == ["Read"]
