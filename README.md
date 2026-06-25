# D_Replicator

Cinema 4D MoGraph 風の**非破壊クローン**アドオン for Blender 5.1 — by **D_plugins**.
A Cinema 4D MoGraph–style **non‑destructive cloner** add‑on for Blender 5.1.

「Python 駆動インスタンシング」方式: numpy で全クローンの変換を毎フレーム計算し、極小の
Geometry Nodes(表示専用)へ一括投入します。実オブジェクトを量産しないので軽量です。

> Site: https://sgnl88.com/ ・ License: **GNU GPL v3 or later**

---

## 主な機能 / Features

- **配置モード**: グリッド / リニア / 放射 / 円形 / **メッシュ**(頂点・辺・面の中心・面上ランダム散布)/ **スプライン**
- **入れ子(Cloner in Cloner)** — 非破壊
- **複数複製元の分配**(ランダム割当・ダイス)。複製元に**メッシュ / ライト / 別の Replicator** を使用可
  (ライトは GN インスタンスとして実際に照らす — EEVEE Next / Cycles)
- **内蔵 段階トランスフォーム**(複製ごとに P/S/R を加算)
- **モジュレータ・スタック**(Random / Step / Time)
- **フィールド**(球 / 箱 / リニア / ノイズ)で効果を範囲で絞る・ライブドラッグ
- **ほぼ全パラメータのキーフレーム**(間隔・半径・散布率・段階・モジュレータ・フィールド…)
- **日本語 / 英語 切り替え**(このパネルだけ。Blender 全体の言語は変えない)
- 数のセーフティ上限(既定100、解除で1000)

---

## 動作環境 / Requirements

- **Blender 5.1**(開発・検証は 5.1.2)。拡張機能の最低要件は 4.2。
- 追加依存なし(numpy は Blender に同梱)。

## インストール / Install

1. [**Releases**](https://github.com/sugarmgx/D_replicator/releases) から最新の
   **`D_Replicator-<version>.zip`** をダウンロード / Download the latest zip from **Releases**.
2. Blender で `編集 > プリファレンス > 入手(Get Extensions)`
3. 右上 `▼` > **ディスクからインストール…** > ダウンロードした zip を選択
4. 一覧の **D_Replicator** を有効化
5. パネルは `3Dビューポート > サイドバー(N) > Replicator` タブ

> 旧バージョンからの更新でエラーが出たら: 古い D_Replicator を削除 → Blender 再起動 → zip を入れ直し。

## ソースからビルド / Build from source

`src/replicator.py` が唯一の実装です。配布 zip は以下で再生成します:

```powershell
pwsh -File build_extension.ps1   # extension/blender_manifest.toml の version を上げてから
```

`build_extension.ps1` が `src/replicator.py` を `extension/D_Replicator.py` にコピーし、
Blender 公式ツールで `D_Replicator-<ver>.zip` を作ります
(`extension/D_Replicator.py` は生成物のため Git では追跡しません)。

開発中はテキストエディタで `src/replicator.py` を開き **Alt+P** が最速です。

## テスト / Tests

ヘッドレスの自己検証スクリプト(`tests/`):

```
"<Blender>\blender.exe" --background --factory-startup --python tests\test_phase1.py
```

`tests/render_*.py` は機能の見た目を確認する PNG を `bench/` に出力します(Git では追跡しません)。

---

## 構成 / Layout

```
src/replicator.py      … 本体(唯一の実装)
extension/             … 配布パッケージ(__init__.py シム + manifest + LICENSE)
build_extension.ps1    … 配布 zip のビルド
tests/                 … ヘッドレス検証 + render_*.py
```

## ライセンス / License

**GNU General Public License v3.0 or later** (`SPDX:GPL-3.0-or-later`)。
Blender アドオンは `bpy` を利用するため GPL 互換が必須です。販売は可能ですが、
購入者にソースが渡り再配布も妨げられません。全文は [`LICENSE`](LICENSE) を参照。

Copyright (C) 2026 D_plugins.
