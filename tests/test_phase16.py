# -*- coding: utf-8 -*-
# v0.8.2 テスト: 間隔(cm)spacing_x/y/z + CIRCLE 半径 のキーフレーム
# 実行: blender.exe --background --factory-startup --python tests/test_phase16.py
import bpy
import sys
import math
import bmesh
import numpy as np

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


def check(name, cond, extra=""):
    log(("PASS" if cond else "FAIL"), "-", name, extra)
    if not cond:
        _fails.append(name)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mk_cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.5)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    sc = bpy.context.scene
    sc.frame_start = 1

    # ===== A. グリッド 間隔X のキーフレーム(frame1=100cm, frame10=300cm) =====
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mode = 'GRID'
    p.count_x = 3
    p.count_y = 1
    p.count_z = 1

    p.spacing_x = 100.0
    e.keyframe_insert("replicator.spacing_x", frame=1)
    p.spacing_x = 300.0
    e.keyframe_insert("replicator.spacing_x", frame=10)

    def half_x():
        pos, _ = replicator.compute_points(p)
        return float(pos[:, 0].max())     # = spacing_x * 0.01 (3個 → -s,0,+s)

    sc.frame_set(1)
    s1 = half_x()
    sc.frame_set(10)
    s10 = half_x()
    sc.frame_set(5)
    s5 = half_x()
    log("間隔X half-spread frame1/5/10:", round(s1, 3), round(s5, 3), round(s10, 3),
        "(expect 1.0 / 中間 / 3.0)")
    check("間隔X: frame1=1.0m(100cm)", abs(s1 - 1.0) < 1e-3, "s1=%.3f" % s1)
    check("間隔X: frame10=3.0m(300cm)", abs(s10 - 3.0) < 1e-3, "s10=%.3f" % s10)
    # 既定の F カーブ補間は Bezier(イーズ)なので線形値ではなく「厳密に中間」を確認
    check("間隔X: frame5は中間(補間されている)", s1 < s5 < s10, "s5=%.3f" % s5)

    # frame_change ハンドラが表示メッシュにも反映しているか
    sc.frame_set(10)
    disp = replicator.get_display(e)
    mesh_max_x = max(v.co.x for v in disp.data.vertices)
    check("間隔X: ハンドラ経由で表示メッシュも更新(frame10)", abs(mesh_max_x - 3.0) < 1e-3,
          "mesh=%.3f" % mesh_max_x)

    # ===== B. 間隔Y/Z もキー可(ボタン=オペレータで挿入/削除) =====
    bpy.context.view_layer.objects.active = e
    sc.frame_set(3)
    bpy.ops.object.replicator_keyframe(data_path="replicator.spacing_y", obj_name=e.name)
    check("間隔Y: ボタンでキー挿入", replicator._has_key(e, "replicator.spacing_y", 3))
    bpy.ops.object.replicator_keyframe(data_path="replicator.spacing_y", obj_name=e.name,
                                       remove=True)
    check("間隔Y: ボタンでキー削除", not replicator._has_key(e, "replicator.spacing_y", 3))

    bpy.ops.object.replicator_keyframe(data_path="replicator.spacing_z", obj_name=e.name)
    check("間隔Z: ボタンでキー挿入", replicator._has_key(e, "replicator.spacing_z", 3))

    # ===== C. CIRCLE 半径のキーフレーム(frame1=100cm, frame10=300cm) =====
    clear()
    c2 = mk_cube("c2")
    e2 = replicator.create_replicator(bpy.context, [c2])
    p2 = e2.replicator
    p2.mode = 'CIRCLE'
    p2.count_x = 4
    p2.radial_plane = 'XY'
    p2.radial_arc = 360.0

    p2.radius = 100.0
    e2.keyframe_insert("replicator.radius", frame=1)
    p2.radius = 300.0
    e2.keyframe_insert("replicator.radius", frame=10)

    def ring_r():
        pos, _ = replicator.compute_points(p2)
        return float(np.hypot(pos[:, 0], pos[:, 1]).max())

    sc.frame_set(1)
    r1 = ring_r()
    sc.frame_set(10)
    r10 = ring_r()
    log("CIRCLE 半径 frame1/10:", round(r1, 3), round(r10, 3), "(expect 1.0 / 3.0)")
    check("CIRCLE半径: frame1=1.0m", abs(r1 - 1.0) < 1e-3, "r1=%.3f" % r1)
    check("CIRCLE半径: frame10=3.0m", abs(r10 - 3.0) < 1e-3, "r10=%.3f" % r10)

    # ===== D. 回帰: キー無しの通常動作(間隔変更が即反映) =====
    clear()
    c3 = mk_cube("c3")
    e3 = replicator.create_replicator(bpy.context, [c3])
    p3 = e3.replicator
    p3.mode = 'GRID'
    p3.count_x = 2
    p3.count_y = 1
    p3.count_z = 1
    p3.spacing_x = 500.0
    pos, _ = replicator.compute_points(p3)
    sp = float(pos[:, 0].max() - pos[:, 0].min())
    check("回帰: キー無しでも間隔反映(2個・500cm=5m)", abs(sp - 5.0) < 1e-3, "sp=%.3f" % sp)

    sc.frame_set(1)
    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
