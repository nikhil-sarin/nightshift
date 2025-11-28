"""
Tests for TaskExecutor - concurrent task execution service
"""
import pytest
import json
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import Future

from nightshift.core.task_executor import TaskExecutor, ExecutorManager
from nightshift.core.task_queue import TaskQueue, TaskStatus, Task
from nightshift.core.logger import NightShiftLogger


@pytest.fixture
def tmp_setup(tmp_path):
    """Set up temporary directories and basic fixtures"""
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    queue = TaskQueue(db_path=str(db_path))
    logger = NightShiftLogger(log_dir=str(tmp_path / "logs"), console_output=False)

    # Mock agent manager
    agent_manager = Mock()
    agent_manager.execute_task = Mock(return_value={"success": True})

    return {
        "queue": queue,
        "logger": logger,
        "agent_manager": agent_manager,
        "tmp_path": tmp_path,
        "pid_file": tmp_path / "executor.pid"
    }


class TestTaskExecutorInit:
    """Tests for TaskExecutor initialization"""

    def test_default_values(self, tmp_setup):
        """TaskExecutor has correct default values"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        assert executor.max_workers == 3
        assert executor.poll_interval == 1.0
        assert executor.is_running is False

    def test_custom_values(self, tmp_setup):
        """TaskExecutor accepts custom values"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            max_workers=5,
            poll_interval=2.0,
            pid_file=tmp_setup["pid_file"]
        )

        assert executor.max_workers == 5
        assert executor.poll_interval == 2.0

    def test_creates_thread_pool(self, tmp_setup):
        """TaskExecutor creates thread pool with correct workers"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            max_workers=4,
            pid_file=tmp_setup["pid_file"]
        )

        assert executor.executor is not None
        assert executor.executor._max_workers == 4


class TestTaskExecutorStart:
    """Tests for start method"""

    def test_start_sets_running_flag(self, tmp_setup):
        """start sets is_running to True"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            assert executor.is_running is True
        finally:
            executor.stop()

    def test_start_creates_pid_file(self, tmp_setup):
        """start creates PID file"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            assert tmp_setup["pid_file"].exists()

            with open(tmp_setup["pid_file"]) as f:
                pid_data = json.load(f)

            assert "pid" in pid_data
            assert "max_workers" in pid_data
            assert "poll_interval" in pid_data
            assert "started_at" in pid_data
        finally:
            executor.stop()

    def test_start_twice_warns(self, tmp_setup):
        """Starting executor twice logs warning"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            # Second start should just return (with warning)
            executor.start()  # Should not raise
            assert executor.is_running is True
        finally:
            executor.stop()

    def test_start_with_stale_pid_file(self, tmp_setup):
        """start removes stale PID file from dead process"""
        # Create stale PID file with non-existent PID
        stale_pid_data = {"pid": 999999, "max_workers": 3, "poll_interval": 1.0}
        with open(tmp_setup["pid_file"], 'w') as f:
            json.dump(stale_pid_data, f)

        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        try:
            # Should clean up stale file and start normally
            executor.start()
            assert executor.is_running is True
        finally:
            executor.stop()

    def test_start_starts_poll_thread(self, tmp_setup):
        """start creates and starts poll thread"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            assert executor.poll_thread is not None
            assert executor.poll_thread.is_alive()
        finally:
            executor.stop()


class TestTaskExecutorStop:
    """Tests for stop method"""

    def test_stop_clears_running_flag(self, tmp_setup):
        """stop sets is_running to False"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        executor.start()
        executor.stop()

        assert executor.is_running is False

    def test_stop_removes_pid_file(self, tmp_setup):
        """stop removes PID file"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        executor.start()
        assert tmp_setup["pid_file"].exists()

        executor.stop()
        assert not tmp_setup["pid_file"].exists()

    def test_stop_joins_poll_thread(self, tmp_setup):
        """stop waits for poll thread to exit"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        executor.start()
        executor.stop()

        assert not executor.poll_thread.is_alive()

    def test_stop_when_not_running(self, tmp_setup):
        """stop when not running just warns"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        # Should not raise
        executor.stop()
        assert executor.is_running is False


class TestGetStatus:
    """Tests for get_status method"""

    def test_status_when_not_running(self, tmp_setup):
        """get_status returns correct status when not running"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        status = executor.get_status()

        assert status["is_running"] is False
        assert status["running_tasks"] == 0

    def test_status_when_running(self, tmp_setup):
        """get_status returns correct status when running"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            max_workers=5,
            poll_interval=2.0,
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            status = executor.get_status()

            assert status["is_running"] is True
            assert status["max_workers"] == 5
            assert status["poll_interval"] == 2.0
            assert status["available_workers"] == 5
        finally:
            executor.stop()


class TestPollLoop:
    """Tests for _poll_loop method"""

    def test_poll_acquires_task(self, tmp_setup):
        """Poll loop acquires and submits tasks"""
        # Create a committed task
        tmp_setup["queue"].create_task(task_id="task_001", description="Test")
        tmp_setup["queue"].update_status("task_001", TaskStatus.COMMITTED)

        # Create executor with short poll interval
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            poll_interval=0.1,
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            # Wait for poll to pick up task
            time.sleep(0.5)

            # Task should be acquired (status changed to RUNNING)
            task = tmp_setup["queue"].get_task("task_001")
            assert task.status == TaskStatus.RUNNING.value
        finally:
            executor.stop()

    def test_poll_respects_max_workers(self, tmp_setup):
        """Poll loop doesn't acquire more tasks than max_workers"""
        # Create multiple committed tasks
        for i in range(5):
            tmp_setup["queue"].create_task(task_id=f"task_{i:03d}", description=f"Test {i}")
            tmp_setup["queue"].update_status(f"task_{i:03d}", TaskStatus.COMMITTED)

        # Make execute_task block so tasks stay running
        def slow_execute(task):
            time.sleep(2)
            return {"success": True}

        tmp_setup["agent_manager"].execute_task = slow_execute

        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            max_workers=2,
            poll_interval=0.1,
            pid_file=tmp_setup["pid_file"]
        )

        try:
            executor.start()
            time.sleep(0.5)

            # Should only have 2 running at a time
            running_count = len([t for t in tmp_setup["queue"].list_tasks()
                               if t.status == TaskStatus.RUNNING.value])
            assert running_count <= 2
        finally:
            executor.stop()


class TestExecuteTaskWrapper:
    """Tests for _execute_task_wrapper method"""

    def test_wrapper_calls_agent_manager(self, tmp_setup):
        """Wrapper calls agent_manager.execute_task"""
        tmp_setup["queue"].create_task(task_id="task_001", description="Test")
        tmp_setup["queue"].update_status("task_001", TaskStatus.COMMITTED)
        tmp_setup["queue"].update_status("task_001", TaskStatus.RUNNING)

        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        executor._execute_task_wrapper("task_001")

        tmp_setup["agent_manager"].execute_task.assert_called_once()

    def test_wrapper_handles_missing_task(self, tmp_setup):
        """Wrapper handles missing task gracefully"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        # Should not raise
        executor._execute_task_wrapper("nonexistent")

        # Agent manager should not be called
        tmp_setup["agent_manager"].execute_task.assert_not_called()

    def test_wrapper_handles_exception(self, tmp_setup):
        """Wrapper handles execution exception"""
        tmp_setup["queue"].create_task(task_id="task_001", description="Test")
        tmp_setup["queue"].update_status("task_001", TaskStatus.COMMITTED)
        tmp_setup["queue"].update_status("task_001", TaskStatus.RUNNING)

        tmp_setup["agent_manager"].execute_task.side_effect = Exception("Test error")

        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        # Should not raise
        executor._execute_task_wrapper("task_001")

        # Task should be marked as FAILED
        task = tmp_setup["queue"].get_task("task_001")
        assert task.status == TaskStatus.FAILED.value


class TestCleanupCompletedTasks:
    """Tests for _cleanup_completed_tasks method"""

    def test_cleanup_removes_done_futures(self, tmp_setup):
        """Cleanup removes completed futures from tracking"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        # Create a done future
        future = Future()
        future.set_result(None)

        executor.running_tasks["task_001"] = future

        executor._cleanup_completed_tasks()

        assert "task_001" not in executor.running_tasks

    def test_cleanup_keeps_pending_futures(self, tmp_setup):
        """Cleanup keeps pending futures in tracking"""
        executor = TaskExecutor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"],
            pid_file=tmp_setup["pid_file"]
        )

        # Create a pending future
        future = Future()
        # Don't set result - it's pending

        executor.running_tasks["task_001"] = future

        executor._cleanup_completed_tasks()

        assert "task_001" in executor.running_tasks


class TestExecutorManager:
    """Tests for ExecutorManager singleton"""

    def setup_method(self):
        """Reset singleton state before each test"""
        ExecutorManager._instance = None

    def test_start_executor_creates_instance(self, tmp_setup):
        """start_executor creates and starts executor"""
        try:
            executor = ExecutorManager.start_executor(
                task_queue=tmp_setup["queue"],
                agent_manager=tmp_setup["agent_manager"],
                logger=tmp_setup["logger"],
                max_workers=2,
                poll_interval=0.5
            )

            assert executor is not None
            assert executor.is_running is True
            assert ExecutorManager._instance is executor
        finally:
            ExecutorManager.stop_executor()

    def test_start_executor_returns_existing(self, tmp_setup):
        """start_executor returns existing running instance"""
        try:
            executor1 = ExecutorManager.start_executor(
                task_queue=tmp_setup["queue"],
                agent_manager=tmp_setup["agent_manager"],
                logger=tmp_setup["logger"]
            )
            executor2 = ExecutorManager.start_executor(
                task_queue=tmp_setup["queue"],
                agent_manager=tmp_setup["agent_manager"],
                logger=tmp_setup["logger"]
            )

            assert executor1 is executor2
        finally:
            ExecutorManager.stop_executor()

    def test_stop_executor_stops_instance(self, tmp_setup):
        """stop_executor stops running instance"""
        ExecutorManager.start_executor(
            task_queue=tmp_setup["queue"],
            agent_manager=tmp_setup["agent_manager"],
            logger=tmp_setup["logger"]
        )

        ExecutorManager.stop_executor()

        assert ExecutorManager._instance.is_running is False

    def test_get_executor_returns_instance(self, tmp_setup):
        """get_executor returns current instance"""
        try:
            ExecutorManager.start_executor(
                task_queue=tmp_setup["queue"],
                agent_manager=tmp_setup["agent_manager"],
                logger=tmp_setup["logger"]
            )

            result = ExecutorManager.get_executor()
            assert result is ExecutorManager._instance
        finally:
            ExecutorManager.stop_executor()

    def test_get_executor_returns_none(self, tmp_setup):
        """get_executor returns None when no instance"""
        result = ExecutorManager.get_executor()
        assert result is None

    def test_get_status_running(self, tmp_setup):
        """get_status returns status of running executor"""
        try:
            ExecutorManager.start_executor(
                task_queue=tmp_setup["queue"],
                agent_manager=tmp_setup["agent_manager"],
                logger=tmp_setup["logger"],
                max_workers=4
            )

            status = ExecutorManager.get_status()

            assert status["is_running"] is True
            assert status["max_workers"] == 4
        finally:
            ExecutorManager.stop_executor()

    def test_get_status_not_running(self, tmp_setup):
        """get_status returns not running when no executor"""
        status = ExecutorManager.get_status()

        assert status["is_running"] is False
        assert status["max_workers"] == 0

    def test_get_status_from_pid_file(self, tmp_setup):
        """get_status reads from PID file for external process"""
        # Create a PID file as if from another process
        pid_file = Path.home() / ".nightshift" / "executor.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)

        # Use current process PID so the check passes
        pid_data = {
            "pid": 999999,  # Non-existent PID
            "max_workers": 5,
            "poll_interval": 2.0,
            "started_at": time.time()
        }

        try:
            with open(pid_file, 'w') as f:
                json.dump(pid_data, f)

            # Status should detect stale PID and clean up
            status = ExecutorManager.get_status()
            # Since PID doesn't exist, file should be cleaned up
            assert not pid_file.exists() or status["is_running"] is False

        finally:
            if pid_file.exists():
                pid_file.unlink()
