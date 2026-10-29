import os


def _request_timeout() -> float:
    """Return a bounded per-request timeout without accepting invalid env values."""
    value = os.getenv("LLM_REQUEST_TIMEOUT", "180")
    try:
        timeout = float(value)
    except ValueError:
        return 180.0
    return timeout if timeout > 0 else 180.0


class LLMConfig:
    def __init__(self, api_key: str = None, api_endpoint: str = None, model_name: str = "gpt-4"):
        self.API_KEY = api_key if api_key is not None else os.getenv("LLM_API_KEY", "YOUR_LLM_API_KEY")
        self.API_ENDPOINT = api_endpoint if api_endpoint is not None else os.getenv("LLM_API_ENDPOINT", "https://api.apiyi.com/v1")
        self.MODEL_NAME = model_name
        # OpenAI's SDK default timeout is much too long for the retry-driven
        # pipeline: a stalled upstream response otherwise blocks every later
        # bug/test attempt indefinitely.  Set LLM_REQUEST_TIMEOUT to override.
        self.REQUEST_TIMEOUT = _request_timeout()
