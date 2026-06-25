# -*- coding: utf-8 -*-
# Phase 1.5 テスト: 間隔XYZ / 入れ子 / Random
# 実行: blender.exe --background --factory-startup --python tests/test_phase2.py
import bpy
import sys
import bmesh

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


def mk_cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def count_instances():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return sum(1 for i in deps.object_instances if i.is_instance)


def inst_x_coords():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    xs = set()
    for i in deps.object_instances:
        if i.is_instance:
            xs.add(round(i.matrix_world.translation.x, 3))
    return sorted(xs)


def test_spacing_xyz():
    clear()
    cube = mk_cube("cube")
    bpy.context.view_layer.objects.active = cube
    e = replicator.create_replicator(bpy.context, [cube])
    e.replicator.spacing_x = 100.0
    e.replicator.spacing_y = 200.0
    e.replicator.spacing_z = 300.0
    xs = inst_x_coords()
    log("SPACING_XYZ x-coords:", xs, "(expect [-1.0, 0.0, 1.0] from 100cm)")
    log("  ->", "PASS" if xs == [-1.0, 0.0, 1.0] else "FAIL")


def test_nesting():
    clear()
    cube = mk_cube("cube")
    bpy.context.view_layer.objects.active = cube
    A = replicator.create_replicator(bpy.context, [cube])   # 内側 3x3x3
    A.name = "Repl_A"
    B = replicator.create_replicator(bpy.context, None)   # 外側(空)
    B.name = "Repl_B"
    log("B empty (no source) count:", count_instances(), "(expect 0)")
    # A を B に入れ子
    A.parent = B
    A.matrix_parent_inverse = B.matrix_world.inverted()
    replicator.update_replicator(B)
    disp_A = replicator.get_display(A)
    log("A.display hide_get:", disp_A.hide_get(), "hide_render:", disp_A.hide_render)
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    from collections import Counter
    tally = Counter()       # 何がインスタンス化されているか
    for i in deps.object_instances:
        if i.is_instance and i.object:
            tally[i.object.name] += 1
    log("NESTED total:", sum(tally.values()), "by instanced object:", dict(tally))
    cubes = tally.get("cube", 0)
    log("  real cube clones:", cubes, "(expect 729)")
    log("  ->", "PASS" if cubes == 729 else ("CHECK cubes=%d" % cubes))


def test_random():
    clear()
    cube = mk_cube("cube")
    bpy.context.view_layer.objects.active = cube
    e = replicator.create_replicator(bpy.context, [cube])
    log("random off x-coords:", inst_x_coords())
    p = e.replicator
    m = p.modulators.add()            # 新API: Random モジュレータ
    m.mtype = 'RANDOM'
    m.pos = (100.0, 0.0, 0.0)         # ±1m on X
    m.seed = 1
    p.modulator_index = 0
    replicator.update_replicator(e)
    xs1 = inst_x_coords()
    log("random seed=1 unique-x count:", len(xs1), "(expect > 3 = randomized)",
        "->", "PASS" if len(xs1) > 3 else "FAIL")
    cnt = count_instances()
    log("  instance count still:", cnt, "(expect 27)",
        "->", "PASS" if cnt == 27 else "FAIL")
    # ダイス: モジュレータのシードが変わり、パターンも変わる
    bpy.context.view_layer.objects.active = e
    old = m.seed
    bpy.ops.object.replicator_modulator_dice()
    xs2 = inst_x_coords()
    log("dice seed:", old, "->", m.seed)
    log("pattern changed by dice:", "YES" if xs1 != xs2 else "NO",
        "->", "PASS" if xs1 != xs2 else "FAIL")


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    test_spacing_xyz()
    test_nesting()
    test_random()
    log("DONE")


main()
