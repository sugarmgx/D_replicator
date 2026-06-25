# -*- coding: utf-8 -*-
# 開発ループ検証: テキストエディタ Alt+P の連打(register 連続実行)で
# ハンドラ二重化・登録エラーが起きないことを確認する。
# 実行: blender.exe --background --factory-startup --python tests/test_reload.py
import bpy
import sys
import bmesh

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


def count_handler(handlers, name):
    return sum(1 for h in handlers if getattr(h, "__name__", "") == name)


def mk_cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def main():
    # Alt+P を3回連打した状況(register をそのまま3回。reload も挟む)
    for i in range(3):
        importlib.reload(replicator)
        replicator.register()       # __main__ と同じく register() だけ
        log("register pass", i + 1, "done")

    fcp = count_handler(bpy.app.handlers.frame_change_post, "_frame_handler")
    dgp = count_handler(bpy.app.handlers.depsgraph_update_post, "_depsgraph_handler")
    ldp = count_handler(bpy.app.handlers.load_post, "_load_handler")
    check("frame_change ハンドラは1個だけ(二重化なし)", fcp == 1, "count=%d" % fcp)
    check("depsgraph ハンドラは1個だけ", dgp == 1, "count=%d" % dgp)
    check("load ハンドラは1個だけ", ldp == 1, "count=%d" % ldp)

    # 連打後もちゃんと機能する
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    cnt = sum(1 for inst in deps.object_instances if inst.is_instance)
    check("連打後も生成が機能(27インスタンス)", cnt == 27, "cnt=%d" % cnt)

    # unregister 後はハンドラが0個
    replicator.unregister()
    fcp2 = count_handler(bpy.app.handlers.frame_change_post, "_frame_handler")
    check("unregister でハンドラが消える", fcp2 == 0, "count=%d" % fcp2)

    # 拡張機能のチェックON/OFF再有効化(reload無しで register/unregister 連続)。
    # PropertyGroup が bpy.types に名前で出ない件で以前 'already registered' になった回帰。
    toggle_ok = True
    for i in range(5):
        try:
            replicator.register()
            replicator.unregister()
        except Exception as ex:
            toggle_ok = False
            log("toggle cycle", i, "ERROR:", repr(ex)[:80])
            break
    check("拡張のON/OFF再有効化×5でエラー無し(register/unregister 連続)", toggle_ok)
    # 最後に有効化しておく(後続で使えるよう)
    replicator.register()
    check("再有効化後も RM/RP が登録される",
          replicator.ReplicatorModulator.is_registered and replicator.ReplicatorProps.is_registered)

    log("=== RESULT:", "ALL PASS" if PASS else "SOME FAILED", "===")


main()
