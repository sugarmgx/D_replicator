# -*- coding: utf-8 -*-
# v0.8 テスト: メッシュ面上ランダム散布(面積重み)+ 散布率0-100% + シード
# 実行: blender.exe --background --factory-startup --python tests/test_phase14.py
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


def mk_plane(name, size):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
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
            pts.append((round(t.x, 3), round(t.y, 3), round(t.z, 3)))
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

    # 平面(size2 → -1..1, 法線+Z, z=0)に200個 散布
    plane = mk_plane("plane", 2.0)
    src = mk_cube("src", 0.2)
    e = replicator.create_replicator(bpy.context, [src])
    p = e.replicator
    p.mode = 'MESH'
    p.mesh_object = plane
    p.mesh_source = 'SURFACE'
    p.count_safety = False               # 200個使うのでセーフティ解除
    p.count_x = 200
    p.scatter_seed = 1
    p.scatter_amount = 100.0
    p.mesh_align = False

    pts100, _ = sample()
    ext = max(max(abs(v.co.x), abs(v.co.y)) for v in plane.data.vertices)  # 面の実寸
    log("amount100 count:", len(pts100), "(expect 200) / 面の半幅:", round(ext, 2))
    check("散布率100%で200個", len(pts100) == 200)
    check("散布点は平面上(z=0)", all(z == 0.0 for (x, y, z) in pts100))
    check("散布点は面内(メッシュ範囲)",
          all(abs(x) <= ext + 1e-3 and abs(y) <= ext + 1e-3 for (x, y, z) in pts100))

    # 散布率 50% → 100個、かつ 100% の部分集合(前から k 個=既存点が動かない)
    p.scatter_amount = 50.0
    pts50, _ = sample()
    log("amount50 count:", len(pts50), "(expect 100)")
    check("散布率50%で100個", len(pts50) == 100)
    check("50%点は100%点の部分集合(前からk個で安定)",
          set(pts50).issubset(set(pts100)))

    # 散布率 0% → 0個
    p.scatter_amount = 0.0
    pts0, _ = sample()
    log("amount0 count:", len(pts0))
    check("散布率0%で0個", len(pts0) == 0)

    # シード違いで別パターン(同数だが位置集合が変わる)
    p.scatter_amount = 100.0
    p.scatter_seed = 1
    a1, _ = sample()
    p.scatter_seed = 2
    a2, _ = sample()
    log("seed1 vs seed2 同集合?:", set(a1) == set(a2), "(expect False)")
    check("シードで別パターン", len(a1) == 200 and len(a2) == 200 and set(a1) != set(a2))

    # 同シードは決定論(再計算で同じ)
    p.scatter_seed = 1
    a1b, _ = sample()
    check("同シードは決定論", set(a1) == set(a1b))

    # 法線に揃える: 平面(法線+Z)・揃え軸Z → 全クローンのZ軸が(0,0,1)
    p.mesh_align = True
    p.align_axis = 'Z'
    _, zax = sample()
    log("align z-axes uniq:", sorted(set(zax)), "(expect [(0,0,1)])")
    check("法線揃え: 全点のZ軸が(0,0,1)", zax and all(z == (0.0, 0.0, 1.0) for z in zax))

    # 面積重み: 大きい面に多く乗る(小1x1 と 大3x3 の2枚)
    clear()
    me = bpy.data.meshes.new("two")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)   # 中心(0,0) 辺長2 面積4
    for v in bm.verts:
        v.co.x += 10.0                                                # 小さい面を x=10 側へ
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=3.0)   # 中心(0,0) 辺長6 面積36
    bm.to_mesh(me)
    bm.free()
    two = bpy.data.objects.new("two", me)
    bpy.context.scene.collection.objects.link(two)
    src2 = mk_cube("src2", 0.2)
    e2 = replicator.create_replicator(bpy.context, [src2])
    p2 = e2.replicator
    p2.mode = 'MESH'
    p2.mesh_object = two
    p2.mesh_source = 'SURFACE'
    p2.count_safety = False              # 400個使うのでセーフティ解除
    p2.count_x = 400
    p2.scatter_seed = 7
    p2.mesh_align = False
    pts, _ = sample()
    near_small = sum(1 for (x, y, z) in pts if x > 5.0)   # 面積4の小さい面側
    near_big = len(pts) - near_small                      # 面積36の大きい面側
    log("area-weight small/big:", near_small, "/", near_big, "(big が圧倒的に多い)")
    check("面積重み: 大きい面に多く乗る", near_big > near_small * 4)

    # 散布→頂点へ戻して回帰(平面=4頂点)
    clear()
    pl = mk_plane("pl", 2.0)
    src3 = mk_cube("src3", 0.2)
    e3 = replicator.create_replicator(bpy.context, [src3])
    p3 = e3.replicator
    p3.mode = 'MESH'
    p3.mesh_object = pl
    p3.mesh_source = 'SURFACE'
    p3.count_x = 50
    pts, _ = sample()
    check("散布50個", len(pts) == 50)
    p3.mesh_source = 'VERTS'
    pts, _ = sample()
    log("back to VERTS:", len(pts), "(expect 4)")
    check("散布→頂点へ戻して4個", len(pts) == 4)

    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
