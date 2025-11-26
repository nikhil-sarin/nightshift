"""
TUI Layout
prompt_toolkit layout configuration
"""
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.containers import FloatContainer
from .models import UIState
from .widgets import create_task_list_window, create_detail_window, create_status_bar


def create_root_container(state: UIState):
    """Create the root container for the TUI"""

    # Main body: task list | separator | detail panel
    body = VSplit([
        create_task_list_window(state),
        Window(width=1, char='│', style='class:separator'),
        create_detail_window(state),
    ])

    # Status bar at bottom
    status = create_status_bar(state)

    # Vertical split: body + status
    root = HSplit([
        body,
        status,
    ])

    # Wrap in FloatContainer for future modals
    float_container = FloatContainer(
        content=root,
        floats=[
            # Modals will go here in later phases
        ],
    )

    return float_container


def create_layout(state: UIState) -> Layout:
    """Create the prompt_toolkit Layout"""
    root = create_root_container(state)
    return Layout(root)
