# -*- coding: utf-8 -*-
# v0.4 テスト: 球フィールド — クローンごとの 0..1 重みで Random を変調
# 実行: blender.exe --background --factory-startup --python tests/test_phase7.py
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
    print("[TEST]", *a)
    sys.stdout.flush()


def check(name, cond):
    global PASS
    PASS = PASS and bool(cond)
    log(("PASS" if cond else "FAIL"), "-", name)


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


def inst_count():
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
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    # グリッド 3x3x3 / 間隔 200cm → 各軸 [-2,0,2] m。index: ix*9+iy*3+iz
    p.mode = 'GRID'
    p.count_x = p.count_y = p.count_z = 3
    p.spacing_x = p.spacing_y = p.spacing_z = 200.0
    # Random モジュレータ(Z 方向のみ・seed 固定・フィールドでゲート)
    m = p.modulators.add()
    m.mtype = 'RANDOM'
    m.name = "R"
    m.seed = 0
    m.pos = (0.0, 0.0, 100.0)   # Z に ±100cm
    m.use_field = True           # フィールドで局所化

    pos_grid, _ = replicator.compute_points(p)
    n = len(pos_grid)
    CENTER, C0, C26 = 13, 0, 26     # (0,0,0) / (-2,-2,-2) / (2,2,2)
    check("グリッド27点", n == 27)
    check("中心 index=13 が原点", np.allclose(pos_grid[CENTER], [0, 0, 0], atol=1e-4))
    check("隅 index=0,26 が対角", np.allclose(pos_grid[C0], [-2, -2, -2], atol=1e-4)
          and np.allclose(pos_grid[C26], [2, 2, 2], atol=1e-4))

    def dz():
        pos, _, _ = replicator.compute_clone_data(p, e)
        return pos[:, 2] - pos_grid[:, 2]      # Z の変位 = randZ * weight

    # --- フィールド無し: 全クローンが変位 ---
    moved0 = np.count_nonzero(np.abs(dz()) > 1e-4)
    check("フィールド無しで全27変位", moved0 == 27)

    # --- 球フィールド追加(中心・半径250cm・滑らか減衰) ---
    fo = replicator.ensure_field(e)
    p.field_enable = True              # 実フローでは追加ボタンが立てる
    p.field_type = 'SPHERE'
    p.field_radius = 250.0
    p.field_falloff = 1.0
    p.field_invert = False
    fo.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    w = replicator.compute_field_weight(p, e, pos_grid)
    check("中心の重み≈1", w[CENTER] > 0.9)
    check("隅の重み=0", w[C0] == 0.0 and w[C26] == 0.0)

    d = dz()
    moved1 = np.count_nonzero(np.abs(d) > 1e-4)
    check("フィールドで変位が局所化(0<count<27)", 0 < moved1 < 27)
    check("隅は変位しない(weight0)", abs(d[C0]) < 1e-6 and abs(d[C26]) < 1e-6)
    check("中心付近は変位する", np.abs(d[CENTER]) > 1e-4)

    # --- フィールドを遠くへ → 影響ゼロ ---
    fo.location = (100.0, 100.0, 100.0)
    bpy.context.view_layer.update()
    moved2 = np.count_nonzero(np.abs(dz()) > 1e-4)
    check("遠方フィールドで変位ゼロ", moved2 == 0)

    # --- 反転: 隅が効いて中心が効かない ---
    fo.location = (0.0, 0.0, 0.0)
    p.field_invert = True
    bpy.context.view_layer.update()
    wi = replicator.compute_field_weight(p, e, pos_grid)
    check("反転で中心の重み0", wi[CENTER] < 0.1)
    check("反転で隅の重み1", wi[C0] == 1.0 and wi[C26] == 1.0)
    di = dz()
    check("反転で隅が変位", abs(di[C0]) > 1e-4 and abs(di[C26]) > 1e-4)
    p.field_invert = False

    # --- ライブ再計算: フィールド移動 → 表示メッシュが実際に更新される ---
    fo.location = (2.0, 2.0, 2.0)      # 隅(index26)へ寄せる
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)     # depsgraph ハンドラが行う処理を直呼び
    disp = replicator.get_display(e)
    coz = np.array([v.co.z for v in disp.data.vertices])
    moved_idx = set(np.where(np.abs(coz - pos_grid[:, 2]) > 1e-4)[0].tolist())
    check("移動後 隅26が変位集合に入る", C26 in moved_idx)
    check("移動後 反対隅0は変位しない", C0 not in moved_idx)

    # --- レンダリング経路: フィールド有効でもインスタンス27個 ---
    check("インスタンス数27(描画経路維持)", inst_count() == 27)

    # --- 複製元一覧にフィールドが混ざらない ---
    srcs = [c for c in e.children if not c.get(replicator.DISPLAY_TAG)
            and not c.get(replicator.FIELD_TAG)]
    check("複製元一覧にフィールド混入なし(=1)", len(srcs) == 1)

    log("=== RESULT:", "ALL PASS" if PASS else "SOME FAILED", "===")


main()
