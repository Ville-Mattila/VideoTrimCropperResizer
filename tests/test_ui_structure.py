def test_tabs_and_widgets(app):
    assert list(app._tabs.keys()) == ["Crop", "Effects", "Overlay", "Audio",
                                      "Export"]
    # the flat tab bar has a clickable cell (label + indicator) per tab
    assert list(app._tab_cells.keys()) == list(app._tabs.keys())
    # selecting a tab raises its content and marks it active
    app._select_tab("Export")
    assert app._active_tab == "Export"
    # every variable _settings() reads must still exist after the re-home
    for name in ("scale_var", "crf_var", "fmt_var", "fast_trim_var",
                 "hw_var", "gif_fps_var", "size_var", "mute_var",
                 "volume_var", "audio_only_var", "speed_var", "aspect_var",
                 "fill_var", "fade_in_var", "fade_out_var", "flip_h_var",
                 "flip_v_var", "effect_var", "loop_var", "bright_var",
                 "contrast_var", "satur_var", "gray_var", "denoise_var",
                 "sharpen_var", "stabilize_var", "text_var", "text_pos_var",
                 "wm_pos_var"):
        assert hasattr(app, name), name
    # the relocations: trim row + export footer are present
    assert app.export_btn is not None and app.trim_label is not None
    assert app.cancel_btn is not None and app.export_hint is not None


def test_playback_symbols_exist(leike):
    # playback is optional; the flag, wrapper, and pure helper always exist
    assert "HAS_MPV" in leike
    assert "Player" in leike and "build_preview_vf" in leike
