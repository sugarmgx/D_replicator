# -*- coding: utf-8 -*-
# v0.3 テスト: 複数オブジェクト×ランダム分配 / 内蔵段階トランスフォーム
# 実行: blender.exe --background --factory-startup --python tests/test_phase3.py
import bpy
import sys
import bmesh
from collections import Counter

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)


def log(*a):
    print("[TEST]", *a)
    sys.stdout.flush()


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mk_cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def tally_instances():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    t = Counter()
    for i in deps.object_instances:
        if i.is_instance and i.object:
            t[i.object.name] += 1
    return t


def inst_x_coords():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    xs = set()
    for i in deps.object_instances:
        if i.is_instance:
            xs.add(round(i.matrix_world.translation.x, 3))
    return sorted(xs)


def test_multiobject():
    clear()
    A, B, C = mk_cube("A"), mk_cube("B"), mk_cube("C")
    e = replicator.create_replicator(bpy.context, [A, B, C])
    e.replicator.dist_seed = 1
    t = tally_instances()
    abc = {k: t.get(k, 0) for k in ("A", "B", "C")}
    total = sum(abc.values())
    log("MULTI distribution:", abc, "total:", total)
    log("  -> count PASS" if total == 27 else "  -> count FAIL=%d" % total)
    log("  -> distributed PASS" if sum(1 for v in abc.values() if v > 0) >= 2 else "  -> NOT distributed")
    # ダイスで分配が変わる(割当配列そのもので判定)
    disp = replicator.get_display(e)

    def get_idx():
        return [d.value for d in disp.data.attributes["rep_index"].data]

    before_idx = get_idx()
    before_seed = e.replicator.dist_seed
    bpy.context.view_layer.objects.active = e
    bpy.ops.object.replicator_dice()
    after_idx = get_idx()
    log("dice dist_seed:", before_seed, "->", e.replicator.dist_seed)
    log("  assignment changed:", "YES" if before_idx != after_idx else "NO")


def test_step_transform():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    base = inst_x_coords()
    log("STEP base x (no step):", base)
    e.replicator.step_pos = (50.0, 0.0, 0.0)   # 複製ごとに +0.5m x
    xs = inst_x_coords()
    log("STEP with step_pos x unique:", len(xs), "(expect > 3 = gradient)")
    log("  ->", "PASS" if len(xs) > 3 else "FAIL")


def sample_scale_x():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    for i in deps.object_instances:
        if i.is_instance:
            return round(i.matrix_world.to_scale().x, 3)
    return None


def test_scale():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    log("SCALE base:", sample_scale_x(), "x-coords:", inst_x_coords(), "(scale~1, grid ±2.0)")
    e.replicator.base_scale = (2.0, 2.0, 2.0)
    log("SCALE base_scale=2:", sample_scale_x(), "(expect ~2.0)")
    # Relative: 複製元自身をスケールしても反映される
    e.replicator.base_scale = (1.0, 1.0, 1.0)
    cube.scale = (3.0, 3.0, 3.0)
    log("SCALE source.scale=3 (Relative):", sample_scale_x(), "(expect ~3.0)")
    log("  grid still:", inst_x_coords(), "(expect [-2.0,0.0,2.0])")


def scale_range():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    vals = [i.matrix_world.to_scale().x for i in deps.object_instances if i.is_instance]
    return (round(min(vals), 4), round(max(vals), 4)) if vals else (None, None)


def test_step_scale_tame():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    e.replicator.step_scale = 1.0
    e.replicator.step_normalized = True
    log("STEP-SCALE normalized=ON range:", scale_range(), "(expect max~2.0 = 暴れない)")
    e.replicator.step_normalized = False
    log("STEP-SCALE normalized=OFF range:", scale_range(), "(expect max~27 = 従来の累積)")
    e.replicator.step_normalized = True
    e.replicator.step_scale = -10.0
    rng = scale_range()
    log("STEP-SCALE step=-10 clamp range:", rng, "->", "PASS" if rng[0] and rng[0] > 0 else "FAIL")


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    test_multiobject()
    test_step_transform()
    test_scale()
    test_step_scale_tame()
    log("DONE")


main()
