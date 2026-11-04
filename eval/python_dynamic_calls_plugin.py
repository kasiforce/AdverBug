"""Re-enable the dynamic profile after coverage initializes pytest."""

import sitecustomize


def pytest_sessionstart(session):
    if sitecustomize.os.environ.get("ADVER_TRACE_DISABLED") != "1":
        sitecustomize.enable()
