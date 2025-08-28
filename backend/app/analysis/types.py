from typing import TypedDict, Any

class AnalysisResult(TypedDict, total=False):
    pylint: dict
    bandit: dict
    radon: dict
