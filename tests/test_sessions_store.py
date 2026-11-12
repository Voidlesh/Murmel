import pytest

from engine.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def test_session_lifecycle_stores_segments_in_order(store):
    session = store.create_session("Standup", started_at=100.0, language="de")
    assert session["status"] == "recording"
    first = store.add_session_segment(session["id"], 0.0, 5.0, "Hallo zusammen.")
    assert first["text"] == "Hallo zusammen."
    store.add_session_segment(session["id"], 5.0, 9.5, "Wir starten.")
    store.finish_session(session["id"], ended_at=200.0, status="done")

    got = store.get_session(session["id"])
    assert got["status"] == "done" and got["ended_at"] == 200.0
    assert [s["text"] for s in store.session_segments(session["id"])] == ["Hallo zusammen.", "Wir starten."]


def test_notes_and_summary_are_stored(store):
    session = store.create_session("", started_at=1.0, language="de")
    store.update_session_notes(session["id"], "- Idee notiert")
    store.set_session_summary(session["id"], "Kurz gesagt.", ["Angebot schicken"])

    got = store.get_session(session["id"])
    assert got["notes"] == "- Idee notiert"
    assert got["summary"] == "Kurz gesagt."
    assert got["action_items"] == ["Angebot schicken"]


def test_list_sessions_newest_first(store):
    older = store.create_session("alt", started_at=1.0, language="de")
    newer = store.create_session("neu", started_at=2.0, language="de")
    assert [s["id"] for s in store.list_sessions()] == [newer["id"], older["id"]]


def test_delete_session_removes_segments_and_returns_audio_path(store):
    session = store.create_session("", started_at=1.0, language="de")
    store.add_session_segment(session["id"], 0.0, 1.0, "x")
    store.set_session_audio(session["id"], "/audio/a.wav")

    assert store.delete_session(session["id"]) == "/audio/a.wav"
    with pytest.raises(KeyError):
        store.get_session(session["id"])
    assert store.session_segments(session["id"]) == []


def test_interrupted_sessions_are_marked_on_startup(store):
    session = store.create_session("", started_at=1.0, language="de")
    assert store.mark_interrupted_sessions() == 1
    assert store.get_session(session["id"])["status"] == "interrupted"
    assert store.mark_interrupted_sessions() == 0


def test_cut_off_rerun_keeps_the_old_transcript_as_done(store):
    session = store.create_session("", started_at=1.0, language="de", status="processing")
    store.add_session_segment(session["id"], 0.0, 2.0, "alt")
    store.mark_interrupted_sessions()
    assert store.get_session(session["id"])["status"] == "done"
    assert [s["text"] for s in store.session_segments(session["id"])] == ["alt"]


def test_replace_segments_swaps_the_whole_transcript(store):
    session = store.create_session("", started_at=1.0, language="de", source="desktop", terms="Eigenwert")
    store.add_session_segment(session["id"], 0.0, 2.0, "alt")
    store.replace_session_segments(session["id"], [("them", 0.0, 1.0, "neu"), ("you", 1.0, 2.0, "auch neu")])
    assert [(s["speaker"], s["text"]) for s in store.session_segments(session["id"])] == [
        ("them", "neu"), ("you", "auch neu"),
    ]
    stored = store.get_session(session["id"])
    assert (stored["source"], stored["terms"]) == ("desktop", "Eigenwert")


def test_session_audio_pruning_keeps_newest(store):
    ids = [store.create_session("", started_at=float(i), language="de")["id"] for i in range(3)]
    for session_id in ids:
        store.set_session_audio(session_id, f"/audio/{session_id}.wav")

    assert [path for _, path in store.session_audio_paths_beyond(2)] == [f"/audio/{ids[0]}.wav"]
    store.clear_session_audio_path(ids[0])
    assert store.session_audio_paths_beyond(2) == []


def test_segments_keep_their_speaker_and_default_to_you(store):
    session = store.create_session("Call", started_at=1.0, language="de")
    store.add_session_segment(session["id"], 0.0, 2.0, "Hallo von mir.")
    store.add_session_segment(session["id"], 2.0, 4.0, "Hallo zurück.", speaker="them")

    speakers = [seg["speaker"] for seg in store.session_segments(session["id"])]

    assert speakers == ["you", "them"]
