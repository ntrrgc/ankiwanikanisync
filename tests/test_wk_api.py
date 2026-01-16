from __future__ import annotations

from .fixtures import SubSession


def test_wk_api_paging(session_mock: SubSession):
    from ankiwanikanisync.wk_api import wk

    res1 = {
        "object": "collection",
        "pages": {
            "next_url": f"{session_mock.BASE_URL}/req2"
        },
        "data": [1, 2],
    }
    res2 = {
        "object": "collection",
        "pages": {
            "next_url": None
        },
        "data": [3, 4],
    }

    session_mock.get("req1", json=res1)
    session_mock.get("req2", json=res2)

    res = wk.api_req("req1")

    assert res["data"] == [1, 2, 3, 4]
