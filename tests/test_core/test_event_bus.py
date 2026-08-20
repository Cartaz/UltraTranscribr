# tests/test_core/test_event_bus.py
"""Test per l'EventBus dell'applicazione unificata."""

from core.event_bus import EventBus


class TestEventBus:
    """Test per il bus eventi singleton."""

    def test_singleton_identity(self) -> None:
        """Istanze multiple devono riferire allo stesso singleton."""
        a = EventBus()
        b = EventBus()
        assert a is b

    def test_subscribe_and_emit(self) -> None:
        """Subscribe + Emit deve invocare l'handler con i dati."""
        bus = EventBus()
        received = []
        bus.subscribe("test_event", lambda data: received.append(data))
        bus.emit("test_event", {"key": "value"})
        assert len(received) == 1
        assert received[0] == {"key": "value"}

    def test_multiple_handlers(self) -> None:
        """Piu handler per lo stesso evento devono essere tutti invocati."""
        bus = EventBus()
        results_a: list[str] = []
        results_b: list[str] = []
        bus.subscribe("multi", lambda _: results_a.append("a"))
        bus.subscribe("multi", lambda _: results_b.append("b"))
        bus.emit("multi", None)
        assert results_a == ["a"]
        assert results_b == ["b"]

    def test_unsubscribe(self) -> None:
        """Unsubscribe deve rimuovere l'handler."""
        bus = EventBus()
        counter = [0]
        handler = lambda _: counter.__setitem__(0, counter[0] + 1)  # noqa: E731
        bus.subscribe("unsub", handler)
        bus.emit("unsub", None)
        assert counter[0] == 1
        bus.unsubscribe("unsub", handler)
        bus.emit("unsub", None)
        assert counter[0] == 1

    def test_emit_without_handlers(self) -> None:
        """Emit senza handler non deve sollevare eccezioni."""
        bus = EventBus()
        bus.emit("no_handlers", None)

    def test_error_isolation(self) -> None:
        """Un handler che solleva eccezione non deve bloccare gli altri."""
        bus = EventBus()
        results: list[str] = []
        bus.subscribe("error_test", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
        bus.subscribe("error_test", lambda _: results.append("ok"))
        bus.emit("error_test", None)
        # Il secondo handler deve essere eseguito comunque
        assert results == ["ok"]
