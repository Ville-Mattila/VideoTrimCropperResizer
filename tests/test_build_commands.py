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


def test_gif_two_pass(leike):
    cmds = leike["build_commands"](make(leike, fmt="gif", output_path="out.gif"))
    assert len(cmds) == 2
    assert "palettegen" in " ".join(cmds[0])
    assert "paletteuse" in " ".join(cmds[1])
    assert "fps=15" in " ".join(cmds[0])
    assert "-c:a" not in " ".join(cmds[1])        # GIF has no audio


def test_gif_fps_setting(leike):
    cmds = leike["build_commands"](make(leike, fmt="gif", gif_fps=24))
    assert "fps=24" in " ".join(cmds[0])


def test_webm_vp9_opus(leike):
    cmds = leike["build_commands"](make(leike, fmt="webm", output_path="out.webm"))
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "libvpx-vp9" in j and "libopus" in j
    assert "-c copy" not in j        # webm always re-encodes, even trim-only


def test_size_target_two_pass(leike):
    cmds = leike["build_commands"](make(leike, target_size_mb=10.0))   # 3.0s clip
    assert len(cmds) == 2
    j0, j1 = " ".join(cmds[0]), " ".join(cmds[1])
    assert "-pass 1" in j0 and "-pass 2" in j1
    expected = int(((10.0 * 8192) / 3.0 - 128) * 0.97)
    assert f"-b:v {expected}k" in j1


def test_size_target_overrides_passthrough(leike):
    # no crop would normally be a -c copy passthrough; a size target forces 2-pass
    cmds = leike["build_commands"](make(leike, target_size_mb=5.0))
    assert len(cmds) == 2
    assert "-c copy" not in " ".join(cmds[0])


def test_mute_drops_audio(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), mute=True))
    j = " ".join(cmds[0])
    assert "-an" in j and "aac" not in j


def test_volume_filter(leike):
    cmds = leike["build_commands"](make(leike, crop=(0, 0, 1280, 720), volume=1.5))
    assert "volume=1.500" in " ".join(cmds[0])


def test_mute_disables_passthrough(leike):
    # mute on a trim-only job can't stream-copy; must re-encode with -an
    cmds = leike["build_commands"](make(leike, mute=True))
    j = " ".join(cmds[0])
    assert "-c copy" not in j and "-an" in j


def test_audio_only_mp3(leike):
    cmds = leike["build_commands"](make(leike, audio_only=True, output_path="out.mp3"))
    assert len(cmds) == 1
    j = " ".join(cmds[0])
    assert "-vn" in j and "libmp3lame" in j
