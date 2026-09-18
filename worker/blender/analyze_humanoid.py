"""Avatar measurement helpers executed inside Blender."""


def analyze_avatar(context) -> dict:
    return {
        "humanoid": True,
        "height_m": None,
        "shoulder_width_m": None,
        "chest_width_m": None,
        "waist_width_m": None,
        "hip_width_m": None,
    }
