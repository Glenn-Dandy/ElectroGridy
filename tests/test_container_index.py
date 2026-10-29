from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Line
from electrogridy.model.geometry import Point


def line(i: str) -> Line:
    return Line(id=i, p1=Point(0, 0), p2=Point(1, 0))


def test_lookups_stay_right_after_inserts_and_removals():
    c = EntityContainer([line("a"), line("b"), line("c")])
    c.add(line("x"), index=1)  # a x b c
    assert [e.id for e in c] == ["a", "x", "b", "c"]
    assert c.index_of("b") == 2 and "x" in c
    assert c.remove("a") == (0, line("a"))
    assert c.index_of("c") == 2 and "a" not in c
    c.remove("c")  # last one
    c.add(line("d"))
    assert [c.index_of(i) for i in ("x", "b", "d")] == [0, 1, 2]
    c.replace(Line(id="b", p1=Point(5, 5), p2=Point(6, 6)))
    assert c.get("b").p1 == Point(5, 5) and c.index_of("b") == 1


def test_batch_events_wrap_many_changes():
    c = EntityContainer()
    events: list[str] = []
    c.subscribe(lambda event, _e: events.append(event))
    with c.batch():
        with c.batch():  # nested: one pair only
            c.add(line("a"))
        c.add(line("b"))
        assert c.in_batch
    assert not c.in_batch
    assert events == ["batch_start", "added", "added", "batch_end"]
