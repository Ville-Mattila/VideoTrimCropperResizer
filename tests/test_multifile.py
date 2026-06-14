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


def test_batch_out_name_suffix_and_numbering(leike, tmp_path):
    taken = set()
    p1 = leike["_batch_out_name"](str(tmp_path), "C:/x/clip.mp4", ".mp4", taken)
    assert p1.replace("\\", "/").endswith("clip_export.mp4")
    # same stem again -> auto-numbered, never overwrites
    p2 = leike["_batch_out_name"](str(tmp_path), "D:/y/clip.mov", ".mp4", taken)
    assert p2.replace("\\", "/").endswith("clip_export_2.mp4")
    p3 = leike["_batch_out_name"](str(tmp_path), "E:/z/clip.avi", ".mp4", taken)
    assert p3.replace("\\", "/").endswith("clip_export_3.mp4")

def test_batch_out_name_distinct_stems(leike, tmp_path):
    taken = set()
    a = leike["_batch_out_name"](str(tmp_path), "a.mp4", ".mp4", taken)
    b = leike["_batch_out_name"](str(tmp_path), "b.mp4", ".mp4", taken)
    assert a.endswith("a_export.mp4")
    assert b.endswith("b_export.mp4")


def test_combine_target_largest_and_fps(leike):
    Clip = leike["Clip"]
    clips = [Clip("a", 1280, 720, 5, fps=30, end=5),
             Clip("b", 1920, 1080, 5, fps=60, end=5)]
    assert leike["_combine_target"](clips) == (1920, 1080, 60.0)

def test_combine_target_uses_per_clip_crop(leike):
    Clip = leike["Clip"]
    clips = [Clip("a", 1920, 1080, 5, end=5, crop=(0, 0, 640, 480))]
    assert leike["_combine_target"](clips)[:2] == (640, 480)

def test_combine_target_applies_scale_cap(leike):
    Clip = leike["Clip"]
    clips = [Clip("a", 1280, 720, 5, fps=30, end=5),
             Clip("b", 1920, 1080, 5, fps=60, end=5)]
    W, H, F = leike["_combine_target"](clips, scale_cap=1280)
    assert max(W, H) == 1280 and (W, H) == (1280, 720) and F == 60.0
