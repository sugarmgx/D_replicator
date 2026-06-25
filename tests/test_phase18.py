# -*- coding: utf-8 -*-
# v0.10 テスト: アドオン内だけの日英切替(Blender 全体の言語は変えない)
# 実行: blender.exe --background --factory-startup --python tests/test_phase18.py
import bpy
import sys
import types
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


def check(name, cond, extra=""):
    log(("PASS" if cond else "FAIL"), "-", name, extra)
    if not cond:
        _fails.append(name)


def mk_cube(name, size=1.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def set_lang(v):
    bpy.context.window_manager.d_replicator_lang = v


# --- パネル draw を GUI 無しで走らせるためのダミー layout ---
class FakeLayout:
    def row(self, *a, **k): return self
    def column(self, *a, **k): return self
    def box(self, *a, **k): return self
    def split(self, *a, **k): return self
    def separator(self, *a, **k): return None
    def label(self, *a, **k): return None
    def template_list(self, *a, **k): return None
    def prop(self, *a, **k): return None
    def operator(self, *a, **k): return types.SimpleNamespace()


def draw_panel(active):
    """実 GUI 無しでパネル draw を実行(描画時エラーを検出)。"""
    bpy.context.view_layer.objects.active = active
    fake = types.SimpleNamespace(layout=FakeLayout())
    replicator.VIEW3D_PT_replicator.draw(fake, bpy.context)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()

    # 既定は日本語
    check("既定 言語=JA", bpy.context.window_manager.d_replicator_lang == 'JA')

    # --- t() の翻訳 ---
    set_lang('EN')
    check("EN: 間隔→Spacing", replicator.t("間隔 (cm)") == "Spacing (cm)", replicator.t("間隔 (cm)"))
    check("EN: モード→Mode", replicator.t("モード") == "Mode")
    check("EN: クローン数→Clones", replicator.t("クローン数") == "Clones")
    check("EN: 辞書に無い語は原文のまま", replicator.t("未登録の語ABC") == "未登録の語ABC")
    set_lang('JA')
    check("JA: 間隔 は原文", replicator.t("間隔 (cm)") == "間隔 (cm)")
    check("JA: モード は原文", replicator.t("モード") == "モード")

    # --- 動的 enum が言語連動 ---
    set_lang('EN')
    mode_items = replicator._mode_items(None, bpy.context)
    names = {idf: nm for (idf, nm, ds) in mode_items}
    check("EN enum: GRID→Grid", names.get('GRID') == "Grid", str(names.get('GRID')))
    check("EN enum: MESH→Mesh", names.get('MESH') == "Mesh")
    msrc = {idf: nm for (idf, nm, ds) in replicator._mesh_src_items(None, bpy.context)}
    check("EN enum: SURFACE→On Surface", msrc.get('SURFACE') == "On Surface (random)")
    set_lang('JA')
    names_ja = {idf: nm for (idf, nm, ds) in replicator._mode_items(None, bpy.context)}
    check("JA enum: GRID→グリッド", names_ja.get('GRID') == "グリッド")

    # --- ★ Blender 全体の言語は変えていない ---
    lang_before = bpy.context.preferences.view.language
    set_lang('EN')
    set_lang('JA')
    set_lang('EN')
    check("Blender 全体の言語は不変", bpy.context.preferences.view.language == lang_before,
          "before=%s after=%s" % (lang_before, bpy.context.preferences.view.language))

    # --- パネル draw のスモーク(全モード × 日英)でエラーが出ない ---
    cube = mk_cube("cube", 1.0)
    refmesh = mk_cube("refmesh", 2.0)
    crv = bpy.data.objects.new("crv", bpy.data.curves.new("crv", 'CURVE'))
    sp = crv.data.splines.new('POLY'); sp.points.add(1)
    sp.points[0].co = (0, 0, 0, 1); sp.points[1].co = (2, 0, 0, 1)
    bpy.context.scene.collection.objects.link(crv)
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mesh_object = refmesh
    p.spline_object = crv
    # モジュレータ + フィールドも出して全 UI 経路を通す
    m = p.modulators.add(); m.mtype = 'RANDOM'; p.modulator_index = 0
    p.field_enable = True
    replicator.ensure_field(e)

    ok = True
    err = ""
    try:
        for lang in ('JA', 'EN'):
            set_lang(lang)
            for mode in ('GRID', 'LINEAR', 'RADIAL', 'CIRCLE', 'MESH', 'SPLINE'):
                p.mode = mode
                if mode == 'MESH':
                    for src in ('VERTS', 'EDGES', 'FACES', 'SURFACE'):
                        p.mesh_source = src
                        draw_panel(e)
                else:
                    draw_panel(e)
            # フィールドギズモ選択中のパネルも
            fo = replicator.get_field(e)
            if fo:
                draw_panel(fo)
    except Exception as ex:
        ok = False
        err = repr(ex)
    check("パネル draw が全モード×日英でエラー無し", ok, err)

    set_lang('JA')
    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
