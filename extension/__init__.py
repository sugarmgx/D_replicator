# -*- coding: utf-8 -*-
# D_Replicator (by D_plugins) — Blender 拡張機能のエントリ。
# 実体は D_Replicator.py。ここは register/unregister を委譲する薄いシム。
# License: GNU GPL v3 or later (see LICENSE).
from . import D_Replicator


def register():
    D_Replicator.register()


def unregister():
    D_Replicator.unregister()
