import pytest
import requests


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that reaches the network.

    A suite that quietly makes one live call looks the same as an offline
    suite, except that it is slower. That has happened here twice: once when a
    test called a real API, and once when a category became valid and a test
    that expected a rejection went to the site instead. Both times the runtime
    was the only signal, and nobody read it.

    Blocking the transport turns a slow suite into a failed one.
    """

    def blocked(self, request, *args, **kwargs):
        raise AssertionError(
            f"A test tried to reach {request.url}. The suite must stay offline. "
            "Use a fixture or a fake fetcher."
        )

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", blocked)
