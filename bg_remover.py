"""
背景透過ツール（イラスト特化・軽量版）
rembg + isnet-anime モデルによるイラスト画像の高品質背景除去

使い方:
  # 単一画像の処理
  python bg_remover.py -i image.png

  # フォルダ一括処理
  python bg_remover.py -i ./input_folder -o ./output_folder

  # alpha matting を有効にして処理
  python bg_remover.py -i image.png --alpha-matting

  # パラメータ調整
  python bg_remover.py -i image.png --alpha-matting --erode-size 15 --fg-threshold 230 --bg-threshold 20

  # 手動で色を指定する場合
  python bg_remover.py -i ryoukai.png -c white
  python bg_remover.py -i ryoukai.png -c 255,255,255  # RGB直接指定

  # 【New!】背景色を自動で認識させる場合
  # -c auto を指定すると、画像の四隅などから背景のRGB値を自動計算して透過します。
  python bg_remover.py -i testyou.png -c auto
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rembg import remove, new_session
from scipy.ndimage import binary_fill_holes


# 対応する画像拡張子
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def parse_args():
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="イラスト画像の背景透過ツール（isnet-anime モデル使用）"
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="入力画像ファイル or フォルダのパス",
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="出力先フォルダ（デフォルト: output）",
    )
    parser.add_argument(
        "-c", "--color-key",
        default=None,
        help="単色背景透過の色指定（例: auto, white, black, または 255,255,255）。"
             "これを指定すると【AI抽出＋色抽出のハイブリッド方式】で動作します。"
             "'auto' を指定すると背景色を自動で認識します。",
    )
    parser.add_argument(
        "--color-tolerance",
        type=int,
        default=15,
        help="色ベース透過の際の許容誤差（デフォルト: 15）",
    )
    parser.add_argument(
        "--color-erode",
        type=int,
        default=2,
        help="【文字側のフチ除去】色指定マスクを削るサイズ。緑のフチ残りを消すのに有効（例: 2 や 3。デフォルト: 2）",
    )
    # キャラ側のAlpha Mattingはデフォルトで真にするため、無効化オプションを用意
    parser.add_argument(
        "--no-alpha-matting",
        action="store_false",
        dest="alpha_matting",
        default=True,
        help="【キャラ側のフチ除去無効化】Alpha mattingを無効化します（デフォルトでは常に有効）",
    )
    # 後方互換性と明示的な指定のため
    parser.add_argument(
        "--alpha-matting",
        action="store_true",
        dest="alpha_matting",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--erode-size",
        type=int,
        default=10,
        help="alpha_matting_erode_structure_size（デフォルト: 10）",
    )
    parser.add_argument(
        "--fg-threshold",
        type=int,
        default=240,
        help="alpha_matting_foreground_threshold（デフォルト: 240）",
    )
    parser.add_argument(
        "--bg-threshold",
        type=int,
        default=10,
        help="alpha_matting_background_threshold（デフォルト: 10）",
    )
    parser.add_argument(
        "--no-fill-holes",
        action="store_true",
        default=False,
        help="中抜け防止処理を無効化する",
    )
    return parser.parse_args()


def parse_color(color_str: str) -> tuple[int, int, int] | str:
    """色文字列をRGBタプル、または 'auto' に変換する"""
    color_str = color_str.lower().strip()
    
    if color_str == "auto":
        return "auto"

    color_map = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "yellow": (255, 255, 0),
        "magenta": (255, 0, 255),
        "cyan": (0, 255, 255),
    }

    if color_str in color_map:
        return color_map[color_str]

    try:
        # "255,255,255" のようなカンマ区切り形式のパース
        parts = [int(x.strip()) for x in color_str.split(",")]
        if len(parts) == 3 and all(0 <= x <= 255 for x in parts):
            return tuple(parts)
    except Exception:
        pass

    raise ValueError(f"無効な色指定です: {color_str}")


def process_hybrid(
    img: Image.Image,
    session,
    target_color: tuple[int, int, int] | str,
    tolerance: int,
    color_erode: int,
    alpha_matting: bool,
    erode_size: int,
    fg_threshold: int,
    bg_threshold: int,
    do_fill_holes: bool
) -> Image.Image:
    """
    【AIマスク】と【色指定マスク】のハイブリッド合成を行う
    """
    img_rgba = img.convert("RGBA")
    img_rgb = np.array(img.convert("RGB"))
    
    if target_color == "auto":
        # 画像のフチ周辺（外周10ピクセル）から、最も多く使われている背景色（最頻値）を自動認識
        h, w = img_rgb.shape[:2]
        mask = np.ones((h, w), dtype=bool)
        if h > 20 and w > 20: # 小さすぎる画像への対策
            mask[10:h-10, 10:w-10] = False
        
        border_pixels = img_rgb[mask]
        
        # RGB値を1Dの一意な整数に変換して最頻値を取得 (R*65536 + G*256 + B)
        pixels_1d = border_pixels[:, 0].astype(np.int64) * 65536 + \
                    border_pixels[:, 1].astype(np.int64) * 256 + \
                    border_pixels[:, 2].astype(np.int64)
                    
        # np.bincountの長さを防ぐため、np.uniqueを使用するか、外周なら多少遅くてもよいが
        # bincountは高速なので最大16777215までメモリを少し使うが高速
        counts = np.bincount(pixels_1d)
        mode_idx = int(np.argmax(counts))
        
        target_color = (mode_idx // 65536, (mode_idx // 256) % 256, mode_idx % 256)
        # （※コマンドラインに毎回出力するとログが流れるため、自動取得したことを裏で使います）

    # 1. AIマスクの生成
    ai_result = remove(
        img_rgba,
        session=session,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=fg_threshold,
        alpha_matting_background_threshold=bg_threshold,
        alpha_matting_erode_structure_size=erode_size,
    )
    
    if do_fill_holes:
        ai_result = fill_holes(ai_result)
        
    ai_mask = np.array(ai_result)[:, :, 3]

    # 2. 色指定マスクの生成
    lower_bound = np.array([max(0, c - tolerance) for c in target_color], dtype=np.uint8)
    upper_bound = np.array([min(255, c + tolerance) for c in target_color], dtype=np.uint8)
    
    # 指定背景色部分が255になるマスク
    bg_color_mask = cv2.inRange(img_rgb, lower_bound, upper_bound)
    
    # 反転させて、文字やキャラ部分が255になるようにする
    fg_color_mask = cv2.bitwise_not(bg_color_mask)
    
    # フチ除去処理: 色ベースマスク（文字など）の境界を削る
    if color_erode > 0:
        kernel = np.ones((color_erode, color_erode), np.uint8)
        fg_color_mask = cv2.erode(fg_color_mask, kernel, iterations=1)
        
        # 削った境界を滑らかにぼかす（ジャギー防止）
        blur_size = color_erode * 2 + 1
        fg_color_mask = cv2.GaussianBlur(fg_color_mask, (blur_size, blur_size), 0)
        
        # Guided Filter によるエッジの復元と整え（元のRGB画像をガイドにする）
        try:
            # ガイド画像はグレースケールまたはカラーだが、cv2.ximgproc.createGuidedFilter は
            # ガイドとしてcv2.CV_8U または cv2.CV_32Fを要求する。今回は処理しやすいようにグレー化。
            guide = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
            # ximgproc は opencv-contrib-python が必要
            guided_filter = cv2.ximgproc.createGuidedFilter(guide=guide, radius=color_erode * 2, eps=100)
            fg_color_mask = guided_filter.filter(fg_color_mask)
        except AttributeError:
            # opencv-contrib-python が入っていない場合のフォールバック（ぼかしのみ）
            pass

    # 3. マスクの合成 (np.maximum を用いたアルファ値の保持)
    # bitwise_or では0か255の2値になってしまうため、ピクセルごとの強い方のアルファ値を採用する
    combined_mask = np.maximum(ai_mask, fg_color_mask)
    
    # 4. 最終処理
    final_arr = np.array(img_rgba)
    final_arr[:, :, 3] = combined_mask
    
    return Image.fromarray(final_arr)


def fill_holes(image: Image.Image) -> Image.Image:
    """
    中抜け防止処理
    アルファチャンネルの穴（被写体内部の意図しない透過部分）を塞ぐ
    """
    img_array = np.array(image)

    if img_array.shape[2] != 4:
        return image

    alpha = img_array[:, :, 3]

    # アルファ値が0より大きいピクセルをマスクとして使う
    mask = alpha > 0

    # binary_fill_holes で穴を埋める
    filled_mask = binary_fill_holes(mask)

    # 穴が埋まった部分（元が透明だったが内部と判定された部分）のアルファ値を255にする
    holes = filled_mask & ~mask
    img_array[holes, 3] = 255

    return Image.fromarray(img_array)


def process_image(
    input_path: Path,
    output_path: Path,
    session,
    alpha_matting: bool = False,
    erode_size: int = 10,
    fg_threshold: int = 240,
    bg_threshold: int = 10,
    do_fill_holes: bool = True,
    color_key: str | None = None,
    color_tolerance: int = 15,
    color_erode: int = 0,
) -> bool:
    """
    単一画像を処理して背景透過PNGを出力する

    Returns:
        bool: 処理成功なら True
    """
    try:
        # 画像読み込み
        img = Image.open(input_path).convert("RGBA")

        if color_key:
            # ハイブリッド方式（AI + 色指定マスク合成）
            target_rgb = parse_color(color_key)
            result = process_hybrid(
                img,
                session=session,
                target_color=target_rgb,
                tolerance=color_tolerance,
                color_erode=color_erode,
                alpha_matting=alpha_matting,
                erode_size=erode_size,
                fg_threshold=fg_threshold,
                bg_threshold=bg_threshold,
                do_fill_holes=do_fill_holes
            )
        else:
            # rembg (AI) による被写体抽出処理
            result = remove(
                img,
                session=session,
                alpha_matting=alpha_matting,
                alpha_matting_foreground_threshold=fg_threshold,
                alpha_matting_background_threshold=bg_threshold,
                alpha_matting_erode_structure_size=erode_size,
            )

            # AIセグメンテーション時の中抜け防止処理を適用
            if do_fill_holes:
                result = fill_holes(result)

        # RGBA形式でPNG保存
        result.save(output_path, format="PNG")
        return True

    except Exception as e:
        print(f"  ✗ エラー: {input_path.name} - {e}", file=sys.stderr)
        return False


def collect_images(input_path: Path) -> list[Path]:
    """入力パスから処理対象の画像ファイルリストを取得する"""
    if input_path.is_file():
        if input_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [input_path]
        else:
            print(f"非対応の拡張子です: {input_path.suffix}", file=sys.stderr)
            return []
    elif input_path.is_dir():
        images = sorted(
            f for f in input_path.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        return images
    else:
        print(f"パスが見つかりません: {input_path}", file=sys.stderr)
        return []


def main():
    args = parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)

    # 画像ファイル収集
    images = collect_images(input_path)
    if not images:
        print("処理対象の画像が見つかりませんでした。")
        sys.exit(1)

    # 出力フォルダ作成
    output_dir.mkdir(parents=True, exist_ok=True)

    # isnet-anime セッションの初期化 (ハイブリッド機能があるので常に初期化する)
    print("モデルを初期化中（isnet-anime）...")
    session = new_session("isnet-anime")
    print("モデル初期化完了！\n")

    # 設定表示
    print("=" * 50)
    print("  背景透過ツール（イラスト特化版）")
    print("=" * 50)
    
    if args.color_key:
        print(f"  モード       : ハイブリッド (AI + 色ベース透過)")
        print(f"  対象背景色   : {args.color_key}")
        print(f"  許容誤差     : {args.color_tolerance}")
        if args.color_erode > 0:
            print(f"  文字フチ除去 : {args.color_erode}")
    else:
        print(f"  モード       : AI推論 (isnet-anime)")
        
    print(f"  Alpha Matting: {'ON' if args.alpha_matting else 'OFF'}")
    if args.alpha_matting:
        print(f"    Erode Size      : {args.erode_size}")
        print(f"    FG Threshold    : {args.fg_threshold}")
        print(f"    BG Threshold    : {args.bg_threshold}")
    print(f"  中抜け防止   : {'ON' if not args.no_fill_holes else 'OFF'}")

    print(f"  入力         : {input_path}")
    print(f"  出力先       : {output_dir}")
    print(f"  処理対象     : {len(images)} 枚")
    print("=" * 50)
    print()

    # バッチ処理
    success_count = 0
    fail_count = 0

    for idx, img_path in enumerate(images, 1):
        output_file = output_dir / f"{img_path.stem}.png"
        print(f"[{idx}/{len(images)}] {img_path.name} → {output_file.name} ...", end=" ")

        ok = process_image(
            input_path=img_path,
            output_path=output_file,
            session=session,
            alpha_matting=args.alpha_matting,
            erode_size=args.erode_size,
            fg_threshold=args.fg_threshold,
            bg_threshold=args.bg_threshold,
            do_fill_holes=not args.no_fill_holes,
            color_key=args.color_key,
            color_tolerance=args.color_tolerance,
            color_erode=args.color_erode,
        )

        if ok:
            print("✓ 完了")
            success_count += 1
        else:
            fail_count += 1

    # 結果サマリー
    print()
    print("=" * 50)
    print(f"  処理完了: {success_count} 成功 / {fail_count} 失敗")
    print(f"  出力先 : {output_dir.resolve()}")
    print("=" * 50)


if __name__ == "__main__":
    main()
