from unittest import mock

import pytest

from tv_view import (
    TvViewer,
    build_rtsp_url,
    compositor_cmd,
    compute_grid,
    detect_host_ip,
    feeder_cmd,
    grid_layout,
    resolve_cameras,
)


def test_build_rtsp_url_encodes_credentials():

    url = build_rtsp_url(
        {
            "host": "192.168.2.32",
            "port": 554,
            "user": "admin",
            "password": "s3cr3t@@",
            "path": "/h264Preview_01_sub",
        }
    )

    assert url == (
        "rtsp://admin:s3cr3t%40%40"
        "@192.168.2.32:554/h264Preview_01_sub"
    )


def test_build_rtsp_url_defaults():

    url = build_rtsp_url(
        {
            "host": "10.0.0.1",
            "user": "edgeguard",
            "password": "plain",
        }
    )

    assert url == (
        "rtsp://edgeguard:plain@10.0.0.1:554/Preview_01_main"
    )


def test_build_rtsp_url_without_user():

    url = build_rtsp_url({"host": "10.0.0.1"})

    assert url == "rtsp://10.0.0.1:554/Preview_01_main"


def test_build_rtsp_url_requires_host():

    with pytest.raises(ValueError):
        build_rtsp_url({"user": "x"})


def test_resolve_cameras_by_id():

    rtsp = [
        {
            "id": "back_yard",
            "host": "192.168.2.184",
            "user": "edgeguard",
            "password": "shared",
            "path": "/Preview_01_main",
        }
    ]

    sources = resolve_cameras(["back_yard"], rtsp)

    assert sources == [
        (
            "back_yard",
            "rtsp://edgeguard:shared"
            "@192.168.2.184:554/Preview_01_main",
        )
    ]


def test_resolve_cameras_id_falls_back_to_shared_password():

    rtsp = [
        {
            "id": "garage",
            "host": "192.168.2.183",
            "user": "edgeguard",
        }
    ]

    sources = resolve_cameras(
        ["garage"], rtsp, shared_password="env-secret"
    )

    assert "edgeguard:env-secret@" in sources[0][1]


def test_resolve_cameras_passes_through_sources():

    sources = resolve_cameras(
        [
            "rtsp://admin:p%40ss@10.0.0.9:554/sub",
            "v4l2:/dev/video2",
        ]
    )

    assert sources[0][1] == (
        "rtsp://admin:p%40ss@10.0.0.9:554/sub"
    )

    assert sources[1][1] == "v4l2:/dev/video2"


def test_resolve_cameras_dict_source():

    sources = resolve_cameras(
        [{"id": "tv", "source": "v4l2:/dev/video4"}]
    )

    assert sources == [("tv", "v4l2:/dev/video4")]


def test_resolve_cameras_dict_inline_doorbell():

    sources = resolve_cameras(
        [
            {
                "id": "front_door",
                "host": "192.168.2.32",
                "user": "admin",
                "password": "own@@",
                "path": "/h264Preview_01_sub",
            }
        ]
    )

    assert sources == [
        (
            "front_door",
            "rtsp://admin:own%40%40"
            "@192.168.2.32:554/h264Preview_01_sub",
        )
    ]


def test_resolve_cameras_dict_merges_rtsp_entry():

    rtsp = [
        {
            "id": "front_door",
            "host": "192.168.2.32",
            "user": "admin",
            "password": "rtsp-secret",
            "path": "/h264Preview_01_main",
        }
    ]

    sources = resolve_cameras(
        [{"id": "front_door", "path": "/h264Preview_01_sub"}],
        rtsp,
    )

    assert "h264Preview_01_sub" in sources[0][1]

    assert "rtsp-secret" in sources[0][1]


def test_resolve_cameras_password_override_wins():

    rtsp = [
        {
            "id": "front_door",
            "host": "192.168.2.32",
            "user": "admin",
            "password": "rtsp-secret",
        }
    ]

    sources = resolve_cameras(
        [{"id": "front_door", "password": "override"}],
        rtsp,
    )

    assert "admin:override@" in sources[0][1]


def test_resolve_cameras_unknown_id():

    with pytest.raises(ValueError):
        resolve_cameras(["nope"], [])


def test_compute_grid_layouts():

    assert compute_grid(1) == {
        "cols": 1,
        "rows": 1,
        "pane_w": 1920,
        "pane_h": 1080,
    }

    assert compute_grid(2)["pane_w"] == 960
    assert compute_grid(2)["pane_h"] == 540
    assert compute_grid(3)["pane_w"] == 640
    assert compute_grid(3)["rows"] == 1
    assert compute_grid(4)["rows"] == 2
    assert compute_grid(4)["pane_w"] == 960
    assert compute_grid(4)["pane_h"] == 540
    assert compute_grid(5)["rows"] == 3
    assert compute_grid(5)["pane_h"] == 360


def test_compute_grid_columns_override():

    grid = compute_grid(4, columns=4)

    assert grid["cols"] == 4
    assert grid["rows"] == 1
    assert grid["pane_w"] == 480
    assert grid["pane_h"] == 540


def test_grid_layout_string():

    layout = grid_layout(compute_grid(4), 4)

    assert layout == "0_0|960_0|0_540|960_540"


def test_feeder_cmd_rtsp():

    cmd = feeder_cmd(
        "rtsp://cam/stream",
        compute_grid(2),
        10,
        "ffmpeg",
    )

    joined = " ".join(cmd)

    assert "-rtsp_transport tcp" in joined
    assert "-allowed_media_types video" in joined
    assert "-timeout 15000000" in joined
    assert "fps=10" in joined
    assert "xstack" not in joined
    assert cmd[-3:] == ["-f", "rawvideo", "-"]


def test_feeder_cmd_v4l2():

    cmd = feeder_cmd(
        "v4l2:/dev/video2",
        compute_grid(1),
        10,
        "ffmpeg",
    )

    joined = " ".join(cmd)

    assert "-f v4l2 -i /dev/video2" in joined
    assert "-rtsp_transport" not in joined


def test_compositor_cmd():

    fifos = [f"/tmp/p/cam{i}.raw" for i in range(4)]

    cmd = compositor_cmd(
        fifos,
        compute_grid(4),
        10,
        "/tmp/hls",
        "http://10.0.0.5:8100",
        2000,
        "ffmpeg",
    )

    joined = " ".join(cmd)

    assert joined.count("-f rawvideo") == 4
    assert "xstack=inputs=4" in joined
    assert "layout=0_0|960_0|0_540|960_540" in joined
    assert "/tmp/p/cam3.raw" in joined
    assert "-hls_segment_type fmp4" in joined
    assert "-start_number 2000" in joined
    assert "init2000.mp4" in joined
    assert "seg2000_%05d.m4s" in joined
    assert "http://10.0.0.5:8100/" in joined
    assert "/tmp/hls/live.m3u8" in joined


def test_detect_host_ip_uses_reachable_probe():

    fake = mock.Mock()

    fake.getsockname.return_value = ("192.168.2.100", 12345)

    with mock.patch(
        "tv_view.socket.socket",
        return_value=fake,
    ):

        assert detect_host_ip(["192.168.2.184"]) == (
            "192.168.2.100"
        )

    fake.connect.assert_called_once_with(
        ("192.168.2.184", 9)
    )


def test_detect_host_ip_gives_up():

    failing = mock.Mock()

    failing.connect.side_effect = OSError("nope")

    with mock.patch(
        "tv_view.socket.socket",
        return_value=failing,
    ):

        assert detect_host_ip(["bad-host"]) == ""


def test_viewer_rejects_missing_tv():

    with pytest.raises(ValueError):
        TvViewer("", [("cam", "v4l2:/dev/video0")])


def test_viewer_rejects_empty_cameras():

    with pytest.raises(ValueError):
        TvViewer("TV", [])


def test_viewer_computes_grid():

    viewer = TvViewer(
        "TV",
        [
            ("a", "v4l2:/dev/video0"),
            ("b", "v4l2:/dev/video1"),
            ("c", "v4l2:/dev/video2"),
            ("d", "v4l2:/dev/video3"),
        ],
        ffmpeg="ffmpeg",
    )

    assert viewer.grid["cols"] == 2
    assert viewer._frame_bytes == 960 * 540 * 3 // 2
