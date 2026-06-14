"""Unit tests for the H.265 (HEVC) + AV1 codec support: codec-aware _venc,
the target-size support predicate, and build_commands routing."""


def mk(leike, **kw):
    S = leike["ExportSettings"]
    base = dict(input_path="i.mp4", output_path="o.mp4", src_w=1920, src_h=1080,
                start=0.0, end=5.0, crf=22)
    base.update(kw)
    return S(**base)


# ---- _venc: codec + GPU/software matrix -----------------------------------

def test_venc_h264_software(leike):
    assert leike["_venc"](mk(leike, fmt="mp4", hw=False)) == \
        ["-c:v", "libx264", "-preset", "medium", "-crf", "22"]


def test_venc_h264_gpu(leike):
    a = leike["_venc"](mk(leike, fmt="mp4", hw=True))
    assert a[:2] == ["-c:v", "h264_nvenc"] and "-cq" in a and "22" in a


def test_venc_hevc_software_tags_hvc1(leike):
    a = leike["_venc"](mk(leike, fmt="hevc", hw=False))
    assert "libx265" in a and "-crf" in a and "22" in a
    assert a[a.index("-tag:v") + 1] == "hvc1"


def test_venc_hevc_gpu_tags_hvc1(leike):
    a = leike["_venc"](mk(leike, fmt="hevc", hw=True))
    assert "hevc_nvenc" in a and "-cq" in a and "22" in a
    assert a[a.index("-tag:v") + 1] == "hvc1"


def test_venc_av1_software(leike):
    assert leike["_venc"](mk(leike, fmt="av1", hw=False)) == \
        ["-c:v", "libsvtav1", "-preset", "6", "-crf", "22"]


def test_venc_av1_gpu_when_capable(leike):
    a = leike["_venc"](mk(leike, fmt="av1", hw=True, av1_nvenc=True))
    assert a[:2] == ["-c:v", "av1_nvenc"] and "-cq" in a and "22" in a


def test_venc_av1_gpu_falls_back_to_software(leike):
    # GPU toggle on but the GPU can't do AV1 NVENC -> software libsvtav1
    a = leike["_venc"](mk(leike, fmt="av1", hw=True, av1_nvenc=False))
    assert "libsvtav1" in a and "av1_nvenc" not in a


# ---- target-size support predicate ----------------------------------------

def test_target_size_supported_only_mp4(leike):
    f = leike["_target_size_supported"]
    assert f("mp4") is True
    assert f("hevc") is False
    assert f("av1") is False
    assert f("webm") is False
    assert f("gif") is False


# ---- build_commands routing for the new codecs ----------------------------

def test_build_commands_hevc(leike):
    cmds = leike["build_commands"](mk(leike, fmt="hevc", output_path="out.mp4"))
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "libx265" in j and "-tag:v hvc1" in j
    assert "+faststart" in j and "aac" in j
    assert cmds[0][-1] == "out.mp4"


def test_build_commands_av1(leike):
    cmds = leike["build_commands"](mk(leike, fmt="av1", output_path="out.mp4"))
    j = " ".join(cmds[0])
    assert "libsvtav1" in j and "aac" in j
    assert cmds[0][-1] == "out.mp4"


def test_build_commands_av1_ignores_target_size(leike):
    cmds = leike["build_commands"](
        mk(leike, fmt="av1", target_size_mb=10, output_path="out.mp4"))
    j = " ".join(cmds[0])
    assert "libsvtav1" in j          # CRF path, the chosen codec
    assert "-pass" not in j          # NOT the two-pass target-size path
    assert "libx264" not in j        # and definitely not coerced to H.264


def test_build_commands_hevc_adds_watermark_input(leike, tmp_path):
    wm = tmp_path / "w.png"
    wm.write_bytes(b"x")
    cmds = leike["build_commands"](
        mk(leike, fmt="hevc", watermark_path=str(wm), output_path="out.mp4"))
    assert str(wm) in " ".join(cmds[0])   # watermark added as a 2nd input


# ---- per-format Export-tab control visibility -----------------------------

def test_format_controls_matrix(leike):
    f = leike["_format_controls"]
    assert f("mp4") == {"quality": True, "gif_fps": False, "fast_trim": True,
                        "gpu": True, "target_size": True}
    assert f("hevc") == {"quality": True, "gif_fps": False, "fast_trim": False,
                         "gpu": True, "target_size": False}
    assert f("av1") == {"quality": True, "gif_fps": False, "fast_trim": False,
                        "gpu": True, "target_size": False}
    assert f("webm") == {"quality": True, "gif_fps": False, "fast_trim": False,
                         "gpu": False, "target_size": False}
    assert f("gif") == {"quality": False, "gif_fps": True, "fast_trim": False,
                        "gpu": False, "target_size": False}
