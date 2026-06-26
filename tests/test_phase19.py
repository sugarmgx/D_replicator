# -*- coding: utf-8 -*-
# v0.11 テスト: 8新機能
#   ① Time ランダム / ② 個別に展開 / ③ 入れ子の解除 / ④ フィールド減衰カーブ /
#   ⑤ 複製元の位置ロック / ⑥ 非表示時の選択でエラーが出ない / ⑦ 規則的分配 / ⑧ 本体の緑表示
# 実行: blender.exe --background --factory-startup --python tests/test_phase19.py
import bpy
import sys
import types
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
    for ng in list(bpy.data.node_groups):
        if ng.name.startswith(replicator.FALLOFF_NG_PREFIX):
            bpy.data.node_groups.remove(ng)


def mk_cube(name, size=1.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


# ---------------------------------------------------------------- ① Time ランダム
def test_time_random():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mode = 'LINEAR'
    p.count_x = 12
    bpy.context.scene.frame_set(10)            # t_sec != 0 にする
    m = p.modulators.add()
    m.mtype = 'TIME'
    m.rot = (0.0, 0.0, 90.0)
    m.speed = 1.0
    m.seed = 1
    m.time_random = 0.0
    _, rot0, _ = replicator.compute_clone_data(p, e)
    std0 = float(np.std(rot0[:, 2]))
    check("Time random=0 は全クローン一様(Z回転の分散≈0)", std0 < 1e-6, "std=%.6f" % std0)

    m.time_random = 0.6
    _, rotA, _ = replicator.compute_clone_data(p, e)
    stdA = float(np.std(rotA[:, 2]))
    check("Time random=0.6 でクローンごとにばらつく(分散>0)", stdA > 1e-4, "std=%.5f" % stdA)

    _, rotB, _ = replicator.compute_clone_data(p, e)  # 同条件で再計算
    check("Time random は決定論的(同seed→同結果)",
          np.allclose(rotA, rotB), "max diff=%.6f" % float(np.max(np.abs(rotA - rotB))))


# ---------------------------------------------------------------- ⑦ 規則的分配(Iterate)
def test_iterate_distribution():
    clear()
    A, B, C = mk_cube("A"), mk_cube("B"), mk_cube("C")
    e = replicator.create_replicator(bpy.context, [A, B, C])
    p = e.replicator                          # 既定 GRID 3x3x3 = 27
    p.dist_mode = 'ITERATE'
    disp = replicator.get_display(e)
    idx = np.array([d.value for d in disp.data.attributes["rep_index"].data])
    expect = np.arange(len(idx)) % 3
    check("ITERATE: index が 0,1,2,0,1,2,...(規則的)",
          len(idx) == 27 and np.array_equal(idx, expect), str(idx[:6]) + "...")
    # ランダムに戻すと別配置(規則的ではない)
    p.dist_mode = 'RANDOM'
    p.dist_seed = 5
    idx2 = np.array([d.value for d in disp.data.attributes["rep_index"].data])
    check("RANDOM に戻すと規則列と一致しない", not np.array_equal(idx2, expect))


# ---------------------------------------------------------------- ② 個別に展開
def test_expand():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])   # GRID 27
    bpy.context.view_layer.objects.active = e
    e.select_set(True)
    bpy.context.view_layer.update()
    res = bpy.ops.object.replicator_expand()
    col = bpy.data.collections.get(e.name + "_Expanded")
    n = len(col.objects) if col else 0
    check("展開: 27個の実オブジェクトを書き出す", res == {'FINISHED'} and n == 27, "n=%d" % n)
    if col and col.objects:
        ob0 = col.objects[0]
        check("展開: データは複製(元メッシュと共有しない)",
              ob0.data is not None and ob0.data is not cube.data and ob0.type == 'MESH')
        check("展開: 親なし・位置ロック無しで個別編集できる",
              ob0.parent is None and tuple(ob0.lock_location) == (False, False, False))
    check("展開: 元 Replicator は残る(非破壊)", replicator.is_replicator_empty(e))


# ---------------------------------------------------------------- ③ 最上位を解除(本体削除・構造維持)
def _inst_count_for(disp):
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return sum(1 for i in deps.object_instances
               if i.is_instance and i.parent and i.parent.original is disp)


def test_dissolve():
    clear()
    cube = mk_cube("cube")
    inner = replicator.create_replicator(bpy.context, [cube])
    outer = replicator.create_replicator(bpy.context, [inner])
    inner_name, outer_name = inner.name, outer.name
    inner_disp_name = replicator.get_display(inner).name

    bpy.context.view_layer.objects.active = inner   # 内側(子)では poll が通らない
    check("dissolve: 内側 Replicator では出ない(最上位のみ)",
          not replicator.OBJECT_OT_replicator_dissolve.poll(bpy.context))
    bpy.context.view_layer.objects.active = outer   # 最上位では poll が通る
    check("dissolve: 最上位 Replicator で出る",
          replicator.OBJECT_OT_replicator_dissolve.poll(bpy.context))

    res = bpy.ops.object.replicator_dissolve()
    check("dissolve: 実行成功", res == {'FINISHED'}, str(res))
    check("dissolve: 最上位 outer が削除された", outer_name not in bpy.data.objects)
    surv = bpy.data.objects.get(inner_name)
    check("dissolve: inner は独立 Replicator として残る",
          surv is not None and replicator.is_replicator_empty(surv) and surv.parent is None)
    check("dissolve: inner の構造(クローン27個)が独立で維持される",
          inner_disp_name in bpy.data.objects
          and _inst_count_for(bpy.data.objects[inner_disp_name]) == 27,
          "n=%d" % (_inst_count_for(bpy.data.objects[inner_disp_name])
                    if inner_disp_name in bpy.data.objects else -1))


# ---------------------------------------------------------------- 複製元の並べ替え=複製順
def test_source_reorder():
    clear()
    A, B, C = mk_cube("A"), mk_cube("B"), mk_cube("C")
    e = replicator.create_replicator(bpy.context, [A, B, C])
    p = e.replicator
    p.mode = 'LINEAR'
    p.count_x = 3
    p.dist_mode = 'ITERATE'
    disp = replicator.get_display(e)

    def mapping():
        deps = bpy.context.evaluated_depsgraph_get()
        deps.update()
        return {round(i.matrix_world.translation.x, 2): i.object.name
                for i in deps.object_instances
                if i.is_instance and i.parent and i.parent.original is disp}

    order0 = [it.name for it in p.source_order]
    m0 = mapping()
    check("reorder: ITERATE は source_order の順に割り当て(既定)",
          m0.get(0.0) == order0[0] and m0.get(2.0) == order0[1] and m0.get(4.0) == order0[2],
          "order=%s map=%s" % (order0, m0))
    # 先頭を末尾へ(2回 DOWN)
    first = order0[0]
    bpy.context.view_layer.objects.active = e
    bpy.ops.object.replicator_source_move(name=first, direction='DOWN')
    bpy.ops.object.replicator_source_move(name=first, direction='DOWN')
    order1 = [it.name for it in p.source_order]
    check("reorder: 並べ替えで先頭が末尾へ", order1[-1] == first and order1 != order0, str(order1))
    m1 = mapping()
    check("reorder: 割り当て順が並びに追従",
          m1.get(0.0) == order1[0] and m1.get(2.0) == order1[1] and m1.get(4.0) == order1[2],
          "order=%s map=%s" % (order1, m1))


# ---------------------------------------------------------------- ④ フィールド減衰カーブ
def test_field_curve():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.field_enable = True
    replicator.ensure_field(e)
    p.field_type = 'SPHERE'
    p.field_radius = 100.0                       # 1m
    pos = np.array([[0.0, 0.0, 0.0],             # 芯(内)
                    [10.0, 0.0, 0.0]], dtype=np.float32)  # 10m 先(外)
    w0 = replicator.compute_field_weight(p, e, pos)
    check("カーブOFF: 芯≈1 / 外≈0(従来の減衰)",
          w0[0] > 0.9 and w0[1] < 0.1, "w=%s" % np.round(w0, 3))

    p.field_use_curve = True
    node = replicator._falloff_curve_node(p, create=True)
    check("カーブON: 減衰カーブのノードグループが作られる",
          node is not None and p.falloff_curve_ng != ""
          and bpy.data.node_groups.get(p.falloff_curve_ng) is not None)
    # カーブを全域 1 に平坦化 → どこでも全効き
    cv = node.mapping.curves[0]
    cv.points[0].location = (0.0, 1.0)
    cv.points[1].location = (1.0, 1.0)
    node.mapping.update()
    w1 = replicator.compute_field_weight(p, e, pos)
    check("カーブで再マップが効く(平坦化→外でも≈1)",
          w1[0] > 0.9 and w1[1] > 0.9, "w=%s" % np.round(w1, 3))
    # 全域 0 に → どこでも効かない
    cv.points[0].location = (0.0, 0.0)
    cv.points[1].location = (1.0, 0.0)
    node.mapping.update()
    w2 = replicator.compute_field_weight(p, e, pos)
    check("カーブ平坦化0→どこでも≈0", w2[0] < 0.1 and w2[1] < 0.1, "w=%s" % np.round(w2, 3))


# ---------------------------------------------------------------- ⑤ 複製元の位置ロック(常時)
def test_source_lock():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.show_sources = True                        # 表示 ON で位置が常にロック
    check("表示ON: 複製元の位置は常にロック", tuple(cube.lock_location) == (True, True, True),
          str(tuple(cube.lock_location)))
    # Replicator_Display を選択するオペレータ(全体の位置編集の入口)
    bpy.context.view_layer.objects.active = e
    res = bpy.ops.object.replicator_select_display()
    disp = replicator.get_display(e)
    check("Replicator_Display を選択できる(全体移動の入口)",
          res == {'FINISHED'} and bpy.context.view_layer.objects.active is disp, str(res))


# ---------------------------------------------------------------- ⑥ 非表示時の選択でエラー無し
def test_select_hidden_source():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.show_sources = False                       # 非表示 = ビューレイヤー非所属
    in_vl_before = cube.name in bpy.context.view_layer.objects
    bpy.context.view_layer.objects.active = e
    ok = True
    err = ""
    try:
        res = bpy.ops.object.replicator_select_source(name=cube.name)
    except Exception as ex:                       # ← 旧バグはここで例外
        ok = False
        err = repr(ex)
    check("非表示の複製元を選択してもエラーが出ない", ok, err)
    if ok:
        check("選択で複製元が取り込まれてアクティブになる",
              cube.name in bpy.context.view_layer.objects
              and bpy.context.view_layer.objects.active is cube,
              "in_vl_before=%s" % in_vl_before)


# ---------------------------------------------------------------- ⑧ 本体の緑表示
def test_green():
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    col = tuple(round(c, 2) for c in e.color)
    check("本体カラーが緑", col == tuple(round(c, 2) for c in replicator.REP_GREEN), str(col))
    check("本体名を表示", e.show_name is True)


# ---------------------------------------------------------------- パネル draw スモーク(新UI)
class FakeLayout:
    def row(self, *a, **k): return self
    def column(self, *a, **k): return self
    def box(self, *a, **k): return self
    def split(self, *a, **k): return self
    def separator(self, *a, **k): return None
    def label(self, *a, **k): return None
    def template_list(self, *a, **k): return None
    def template_curve_mapping(self, *a, **k): return None
    def prop(self, *a, **k): return None
    def operator(self, *a, **k): return types.SimpleNamespace()


def test_panel_smoke():
    clear()
    cube, refmesh = mk_cube("cube"), mk_cube("refmesh", 2.0)
    inner = replicator.create_replicator(bpy.context, [cube])
    e = replicator.create_replicator(bpy.context, [mk_cube("c2"), inner])  # 複数 + 入れ子
    p = e.replicator
    p.show_sources = True
    p.dist_mode = 'ITERATE'
    mm = p.modulators.add(); mm.mtype = 'TIME'; mm.time_random = 0.5; p.modulator_index = 0
    p.field_enable = True
    replicator.ensure_field(e)
    p.field_use_curve = True                     # カーブ UI も通す
    ok = True
    err = ""
    try:
        for lang in ('JA', 'EN'):
            bpy.context.window_manager.d_replicator_lang = lang
            fake = types.SimpleNamespace(layout=FakeLayout())
            bpy.context.view_layer.objects.active = e
            replicator.VIEW3D_PT_replicator.draw(fake, bpy.context)
    except Exception as ex:
        ok = False
        err = repr(ex)
    bpy.context.window_manager.d_replicator_lang = 'JA'
    check("新UI込みのパネル draw が日英でエラー無し", ok, err)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    test_time_random()
    test_iterate_distribution()
    test_source_reorder()
    test_expand()
    test_dissolve()
    test_field_curve()
    test_source_lock()
    test_select_hidden_source()
    test_green()
    test_panel_smoke()
    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
