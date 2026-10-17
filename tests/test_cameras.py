"""Offline tests for sotonship26.data.cameras: fake fetcher, fake detector, no network."""

from __future__ import annotations

import io
import urllib.error
from email.message import Message

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from sotonship26.data import cameras as cam

T0 = pd.Timestamp("2026-10-17T09:00:00", tz="UTC")


def jpeg(width: int = 720, height: int = 576, shade: int = 100, flat: bool = False) -> bytes:
    """A test JPEG: top-left pixel carries ``shade``; the rest is a gradient unless ``flat``."""
    rgb = np.full((height, width, 3), shade, dtype=np.uint8)
    if not flat:
        rgb[8:] = np.linspace(0, 255, width, dtype=np.uint8)[None, :, None]
        rgb[:8, :8] = shade
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def table(*ids: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"camera_id": list(ids), "still_url": [cam.STILL_URL.format(id=i) for i in ids]}
    )


class FakeFetch:
    """Serves queued stills per camera id; an Exception in the queue is raised instead."""

    def __init__(self, stills: dict[str, list]):
        self.stills = stills
        self.urls: list[str] = []

    def __call__(self, url: str) -> cam.Still:
        self.urls.append(url)
        cam_id = url.rsplit("/", 1)[-1].removesuffix(".jpg")
        item = self.stills[cam_id].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_detector(rgb: np.ndarray, mode: str = "street") -> pd.DataFrame:
    assert mode == "street" and rgb.ndim == 3 and rgb.shape[2] == 3
    shade = int(rgb[0, 0, 0])
    return pd.DataFrame(
        [{"polygon_id": "all", "cars": shade // 10, "large_vehicles": 1, "conf_mean": 0.5,
          "model": "fake.pt"}]
    )


def test_camera_table_is_complete():
    t = cam.CAMERAS
    for col in ["camera_id", "name", "road", "junction", "direction", "still_url", "source",
                "checked"]:
        assert col in t.columns and t[col].notna().all(), col
    assert t["camera_id"].is_unique
    assert set(t["road"]) == {"M27", "M3"}
    assert (t["still_url"] == t["camera_id"].map(lambda i: cam.STILL_URL.format(id=i))).all()


def test_schema_and_values():
    fetch = FakeFetch({"1": [cam.Still(jpeg(shade=120), T0)], "2": [cam.Still(jpeg(), T0)]})
    out = cam.sample_once(table("1", "2"), detector=fake_detector, fetch=fetch)
    assert list(out.columns) == cam.COLUMNS
    first = out.iloc[0]
    assert first["camera_id"] == "1" and first["fetched_at_utc"] == T0
    assert pd.isna(first["image_time"])
    assert (first["width"], first["height"]) == (720, 576)
    assert first["large_vehicles"] == 1 and first["model"] == "fake.pt"
    assert 10 <= first["cars"] <= 13  # JPEG shade 120 +- compression


def test_last_modified_becomes_image_time():
    lm = pd.Timestamp("2026-10-17T08:59:30", tz="UTC")
    fetch = FakeFetch({"1": [cam.Still(jpeg(), T0, lm)]})
    out = cam.sample_once(table("1"), detector=fake_detector, fetch=fetch)
    assert out["image_time"].iloc[0] == lm


def test_unchanged_still_is_skipped_changed_is_counted():
    same = jpeg(shade=50)
    fetch = FakeFetch(
        {"1": [cam.Still(same, T0), cam.Still(same, T0 + pd.Timedelta(minutes=5)),
               cam.Still(jpeg(shade=200), T0 + pd.Timedelta(minutes=10))]}
    )
    seen: dict[str, str] = {}
    runs = [cam.sample_once(table("1"), fake_detector, fetch, seen) for _ in range(3)]
    assert [len(r) for r in runs] == [1, 0, 1]
    # Same Last-Modified, different bytes: still treated as unchanged.
    lm = pd.Timestamp("2026-10-17T08:00", tz="UTC")
    fetch = FakeFetch({"2": [cam.Still(jpeg(shade=10), T0, lm), cam.Still(jpeg(shade=90), T0, lm)]})
    seen = {}
    runs = [cam.sample_once(table("2"), fake_detector, fetch, seen) for _ in range(2)]
    assert [len(r) for r in runs] == [1, 0]


def test_placeholder_card_and_blank_frame_skipped():
    fetch = FakeFetch(
        {
            "1": [cam.Still(jpeg(352, 288), T0)],
            "2": [cam.Still(jpeg(), T0)],
            "3": [cam.Still(jpeg(shade=92, flat=True), T0)],
        }
    )
    out = cam.sample_once(table("1", "2", "3"), detector=fake_detector, fetch=fetch)
    assert out["camera_id"].tolist() == ["2"]


def test_failures_are_logged_and_skipped(caplog):
    def flaky_detector(rgb, mode="street"):
        if int(rgb[0, 0, 0]) > 240:
            raise RuntimeError("model blew up")
        return fake_detector(rgb, mode)

    fetch = FakeFetch(
        {
            "1": [urllib.error.URLError("timed out")],
            "2": [cam.Still(b"not a jpeg", T0)],
            "3": [cam.Still(jpeg(shade=250), T0)],
            "4": [cam.Still(jpeg(), T0)],
        }
    )
    out = cam.sample_once(table("1", "2", "3", "4"), detector=flaky_detector, fetch=fetch)
    assert out["camera_id"].tolist() == ["4"]
    logged = caplog.text
    assert "camera 1" in logged and "camera 2" in logged and "camera 3" in logged


def test_all_cameras_non_image_stops():
    fetch = FakeFetch({"1": [cam.NotAnImageError("html")], "2": [cam.NotAnImageError("html")]})
    with pytest.raises(cam.NotAnImageError):
        cam.sample_once(table("1", "2"), detector=fake_detector, fetch=fetch)


def test_pause_between_cameras():
    sleeps: list[float] = []
    fetch = FakeFetch({i: [cam.Still(jpeg(), T0)] for i in "123"})
    cam.sample_once(table("1", "2", "3"), fake_detector, fetch, pause=1.5, sleep=sleeps.append)
    assert sleeps == [1.5, 1.5]


class FakeResponse:
    def __init__(self, body: bytes, content_type: str, last_modified: str | None = None):
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if last_modified:
            self.headers["Last-Modified"] = last_modified

    def read(self, n: int = -1) -> bytes:
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_still_retries_with_backoff_and_sends_user_agent(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_header("User-agent"), timeout))
        if len(calls) < 3:
            raise urllib.error.URLError("temporary")
        return FakeResponse(b"\xff\xd8jpeg", "image/jpeg", "Sat, 17 Oct 2026 08:59:30 GMT")

    monkeypatch.setattr(cam.urllib.request, "urlopen", urlopen)
    sleeps: list[float] = []
    still = cam.fetch_still("http://x/1.jpg", timeout=5, sleep=sleeps.append)
    assert still.data == b"\xff\xd8jpeg"
    assert still.last_modified == pd.Timestamp("2026-10-17T08:59:30", tz="UTC")
    assert sleeps == [cam.BACKOFF, cam.BACKOFF * 2]
    assert calls[0] == (cam.USER_AGENT, 5)


def test_fetch_still_gives_up_and_does_not_retry_404_or_html(monkeypatch):
    def gone(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)

    monkeypatch.setattr(cam.urllib.request, "urlopen", gone)
    sleeps: list[float] = []
    with pytest.raises(urllib.error.HTTPError):
        cam.fetch_still("http://x/1.jpg", sleep=sleeps.append)
    assert sleeps == []

    monkeypatch.setattr(
        cam.urllib.request, "urlopen", lambda r, timeout: FakeResponse(b"<html>", "text/html")
    )
    with pytest.raises(cam.NotAnImageError):
        cam.fetch_still("http://x/1.jpg", sleep=sleeps.append)
    assert sleeps == []


def test_parse_until_reads_local_time():
    assert cam.parse_until("2026-10-18T13:00") == pd.Timestamp("2026-10-18T12:00", tz="UTC")
    assert cam.parse_until("2026-10-18T13:00Z") == pd.Timestamp("2026-10-18T13:00", tz="UTC")


def test_main_once_writes_only_the_counts_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = cam.CAMERAS["camera_id"].tolist()[:3]
    fetch = FakeFetch({i: [cam.Still(jpeg(), T0)] for i in ids})
    out_dir = tmp_path / "out"
    code = cam.main(
        ["--once", "--ids", ",".join(ids), "--pause", "0", "--out-dir", str(out_dir)],
        detector=fake_detector,
        fetch=fetch,
        sleep=lambda s: None,
    )
    assert code == 0
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert files == ["out", "out/counts_2026-10-17.csv"]
    written = pd.read_csv(out_dir / "counts_2026-10-17.csv", dtype={"camera_id": str})
    assert list(written.columns) == cam.COLUMNS
    assert written["camera_id"].tolist() == ids


def test_main_loops_until_and_appends(tmp_path):
    clock_times = iter(T0 + pd.Timedelta(seconds=s) for s in [0, 10, 300, 310, 600, 610])
    ids = cam.CAMERAS["camera_id"].tolist()[:1]
    stills = [cam.Still(jpeg(shade=s), T0) for s in (40, 40, 160)]
    sleeps: list[float] = []
    code = cam.main(
        ["--every", "300", "--until", "2026-10-17T10:10", "--ids", ids[0], "--pause", "0",
         "--out-dir", str(tmp_path)],
        detector=fake_detector,
        fetch=FakeFetch({ids[0]: stills}),
        sleep=sleeps.append,
        clock=lambda: next(clock_times),
    )
    assert code == 0 and sleeps == [290.0, 290.0]
    written = pd.read_csv(tmp_path / "counts_2026-10-17.csv")
    assert len(written) == 2  # the second still was unchanged
    assert list(tmp_path.iterdir()) == [tmp_path / "counts_2026-10-17.csv"]


def test_main_stops_on_challenge_page(tmp_path):
    ids = cam.CAMERAS["camera_id"].tolist()[:2]
    fetch = FakeFetch({i: [cam.NotAnImageError("text/html")] for i in ids})
    code = cam.main(
        ["--ids", ",".join(ids), "--pause", "0", "--out-dir", str(tmp_path)],
        detector=fake_detector, fetch=fetch, sleep=lambda s: None,
    )
    assert code == 3 and list(tmp_path.iterdir()) == []
