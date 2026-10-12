import numpy as np
import pytest

from vehicle.models import Pose
from vehicle.transforms import (bbox_to_vcs, cm_to_mm, fia_to_vcs, invert, local_to_vcs, matrix_to_fusion_cm,
                                mm_to_cm, pose_to_matrix, rotation_matrix, vcs_to_fia, vcs_to_local)


def close(a, b, tol=1e-9):
    return np.allclose(np.array(a, dtype=float), np.array(b, dtype=float), atol=tol)


def test_identity_pose():
    assert close(local_to_vcs(Pose(), (1, 2, 3)), (1, 2, 3))


def test_yaw_90_maps_front_to_left():
    # +X (front) rotated +90 deg about +Z must point to +Y (left) in a right-handed VCS
    assert close(local_to_vcs(Pose(rotation_deg=(0, 0, 90)), (1, 0, 0)), (0, 1, 0))


def test_pitch_and_roll_right_handed():
    assert close(rotation_matrix(0, 90, 0) @ np.array([1, 0, 0]), (0, 0, -1))
    assert close(rotation_matrix(90, 0, 0) @ np.array([0, 1, 0]), (0, 0, 1))


def test_rotation_is_orthonormal():
    r = rotation_matrix(13, -27, 151)
    assert close(r @ r.T, np.eye(3)) and np.isclose(np.linalg.det(r), 1.0)


@pytest.mark.parametrize("pose", [Pose(position=(100, -20, 5), rotation_deg=(10, 20, 30)),
                                  Pose(position=(0, 0, 0), rotation_deg=(0, 0, 180))])
def test_local_vcs_round_trip(pose):
    p = (12.5, -3.0, 7.25)
    assert close(vcs_to_local(pose, local_to_vcs(pose, p)), p)
    assert close(invert(pose_to_matrix(pose)) @ pose_to_matrix(pose), np.eye(4))


def test_translation_then_rotation_order():
    pose = Pose(position=(1000, 0, 0), rotation_deg=(0, 0, 90))
    assert close(local_to_vcs(pose, (10, 0, 0)), (1000, 10, 0))


def test_bbox_rotated_box():
    lo, hi = bbox_to_vcs(Pose(rotation_deg=(0, 0, 90)), (0, -1, 0), (10, 1, 2))
    assert close(lo, (-1, 0, 0)) and close(hi, (1, 10, 2))


def test_fia_coordinate_conversion():
    # FIA C2.1.1: X increases rearwards, Y increases to the driver's right, Z up
    front_left_up = (100.0, 50.0, 20.0)
    f = vcs_to_fia(front_left_up)
    assert f[0] < 0 and f[1] < 0 and f[2] == 20.0
    assert close(fia_to_vcs(vcs_to_fia(front_left_up, 3000), 3000), front_left_up)
    # FIA frame is also right-handed: X_fia x Y_fia = Z_fia
    xf = np.array(vcs_to_fia((1, 0, 0))) - np.array(vcs_to_fia((0, 0, 0)))
    yf = np.array(vcs_to_fia((0, 1, 0))) - np.array(vcs_to_fia((0, 0, 0)))
    assert close(np.cross(-xf, -yf), (0, 0, 1))


def test_unit_conversion_and_fusion_matrix():
    assert mm_to_cm(25.0) == 2.5 and cm_to_mm(2.5) == 25.0
    arr = matrix_to_fusion_cm(pose_to_matrix(Pose(position=(100, 20, -30))))
    assert len(arr) == 16 and close([arr[3], arr[7], arr[11]], (10, 2, -3))
