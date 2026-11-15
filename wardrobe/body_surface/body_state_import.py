"""BI1. An operator-supplied body-state VRM for a library character: checked, bound, or refused.

Forge makes a character's looks itself, and for ``bare`` it makes them only from the authored body
(``body-bare-v1``). Some characters cannot be served that way — AvatarSample O's export deleted her
mid-chest — and a production character may arrive with a body-state version an artist made and the
operator holds the rights to. Until this module the only way such a file reached the app was by hand:
copy it into the dataset, edit a wardrobe list, hope its hash, its rig and its face matched. Nothing
checked that the "bare Model Girl" was Model Girl, or the Model Girl this library pins, or a VRM.

``check()`` is that check, pure: bytes in, a verdict out, nothing stored. Every refusal has a stable
``reason`` and a sentence, and every check that ran is reported, passed or not, so a refused import
says everything that is wrong with the file at once rather than one thing per upload.

What it proves, against the library's own pinned file (``original``):

* **Bytes.** The upload's SHA-256, and the operator's stated hash when one is sent (a file damaged
  in transit is refused before it is parsed). The binding is to the library's pinned SHA-256: an
  import that names another version of her is refused, so a look can never be served on a body it
  was not made for (the app drops such looks too, BL2).
* **Structure.** A GLB, a VRM of the same spec as hers, a usable humanoid with skins.
* **Rig.** Every humanoid bone she has, on a node of the same name, within ``RIG_TOLERANCE_M`` of
  where it is on her. A body state that moved her joints would make every animation and pose
  authored for her land somewhere else.
* **Identity.** Her VRM title and authors; every expression she has; and her face and hair: each
  mesh primitive of hers that is skinned mainly to her head (face, eyes, brows, hair — everything a
  person recognises her by) must be present with the same vertex count, the same morph-target
  count and positions within ``IDENTITY_TOLERANCE_M``. A body state changes what she wears or what
  a garment covered; it never changes who she is.
* **State.** ``bare`` must have a closed body in every band ``body-bare-v1`` checks and no detected
  clothing left (author-labelled anatomy is never counted as clothing, as in ``bare_body``).

What it does **not** do is decide who may have it. That is ``eligibility.assess`` — the same
contract ``body-bare-v1`` uses — run once for her source file and once for the uploaded file, so a
bare import needs a clearly-adult design review recorded for *both exact files*. Nothing here reads
a review the caller sends, and nothing here writes either registry.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import numpy as np

from wardrobe.body_surface.eligibility import assess
from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.inspect import NotAVrm, inspect_document, validate_humanoid
from wardrobe.vrm.measure import measure_body

#: The body states an operator may import. ``dressed`` is not one: a dressed look is what Forge makes.
STATES = ("lingerie", "bare")
MAX_BYTES = 64 * 1024 * 1024
#: Her joints may not move: 1 mm absorbs float re-export noise, not a re-rig.
RIG_TOLERANCE_M = 1e-3
#: Her face and hair, per vertex. 0.1 mm absorbs a DCC re-export's float noise; a re-sculpt is mm.
IDENTITY_TOLERANCE_M = 1e-4
#: A primitive whose vertices are, by this share, weighted mostly to her head (or a bone under it).
HEAD_SHARE = 0.5
BARE_REGIONS = {"upper", "lower", "leftThigh", "rightThigh", "leftShin", "rightShin"}
ANATOMY = re.compile(r"genital|vulva|penis|scrot|nipple|areola|anatom", re.I)
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class ImportVerdict:
    accepted: bool
    reason: str | None
    message: str
    sha256: str
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"accepted": self.accepted, "reason": self.reason, "message": self.message,
                "sha256": self.sha256, "checks": self.checks}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _head_subtree(doc: GltfDocument, head: int) -> set[int]:
    children = {i: n.get("children", []) for i, n in enumerate(doc.nodes)}
    out, stack = set(), [head]
    while stack:
        node = stack.pop()
        if node in out:
            continue
        out.add(node)
        stack.extend(children.get(node, []))
    return out


def identity_primitives(doc: GltfDocument, head: int | None) -> list[tuple[str, int, str, int]]:
    """``(mesh name, primitive index, node name, POSITION accessor)`` of her face and hair.

    Read from the skin, not from names: VRoid calls the face ``Face`` but other exporters do not,
    and a hair mesh is named by the hairstyle. A primitive is hers to keep when most of its
    vertices are weighted mostly to her head or a bone under it (hair joints are the head's).
    """
    if head is None:
        return []
    subtree = _head_subtree(doc, head)
    found = []
    for ni in scene_mesh_nodes(doc):
        node = doc.nodes[ni]
        skin = node.get("skin")
        joints = (doc.gltf.get("skins") or [])[skin]["joints"] if skin is not None else None
        mesh = doc.meshes[node["mesh"]]
        for pi, primitive in enumerate(mesh["primitives"]):
            attrs = primitive.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            if joints is None:
                # Unskinned under the head node itself (an accessory parented to the head).
                if ni in subtree:
                    found.append((mesh.get("name", ""), pi, node.get("name", ""), attrs["POSITION"]))
                continue
            if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                continue
            j = doc.read_accessor(attrs["JOINTS_0"]).astype(int)
            w = doc.read_accessor(attrs["WEIGHTS_0"])
            dominant = j[np.arange(len(j)), np.argmax(w, axis=1)]
            in_head = np.isin(np.asarray(joints)[np.clip(dominant, 0, len(joints) - 1)], list(subtree))
            if len(in_head) and in_head.mean() >= HEAD_SHARE:
                found.append((mesh.get("name", ""), pi, node.get("name", ""), attrs["POSITION"]))
    return found


def same_title(title: str | None, original: str | None) -> bool:
    """Her VRM title, or Forge's name for a look of her: ``"<her title> — <look name>"``.

    Forge titles every look it exports that way (a chemise of AvatarSample_A is
    ``AvatarSample_A — Black Satin Chemise``), so the first real body state imported through
    this route — one Forge built — was refused as someone else. Only that exact form is
    accepted: another character's title, or hers with anything but Forge's separator, is not her.
    """
    mine, theirs = (original or "").strip(), (title or "").strip()
    prefix = mine + " \u2014 "
    return theirs == mine or (bool(mine) and theirs.startswith(prefix) and len(theirs) > len(prefix))


def drawn_garments(doc: GltfDocument) -> list[str]:
    """The template ids of the Forge garments this file still draws, in node order.

    A body state Forge built names its garments on their nodes (``extras.wardrobeForge``). The
    companion's coverage model (WardrobeCoverage) knows a look only by its template ids, so an
    import that does not carry them is a look of unknown coverage: never offered as a step of
    undressing. Read from the file, not from anything the caller says.
    """
    out: list[str] = []
    for index in scene_mesh_nodes(doc):
        tag = (doc.nodes[index].get("extras") or {}).get("wardrobeForge") or {}
        template = tag.get("templateId")
        if tag.get("kind") == "garment" and template and template not in out:
            out.append(str(template))
    return out


def scene_mesh_nodes(doc: GltfDocument) -> list[int]:
    """BI6. The nodes the renderer draws: reachable from the active scene's roots and holding a mesh.

    A mesh definition proves nothing about what is on screen. An import that kept her face mesh
    in the file but detached it from the scene (the node removed from every parent, or left
    without its ``mesh``) passed the face-and-hair check while the renderer drew no face at all.
    """
    scenes = doc.gltf.get("scenes") or []
    if not scenes:
        return []
    index = doc.gltf.get("scene", 0)
    scene = scenes[index] if isinstance(index, int) and 0 <= index < len(scenes) else scenes[0]
    seen: set[int] = set()
    stack = list(scene.get("nodes") or [])
    while stack:
        node = stack.pop()
        if not isinstance(node, int) or node in seen or not 0 <= node < len(doc.nodes):
            continue
        seen.add(node)
        stack.extend(doc.nodes[node].get("children") or [])
    return sorted(n for n in seen if "mesh" in doc.nodes[n])


def _primitive(doc: GltfDocument, mesh_name: str, index: int) -> dict | None:
    """The primitive of a mesh of this name that a scene node actually draws, or None."""
    for node in scene_mesh_nodes(doc):
        mesh = doc.meshes[doc.nodes[node]["mesh"]]
        if mesh.get("name", "") == mesh_name and index < len(mesh["primitives"]):
            return mesh["primitives"][index]
    return None


def _structure(data: bytes):
    try:
        doc = GltfDocument.from_bytes(data)
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same refusal
        return None, None, f"not a readable GLB: {exc}"
    try:
        info = inspect_document(doc)
    except NotAVrm as exc:
        return doc, None, str(exc)
    except Exception as exc:  # noqa: BLE001
        return doc, None, f"VRM metadata unreadable: {exc}"
    return doc, info, None


def check(data: bytes, original: bytes, *, state: str, source_sha256: str,
          declared_sha256: str | None = None, operator_enabled: bool, depicts_adult: bool,
          review_root, reference_root) -> ImportVerdict:
    """The verdict for importing ``data`` as ``state`` of the library character whose bytes are
    ``original`` and whose pinned hash is ``source_sha256``. Never raises for a bad upload."""
    digest = sha256(data)
    checks: dict[str, dict] = {}

    def refuse(reason: str, message: str) -> ImportVerdict:
        return ImportVerdict(False, reason, message, digest, checks)

    # -- bytes and binding: cheap, and nothing is parsed until they pass --------------------
    if state not in STATES:
        return refuse("state-unknown", f"state must be one of {', '.join(STATES)}")
    if len(data) > MAX_BYTES:
        return refuse("too-large", f"a body-state VRM is at most {MAX_BYTES // (1024 * 1024)} MB")
    declared = (declared_sha256 or "").strip().lower()
    if declared and not _SHA.match(declared):
        return refuse("sha256-malformed", "the stated SHA-256 is not 64 hex characters")
    checks["sha256"] = {"passed": not declared or declared == digest, "actual": digest,
                        "declared": declared or None}
    if declared and declared != digest:
        return refuse("sha256-mismatch", "the file's SHA-256 is not the one stated: it changed in transit or "
                                         "is not the file that was reviewed")
    pinned = sha256(original)
    bound = (source_sha256 or "").strip().lower()
    checks["source-binding"] = {"passed": bound == pinned, "sourceSha256": bound or None, "pinned": pinned}
    if bound != pinned:
        return refuse("source-mismatch", "the import names another version of her: its source SHA-256 is not "
                                         "the one this library pins")
    if digest == pinned:
        return refuse("same-as-original", "this is her original file, not a body state of it")

    # -- structure ---------------------------------------------------------------------------
    doc, info, problem = _structure(data)
    base, base_info, base_problem = _structure(original)
    if base_problem:  # her own file: a server fault, not the upload's
        return refuse("original-unreadable", f"her library file could not be read: {base_problem}")
    checks["vrm"] = {"passed": problem is None, "why": problem or ""}
    if problem:
        return refuse("not-a-vrm", problem)
    issues = validate_humanoid(doc, info)
    same_spec = info.spec == base_info.spec
    checks["humanoid"] = {"passed": not issues and same_spec, "issues": issues,
                          "spec": str(info.spec), "originalSpec": str(base_info.spec)}
    if issues:
        return refuse("rig-invalid", "; ".join(issues))
    if not same_spec:
        return refuse("spec-mismatch", f"her file is {base_info.spec}, the import is {info.spec}")

    # -- rig -------------------------------------------------------------------------------------
    moved, renamed, missing = [], [], []
    for bone, node in sorted(base_info.humanoid_bones.items()):
        theirs = info.humanoid_bones.get(bone)
        if theirs is None:
            missing.append(bone)
            continue
        if doc.nodes[theirs].get("name") != base.nodes[node].get("name"):
            renamed.append(bone)
        gap = float(np.linalg.norm(doc.node_world_position(theirs) - base.node_world_position(node)))
        if gap > RIG_TOLERANCE_M:
            moved.append({"bone": bone, "movedM": round(gap, 4)})
    checks["rig"] = {"passed": not (moved or renamed or missing), "bones": len(base_info.humanoid_bones),
                     "missing": missing, "renamed": renamed, "moved": moved}
    if missing or renamed or moved:
        return refuse("rig-mismatch", "her skeleton is not the same: "
                      + ", ".join(filter(None, [missing and f"missing {missing}",
                                                renamed and f"renamed {renamed}",
                                                moved and f"moved {[m['bone'] for m in moved]}"])))

    # -- identity --------------------------------------------------------------------------------
    lost = sorted(set(base_info.expressions) - set(info.expressions))
    same_meta = same_title(info.title, base_info.title) and \
        list(info.license.authors) == list(base_info.license.authors)
    checks["expressions"] = {"passed": not lost, "count": len(base_info.expressions), "lost": lost}
    checks["metadata"] = {"passed": same_meta, "title": info.title, "originalTitle": base_info.title,
                          "authors": list(info.license.authors),
                          "originalAuthors": list(base_info.license.authors)}
    head = base_info.humanoid_bones.get("head")
    face_hair = identity_primitives(base, head)
    changed = []
    for mesh_name, pi, _node_name, accessor in face_hair:
        theirs = _primitive(doc, mesh_name, pi)
        if theirs is None or "POSITION" not in theirs.get("attributes", {}):
            changed.append({"mesh": mesh_name, "primitive": pi, "why": "absent"})
            continue
        a = base.read_accessor(accessor)
        b = doc.read_accessor(theirs["attributes"]["POSITION"])
        mine = base.meshes[[m.get("name", "") for m in base.meshes].index(mesh_name)]["primitives"][pi]
        if a.shape != b.shape:
            changed.append({"mesh": mesh_name, "primitive": pi, "why": "vertex count"})
        elif len(mine.get("targets", [])) != len(theirs.get("targets", [])):
            changed.append({"mesh": mesh_name, "primitive": pi, "why": "morph targets"})
        elif float(np.abs(a - b).max(initial=0.0)) > IDENTITY_TOLERANCE_M:
            changed.append({"mesh": mesh_name, "primitive": pi, "why": "geometry"})
    checks["face-and-hair"] = {"passed": bool(face_hair) and not changed, "primitives": len(face_hair),
                               "changed": changed}
    if lost:
        return refuse("expressions-lost", f"expressions she has are missing: {', '.join(lost)}")
    if not same_meta:
        return refuse("identity-mismatch", "VRM title or authors differ from her file")
    if not face_hair:
        return refuse("identity-unverifiable", "no face or hair mesh is skinned to her head, so the import "
                                               "cannot be shown to be her")
    if changed:
        return refuse("identity-mismatch", "her face or hair is not the same: "
                      + ", ".join(f"{c['mesh']}#{c['primitive']} ({c['why']})" for c in changed))

    # -- state -----------------------------------------------------------------------------------
    if state == "bare":
        protected = {i for i, m in enumerate(doc.materials)
                     if ANATOMY.search(m.get("name", "")) or (m.get("extras") or {}).get("authoredAnatomy")}
        clothing = [g for g in garment_inventory(doc)
                    if doc.meshes[g.mesh]["primitives"][g.primitive].get("material") not in protected]
        try:
            integrity = check_body(doc, measure_body(doc, info), BARE_REGIONS, bare=True).to_dict()
        except Exception as exc:  # noqa: BLE001 - an unmeasurable body is not a complete one
            integrity = {"complete": False, "error": str(exc)}
        proxy = any("bodyProxy" in ((item.get("extras") or {}).get("wardrobeForge") or {})
                    or ((item.get("extras") or {}).get("wardrobeForge") or {}).get("kind") == "bodyProxy"
                    for item in [*doc.meshes, *doc.nodes])
        checks["body-state"] = {"passed": integrity.get("complete") and not clothing,
                                "integrity": integrity, "clothingRemains": [g.slot for g in clothing],
                                "reconstructed": proxy}
        if clothing:
            return refuse("clothing-remains", "a bare import still has detected clothing: "
                          + ", ".join(sorted({g.slot for g in clothing})))
        if not integrity.get("complete"):
            return refuse("body-incomplete", "the body is not closed in every band body-bare-v1 checks")
    else:
        checks["body-state"] = {"passed": True, "state": state}

    # -- who may have it: the same contract as body-bare-v1, for both exact files ----------------
    # Lingerie is an intimate category: Forge makes it for an avatar declared adult, whose terms
    # allow it, privately, with no design review (wardrobe.policy.intimate). Bare additionally
    # needs the operator's switch and a clearly-adult review of each exact file.
    roots = {"review_root": review_root, "reference_root": reference_root}
    for label, terms, file_sha in (("eligibility-source", base_info.license, pinned),
                                   ("eligibility-import", info.license, digest)):
        verdict = assess(terms=terms, operator_enabled=operator_enabled, depicts_adult=depicts_adult,
                         private=True, source_sha256=file_sha, **roots)
        if state != "bare":
            needed = ("author-permission", "adult-declaration", "private-session")
            failed = next((n for n in needed if not verdict.checks[n]["passed"]), None)
            checks[label] = {"passed": failed is None, "refusedBy": failed,
                             "checks": {n: verdict.checks[n] for n in needed}}
        else:
            failed = verdict.refused_by
            checks[label] = {"passed": verdict.allowed, **verdict.to_dict()}
        if failed:
            return refuse("not-permitted", f"{label.split('-')[1]} file: {verdict.checks[failed]['why']}")

    checks["garments"] = {"passed": True, "fromFile": drawn_garments(doc)}
    accepted = f"{state} body state of {base_info.title or 'her'} accepted"
    return ImportVerdict(True, None, accepted, digest, checks)


__all__ = [
    "BARE_REGIONS", "IDENTITY_TOLERANCE_M", "MAX_BYTES", "RIG_TOLERANCE_M", "STATES", "ImportVerdict",
    "check", "drawn_garments", "scene_mesh_nodes", "identity_primitives", "same_title", "sha256",
]
