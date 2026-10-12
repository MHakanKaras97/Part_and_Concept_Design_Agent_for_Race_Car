# Vehicle coordinate system (VCS)

**Project convention** (not an FIA definition). All project data, plans, part specs and Fusion geometry use it.

| Item | Definition |
|---|---|
| Axes | right-handed; **+X front** (direction of travel), **+Y left** (driver's left), **+Z up** |
| Units | millimetres (lengths), degrees (angles); Fusion's API uses cm internally — converted only in `vehicle/transforms.py` and the script prelude (`mm()`, `pt()`) |
| Origin X | on the **front-axle centreline**: X = 0 is the X-plane through the front wheel centres |
| Origin Y | Y = 0 on the car's plane of symmetry |
| Origin Z | Z = 0 on the **reference plane** (the horizontal plane the car's floor is designed on) |
| Part pose | position (mm) of the part frame origin in VCS + rotation (roll, pitch, yaw) in degrees about X, Y, Z, applied as **R = Rz(yaw) · Ry(pitch) · Rx(roll)**; local → VCS: `p_vcs = R · p_local + position` (`vehicle/transforms.pose_to_matrix`) |
| Part frame | every free-form part is built at identity in its own component with VCS-parallel axes, then placed by its pose. The script defines geometry in the **part-local frame** and never encodes the world position; the build script measures the local bbox and `PART-FRAME` compares it with the envelope taken back by the inverse pose (`docs/fusion_script_contract.md`). Exception: `frame_mode: legacy_world` records (MON-001 v2: VCS coordinates, identity pose only) |

## Relation to the FIA Car Coordinate System (2026 Section C, Issue 20)

Verbatim, `fia_rules/source/fia_2026_section_c_iss20.txt` (page 9, Article C2.1.1):

> The "Car Coordinate System" is a right−handed Cartesian [X, Y, Z] coordinate system and is defined in the
> following way: a. The X axis is the longitudinal direction of the car and increases rearwards. b. The Y axis is
> the transverse direction of the car and increases to the (driver's) right−hand side. c. The Z axis is the
> vertical direction and increases upwards.

Verbatim, page 10, Article C2.2 (Principal Planes):

> a. The Plane Z = 0 is defined as a horizontal plane sitting at the bottom of the sprung part of the car, except
> for the Plank Assembly defined in Article C3.6.
> b. The Plane Y = 0 is defined as the plane of symmetry of the car.
> e. The planes XF = 0 and XR = 0 are defined as the X−Planes which respectively pass through the origin of the
> two front or two rear Wheel Coordinate Systems, with the wheels in the straight−ahead position and the car at
> Legality Setup.

Resulting relation (applies to directions; tested in `tests/test_transforms.py`):

| | VCS | FIA |
|---|---|---|
| X | +front | +rear → `x_fia = -x_vcs` (+ offset of the chosen FIA X datum) |
| Y | +left | +right → `y_fia = -y_vcs` |
| Z | +up | +up → `z_fia = z_vcs` |

- VCS = FIA axes rotated 180° about Z (`vehicle/transforms.vcs_to_fia`).
- VCS X = 0 (front-axle centreline) corresponds to the FIA plane **XF = 0** only when the front wheel origins of
  C2.1.3 lie on the axle centreline — **NOT_VERIFIED** (no wheels are modelled yet).
- VCS Y = 0 and FIA Plane Y = 0 are both the plane of symmetry.
- VCS Z = 0 (project reference plane) vs FIA Plane Z = 0 (bottom of the sprung part, C2.2 a): treated as the
  same plane by project convention — **NOT_VERIFIED** (no sprung-part/plank geometry exists to measure it).
