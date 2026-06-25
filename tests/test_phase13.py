# -*- coding: utf-8 -*-
# v0.7 テスト: スプラインモード — カーブ上に弧長等間隔配置 + 接線揃え + 周回 + 変換追従
# 実行: blender.exe --background --factory-startup --python tests/test_phase13.py
import bpy
import sys
import bmesh

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)

_fails = []


def log(*a):
    print("[TEST]", *a)
    sys.stdout.flush()


def check(name, cond):
    log(("PASS" if cond else "FAIL"), name)
    if not cond:
        _fails.append(name)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        if c is not bpy.context.scene.collection:
            bpy.data.collections.remove(c)


def mk_cube(name, size):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_poly(name, coords, cyclic=False):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('POLY')
    sp.points.add(len(coords) - 1)
    for i, c in enumerate(coords):
        sp.points[i].co = (c[0], c[1], c[2], 1.0)
    sp.use_cyclic_u = cyclic
    o = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_bezier_straight(name):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(1)
    a, b = sp.bezier_points[0], sp.bezier_points[1]
    a.co = (0, 0, 0); a.handle_left = (-1, 0, 0); a.handle_right = (1, 0, 0)
    b.co = (4, 0, 0); b.handle_left = (3, 0, 0); b.handle_right = (5, 0, 0)
    o = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(o)
    return o


def sample():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    pts, zax = [], []
    for i in deps.object_instances:
        if i.is_instance:
            m = i.matrix_world
            t = m.translation
            pts.append((round(t.x, 2), round(t.y, 2), round(t.z, 2)))
            z = m.col[2].xyz.normalized()
            zax.append((round(z.x, 2), round(z.y, 2), round(z.z, 2)))
    return pts, zax


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    # ===== A. 直線POLY(0,0,0)->(4,0,0) に5個 等間隔 =====
    line = mk_poly("line", [(0, 0, 0), (4, 0, 0)])
    src = mk_cube("src", 0.3)
    e = replicator.create_replicator(bpy.context, [src])
    p = e.replicator
    p.mode = 'SPLINE'
    p.spline_object = line
    p.count_x = 5
    p.spline_align = False

    pts, _ = sample()
    xs = sorted(x for (x, y, z) in pts)
    log("line 5pts xs:", xs, "(expect 0,1,2,3,4)")
    check("直線に5個 等間隔", len(pts) == 5 and xs == [0.0, 1.0, 2.0, 3.0, 4.0])
    check("直線は y=z=0", all(y == 0.0 and z == 0.0 for (x, y, z) in pts))

    # 接線に揃える: 接線(1,0,0)、揃え軸Z → クローンZ軸が(1,0,0)
    p.spline_align = True
    p.align_axis = 'Z'
    _, zax = sample()
    log("align tangent z-axis[0]:", zax[0], "(expect (1,0,0))")
    check("接線揃え: Z軸が進行方向(1,0,0)へ", zax and zax[0] == (1.0, 0.0, 0.0))

    # 数を変えれば追従
    p.count_x = 9
    pts, _ = sample()
    log("count=9 ->", len(pts))
    check("数の変更に追従(9個)", len(pts) == 9)

    # ===== B. カーブを動かすと追従 =====
    p.count_x = 5
    p.spline_align = False
    line.location = (0.0, 0.0, 3.0)
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)
    pts, _ = sample()
    zs = sorted({z for (x, y, z) in pts})
    log("moved curve z:", zs, "(expect [3.0])")
    check("カーブ移動に追従(z=3)", zs == [3.0])

    # ===== C. 周回POLY(正方形)に4個 → 四隅 =====
    clear()
    sq = mk_poly("sq", [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], cyclic=True)
    src2 = mk_cube("src2", 0.2)
    e2 = replicator.create_replicator(bpy.context, [src2])
    p2 = e2.replicator
    p2.mode = 'SPLINE'
    p2.spline_object = sq
    p2.count_x = 4
    p2.spline_align = False
    pts, _ = sample()
    sp = {(x, y) for (x, y, z) in pts}
    log("cyclic square 4pts:", sorted(sp), "(expect 四隅)")
    check("周回スプラインに4個=四隅",
          len(pts) == 4 and sp == {(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)})

    # ===== D. Bezier(直線化)に5個 ≈ 等間隔 =====
    clear()
    bz = mk_bezier_straight("bz")
    src3 = mk_cube("src3", 0.2)
    e3 = replicator.create_replicator(bpy.context, [src3])
    p3 = e3.replicator
    p3.mode = 'SPLINE'
    p3.spline_object = bz
    p3.count_x = 5
    p3.spline_align = False
    pts, _ = sample()
    xs = sorted(x for (x, y, z) in pts)
    log("bezier 5pts xs:", xs, "(直線化なので ~0,1,2,3,4)")
    check("Bezierに5個・端が0と4", len(pts) == 5 and xs[0] == 0.0 and xs[-1] == 4.0)

    # ===== E. スプライン→グリッドへ戻して回帰 =====
    p3.mode = 'GRID'
    p3.count_x = 3                       # スプラインで 5 にしていたので戻す
    pts, _ = sample()
    log("back to GRID:", len(pts), "(expect 27)")
    check("スプライン→グリッドへ戻して27個", len(pts) == 27)

    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
