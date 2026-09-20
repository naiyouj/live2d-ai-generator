"""Neck z-order normalisation (core.structure.zorder).

See-through drew the neck *above* ``face_base`` on a real character, so on every head turn the
neck's rectangular crop edge painted over the jaw — the "square under the chin" artifact. These pin
the tuck rules and, just as importantly, that a correctly-ordered stack is left alone.
"""

from __future__ import annotations

from pathlib import Path

from image2live2d.core.structure import normalize_neck_zorder
from image2live2d.core.types import Layer, LayerStack
from image2live2d.irr.schema import Mesh
from image2live2d.irr.schema import SemanticRole as R


def _mesh(pid, x0, y0, x1, y1) -> Mesh:
    verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return Mesh(part_id=pid, vertices=verts, uvs=[(0.0, 0.0)] * 4, triangles=[(0, 1, 2), (0, 2, 3)])


def _scene(parts):
    """parts: list of (id, role, draw_order, (x0, y0, x1, y1))."""
    layers, meshes = [], []
    for pid, role, order, box in parts:
        layers.append(Layer(id=pid, semantic_role=role, texture_path=Path(f"{pid}.png"),
                            draw_order=order, width=64, height=64))
        meshes.append(_mesh(pid, *box))
    layers.sort(key=lambda ly: ly.draw_order)
    return LayerStack(layers=layers, canvas_width=64, canvas_height=64), meshes


def _order(stack):
    return {ly.id: ly.draw_order for ly in stack.layers}


def test_neck_painting_over_the_jaw_is_tucked_behind_the_face():
    """Real geometry (char 20260916): face at 3, neck at 6 — on head turns the neck's hard top edge
    painted a square block over the jaw. The neck belongs behind the head."""
    stack, meshes = _scene([
        ("hair_back", R.hair_back, 0, (0.30, 0.20, 0.70, 0.95)),
        ("ear", R.ear_l, 1, (0.36, 0.78, 0.40, 0.83)),
        ("face", R.face_base, 3, (0.42, 0.70, 0.58, 0.90)),
        ("neck", R.neck, 6, (0.46, 0.55, 0.54, 0.76)),     # top band under the jaw
        ("clothes", R.clothing, 8, (0.36, 0.60, 0.64, 0.98)),
    ])
    moved = normalize_neck_zorder(stack, meshes)
    assert "neck" in moved
    o = _order(stack)
    assert o["neck"] < o["face"]       # behind the head
    assert o["neck"] > o["hair_back"]  # ...but still in front of the nape hair


def test_a_neck_under_the_collar_is_tucked_behind_the_garment():
    """A neck that paints over a covering garment shows the same artifact at rest, no turn needed."""
    stack, meshes = _scene([
        ("face", R.face_base, 3, (0.42, 0.70, 0.58, 0.90)),
        ("neck", R.neck, 6, (0.46, 0.55, 0.54, 0.76)),
        ("collar", R.clothing, 4, (0.40, 0.58, 0.60, 0.98)),   # covers the neck's bottom band
    ])
    moved = normalize_neck_zorder(stack, meshes)
    assert "neck" in moved
    o = _order(stack)
    assert o["neck"] < _order(stack)["collar"]   # behind the garment
    assert o["neck"] < _order(stack)["face"]     # ...and behind the jaw it was painting over


def test_a_correctly_ordered_neck_is_untouched():
    """neck already behind face/collar, in front of the nape hair -> byte-identical stack."""
    stack, meshes = _scene([
        ("hair_back", R.hair_back, 0, (0.30, 0.20, 0.70, 0.95)),
        ("neck", R.neck, 1, (0.46, 0.55, 0.54, 0.76)),
        ("face", R.face_base, 3, (0.42, 0.70, 0.58, 0.90)),
        ("collar", R.clothing, 4, (0.40, 0.58, 0.60, 0.98)),
    ])
    before = _order(stack)
    assert normalize_neck_zorder(stack, meshes) == []
    assert _order(stack) == before


def test_a_neck_that_misses_the_face_is_left_alone():
    """Only *actual* occlusion tucks the neck — a jaw that misses the neck's top band reorders
    nothing (e.g. a character whose head is fully above the neck crop)."""
    stack, meshes = _scene([
        ("face", R.face_base, 3, (0.42, 0.80, 0.58, 0.95)),    # above the neck crop, no overlap
        ("neck", R.neck, 6, (0.46, 0.55, 0.54, 0.76)),
    ])
    before = _order(stack)
    assert normalize_neck_zorder(stack, meshes) == []
    assert _order(stack) == before


def test_the_tuck_keeps_the_neck_in_front_of_the_torso():
    """A chest reaching up to the throat must not end up painting over the tucked neck: the neck
    slots between the torso and the face, never behind the body it hangs over."""
    stack, meshes = _scene([
        ("hair_back", R.hair_back, 0, (0.30, 0.20, 0.70, 0.95)),
        ("torso", R.torso, 2, (0.38, 0.40, 0.62, 0.72)),       # chest reaching the throat
        ("face", R.face_base, 3, (0.42, 0.70, 0.58, 0.90)),
        ("neck", R.neck, 6, (0.46, 0.55, 0.54, 0.76)),
    ])
    moved = normalize_neck_zorder(stack, meshes)
    assert "neck" in moved
    o = _order(stack)
    assert o["neck"] < o["face"]       # tucked behind the jaw...
    assert o["neck"] > o["torso"]      # ...but never behind the body it hangs over
    assert o["neck"] > o["hair_back"]
