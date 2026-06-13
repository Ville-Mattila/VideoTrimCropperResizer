def make(leike, **kw):
    S = leike["ExportSettings"]
    base = dict(input_path="in.mp4", output_path="out.mp4",
                src_w=1920, src_h=1080, start=1.0, end=4.0)
    base.update(kw)
    return S(**base)


def test_trim_only_is_lossless_copy(leike):
    cmds = leike["build_commands"](make(leike))      # no crop/scale -> passthrough
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "-c copy" in j
    assert "-vf" not in cmds[0]
    assert "-ss 1.000" in j and "-t 3.000" in j      # dur = end - start
    assert "+faststart" in j


def test_fast_trim_off_reencodes(leike):
    cmds = leike["build_commands"](make(leike, fast_trim=False))
    j = " ".join(cmds[0])
    assert "libx264" in j and "-crf 20" in j and "format=yuv420p" in j
    assert "-c copy" not in j


def test_crop_reencodes_with_crop_filter(leike):
    cmds = leike["build_commands"](make(leike, crop=(10, 20, 1280, 720), scale_cap=1280))
    j = " ".join(cmds[0])
    assert "crop=1280:720:10:20" in j     # cropped 1280 already at the 1280 cap
    assert "scale=" not in j
    assert "-c copy" not in j


def test_scale_when_capped(leike):
    cmds = leike["build_commands"](make(leike, scale_cap=1280))
    assert "scale=1280:720" in " ".join(cmds[0])


def test_crf_propagates(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), crf=18))
    assert "-crf 18" in " ".join(cmds[0])


def test_odd_dims_snapped_even(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 641, 361)))
    assert "crop=640:360:0:0" in " ".join(cmds[0])


def test_hw_encoder_nvenc(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), hw=True))
    j = " ".join(cmds[0])
    assert "h264_nvenc" in j and "-cq 20" in j
    assert "libx264" not in j


def test_sw_encoder_default(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), hw=False))
    j = " ".join(cmds[0])
    assert "libx264" in j and "-crf 20" in j
