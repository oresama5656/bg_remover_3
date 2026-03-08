ここは削除して利用する。
GeminiのGEMを生成するカスタム指示用プロンプトなので普段は使用しない

---

# bg_remover_3 (イラスト特化・高品質背景透過ツール)

AI（rembg / isnet-anime）と画像処理（OpenCV）を組み合わせた、イラスト特化の高品質な背景透過バッチツールです。

## 🌟 特徴

本ツールは**「ハイブリッド方式（AI抽出 ＋ 色指定抽出）」**を採用しています。
単純なAI処理では消えてしまう**「文字」や「装飾」を維持**しつつ、AIの力で**「キャラクター本体の中抜け（白目や服の透過）」を完全に防止**します。

1. **AIモデル (isnet-anime) による被写体抽出**: アニメ・イラストの細い線や髪の毛を綺麗に境界認識し、中抜けのないマスクを生成。
2. **色ベース透過 (クロマキー) による情報補完**: 指定した単色背景以外（文字やエフェクトなど）を抽出し、AIマスクと合成。

## ⚙️ 環境構築

Python 3.x が必要です。

```bash
# クローン後にプロジェクトフォルダへ移動
cd bg_remover_3

# 仮想環境の作成（推奨）と依存パッケージのインストール
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Mac/Linux

pip install -r requirements.txt
```

## 🚀 使い方

### 1. ハイブリッド方式（推奨: 文字や装飾があるイラスト向け）

画像生成AIなどで作成した**「単色背景（白、黒、グリーンバックなど）」**の画像に対して最適です。`-c` または `--color-key` オプションで背景色を指定します。

```bash
# 背景色を【自動検出】して透過させる場合（最もおすすめ！）
python bg_remover.py -i input.png -c auto

# 手動で色を指定する場合（白文字以外のキャラ・文字が綺麗に残ります）
python bg_remover.py -i input.png -c white

# RGB値で直接指定する場合
python bg_remover.py -i input.png -c 255,255,255

# フォルダ内を一括処理（背景色は画像ごとに自動検出されます）
python bg_remover.py -i ./input_folder -c auto -o ./output_folder
```

### 2. AI専用方式（背景が複雑な場合や、キャラだけを抜きたい場合）

`-c` オプションを外すと、従来の AI (isnet-anime) のみを使った被写体の抽出（手前のメインキャラだけを残す処理）を行います。

```bash
# 単一画像処理
python bg_remover.py -i input.png

# Alpha_matting（キャラのフチ削り）はデフォルトで有効化されています。無効化する場合：
python bg_remover.py -i input.png --no-alpha-matting
```

## 💡 画像生成時のベストプラクティス（生成AI向け）

このツールで綺麗に透過するための、画像生成AI（Midjourney, DALL-E, などのプロンプト）のコツです。

1. **🏆 第1位: 「非常識な単色背景（グリーンバック等）」**
   - 推奨プロンプト例: `green solid background`
   - コマンド: `python bg_remover.py -i image.png -c green`
   - 理由: イラスト内の色（キャラの服の白や肌色）と100%被らない色を指定できるため、クロマキー透過による誤認（キャラのハイライト部分が透ける現象）のリスクがゼロになります。

2. **🥈 第2位: 「純粋な白 または 黒の単色背景」**
   - 推奨プロンプト例: `white solid background`
   - コマンド: `python bg_remover.py -i image.png -c white`
   - 理由: LINEスタンプ等で最も使いやすい標準的な生成方法。もしイラストの「真っ白なハイライト部分」が少し透けてしまう場合は、`--color-tolerance` をデフォルトの `15` から小さな値（例: `5` や `0`）に下げて調整してください。

3. **❌ 避けるべき背景: 「パネル柄（市松模様）」「グラデーション画像」「複雑な風景風景」**
   - 理由: 色指定による透過（`-c`オプション）が正常に機能しません。単色背景を指定して生成することを強く推奨します。

## 🛠 詳細オプションパラメータ

| オプション | 短縮 | 説明 | デフォルト値 |
|:---|:---|:---|:---|
| `--input` | `-i` | 入力画像ファイル、またはフォルダのパス。 (必須) | - |
| `--output` | `-o` | 透過画像の保存先フォルダ。 | `output` |
| `--color-key` | `-c` | 単色背景透過の色指定（white, black, R,G,B等）。ハイブリッド方式が有効になります。 | `None` |
| `--color-tolerance` | | `-c` 指定時の許容誤差（0〜255）。値を下げると厳密な色のみ消します。 | `15` |
| `--color-erode` | | 【文字側のフチ除去】`-c` 指定時の緑のフチ残りを侵食・削除するサイズ。 | `2` |
| `--no-alpha-matting` | | 【キャラ側のフチ除去無効化】Alpha matting（キャラのフチ削り）を無効化します。 | `False (デフォは有効)` |
| `--erode-size` | | Alpha matting のキャラ側侵食サイズ調整。 | `10` |
| `--fg-threshold` | | Alpha matting の前景しきい値。 | `240` |
| `--bg-threshold` | | Alpha matting の背景しきい値。 | `10` |
| `--no-fill-holes` | | AIマスク使用時の中抜け防止処理（自動穴埋め）を無効化します。 | `False` |