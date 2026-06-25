# -*- coding: utf-8 -*-
# v0.7 テスト: メッシュモード拡張 — 揃え軸の選択 + 評価メッシュ(変形後)追従
# 実行: blender.exe --background --factory-startup --python tests/test_phase12.py
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


def basis0():
    """最初のインスタンスの (col0, col1, col2) を正規化して丸めて返す。"""
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    for i in deps.object_instances:
        if i.is_instance:
            m = i.matrix_world
            return tuple(
                (round(c.xyz.normalized().x, 2),
                 round(c.xyz.normalized().y, 2),
                 round(c.xyz.normalized().z, 2))
                for c in (m.col[0], m.col[1], m.col[2]))
    return None


def n_instances():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return sum(1 for i in deps.object_instances if i.is_instance)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    # ===== A. 揃え軸の選択(平面=法線+Z に各軸を向ける) =====
    plane = mk_plane("plane", 2.0)       # 法線 +Z(未回転)
    src = mk_cube("src", 0.4)
    e = replicator.create_replicator(bpy.context, [src])
    p = e.replicator
    p.mode = 'MESH'
    p.mesh_object = plane
    p.mesh_source = 'FACES'
    p.mesh_align = True

    p.align_axis = 'Z'
    b = basis0()
    log("axis Z -> col2:", b[2], "(expect (0,0,1))")
    check("揃え軸Z: Z軸が法線へ", b is not None and b[2] == (0.0, 0.0, 1.0))

    p.align_axis = 'X'
    b = basis0()
    log("axis X -> col0:", b[0], "(expect (0,0,1))")
    check("揃え軸X: X軸が法線へ", b[0] == (0.0, 0.0, 1.0))

    p.align_axis = 'Y'
    b = basis0()
    log("axis Y -> col1:", b[1], "(expect (0,0,1))")
    check("揃え軸Y: Y軸が法線へ", b[1] == (0.0, 0.0, 1.0))

    p.align_axis = '-Z'
    b = basis0()
    log("axis -Z -> col2:", b[2], "(expect (0,0,-1))")
    check("揃え軸-Z: Z軸が法線の逆へ", b[2] == (0.0, 0.0, -1.0))

    # ===== B. 評価メッシュ(変形後)追従 =====
    clear()
    ref = mk_cube("ref", 2.0)            # 8頂点 / 6面
    arr = ref.modifiers.new("Array", 'ARRAY')
    arr.count = 2                        # 評価後は 2 個ぶん = 16頂点 / 12面
    arr.relative_offset_displace[0] = 2.0  # 隙間を空けて頂点が重ならない=マージ無関係
    bpy.context.view_layer.update()
    src2 = mk_cube("src2", 0.3)
    e2 = replicator.create_replicator(bpy.context, [src2])
    p2 = e2.replicator
    p2.mode = 'MESH'
    p2.mesh_object = ref
    p2.mesh_align = False

    # 素メッシュ(既定 OFF): Array を無視 → 6面 / 8頂点
    p2.mesh_source = 'FACES'
    p2.mesh_use_evaluated = False
    bpy.context.view_layer.update()
    replicator.apply_transforms(e2)
    nf_raw = n_instances()
    log("eval OFF faces:", nf_raw, "(expect 6 = 素メッシュ)")
    check("評価OFFは素メッシュ(6面)", nf_raw == 6)

    # 評価メッシュ ON: Array 適用後 → 12面
    p2.mesh_use_evaluated = True
    bpy.context.view_layer.update()
    replicator.apply_transforms(e2)
    nf_eval = n_instances()
    log("eval ON faces:", nf_eval, "(expect 12 = Array適用後)")
    check("評価ONは変形後メッシュ(12面)", nf_eval == 12)

    # 頂点でも確認(8 -> 16)
    p2.mesh_source = 'VERTS'
    p2.mesh_use_evaluated = False
    replicator.apply_transforms(e2)
    nv_raw = n_instances()
    p2.mesh_use_evaluated = True
    bpy.context.view_layer.update()
    replicator.apply_transforms(e2)
    nv_eval = n_instances()
    log("verts raw/eval:", nv_raw, "/", nv_eval, "(expect 8 / 16)")
    check("評価ONで頂点も増える(8→16)", nv_raw == 8 and nv_eval == 16)

    # 評価メッシュでも一時メッシュがリークしない(連続評価で例外が出ない)
    ok_loop = True
    try:
        for _ in range(5):
            replicator.apply_transforms(e2)
    except Exception as ex:
        ok_loop = False
        log("loop error:", ex)
    check("評価メッシュ連続更新で例外なし(to_mesh_clear)", ok_loop and n_instances() == 16)

    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
