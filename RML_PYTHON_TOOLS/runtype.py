from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

@dataclass
class RunType:
    Type: str = ""
    NumberOfRuns: int = 0
    LeftMean: float = 0.0
    RightMean: float = 0.0
    LeftSDev: float = 0.0
    RightSDev: float = 0.0
    LeftArray: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=float))
    RightArray: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=float))

    def add_run(self, right, left):
        """
        MATLAB logic implied collecting runs and keeping mean/std.
        The original code never incremented NumberOfRuns; we fix that here.
        Accepts scalar or 1D array-like for right/left.
        """
        right = np.atleast_1d(right).astype(float)
        left = np.atleast_1d(left).astype(float)

        # First run (becomes row vectors)
        if self.NumberOfRuns == 0:
            self.LeftArray = left.reshape(1, -1)
            self.RightArray = right.reshape(1, -1)
        else:
            # subsequent: stack rows
            self.LeftArray = np.vstack([self.LeftArray, left.reshape(1, -1)])
            self.RightArray = np.vstack([self.RightArray, right.reshape(1, -1)])

        self.NumberOfRuns += 1

        # Means across runs
        self.LeftMean = float(np.mean(self.LeftArray))
        self.RightMean = float(np.mean(self.RightArray))

        # Std across runs (row-wise population)
        if self.NumberOfRuns > 1:
            self.LeftSDev = float(np.std(self.LeftArray[:self.NumberOfRuns, :], ddof=1))
            self.RightSDev = float(np.std(self.RightArray[:self.NumberOfRuns, :], ddof=1))
        else:
            self.LeftSDev = 0.0
            self.RightSDev = 0.0

        return self

    def __len__(self):
        return self.NumberOfRuns
