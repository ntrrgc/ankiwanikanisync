from __future__ import annotations

from ankiwanikanisync.wk_api import wk

from .fixtures import SubSession


def test_assignment(session_mock: SubSession):
    subj = session_mock.add_subject("kanji")

    assignment = session_mock.add_assignment(subject_id=subj["id"])
    resp = wk.api_req("assignments", assignment["id"])

    assert assignment == resp

    resp2 = wk.query("assignments")
    assert resp2["data"] == [assignment]


def test_assignment_cleanup(session_mock: SubSession):
    resp = wk.query("assignments")
    assert resp["data"] == []


def test_study_materials(session_mock: SubSession):
    subj = session_mock.add_subject("kanji")

    study_mat = session_mock.add_study_materials(subject_id=subj["id"])
    resp = wk.api_req("study_materials", study_mat["id"])

    assert study_mat == resp

    resp2 = wk.query("study_materials")
    assert resp2["data"] == [study_mat]


def test_study_materials_cleanup(session_mock: SubSession):
    resp = wk.query("study_materials")
    assert resp["data"] == []


def test_subject(session_mock: SubSession):
    subj = session_mock.add_subject("kanji")
    resp = wk.api_req("subjects", subj["id"])

    assert subj == resp

    resp2 = wk.query("subjects")
    assert resp2["data"] == [subj]


def test_subject_cleanup(session_mock: SubSession):
    resp = wk.query("subjects")
    assert resp["data"] == []
