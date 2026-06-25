# -*- coding: utf-8 -*-
# v0.5 テスト: モジュレータ・スタック(Random/Step/Time 積み重ね・個別フィールドゲート・移行)
# 実行: blender.exe --background --factory-startup --python tests/test_phase9.py
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


def clear_mods(p):
    while len(p.modulators):
        p.modulators.remove(0)


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
    I0, I13, I26 = 0, 13, 26   # (-2,-2,-2) / (0,0,0) / (2,2,2)

    def dz():
        pos, _, _ = replicator.compute_clone_data(p, e)
        return pos[:, 2] - pos_grid[:, 2]

    def rotz():
        _, rot, _ = replicator.compute_clone_data(p, e)
        return rot[:, 2]

    # ===== 1: Random を2つ積む = 加算スタック + ON/OFF =====
    mA = p.modulators.add(); mA.mtype = 'RANDOM'; mA.seed = 1; mA.pos = (0, 0, 100)
    mB = p.modulators.add(); mB.mtype = 'RANDOM'; mB.seed = 2; mB.pos = (0, 0, 100)
    dz_ab = dz().copy()
    mB.enable = False
    dz_a = dz().copy()
    mA.enable = False; mB.enable = True
    dz_b = dz().copy()
    check("スタック: A+B = A単体 + B単体(加算合成)", np.allclose(dz_ab, dz_a + dz_b, atol=1e-5))
    check("スタック: 異なるシードで別パターン", not np.allclose(dz_a, dz_b))
    mA.enable = False; mB.enable = False
    check("ON/OFF: 全無効ならグリッドのまま(変位0)", np.allclose(dz(), 0.0, atol=1e-6))

    # ===== 2: Step モジュレータ = クローン列に沿った勾配 =====
    clear_mods(p)
    ms = p.modulators.add(); ms.mtype = 'STEP'; ms.rot = (0, 0, 90); ms.normalized = True
    rz = rotz()
    check("Step: 先頭(index0)は回転0", abs(rz[I0]) < 1e-5, "rz=%.3f" % rz[I0])
    check("Step: 末尾(index26)は90°=π/2", abs(rz[I26] - math.pi / 2) < 1e-4, "rz=%.3f" % rz[I26])
    check("Step: 中間(index13)は約45°", abs(rz[I13] - math.pi / 4) < 1e-2, "rz=%.3f" % rz[I13])

    # ===== 3: Time モジュレータ = 時間で累積(キーフレーム不要) =====
    clear_mods(p)
    bpy.context.scene.frame_start = 1
    mt = p.modulators.add(); mt.mtype = 'TIME'; mt.rot = (0, 0, 90); mt.speed = 1.0
    bpy.context.scene.frame_set(1)
    rz1 = rotz()
    bpy.context.scene.frame_set(25)            # 24fps → t=1.0 秒
    rz25 = rotz()
    check("Time: frame1 は t=0 で回転0", abs(rz1[I13]) < 1e-5, "rz=%.3f" % rz1[I13])
    check("Time: frame25(1秒)で 90°=π/2", abs(rz25[I13] - math.pi / 2) < 1e-3, "rz=%.3f" % rz25[I13])
    check("Time: 全クローン一様(index0と26が同じ)", abs(rz25[I0] - rz25[I26]) < 1e-5)
    bpy.context.scene.frame_set(1)

    # ===== 4: モジュレータ個別のフィールドゲート =====
    clear_mods(p)
    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.field_type = 'SPHERE'; p.field_radius = 250.0; p.field_falloff = 1.0
    fo.location = (0.0, 0.0, 0.0); bpy.context.view_layer.update()
    m1 = p.modulators.add(); m1.mtype = 'RANDOM'; m1.seed = 1; m1.pos = (0, 0, 100); m1.use_field = True
    m2 = p.modulators.add(); m2.mtype = 'RANDOM'; m2.seed = 5; m2.pos = (0, 0, 100); m2.use_field = False
    dboth = dz().copy()
    check("ゲート: フィールド外でもuse_field=OFFのm2は効く(隅0が変位)", abs(dboth[I0]) > 1e-4,
          "dz=%.3f" % dboth[I0])
    m2.enable = False
    dm1 = dz().copy()
    check("ゲート: use_field=ONのm1は隅0で0(局所化)", abs(dm1[I0]) < 1e-6, "dz=%.3f" % dm1[I0])
    check("ゲート: m1は中心13では効く", abs(dm1[I13]) > 1e-4, "dz=%.3f" % dm1[I13])

    # ===== 5: 旧データの自動移行(単体Random + field_affect=BOTH → スタック) =====
    clear()
    cube2 = mk_cube("cube2")
    e2 = replicator.create_replicator(bpy.context, [cube2])
    p2 = e2.replicator
    p2.random_enable = True
    p2.random_pos = (0.0, 0.0, 50.0)
    p2.random_seed = 7
    p2.field_affect = 'BOTH'
    p2["_stack_migrated"] = 0                   # 移行フラグをリセットして再移行させる
    replicator._migrate_to_stack(p2)
    ok_mod = len(p2.modulators) == 1 and p2.modulators[0].mtype == 'RANDOM'
    check("移行: 単体Random → Randomモジュレータ1個", ok_mod,
          "n=%d" % len(p2.modulators))
    if ok_mod:
        mm = p2.modulators[0]
        check("移行: 位置が引き継がれる(z=50)", abs(mm.pos[2] - 50.0) < 1e-4, "z=%.3f" % mm.pos[2])
        check("移行: シード引き継ぎ(7)", mm.seed == 7)
        check("移行: field_affect=BOTH → use_field ON", mm.use_field is True)
    check("移行: field_affect=BOTH → 段階も step_use_field ON", p2.step_use_field is True)
    check("移行: 旧 random_enable は False に", p2.random_enable is False)

    log("=== RESULT:", "ALL PASS" if PASS else "SOME FAILED", "===")


main()
