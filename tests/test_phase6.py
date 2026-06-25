# -*- coding: utf-8 -*-
# v0.4 テスト: 円形(放射)モード — 半径/個数/平面/角度/Align
# 実行: blender.exe --background --factory-startup --python tests/test_phase6.py
import bpy
import sys
import math
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


def sample():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    pts, zrots = [], []
    for i in deps.object_instances:
        if i.is_instance:
            t = i.matrix_world.translation
            pts.append((round(t.x, 2), round(t.y, 2), round(t.z, 2)))
            zrots.append(round(math.degrees(i.matrix_world.to_euler().z)) % 360)
    return pts, zrots


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()

    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mode = 'CIRCLE'
    p.count_x = 6
    p.radius = 200.0
    p.radial_plane = 'XY'
    p.radial_align = True

    pts, zrots = sample()
    radii = sorted({round(math.hypot(x, y), 2) for (x, y, z) in pts})
    zset = sorted({z for (x, y, z) in pts})
    log("RADIAL count:", len(pts), "(expect 6)")
    log("  radii:", radii, "(expect [2.0])")
    log("  z-plane:", zset, "(expect [0.0] = XY平面)")
    log("  align z-rots:", sorted(set(zrots)), "(expect 0/60/120/180/240/300)")
    ok = len(pts) == 6 and radii == [2.0] and zset == [0.0]
    log("  ->", "PASS" if ok else "FAIL")

    p.radial_align = False
    _, zrots2 = sample()
    log("align OFF z-rots:", sorted(set(zrots2)), "(expect [0])")

    p.radial_align = True
    p.radial_plane = 'XZ'
    pts3, _ = sample()
    yset = sorted({y for (x, y, z) in pts3})
    log("plane XZ y-set:", yset, "(expect [0.0])")

    p.radial_plane = 'XY'
    p.radial_arc = 180.0
    p.count_x = 3
    pts4, _ = sample()
    xs = sorted({x for (x, y, z) in pts4})
    log("arc=180 count=3 pts:", sorted(pts4), "(半円: 0,90,180度)")

    # 放射(RADIAL/従来)はそのまま: 間隔X=半径・Alignなし
    clear()
    c2 = mk_cube("cube")
    e2 = replicator.create_replicator(bpy.context, [c2])
    e2.replicator.mode = 'RADIAL'
    e2.replicator.count_x = 4
    e2.replicator.spacing_x = 200.0
    pts5, rots5 = sample()
    radii5 = sorted({round(math.hypot(x, y), 2) for (x, y, z) in pts5})
    log("RADIAL(従来) count:", len(pts5), "radii:", radii5, "z-rots:", sorted(set(rots5)),
        "-> ", "PASS" if len(pts5) == 4 and radii5 == [2.0] and sorted(set(rots5)) == [0] else "FAIL")
    log("DONE")


main()
