"""coord/linear_bus.py: event filtering, mentions, settings. No network: Linear is never called."""

import os
import re
import tomllib

import linear_bus as bus

NOW = "2026-10-24T10:00:00.000Z"


def comment(id_, body, who="Ann"):
    return {"id": id_, "createdAt": NOW, "body": body, "user": {"name": who},
            "issue": {"identifier": "OXH-1", "title": "hello", "url": "https://linear.app/x"}}


def issue(id_, description, labels=()):
    return {"id": id_, "createdAt": NOW, "identifier": "OXH-2", "title": "t", "url": "u",
            "description": description, "creator": {"name": "Ann"}, "assignee": None,
            "labels": {"nodes": [{"name": n} for n in labels]}}


def poll(comments=(), issues=(), moved=()):
    return {"comments": {"nodes": list(comments)}, "newIssues": {"nodes": list(issues)},
            "moved": {"nodes": list(moved)}}


def test_own_comments_are_dropped_even_when_linear_escapes_the_brackets():
    data = poll([comment("1", "\\[seb-claude\\] hello"), comment("2", "  [seb-claude] hi"),
                 comment("3", "[keanu-claude] yo"), comment("4", "plain human note")])
    assert [e["id"] for e in bus.collect_events(data, "seb")] == ["3", "4"]


def test_issues_filed_by_this_agent_are_dropped_and_labels_are_listed():
    data = poll(issues=[issue("a", "body\n\n_filed by \\[seb-claude\\]_"),
                        issue("b", "from a human", labels=("research", "agent:seb"))])
    events = bus.collect_events(data, "seb")
    assert [e["id"] for e in events] == ["b"]
    assert events[0]["text"].startswith("labels: research, agent:seb | assignee: -")


def test_moves_skip_the_viewer_and_history_before_since():
    def h(id_, at, actor, **kw):
        return {"id": id_, "createdAt": at, "actor": {"name": actor}, "fromState": None,
                "toState": None, "fromAssignee": None, "toAssignee": None, **kw}

    node = {"identifier": "OXH-3", "title": "t", "history": {"nodes": [
        h("new", "2026-10-24T10:05:00.000Z", "Ann", fromState={"name": "Todo"}, toState={"name": "In Progress"}),
        h("old", "2026-10-24T09:00:00.000Z", "Ann", toState={"name": "Done"}),
        h("mine", "2026-10-24T10:06:00.000Z", "Me", toState={"name": "Done"}),
        h("assign", "2026-10-24T10:07:00.000Z", "Ann", toAssignee={"name": "Bo"})]}}
    events = bus.collect_moves(poll(moved=[node]), since=NOW, viewer="Me")
    assert [(e["id"], e["text"]) for e in events] == [("new", "Todo -> In Progress"), ("assign", "assignee -> Bo")]


def test_mentions_mark_events_for_the_right_agent():
    for text in ("ping @SEB please", "@all standup", "labels: agent:seb | assignee: -"):
        assert bus.is_directed({"text": text}, "seb")
    assert not bus.is_directed({"text": "@keanu only"}, "seb")
    event = {"at": "2026-10-24T10:05:00.000Z", "kind": "comment", "issue": "OXH-1", "who": "Ann",
             "title": "hello", "text": "@seb " + "x" * 800}
    line = bus.format_event(event, "seb")
    assert line.startswith(">>> FOR YOU [10:05Z] comment OXH-1 by Ann: hello")
    assert line.endswith("...(truncated, open the issue)")


def test_look_back_and_seen_ids_deduplicate_overlapping_polls():
    assert bus.look_back("2026-10-24T10:02:00.000Z") == NOW  # two-minute overlap
    events = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert [e["id"] for e in bus.unseen(events, ["b"])] == ["a", "c"]


def test_env_file_fills_gaps_but_real_environment_wins(tmp_path, monkeypatch):
    env = tmp_path / "linear.env"
    env.write_text("# a comment\nLINEAR_API_KEY='lin_api_test'\nCOORD_AGENT=seb\nnot a pair\n", encoding="utf-8")
    monkeypatch.setenv("LINEAR_API_KEY", "placeholder")
    monkeypatch.delenv("LINEAR_API_KEY")  # monkeypatch restores the original state afterwards
    monkeypatch.setenv("COORD_AGENT", "keanu")
    bus.load_env_file(env)
    assert os.environ["LINEAR_API_KEY"] == "lin_api_test"
    assert os.environ["COORD_AGENT"] == "keanu"


def test_team_file_and_parser_defaults(monkeypatch):
    team = tomllib.loads((bus.TEAM_FILE).read_text(encoding="utf-8"))
    assert team["agents"] and all(re.fullmatch(r"[a-z][a-z0-9]*", a) for a in team["agents"])
    assert len(set(team["agents"])) == len(team["agents"])
    assert re.fullmatch(r"[A-Z]{2,5}", team["team"]) and team["hello_issue"].startswith(team["team"] + "-")
    assert set(f"agent:{a}" for a in team["agents"]) <= set(bus.LABELS)
    monkeypatch.delenv("COORD_TEAM", raising=False)
    args = bus.build_parser().parse_args(["--agent", team["agents"][0], "inbox"])
    assert args.team == team["team"] and args.cmd == "inbox"
    assert bus.marker("seb") == "[seb-claude]"
