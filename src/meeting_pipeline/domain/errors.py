"""Typed errors crossing application boundaries."""


class PipelineError(RuntimeError):
    """Base error carrying a stable machine-readable code."""

    code = "PIPELINE_ERROR"


class InvalidAudioError(PipelineError):
    """Audio failed validation or decoding."""

    code = "INVALID_AUDIO"


class AlignmentError(PipelineError):
    """Sources do not contain enough common evidence to align safely."""

    code = "ALIGNMENT_FAILED"


class ModelUnavailableError(PipelineError):
    """A required model or access credential is unavailable."""

    code = "MODEL_UNAVAILABLE"


class DataBudgetExceededError(PipelineError):
    """A transfer would exceed its configured network byte budget."""

    code = "DATA_BUDGET_EXCEEDED"


class DataBudgetBlockedError(PipelineError):
    """A remote package cannot be selectively fetched within budget."""

    code = "DATA_BUDGET_BLOCKED"
