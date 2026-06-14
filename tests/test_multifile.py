def test_clip_from_info_spans_whole_file(leike):
    info = {"w": 1920, "h": 1080, "dur": 12.5, "rotation": 90,
            "fps": 30000 / 1001, "has_audio": False}
    c = leike["clip_from_info"]("a.mp4", info)
    assert c.path == "a.mp4"
    assert c.src_w == 1920 and c.src_h == 1080
    assert c.dur == 12.5
    assert c.start == 0.0 and c.end == 12.5   # trim spans whole file
    assert c.crop is None
    assert c.has_audio is False
    assert c.rotation == 90

def test_clip_from_info_defaults_fps_when_missing(leike):
    c = leike["clip_from_info"]("a.mp4", {"w": 640, "h": 480, "dur": 3.0})
    assert c.fps == 30.0
    assert c.has_audio is True
