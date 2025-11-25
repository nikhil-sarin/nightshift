"""
Output Viewer - Parse and display Claude task execution output in human-readable format
"""
import json
from pathlib import Path
from typing import Dict, Any, List
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.table import Table


class OutputViewer:
    """Parses stream-json output and displays it like a Claude session"""

    def __init__(self):
        self.console = Console()

    def display_task_output(self, output_file: str) -> None:
        """
        Display task output in human-readable format

        Args:
            output_file: Path to the task output JSON file
        """
        output_path = Path(output_file)
        if not output_path.exists():
            self.console.print(f"[red]Error: Output file not found: {output_file}[/red]")
            return

        with open(output_path) as f:
            data = json.load(f)

        # Display task metadata
        self._display_header(data)

        # Parse and display the execution stream
        stdout = data.get("stdout", "")
        if stdout:
            self._display_execution_stream(stdout)
        else:
            self.console.print("[yellow]No execution output found[/yellow]")

        # Display footer with execution stats
        self._display_footer(data)

    def _display_header(self, data: Dict[str, Any]) -> None:
        """Display task metadata header"""
        task_id = data.get("task_id", "unknown")
        returncode = data.get("returncode", -1)
        execution_time = data.get("execution_time", 0)

        status = "✅ SUCCESS" if returncode == 0 else "❌ FAILED"
        status_color = "green" if returncode == 0 else "red"

        header_text = f"""[bold]{status}[/bold] - Task ID: {task_id}
Execution Time: {execution_time:.2f}s
Return Code: {returncode}"""

        self.console.print(Panel(header_text, style=status_color, title="Task Execution"))
        self.console.print()

    def _display_execution_stream(self, stdout: str) -> None:
        """Parse stream-json and display execution flow"""
        lines = stdout.strip().split("\n")

        for line in lines:
            if not line:
                continue

            try:
                event = json.loads(line)
                self._display_event(event)
            except json.JSONDecodeError:
                # Plain text output
                self.console.print(line)

    def _display_event(self, event: Dict[str, Any]) -> None:
        """Display a single stream-json event"""
        event_type = event.get("type")

        if event_type == "system":
            self._display_system_event(event)
        elif event_type == "assistant":
            self._display_assistant_event(event)
        elif event_type == "user":
            self._display_user_event(event)
        elif event_type == "result":
            self._display_result_event(event)

    def _display_system_event(self, event: Dict[str, Any]) -> None:
        """Display system initialization event"""
        subtype = event.get("subtype")
        if subtype == "init":
            cwd = event.get("cwd", "unknown")
            model = event.get("model", "unknown")
            tools = event.get("tools", [])

            self.console.print(Panel(
                f"[dim]Working Directory:[/dim] {cwd}\n"
                f"[dim]Model:[/dim] {model}\n"
                f"[dim]Available Tools:[/dim] {len(tools)} tools",
                title="🔧 Session Initialized",
                style="dim"
            ))
            self.console.print()

    def _display_assistant_event(self, event: Dict[str, Any]) -> None:
        """Display assistant message or tool use"""
        message = event.get("message", {})
        content = message.get("content", [])

        for item in content:
            item_type = item.get("type")

            if item_type == "text":
                text = item.get("text", "")
                if text.strip():
                    self.console.print(Panel(
                        Markdown(text),
                        title="💬 Claude",
                        border_style="blue"
                    ))
                    self.console.print()

            elif item_type == "tool_use":
                tool_name = item.get("name", "unknown")
                tool_input = item.get("input", {})
                self._display_tool_use(tool_name, tool_input)

    def _display_tool_use(self, tool_name: str, tool_input: Dict[str, Any]) -> None:
        """Display tool invocation"""
        # Format tool input as JSON
        input_json = json.dumps(tool_input, indent=2)
        syntax = Syntax(input_json, 'json', theme='monokai', word_wrap=True)

        self.console.print(Panel(
            f"[bold cyan]Tool:[/bold cyan] {tool_name}\n\n[dim]Parameters:[/dim]",
            title="🔧 Tool Call",
            border_style="cyan"
        ))
        self.console.print(syntax)
        self.console.print()

    def _display_user_event(self, event: Dict[str, Any]) -> None:
        """Display tool results (user messages are tool results)"""
        message = event.get("message", {})
        content = message.get("content", [])

        for item in content:
            if item.get("type") == "tool_result":
                tool_result = item.get("content", "")
                is_error = item.get("is_error", False)

                style = "red" if is_error else "green"
                title = "❌ Tool Error" if is_error else "✅ Tool Result"

                # Try to format as code if it looks like code
                if isinstance(tool_result, str):
                    self.console.print(Panel(
                        tool_result,
                        title=title,
                        border_style=style
                    ))
                else:
                    self.console.print(Panel(
                        json.dumps(tool_result, indent=2),
                        title=title,
                        border_style=style
                    ))
                self.console.print()

    def _display_result_event(self, event: Dict[str, Any]) -> None:
        """Display final execution result"""
        subtype = event.get("subtype")
        is_error = event.get("is_error", False)
        result_text = event.get("result", "")
        usage = event.get("usage", {})

        status = "❌ Error" if is_error else "✅ Complete"
        style = "red" if is_error else "green"

        # Display final result
        if result_text:
            self.console.print(Panel(
                Markdown(result_text),
                title=status,
                border_style=style
            ))
            self.console.print()

        # Display usage statistics
        if usage:
            self._display_usage_stats(usage)

    def _display_usage_stats(self, usage: Dict[str, Any]) -> None:
        """Display token usage and cost statistics"""
        table = Table(title="📊 Usage Statistics", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="yellow")

        # Token usage
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        total_cost = usage.get("total_cost_usd", 0)

        table.add_row("Input Tokens", f"{input_tokens:,}")
        table.add_row("Output Tokens", f"{output_tokens:,}")
        if cache_read > 0:
            table.add_row("Cache Read Tokens", f"{cache_read:,}")
        if cache_creation > 0:
            table.add_row("Cache Creation Tokens", f"{cache_creation:,}")
        table.add_row("Total Cost", f"${total_cost:.4f}")

        self.console.print(table)
        self.console.print()

    def _display_footer(self, data: Dict[str, Any]) -> None:
        """Display execution summary footer"""
        stderr = data.get("stderr", "")
        if stderr.strip():
            self.console.print(Panel(
                stderr,
                title="⚠️  Stderr Output",
                border_style="yellow"
            ))
            self.console.print()
