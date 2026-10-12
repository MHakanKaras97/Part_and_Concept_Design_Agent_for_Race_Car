"""Render camera framing: pure helpers, inserted verbatim into the render start script and exec'd by the unit tests
(tests/test_render_frame.py). Units: whatever the points use (the script passes cm); directions are unit-free.

The camera looks from eye = target + dir * distance towards target, with `up` as the screen's up. Every point (the 8
corners of every part's measured world bbox) is projected; the target is shifted until the projected extent is centred
(even margin) and the distance (perspective) or the extents (orthographic) are chosen so the larger relative side fills
`fill` of the frame.
"""

FRAME_HELPERS = r'''
import math


def _basis(d, up):
    n = math.sqrt(sum(c * c for c in d))
    d = [c / n for c in d]                                   # from target towards the eye
    f = [-c for c in d]                                      # viewing direction
    r = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]]
    rn = math.sqrt(sum(c * c for c in r))
    r = [c / rn for c in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    return d, r, u


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def project(points, target, d, up, distance=None):
    """Screen coordinates of points: (x, y) along right / up; divided by the depth for a perspective camera
    (distance given) -> tangents of the angle off the view axis."""
    d, r, u = _basis(d, up)
    out = []
    for p in points:
        v = [p[i] - target[i] for i in range(3)]
        x, y = _dot(v, r), _dot(v, u)
        if distance is not None:
            z = distance - _dot(v, d)
            x, y = x / z, y / z
        out.append((x, y))
    return out


def _bounds(xy):
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    return min(xs), max(xs), min(ys), max(ys)


def frame_ortho(points, d, up, aspect, fill):
    """-> (target, width, height): an orthographic view of extents width x height (width / height = aspect) in which
    the projected points are centred and the larger relative side fills `fill`."""
    _, r, u = _basis(d, up)
    c = [sum(p[i] for p in points) / len(points) for i in range(3)]
    x0, x1, y0, y1 = _bounds(project(points, c, d, up))
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    t = [c[i] + r[i] * cx + u[i] * cy for i in range(3)]
    w = max((x1 - x0) / fill, (y1 - y0) / fill * aspect)
    return t, w, w / aspect


def frame_perspective(points, d, up, tan_h, tan_v, fill, iterations=6):
    """-> (target, distance): a perspective view (half-angle tangents tan_h / tan_v) in which the projected points are
    centred and the larger relative side fills `fill`. The relative size falls monotonically with the distance, so
    the distance is found by bisection, and so is the sideways target shift per screen axis (the centre offset falls
    monotonically with it); the two alternate a few times."""
    dn, r, u = _basis(d, up)
    t = [sum(p[i] for p in points) / len(points) for i in range(3)]
    radius = max(math.sqrt(sum((p[i] - t[i]) ** 2 for i in range(3))) for p in points)
    near = max(_dot([p[i] - t[i] for i in range(3)], dn) for p in points)     # unchanged by sideways moves

    def size(dist):
        x0, x1, y0, y1 = _bounds(project(points, t, d, up, dist))
        return max((x1 - x0) / (2.0 * tan_h), (y1 - y0) / (2.0 * tan_v)), (x0 + x1) / 2.0, (y0 + y1) / 2.0

    def solve(dist):
        lo, hi = near + 1e-3 * radius, max(dist, radius) * 4.0
        while size(hi)[0] > fill:
            hi *= 2.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if size(mid)[0] > fill:
                lo = mid
            else:
                hi = mid
        return hi

    def centre(dist):
        # moving the target along a screen axis shifts every point the other way: bisection per axis
        nonlocal t
        for k, ax in ((1, r), (2, u)):
            base = list(t)
            lo, hi = -2.0 * radius, 2.0 * radius
            for _ in range(60):
                mid = (lo + hi) / 2.0
                t = [base[i] + ax[i] * mid for i in range(3)]
                if size(dist)[k] > 0:
                    lo = mid
                else:
                    hi = mid
            t = [base[i] + ax[i] * (lo + hi) / 2.0 for i in range(3)]

    dist = solve(radius / min(tan_h, tan_v) * 2.0)
    for _ in range(iterations):
        centre(dist)
        dist = solve(dist)
    return t, dist


def fill_of(points, target, d, up, distance, tan_h, tan_v):
    """(fraction of the width, fraction of the height, centre offset x, y as fractions) for a perspective view."""
    x0, x1, y0, y1 = _bounds(project(points, target, d, up, distance))
    return ((x1 - x0) / (2 * tan_h), (y1 - y0) / (2 * tan_v), (x0 + x1) / (4 * tan_h), (y0 + y1) / (4 * tan_v))


def narrow_factor(planned, scale, fill):
    """Angle-based correction. planned = (fill_x, fill_y) of a TRUE-lens view (distance from the uncorrected field);
    scale = measured render field / camera field per axis. Narrowing the camera's half-angle tangent by k makes the
    render show planned * k / scale per axis; k is chosen so the larger of the two is `fill`."""
    return fill / max(planned[0] / scale[0], planned[1] / scale[1])


def narrowed_angle(angle, k):
    """The full angle whose half-angle tangent is tan(angle / 2) / k."""
    return 2.0 * math.atan(math.tan(angle / 2.0) / k)


FILM_HALF_MM = {"horizontal": 18.0, "vertical": 12.0, "diagonal": math.hypot(18.0, 12.0)}


def focal_of(angle, axis):
    """The focal length (36 x 24 mm film) whose angle along `axis` is `angle`."""
    return FILM_HALF_MM[axis] / math.tan(angle / 2.0)


def fov_axis(angle, focal_mm):
    """Which film axis (36 x 24 mm frame) Fusion's perspectiveAngle corresponds to for this focal length:
    -> (axis, relative error). axis is horizontal | vertical | diagonal."""
    cands = {"horizontal": 18.0, "vertical": 12.0, "diagonal": math.hypot(18.0, 12.0)}
    errs = {k: abs(2 * math.atan(h / focal_mm) - angle) / angle for k, h in cands.items()}
    k = min(errs, key=errs.get)
    return k, errs[k]


def half_tangents(angle, axis, aspect):
    """(tan_h, tan_v) of the half field of view for a frame of this aspect (width / height), given the full angle
    along `axis`."""
    t = math.tan(angle / 2.0)
    if axis == "horizontal":
        return t, t / aspect
    if axis == "vertical":
        return t * aspect, t
    k = math.hypot(aspect, 1.0)
    return t * aspect / k, t / k
'''
