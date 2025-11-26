"""
TUI Keybindings
Vi-style keymaps for NightShift
"""
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import vi_insert_mode
from prompt_toolkit.application.current import get_app
from .models import UIState


def create_keybindings(state: UIState) -> KeyBindings:
    """Create keybindings for the TUI"""
    kb = KeyBindings()

    # Movement: j/k for up/down navigation
    @kb.add('j', filter=~vi_insert_mode)
    def _(event):
        """Move selection down"""
        if state.selected_index < len(state.tasks) - 1:
            state.selected_index += 1

    @kb.add('k', filter=~vi_insert_mode)
    def _(event):
        """Move selection up"""
        if state.selected_index > 0:
            state.selected_index -= 1

    # Tab switching: 1-4 for direct tab access
    @kb.add('1', filter=~vi_insert_mode)
    def _(event):
        """Switch to overview tab"""
        state.detail_tab = "overview"

    @kb.add('2', filter=~vi_insert_mode)
    def _(event):
        """Switch to exec tab"""
        state.detail_tab = "exec"

    @kb.add('3', filter=~vi_insert_mode)
    def _(event):
        """Switch to files tab"""
        state.detail_tab = "files"

    @kb.add('4', filter=~vi_insert_mode)
    def _(event):
        """Switch to summary tab"""
        state.detail_tab = "summary"

    # H/L for prev/next tab
    @kb.add('H', filter=~vi_insert_mode)
    def _(event):
        """Previous tab"""
        tabs = ["overview", "exec", "files", "summary"]
        current_idx = tabs.index(state.detail_tab)
        state.detail_tab = tabs[(current_idx - 1) % len(tabs)]

    @kb.add('L', filter=~vi_insert_mode)
    def _(event):
        """Next tab"""
        tabs = ["overview", "exec", "files", "summary"]
        current_idx = tabs.index(state.detail_tab)
        state.detail_tab = tabs[(current_idx + 1) % len(tabs)]

    # Quit
    @kb.add('q', filter=~vi_insert_mode)
    def _(event):
        """Quit the TUI"""
        event.app.exit()

    # Refresh
    @kb.add('c-l')
    def _(event):
        """Refresh display"""
        state.message = "Refreshed"
        get_app().invalidate()

    return kb
