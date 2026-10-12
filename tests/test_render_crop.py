"""Crop of a finished render around the car (fusion/render_crop.py): centring, even margins, 3:2 aspect, resize down
only (never a silent upscale), a car at the image edge (background padding), nearly empty / unreadable images, the
run.json fields and the custom render size limits."""
import pytest
from PIL import Image, ImageDraw

from agent.design_run import load_design_run
from agent.render_run import parse_options
from fusion.render_crop import crop_plan, crop_render
from tests.test_render import setup  # noqa: F401  (fixture)

BG = (58, 63, 71)


def image(path, size, box, colour=(220, 40, 40)):
    im = Image.new("RGB", size, BG)
    if box:
        ImageDraw.Draw(im).rectangle(box, fill=colour)
    im.save(path, "PNG")
    return path


def test_window_is_centred_3_to_2_with_the_car_at_80_percent():
    p = crop_plan((1000, 800, 2199, 1399), (3600, 2400), 0.8, 1.5)               # car 1200 x 600 px
    (x0, y0, x1, y1), (nw, nh) = p["box"], p["native_size"]
    assert nw / nh == pytest.approx(1.5, abs=0.002) and (x1 - x0, y1 - y0) == (nw, nh)
    assert p["car_fill_planned"][0] == pytest.approx(0.8, abs=0.002)              # width binds (1200/0.8 = 1500)
    assert p["car_fill_planned"][1] <= 0.8
    assert (1000 - x0) == pytest.approx(x1 - 2200, abs=1)                         # even margin left / right
    assert (800 - y0) == pytest.approx(y1 - 1400, abs=1)                          # ... and top / bottom
    assert p["padded"] == [0, 0, 0, 0] and not p["car_touches_edge"]


def test_a_tall_car_binds_the_height():
    p = crop_plan((100, 100, 399, 899), (3600, 2400), 0.8, 1.5)                  # 300 x 800 px
    assert p["car_fill_planned"][1] == pytest.approx(0.8, abs=0.002) and p["car_fill_planned"][0] < 0.8


def test_larger_than_the_target_is_resized_down_never_up():
    down = crop_plan((1000, 800, 2199, 1399), (3600, 2400), 0.8, 1.5, target=(1280, 853))
    assert down["resized"] == "down" and down["output_size"][0] <= 1280 and down["output_size"][1] <= 853
    assert down["factor"] == pytest.approx(min(1280 / down["native_size"][0], 853 / down["native_size"][1]), abs=1e-4)
    up = crop_plan((1000, 800, 2199, 1399), (3600, 2400), 0.8, 1.5, target=(2400, 1600))
    assert up["resized"] == "none" and up["factor"] == 1.0 and up["output_size"] == up["native_size"]
    assert "smaller than the target 2400x1600: kept at native size, NOT upscaled" in up["note"]


def test_a_car_at_the_image_edge_is_padded_not_shifted(tmp_path):
    src = image(tmp_path / "edge.png", (1200, 800), (0, 300, 499, 549))          # touches the left edge
    c = crop_render(src, tmp_path / "edge_c.png", 0.8, 1.5)
    assert c["car_touches_edge"] and c["padded"][0] > 0                         # window reaches past the left edge
    out = Image.open(tmp_path / "edge_c.png").convert("RGB")
    assert out.getpixel((1, out.size[1] // 2)) == BG                              # padding = background colour
    assert abs(c["car_offset_cropped"][0]) < 0.005 and abs(c["car_offset_cropped"][1]) < 0.005   # still centred


def test_crop_render_measures_the_result(tmp_path):
    src = image(tmp_path / "r.png", (3600, 2400), (1200, 820, 2423, 1659))        # ~34 % x 35 %
    c = crop_render(src, tmp_path / "r_c.png", 0.8, 1.5, target=(2400, 1600))
    assert c["car_fill_full"] == [pytest.approx(0.34, abs=0.002), pytest.approx(0.35, abs=0.002)]
    assert max(c["car_fill_cropped"]) == pytest.approx(0.8, abs=0.005)
    assert Image.open(tmp_path / "r_c.png").size == tuple(c["output_size"])


@pytest.mark.parametrize("box", [None, (500, 500, 509, 509)])
def test_a_nearly_empty_image_is_not_cropped(tmp_path, box):
    src = image(tmp_path / "e.png", (1280, 853), box)
    c = crop_render(src, tmp_path / "e_c.png")
    assert c["skipped"] and not (tmp_path / "e_c.png").exists()


def test_an_unreadable_render_is_not_cropped(tmp_path):
    (tmp_path / "bad.png").write_bytes(b"\x89PNG not really")
    assert "could not be read" in crop_render(tmp_path / "bad.png", tmp_path / "bad_c.png")["skipped"]


# ---------------------------------------------------------------- pipeline + run.json
def test_run_json_lists_the_full_and_the_cropped_render(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    rd = orch.render(load_design_run(store, run.id),
                     options={"preset": "draft", "size": "3600x2400", "crop_output": "2400x1600"})
    (it,) = load_design_run(store, run.id)["renders"][-1]["items"]
    assert fake.render_starts[-1]["width"] == 3600 and fake.render_starts[-1]["height"] == 2400
    assert it["render_full"] == f"renders/{rd['id']}/iso.png" and it["full_size"] == [3600, 2400]
    assert it["render_cropped"] == f"renders/{rd['id']}/iso_cropped.png" and it["path"] == it["render_cropped"]
    c = it["crop"]
    assert {"box", "native_size", "output_size", "factor", "resized", "car_fill_full", "car_fill_cropped"} <= set(c)
    assert it["native_size"] == c["native_size"] and [it["width"], it["height"]] == c["output_size"]
    assert c["resized"] == "none" and "NOT upscaled" in it["note"]                   # 34 % car: native < 2400x1600


def test_no_crop_keeps_the_full_render(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    rd = orch.render(load_design_run(store, run.id), options={"preset": "draft", "crop": False})
    (it,) = rd["items"]
    assert it["render_cropped"] is None and it["crop"] is None and it["path"] == it["render_full"]


def test_an_empty_render_is_kept_full_and_noted(setup):  # noqa: F811
    store, fake, reasoner, orch, run, clock = setup
    fake.render_car = None
    (it,) = orch.render(load_design_run(store, run.id), options={"preset": "draft"})["items"]
    assert it["render_cropped"] is None and it["path"] == it["render_full"] and "not cropped" in it["note"]


@pytest.mark.parametrize("raw,needle", [({"size": "4800x3200"}, "between 108 and 4000"),
                                        ({"size": "100x80"}, "between 108 and 4000"),
                                        ({"size": "big"}, "WIDTHxHEIGHT"), ({"crop": "yes"}, "crop")])
def test_size_limits_follow_the_api(raw, needle):
    with pytest.raises(ValueError, match=needle):
        parse_options(raw)
    assert parse_options({"size": "3600x2400"}).resolution == [3600, 2400]
    assert parse_options({"size": [4000, 2667]}).resolution == [4000, 2667]
