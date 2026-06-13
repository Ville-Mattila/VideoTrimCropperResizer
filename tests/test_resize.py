"""Headless tests for the responsive-preview coordinate mapping.

These bind the pure mapping methods onto a lightweight stub rather than
constructing a real Tk window, so the suite never creates Tk roots here
(repeated Tk() creation in one process eventually fails to load init.tcl).
"""
import types


def _stub(leike, **attrs):
    app_cls = leike["App"]
    s = types.SimpleNamespace(**attrs)
    for name in ("_s2c", "_c2s", "_recompute_display"):
        setattr(s, name, types.MethodType(app_cls.__dict__[name], s))
    return s


def test_coordinate_roundtrip(leike):
    s = _stub(leike, src_w=1920, src_h=1080, scale=0.5,
              off_x=30, off_y=10, disp_w=960, disp_h=540)
    assert s._s2c(100, 200) == (80, 110)            # 30+50, 10+100
    sx, sy = s._c2s(80, 110)
    assert abs(sx - 100) < 1e-6 and abs(sy - 200) < 1e-6
    assert s._c2s(-1000, -1000) == (0, 0)
    assert s._c2s(99999, 99999) == (1920, 1080)


def test_recompute_letterbox(leike):
    class StubCanvas:
        def winfo_width(self):
            return 800

        def winfo_height(self):
            return 800

    s = _stub(leike, src_w=1920, src_h=1080, canvas=StubCanvas())
    s._recompute_display()
    assert abs(s.scale - 800 / 1920) < 1e-9       # 16:9 into 800x800: width-bound
    assert s.disp_w == 800
    assert s.disp_h == int(1080 * 800 / 1920)     # 450
    assert s.off_x == 0
    assert s.off_y == (800 - 450) // 2            # vertical letterbox
