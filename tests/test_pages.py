"""Tests for the backend-served web pages (D31, §9.1).

The player card, the standalone standings page, and the public JSON views they
read. The pages are inline HTML with no templating, so the assertions check the
load-bearing substrings + that the public endpoints serve the shapes the inline
JS expects -- enough to catch a broken page or a renamed endpoint field before
someone opens the page on a phone at camp and finds it blank.
"""
from tests.test_server_api import _force_target


def test_root_redirects_to_player_card(server):
    r = server.client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 307)
    assert r.headers["location"] == "/gotcha/"


def test_player_card_renders(server):
    r = server.client.get("/gotcha/")
    assert r.status_code == 200
    assert "!Fri3d Friends" in r.text
    # the three sections the page wires up (player, boards, hit list)
    assert 'id="me"' in r.text
    assert 'id="board"' in r.text
    assert 'id="hitlist"' in r.text
    # nav link to the standalone standings page
    assert 'href="/klassement"' in r.text


def test_standings_page_renders(server):
    r = server.client.get("/klassement")
    assert r.status_code == 200
    assert "Klassement" in r.text
    # all four boards are offered as tabs
    for label in ("Totaal (punten)", "Langste reeks",
                  "Groepen: totaal", "Groepen: per lid"):
        assert label in r.text
    assert 'id="boardbody"' in r.text
    assert 'id="hitlist"' in r.text


def test_public_leaderboard_supports_all_four_boards(server, badges):
    server.start_game()
    badges(n=3, groups=["makers"])
    for board in ("total", "streak", "group_total", "group_per_member"):
        r = server.client.get("/v1/public/leaderboard", params={"board": board, "limit": 10})
        assert r.status_code == 200, (board, r.text)
        body = r.json()
        assert body["board"] == board
        assert isinstance(body["entries"], list)


def test_public_player_card_shape(server, badges):
    server.start_game()
    b = badges(n=1, groups=["makers"])
    r = server.client.get("/v1/public/player/%d" % b.pid)
    assert r.status_code == 200, r.text
    d = r.json()
    # the fields the player-card JS reads
    for k in ("pid", "name", "status", "status_nl", "score", "kills",
              "deaths", "streak", "best_streak", "rank_total", "groups"):
        assert k in d, k
    # no target without the read token (public view only)
    assert "target" not in d


def test_public_hitlist_shape(server, badges):
    server.start_game()
    badges(n=2)
    r = server.client.get("/v1/public/hitlist")
    assert r.status_code == 200
    assert isinstance(r.json()["hitlist"], list)


def test_public_leaderboard_reflects_a_kill(server, badges):
    """A real kill lands on the public total board -- the same flush path a badge
    uses, exercised here through the badge simulator (§11 harness) so the page's
    data source is proven end to end."""
    a, v = badges(2)
    server.start_game()
    server.advance(200)                       # let spawn protection lapse
    _force_target(server, a, v)
    a.kill(v)
    r = server.client.get("/v1/public/leaderboard", params={"board": "total"})
    rows = {e["pid"]: e for e in r.json()["entries"]}
    assert rows[a.pid]["score"] >= 1, rows
    assert rows[a.pid]["kills"] == 1, rows
