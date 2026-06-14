# Pure tests for build_preview_vf — no GUI, no mpv.
def make(leike, **kw):
    base = dict(input_path="in.mp4", output_path="out.mp4",
                src_w=1920, src_h=1080, start=2.0, end=8.0)
    base.update(kw)
    return leike["ExportSettings"](**base)


def vf_props(leike, **kw):
    return leike["build_preview_vf"](make(leike, **kw))


def test_empty_settings_minimal(leike):
    vf, props = vf_props(leike)
    assert "crop=" not in vf and "eq=" not in vf
    assert props.get("speed", 1.0) == 1.0


def test_crop_orient_color(leike):
    vf, _ = vf_props(leike, crop=(10, 20, 1280, 720), rotate=90,
                     flip_h=True, brightness=0.2, contrast=1.1, saturation=1.2)
    assert "crop=1280:720:10:20" in vf
    assert "transpose=1" in vf and "hflip" in vf
    assert "eq=brightness=0.200:contrast=1.100:saturation=1.200" in vf


def test_grayscale_denoise_sharpen(leike):
    vf, _ = vf_props(leike, grayscale=True, denoise=True, sharpen=True)
    assert "hue=s=0" in vf and "hqdn3d" in vf and "unsharp" in vf


def test_text_overlay(leike):
    vf, _ = vf_props(leike, text="Hello")
    assert "drawtext=" in vf and "textfile=" in vf


def test_fades_use_absolute_timeline(leike):
    # mpv plays from s.start, so fade st must be source-absolute
    vf, _ = vf_props(leike, start=2.0, end=8.0, fade_in=1.0, fade_out=1.5)
    assert "fade=t=in:st=2.00:d=1.00" in vf
    assert "fade=t=out:st=6.50:d=1.50" in vf


def test_watermark_bridges_movie_source(leike):
    vf, _ = vf_props(leike, watermark_path="logo.png", watermark_pos="br")
    assert "movie=" in vf and "overlay=" in vf


def test_audio_props(leike):
    _, props = vf_props(leike, speed=2.0, volume=1.5, mute=True)
    assert props["speed"] == 2.0
    assert abs(props["volume"] - 150.0) < 0.01      # mpv volume is 0-100(+)
    assert props["mute"] is True


def test_subtitles_use_native_sub_file(leike):
    _, props = vf_props(leike, subtitles_path="subs.srt")
    assert props["sub-file"] == "subs.srt"


def test_non_live_effects_omitted(leike):
    vf, props = vf_props(leike, reverse=True, boomerang=True, stabilize=True,
                         target_size_mb=10.0)
    assert "vidstab" not in vf and "reverse" not in vf
    # scale is omitted too (mpv fits the window)
    assert "scale=" not in vf
