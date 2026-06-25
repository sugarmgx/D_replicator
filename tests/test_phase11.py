# -*- coding: utf-8 -*-
# v0.6 テスト: メッシュモード — 任意メッシュの頂点/辺の中心/面の中心に配置 + 法線揃え
# 実行: blender.exe --background --factory-startup --python tests/test_phase11.py
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


def mk_cube(name, size, location=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = location
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
    """インスタンスの (位置, ローカルZ軸) を集める。"""
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    pts, zaxes = [], []
    for i in deps.object_instances:
        if i.is_instance:
            m = i.matrix_world
            t = m.translation
            pts.append((round(t.x, 2), round(t.y, 2), round(t.z, 2)))
            z = m.col[2].xyz.normalized()
            zaxes.append((round(z.x, 2), round(z.y, 2), round(z.z, 2)))
    return pts, zaxes


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    # 参照メッシュ = サイズ2の立方体(頂点±1 / 面中心±1)を (5,0,0) に置く
    ref = mk_cube("ref", 2.0, location=(5.0, 0.0, 0.0))
    bpy.context.view_layer.update()
    src = mk_cube("src", 0.4)        # 複製されるもの(小さい立方体)

    e = replicator.create_replicator(bpy.context, [src])
    p = e.replicator
    p.mode = 'MESH'
    p.mesh_object = ref
    p.mesh_align = False

    # --- 頂点モード: 8個、立方体の頂点に一致 ---
    p.mesh_source = 'VERTS'
    pts, _ = sample()
    sp = set(pts)
    want_v = {(4, -1, -1), (4, -1, 1), (4, 1, -1), (4, 1, 1),
              (6, -1, -1), (6, -1, 1), (6, 1, -1), (6, 1, 1)}
    log("VERTS count:", len(pts), "pts:", sorted(sp))
    check("頂点=8個", len(pts) == 8)
    check("頂点位置が立方体頂点に一致(参照の世界位置に乗る)", sp == want_v)

    # --- 面の中心モード: 6個、面中心に一致 ---
    p.mesh_source = 'FACES'
    pts, _ = sample()
    sp = set(pts)
    want_f = {(6, 0, 0), (4, 0, 0), (5, 1, 0), (5, -1, 0), (5, 0, 1), (5, 0, -1)}
    log("FACES count:", len(pts), "pts:", sorted(sp))
    check("面=6個", len(pts) == 6)
    check("面中心位置が一致", sp == want_f)

    # --- 辺の中心モード: 12個 ---
    p.mesh_source = 'EDGES'
    pts, _ = sample()
    log("EDGES count:", len(pts), "(expect 12)")
    check("辺=12個", len(pts) == 12)
    # 各辺中点は2軸が±1・残り1軸が0(立方体の辺)
    edge_ok = all(sorted(abs(v) for v in pt_local) == [0, 1, 1]
                  for pt_local in [(x - 5, y, z) for (x, y, z) in pts])
    check("辺中点が立方体の辺上(2軸±1, 1軸0)", edge_ok)

    # --- 参照を動かすと追従(compute が現在の matrix_world を読む) ---
    p.mesh_source = 'VERTS'
    ref.location = (0.0, 5.0, 0.0)
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)      # ライブ移動相当(headless はハンドラ自動発火しないので明示)
    pts, _ = sample()
    xs = sorted({x for (x, y, z) in pts})
    ys = sorted({y for (x, y, z) in pts})
    log("moved ref -> xs:", xs, "ys:", ys)
    check("参照移動に追従(x=±1, y=4/6)", xs == [-1.0, 1.0] and ys == [4.0, 6.0])

    # --- 参照なし → 0個(空 Cloner と同じく何も出さない) ---
    p.mesh_object = None
    pts, _ = sample()
    log("no ref -> count:", len(pts))
    check("参照なしで0個", len(pts) == 0)

    # --- 法線揃え: 平面(法線+Z)を90°回転 → 法線(0,-1,0)にクローンZ軸が向く ---
    clear()
    plane = mk_plane("plane", 2.0)
    plane.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    bpy.context.view_layer.update()
    src2 = mk_cube("src2", 0.4)
    e2 = replicator.create_replicator(bpy.context, [src2])
    p2 = e2.replicator
    p2.mode = 'MESH'
    p2.mesh_object = plane
    p2.mesh_source = 'FACES'

    p2.mesh_align = False
    _, zaxes_off = sample()
    log("align OFF z-axis:", zaxes_off, "(複製元そのまま = +Z)")
    check("揃えOFFはZ軸そのまま(0,0,1)", zaxes_off and zaxes_off[0] == (0.0, 0.0, 1.0))

    p2.mesh_align = True
    _, zaxes_on = sample()
    log("align ON z-axis:", zaxes_on, "(expect ~ (0,-1,0))")
    ok_align = bool(zaxes_on) and abs(zaxes_on[0][1] - (-1.0)) < 0.05 \
        and abs(zaxes_on[0][0]) < 0.05 and abs(zaxes_on[0][2]) < 0.05
    check("揃えONでZ軸が面法線(0,-1,0)に向く", ok_align)

    # --- 他モードへ戻しても壊れない(回帰) ---
    p2.mode = 'GRID'
    pts, _ = sample()
    log("back to GRID count:", len(pts), "(expect 27)")
    check("メッシュ→グリッドへ戻して27個", len(pts) == 27)

    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
