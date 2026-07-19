from abc import ABC, abstractmethod


class BaseTool(ABC):

    """
    Base class for all enterprise tools.
    Every tool must implement execute()
    """

    @abstractmethod
    def execute(self, input_data):
        pass