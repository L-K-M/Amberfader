"""Built-in ad blocking: request rules and the profile's interceptor."""
import pytest

from amberfader.embedded.adblock import is_ad_request


@pytest.mark.parametrize("url", [
    "https://googleads.g.doubleclick.net/pagead/id",
    "https://stats.g.doubleclick.net/r/collect",
    "https://ad.doubleclick.net/ddm/clk/1",
    "https://static.doubleclick.net/instream/ad_status.js",
    "https://td.doubleclick.net/td/rul/1",
    "https://fls.doubleclick.net/activityi",
    "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js",
    "https://www.googleadservices.com/pagead/conversion/1",
    "https://www.googletagservices.com/tag/js/gpt.js",
    "https://imasdk.googleapis.com/js/sdkloader/ima3.js",
    "https://music.youtube.com/pagead/viewthroughconversion/1",
    "https://www.youtube.com/pagead/paralleladview",
    "https://music.youtube.com/youtubei/v1/player/ad_break?prettyPrint=false",
    "https://www.youtube.com/api/stats/ads?ver=2",
    "https://www.youtube.com/pcs/activeview?xai=1",
    "https://www.youtube.com/get_video_info?video_id=x&adunit=1",
    "HTTPS://WWW.YOUTUBE.COM/pagead/1",
])
def test_ad_requests_are_blocked(url):
    assert is_ad_request(url)


@pytest.mark.parametrize("url", [
    "https://music.youtube.com/",
    "https://music.youtube.com/youtubei/v1/player?prettyPrint=false",
    "https://music.youtube.com/youtubei/v1/next",
    "https://music.youtube.com/api/stats/playback?ns=yt",
    "https://music.youtube.com/api/stats/watchtime?ns=yt",
    "https://www.youtube.com/api/stats/adsomething",
    "https://www.youtube.com/get_video_info?video_id=x",
    "https://rr1---sn-abc.googlevideo.com/videoplayback?itag=251",
    "https://lh3.googleusercontent.com/abc=w60-h60",
    "https://accounts.google.com/ServiceLogin",
    "https://doubleclick.net.example.org/pagead/",
    "https://notyoutube.com/pagead/",
    "data:text/html,<p>pagead</p>",
    "not a url",
])
def test_playback_and_sign_in_requests_pass(url):
    assert not is_ad_request(url)


class _Url:
    def __init__(self, text):
        self._text = text

    def toString(self):
        return self._text


class _Request:
    def __init__(self, url):
        self._url = _Url(url)
        self.blocked = False

    def requestUrl(self):
        return self._url

    def block(self, value):
        self.blocked = value


def test_interceptor_blocks_only_while_enabled():
    pytest.importorskip(
        "PySide6.QtWebEngineCore", reason="Qt WebEngine unavailable", exc_type=ImportError,
    )
    from amberfader.embedded.page import AdRequestFilter

    interceptor = AdRequestFilter(enabled=True)
    ad, music = _Request("https://www.youtube.com/pagead/1"), _Request("https://music.youtube.com/")
    interceptor.interceptRequest(ad)
    interceptor.interceptRequest(music)
    assert (ad.blocked, music.blocked) == (True, False)

    interceptor.enabled = False
    later = _Request("https://www.youtube.com/pagead/2")
    interceptor.interceptRequest(later)
    assert later.blocked is False
