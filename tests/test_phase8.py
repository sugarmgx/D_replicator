# -*- coding: utf-8 -*-
# v0.4 テスト2: フィールドの対象3モード(Random/段階/両方)+ 種類(箱/リニア/ノイズ)
# 実行: blender.exe --background --factory-startup --python tests/test_phase8.py
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
    print("[TEST]", *a)
    sys.stdout.flush()


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
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def reset_field(fo):
    fo.location = (0.0, 0.0, 0.0)
    fo.rotation_euler = (0.0, 0.0, 0.0)
    fo.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


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
    p.mode = 'GRID'
    p.count_x = p.count_y = p.count_z = 3
    p.spacing_x = p.spacing_y = p.spacing_z = 200.0   # 各軸 [-2,0,2] m
    pos_grid, _ = replicator.compute_points(p)
    # index = ix*9+iy*3+iz。0=(-2,-2,-2) 2=(-2,-2,2) 13=(0,0,0) 25=(2,2,0) 26=(2,2,2)
    I0, I2, I13, I25, I26 = 0, 2, 13, 25, 26

    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.field_type = 'SPHERE'
    p.field_radius = 250.0
    p.field_falloff = 1.0
    reset_field(fo)

    def Z(i):
        pos, _, _ = replicator.compute_clone_data(p, e)
        return pos[i, 2]

    # ===== A: フィールドが「段階トランスフォーム」に効く(step_use_field) =====
    p.step_pos = (0.0, 0.0, 100.0)     # Z に 1m ステップ(正規化: 端で最大)
    # index26 は ramp=1.0(最後)・grid z=2 → 段階フルなら z=3
    p.step_use_field = False           # 段階にフィールドを効かせない → フル
    check("段階: フィールドOFFなら段階フル(隅26 z≈3)", abs(Z(I26) - 3.0) < 1e-3,
          "z=%.3f" % Z(I26))
    p.step_use_field = True            # 段階を絞る → 隅は重み0で段階が消える
    check("段階: フィールドONで隅26の段階が消える(z≈2)", abs(Z(I26) - 2.0) < 1e-3,
          "z=%.3f" % Z(I26))
    check("段階: 中心13は重み1で段階維持(z≈0.5)", abs(Z(I13) - 0.5) < 1e-2,
          "z=%.3f" % Z(I13))

    # ===== B: 段階 + Random モジュレータ 両方をフィールドで絞る =====
    p.step_use_field = True
    mB = p.modulators.add()
    mB.mtype = 'RANDOM'
    mB.seed = 0
    mB.pos = (0.0, 0.0, 100.0)
    mB.use_field = True
    pos, _, _ = replicator.compute_clone_data(p, e)
    check("両方: 隅26は段階もRandomも消えグリッド維持(z≈2)", abs(pos[I26, 2] - 2.0) < 1e-3,
          "z=%.3f" % pos[I26, 2])
    check("両方: 隅0もグリッド維持(z≈-2)", abs(pos[I0, 2] - (-2.0)) < 1e-3,
          "z=%.3f" % pos[I0, 2])
    check("両方: 中心13は段階+Randomで変位(z≠0)", abs(pos[I13, 2]) > 1e-3,
          "z=%.3f" % pos[I13, 2])

    # 段階/モジュレータをオフに戻して、以降は重みそのものを検証
    p.step_pos = (0.0, 0.0, 0.0)
    p.step_use_field = False
    while len(p.modulators):
        p.modulators.remove(0)

    # ===== C: 箱フィールド(球と違い角・辺も含む) =====
    p.field_type = 'SPHERE'
    p.field_radius = 250.0
    reset_field(fo)
    w_sph = replicator.compute_field_weight(p, e, pos_grid)
    p.field_type = 'BOX'
    reset_field(fo)
    w_box = replicator.compute_field_weight(p, e, pos_grid)
    # 辺クローン (2,2,0)=index25: 球では距離2.83>2.5で0、箱では max|軸|=2<2.5 で>0
    check("箱: 辺(2,2,0)は箱で効くが球では0",
          w_box[I25] > 0.05 and w_sph[I25] == 0.0,
          "box=%.3f sph=%.3f" % (w_box[I25], w_sph[I25]))
    check("箱: 中心は重み1", w_box[I13] > 0.99)
    check("箱: 範囲外(半径100で隅)は0",
          (lambda: (setattr(p, 'field_radius', 100.0),
                    replicator.compute_field_weight(p, e, pos_grid)[I26])[1])() == 0.0)
    p.field_radius = 250.0

    # ===== D: リニアフィールド(+Z 側が強い / 回転で向きが変わる) =====
    p.field_type = 'LINEAR'
    p.field_radius = 400.0            # 長さ4m
    reset_field(fo)
    w_lin = replicator.compute_field_weight(p, e, pos_grid)
    # z=2 のクローン(index2)は g=0.5→効く、z=-2(index0)は0
    check("リニア: +Z側(z=2)が効く", w_lin[I2] > 0.4, "w=%.3f" % w_lin[I2])
    check("リニア: -Z側(z=-2)は0", w_lin[I0] == 0.0, "w=%.3f" % w_lin[I0])
    # 180°回転で向きが反転(ローカル空間評価の確認)
    fo.rotation_euler = (math.pi, 0.0, 0.0)
    bpy.context.view_layer.update()
    w_lin2 = replicator.compute_field_weight(p, e, pos_grid)
    check("リニア: X軸180°回転で上下反転", w_lin2[I0] > 0.4 and w_lin2[I2] == 0.0,
          "z-2=%.3f z+2=%.3f" % (w_lin2[I0], w_lin2[I2]))
    reset_field(fo)

    # ===== E: ノイズフィールド(0..1 で濃淡・決定論的) =====
    p.field_type = 'NOISE'
    p.field_radius = 120.0
    reset_field(fo)
    w_n1 = replicator.compute_field_weight(p, e, pos_grid)
    w_n2 = replicator.compute_field_weight(p, e, pos_grid)
    check("ノイズ: 値域 0..1", w_n1.min() >= 0.0 and w_n1.max() <= 1.0,
          "min=%.3f max=%.3f" % (w_n1.min(), w_n1.max()))
    check("ノイズ: 濃淡がある(一定でない)", w_n1.std() > 1e-3, "std=%.3f" % w_n1.std())
    check("ノイズ: 決定論的(再計算で一致)", np.allclose(w_n1, w_n2))

    # ===== 描画経路: 各種類でインスタンス27個維持 =====
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    cnt = sum(1 for i in deps.object_instances if i.is_instance)
    check("ノイズ種類でもインスタンス27", cnt == 27, "cnt=%d" % cnt)

    log("=== RESULT:", "ALL PASS" if PASS else "SOME FAILED", "===")


main()
