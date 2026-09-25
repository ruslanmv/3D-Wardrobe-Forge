"""The Blender worker picks her body by what drives it, not by vertex count."""

from worker.blender.body_select import Candidate, choose_body

HUMANOID = {
    "hips": "J_Bip_C_Hips", "spine": "J_Bip_C_Spine", "chest": "J_Bip_C_Chest",
    "leftUpperLeg": "J_Bip_L_UpperLeg", "rightUpperLeg": "J_Bip_R_UpperLeg", "head": "J_Bip_C_Head",
}


def test_long_hair_with_more_vertices_is_not_the_body():
    hair = Candidate("Hair", 9000, ["J_Sec_Hair1_01"] * 9000)
    body = Candidate("Body", 6000, ["J_Bip_C_Spine"] * 3000 + ["J_Bip_L_UpperLeg"] * 2000 + ["J_Bip_C_Head"] * 1000)
    assert choose_body([hair, body], HUMANOID).name == "Body"


def test_a_face_driven_by_the_head_is_not_the_body():
    face = Candidate("Face", 5000, ["J_Bip_C_Head"] * 5000)
    body = Candidate("Body", 4000, ["J_Bip_C_Hips"] * 4000)
    assert choose_body([face, body], HUMANOID).name == "Body"


def test_nothing_torso_driven_falls_back_to_the_largest():
    small, large = Candidate("A", 10, [None] * 10), Candidate("B", 20, [None] * 20)
    assert choose_body([small, large], HUMANOID).name == "B"
