"""
TUI Widgets
prompt_toolkit UI components for NightShift
"""
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Window
from .models import UIState


class TaskListControl(FormattedTextControl):
    """Control for displaying the task list"""

    def __init__(self, state: UIState):
        self.state = state
        super().__init__(self.get_text)

    def get_text(self):
        """Generate formatted text for task list"""
        lines = []
        for i, row in enumerate(self.state.tasks):
            selected = (i == self.state.selected_index)
            style = f"reverse {row.status_color}" if selected else row.status_color
            desc = row.description
            if len(desc) > 50:
                desc = desc[:47] + "..."
            created = row.created_at.split("T")[0] if row.created_at else ""
            text = f" {row.status_emoji} {row.task_id} {desc} [{created}]"
            lines.append((style, text + "\n"))

        if not lines:
            lines = [("class:dim", "No tasks\n")]

        return lines


class DetailControl(FormattedTextControl):
    """Control for displaying task details"""

    def __init__(self, state: UIState):
        self.state = state
        super().__init__(self.get_text)

    def get_text(self):
        """Generate formatted text for detail panel"""
        st = self.state.selected_task
        tab = self.state.detail_tab

        if not st.details:
            return [("class:dim", "No task selected\n")]

        lines = []

        if tab == "overview":
            lines.append(("bold", f"Task: {st.task_id}\n\n"))
            lines.append(("", f"Status: "))

            # Get status with color
            status = st.details.get('status', 'unknown').upper()
            status_colors = {
                "STAGED": "yellow",
                "RUNNING": "cyan",
                "COMPLETED": "green",
                "FAILED": "red",
                "CANCELLED": "ansired",
            }
            status_color = status_colors.get(status, "white")
            lines.append((status_color, f"{status}\n"))

            lines.append(("", f"Created: {st.details.get('created_at', 'N/A')}\n"))
            lines.append(("", f"\nDescription:\n{st.details.get('description', 'N/A')}\n"))

            if st.details.get('estimated_tokens'):
                lines.append(("", f"\nEstimated Tokens: {st.details['estimated_tokens']}\n"))
            if st.details.get('estimated_time'):
                lines.append(("", f"Estimated Time: {st.details['estimated_time']}s\n"))

        elif tab == "exec":
            lines.append(("bold", "Execution Log\n\n"))
            if st.exec_snippet:
                lines.append(("", st.exec_snippet + "\n"))
            else:
                lines.append(("class:dim", "No execution log available\n"))

        elif tab == "files":
            lines.append(("bold", "File Changes\n\n"))
            if st.files_info:
                created = st.files_info.get('created', [])
                modified = st.files_info.get('modified', [])
                deleted = st.files_info.get('deleted', [])

                if created:
                    lines.append(("green", f"Created ({len(created)}):\n"))
                    for f in created[:10]:
                        lines.append(("", f"  • {f}\n"))

                if modified:
                    lines.append(("yellow", f"Modified ({len(modified)}):\n"))
                    for f in modified[:10]:
                        lines.append(("", f"  • {f}\n"))

                if deleted:
                    lines.append(("red", f"Deleted ({len(deleted)}):\n"))
                    for f in deleted[:10]:
                        lines.append(("", f"  • {f}\n"))
            else:
                lines.append(("class:dim", "No file changes\n"))

        elif tab == "summary":
            lines.append(("bold", "Task Summary\n\n"))
            if st.summary_info:
                lines.append(("", str(st.summary_info) + "\n"))
            else:
                lines.append(("class:dim", "No summary available\n"))

        return lines


class StatusBarControl(FormattedTextControl):
    """Control for the status bar"""

    def __init__(self, state: UIState):
        self.state = state
        super().__init__(self.get_text)

    def get_text(self):
        """Generate formatted text for status bar"""
        mode = "COMMAND" if self.state.command_active else "NORMAL"
        filt = self.state.status_filter or "all"
        msg = self.state.busy_label or self.state.message or ""
        # Limit message length
        msg = msg[:80]
        text = f" {mode} | filter:{filt} | tasks:{len(self.state.tasks)} | {msg}"
        return [("class:status", text)]


def create_task_list_window(state: UIState) -> Window:
    """Create the task list window"""
    return Window(
        TaskListControl(state),
        wrap_lines=False,
        always_hide_cursor=True,
    )


def create_detail_window(state: UIState) -> Window:
    """Create the detail panel window"""
    return Window(
        DetailControl(state),
        wrap_lines=True,
        always_hide_cursor=True,
    )


def create_status_bar(state: UIState) -> Window:
    """Create the status bar window"""
    return Window(
        StatusBarControl(state),
        height=1,
        style="class:statusbar",
        always_hide_cursor=True,
    )
