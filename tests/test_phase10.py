# -*- coding: utf-8 -*-
# v0.5.2 テスト: パラメータのキーフレーム(動く + キーボタン操作の挿入/削除)
# 実行: blender.exe --background --factory-startup --python tests/test_phase10.py
import bpy
import sys
import bmesh
import numpy as np

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)

PASS = True


def log(*a):
    print("[TEST]", *a); sys.stdout.flush()


def check(name, cond, extra=""):
    global PASS
    PASS = PASS and bool(cond)
    log(("PASS" if cond else "FAIL"), "-", name, extra)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mk_cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


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
    p.count_x = p.count_y = p.count_z = 3
    p.spacing_x = p.spacing_y = p.spacing_z = 200.0
    pos_grid, _ = replicator.compute_points(p)
    sc = bpy.context.scene
    sc.frame_start = 1

    # Random モジュレータ(Z 位置)。これをキーフレームで 0→200cm に動かす。
    m = p.modulators.add()
    m.mtype = 'RANDOM'
    m.seed = 0
    m.pos = (0.0, 0.0, 0.0)

    def dzmax():
        pos, _, _ = replicator.compute_clone_data(p, e)
        return float(np.abs(pos[:, 2] - pos_grid[:, 2]).max())

    # --- キーフレーム挿入(frame1: z=0, frame10: z=200) ---
    m.pos = (0.0, 0.0, 0.0)
    e.keyframe_insert("replicator.modulators[0].pos", frame=1)
    m.pos = (0.0, 0.0, 200.0)
    e.keyframe_insert("replicator.modulators[0].pos", frame=10)

    sc.frame_set(1)
    d1 = dzmax()
    sc.frame_set(10)
    d10 = dzmax()
    sc.frame_set(5)
    d5 = dzmax()
    log("dzmax frame1/5/10:", round(d1, 3), round(d5, 3), round(d10, 3))
    check("キー: frame1 は変位ほぼ0(pos.z=0)", d1 < 1e-4, "d1=%.4f" % d1)
    check("キー: frame10 は大きく変位(pos.z=200cm)", d10 > 1.0, "d10=%.3f" % d10)
    check("キー: frame5 は中間(0<d5<d10)", 1e-4 < d5 < d10, "d5=%.3f" % d5)

    # --- frame_change ハンドラが表示メッシュに反映しているか(描画経路) ---
    sc.frame_set(10)
    disp = replicator.get_display(e)
    coz = np.array([v.co.z for v in disp.data.vertices])
    handler_dz = float(np.abs(coz - pos_grid[:, 2]).max())
    check("キー: ハンドラ経由で表示メッシュも更新(frame10)", abs(handler_dz - d10) < 1e-4,
          "mesh=%.3f compute=%.3f" % (handler_dz, d10))

    # --- キーフレームボタン(オペレータ)で挿入/削除 ---
    clear()
    cube2 = mk_cube("cube2")
    e2 = replicator.create_replicator(bpy.context, [cube2])
    bpy.context.view_layer.objects.active = e2
    sc.frame_set(3)
    e2.replicator.step_pos = (0.0, 0.0, 50.0)
    bpy.ops.object.replicator_keyframe(data_path="replicator.step_pos", obj_name=e2.name)
    inserted = replicator._has_key(e2, "replicator.step_pos", 3)
    check("ボタン: オペレータでキー挿入できる", inserted)
    bpy.ops.object.replicator_keyframe(data_path="replicator.step_pos", obj_name=e2.name, remove=True)
    removed = not replicator._has_key(e2, "replicator.step_pos", 3)
    check("ボタン: オペレータでキー削除できる", removed)

    # --- フィールドギズモの位置キー(フィールドを掃く動き) ---
    clear()
    cube3 = mk_cube("cube3")
    e3 = replicator.create_replicator(bpy.context, [cube3])
    fo = replicator.ensure_field(e3)
    bpy.ops.object.replicator_keyframe(data_path="location", obj_name=fo.name)
    check("ボタン: フィールドギズモ位置にもキー可", replicator._has_key(fo, "location",
          sc.frame_current))

    sc.frame_set(1)
    log("=== RESULT:", "ALL PASS" if PASS else "SOME FAILED", "===")


main()
