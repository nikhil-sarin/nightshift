"""
Task Executor Service
Polls for COMMITTED tasks and executes them concurrently using a process pool
"""
import threading
import time
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, Optional, Set
from pathlib import Path

from .task_queue import TaskQueue, Task, TaskStatus
from .agent_manager import AgentManager
from .logger import NightShiftLogger


class TaskExecutor:
    """
    Background service that polls for COMMITTED tasks and executes them concurrently

    Uses ThreadPoolExecutor (not ProcessPoolExecutor) because AgentManager already
    spawns Claude CLI as separate processes via subprocess.Popen. We just need
    concurrent thread management for polling and coordination.
    """

    def __init__(
        self,
        task_queue: TaskQueue,
        agent_manager: AgentManager,
        logger: NightShiftLogger,
        max_workers: int = 3,
        poll_interval: float = 1.0
    ):
        """
        Initialize task executor

        Args:
            task_queue: TaskQueue instance for acquiring tasks
            agent_manager: AgentManager instance for executing tasks
            logger: Logger instance
            max_workers: Maximum number of concurrent task executions
            poll_interval: How often to poll for new tasks (seconds)
        """
        self.task_queue = task_queue
        self.agent_manager = agent_manager
        self.logger = logger
        self.max_workers = max_workers
        self.poll_interval = poll_interval

        # Thread pool for concurrent task execution
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="nightshift-worker"
        )

        # Track running tasks
        self.running_tasks: Dict[str, Future] = {}  # task_id -> Future
        self.running_lock = threading.Lock()

        # Control flags
        self.shutdown_event = threading.Event()
        self.poll_thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self):
        """Start the executor service"""
        if self.is_running:
            self.logger.warning("Task executor is already running")
            return

        self.logger.info(f"Starting task executor (max_workers={self.max_workers}, poll_interval={self.poll_interval}s)")

        self.is_running = True
        self.shutdown_event.clear()

        # Start polling thread
        self.poll_thread = threading.Thread(
            target=self._poll_loop,
            name="nightshift-poller",
            daemon=False  # Not daemon so we can gracefully shutdown
        )
        self.poll_thread.start()

        self.logger.info("Task executor started successfully")

    def stop(self, timeout: float = 30.0):
        """
        Gracefully stop the executor service

        Args:
            timeout: Maximum time to wait for running tasks to complete (seconds)
        """
        if not self.is_running:
            self.logger.warning("Task executor is not running")
            return

        self.logger.info("Stopping task executor...")

        # Signal shutdown
        self.shutdown_event.set()

        # Wait for poll thread to exit
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=5.0)

        # Shutdown executor (waits for running tasks)
        self.logger.info(f"Waiting up to {timeout}s for {len(self.running_tasks)} running tasks to complete...")
        self.executor.shutdown(wait=True, cancel_futures=False)

        self.is_running = False
        self.logger.info("Task executor stopped")

    def get_status(self) -> Dict:
        """
        Get executor status

        Returns:
            Dict with status information
        """
        with self.running_lock:
            running_count = len(self.running_tasks)

        return {
            "is_running": self.is_running,
            "max_workers": self.max_workers,
            "running_tasks": running_count,
            "available_workers": self.max_workers - running_count,
            "poll_interval": self.poll_interval
        }

    def _poll_loop(self):
        """Main polling loop (runs in background thread)"""
        self.logger.info("Poll loop started")

        while not self.shutdown_event.is_set():
            try:
                # Check if we have capacity for more tasks
                with self.running_lock:
                    current_running = len(self.running_tasks)

                if current_running < self.max_workers:
                    # Try to acquire a task
                    task = self.task_queue.acquire_task_for_execution()

                    if task:
                        self.logger.info(f"Acquired task {task.task_id} for execution")
                        self._submit_task(task)
                    # else: No COMMITTED tasks available, continue polling

                # Clean up completed tasks
                self._cleanup_completed_tasks()

                # Sleep before next poll
                self.shutdown_event.wait(self.poll_interval)

            except Exception as e:
                self.logger.error(f"Error in poll loop: {e}")
                # Continue polling even after errors
                self.shutdown_event.wait(self.poll_interval)

        self.logger.info("Poll loop exited")

    def _submit_task(self, task: Task):
        """
        Submit task to executor thread pool

        Args:
            task: Task to execute
        """
        # Submit to thread pool
        future = self.executor.submit(self._execute_task_wrapper, task.task_id)

        # Track the future
        with self.running_lock:
            self.running_tasks[task.task_id] = future

        self.logger.info(f"Task {task.task_id} submitted to executor ({len(self.running_tasks)}/{self.max_workers} workers busy)")

    def _execute_task_wrapper(self, task_id: str):
        """
        Wrapper for executing task (runs in worker thread)

        Args:
            task_id: ID of task to execute
        """
        try:
            # Get fresh task data
            task = self.task_queue.get_task(task_id)
            if not task:
                self.logger.error(f"Task {task_id} not found in queue")
                return

            self.logger.info(f"Worker thread executing task {task_id}")

            # Execute task using AgentManager
            # This will spawn Claude CLI subprocess and wait for completion
            result = self.agent_manager.execute_task(task)

            if result['success']:
                self.logger.info(f"Task {task_id} completed successfully")
            else:
                self.logger.error(f"Task {task_id} failed: {result.get('error')}")

        except Exception as e:
            self.logger.error(f"Unexpected error executing task {task_id}: {e}")

            # Update task status to FAILED
            try:
                self.task_queue.update_status(
                    task_id,
                    TaskStatus.FAILED,
                    error_message=f"Executor error: {str(e)}"
                )
            except:
                pass

    def _cleanup_completed_tasks(self):
        """Remove completed futures from tracking"""
        with self.running_lock:
            completed_tasks = [
                task_id for task_id, future in self.running_tasks.items()
                if future.done()
            ]

            for task_id in completed_tasks:
                del self.running_tasks[task_id]

            if completed_tasks:
                self.logger.debug(f"Cleaned up {len(completed_tasks)} completed tasks")


class ExecutorManager:
    """
    Singleton manager for global executor instance

    Provides a way to start/stop a single executor service that can be
    shared across CLI commands and Slack server.
    """

    _instance: Optional[TaskExecutor] = None
    _lock = threading.Lock()

    @classmethod
    def start_executor(
        cls,
        task_queue: TaskQueue,
        agent_manager: AgentManager,
        logger: NightShiftLogger,
        max_workers: int = 3,
        poll_interval: float = 1.0
    ) -> TaskExecutor:
        """
        Start the global executor instance

        Args:
            task_queue: TaskQueue instance
            agent_manager: AgentManager instance
            logger: Logger instance
            max_workers: Maximum concurrent tasks
            poll_interval: Polling interval in seconds

        Returns:
            TaskExecutor instance
        """
        with cls._lock:
            if cls._instance and cls._instance.is_running:
                logger.warning("Executor already running")
                return cls._instance

            if not cls._instance:
                cls._instance = TaskExecutor(
                    task_queue=task_queue,
                    agent_manager=agent_manager,
                    logger=logger,
                    max_workers=max_workers,
                    poll_interval=poll_interval
                )

            cls._instance.start()
            return cls._instance

    @classmethod
    def stop_executor(cls, timeout: float = 30.0):
        """Stop the global executor instance"""
        with cls._lock:
            if cls._instance:
                cls._instance.stop(timeout=timeout)

    @classmethod
    def get_executor(cls) -> Optional[TaskExecutor]:
        """Get the global executor instance (may be None)"""
        return cls._instance

    @classmethod
    def get_status(cls) -> Dict:
        """Get executor status"""
        with cls._lock:
            if cls._instance:
                return cls._instance.get_status()
            else:
                return {
                    "is_running": False,
                    "max_workers": 0,
                    "running_tasks": 0,
                    "available_workers": 0,
                    "poll_interval": 0
                }
