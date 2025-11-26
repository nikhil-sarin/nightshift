"""
TUI Application
Main application factory and event loop management
"""
import asyncio
from prompt_toolkit.application import Application
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding.bindings.vi import load_vi_bindings
from prompt_toolkit.key_binding import merge_key_bindings

from nightshift.core.config import Config
from nightshift.core.logger import NightShiftLogger
from nightshift.core.task_queue import TaskQueue
from nightshift.core.task_planner import TaskPlanner
from nightshift.core.agent_manager import AgentManager

from .models import UIState, task_to_row
from .layout import create_layout
from .keybindings import create_keybindings


def create_app() -> Application:
    """Create and configure the TUI application"""

    # Initialize backends
    cfg = Config()
    logger = NightShiftLogger(log_dir=str(cfg.get_log_dir()))
    queue = TaskQueue(db_path=str(cfg.get_database_path()))
    planner = TaskPlanner(logger, tools_reference_path=str(cfg.get_tools_reference_path()))
    agent = AgentManager(queue, logger, output_dir=str(cfg.get_output_dir()))

    # Initialize UI state
    state = UIState()

    # Load initial tasks
    tasks = queue.list_tasks()
    state.tasks = [task_to_row(t) for t in tasks]
    state.message = f"Loaded {len(state.tasks)} tasks"

    # Load details for the first task if any exist
    if state.tasks:
        first_task = queue.get_task(state.tasks[0].task_id)
        if first_task:
            state.selected_task.task_id = first_task.task_id
            state.selected_task.details = first_task.to_dict()
            state.selected_task.last_loaded = __import__('datetime').datetime.utcnow()

    # Create layout
    layout = create_layout(state)

    # Create keybindings (merge Vi bindings with custom)
    vi_bindings = load_vi_bindings()
    custom_bindings = create_keybindings(state)
    key_bindings = merge_key_bindings([vi_bindings, custom_bindings])

    # Define style
    style = Style.from_dict({
        "statusbar": "reverse",
        "separator": "fg:#444444",
        "dim": "fg:#666666",
        "yellow": "fg:ansiyellow",
        "blue": "fg:ansiblue",
        "cyan": "fg:ansicyan",
        "magenta": "fg:ansimagenta",
        "green": "fg:ansigreen",
        "red": "fg:ansired",
        "ansired": "fg:ansired",
    })

    # Create application
    app = Application(
        layout=layout,
        key_bindings=key_bindings,
        full_screen=True,
        style=style,
        mouse_support=False,
    )

    # Auto-refresh task list every 2 seconds
    async def auto_refresh():
        """Periodically refresh the task list"""
        while True:
            await asyncio.sleep(2)
            try:
                tasks = queue.list_tasks()
                state.tasks = [task_to_row(t) for t in tasks]
                app.invalidate()
            except Exception as e:
                logger.error(f"Auto-refresh failed: {e}")

    # Schedule auto-refresh
    app.pre_run_callables.append(
        lambda: app.create_background_task(auto_refresh())
    )

    return app
