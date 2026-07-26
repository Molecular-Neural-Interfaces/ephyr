
class BaseCommand:
    """Base command for undo/redo operations."""
    description: str = ""

    def do(self, wrapper: "QtWeegitSessionManagerWrapper") -> None:
        """Execute the command. Should emit necessary signals via wrapper."""
        raise NotImplementedError

    def undo(self, wrapper: "QtWeegitSessionManagerWrapper") -> None:
        """Revert the command. Should emit necessary signals via wrapper."""
        raise NotImplementedError
