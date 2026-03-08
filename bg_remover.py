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

  # 単色背景の透過（イラストの文字などが消えてしまう場合）
  # -c / --color-key オプションで透過したい背景色を指定（white, black, R,G,B）
  python bg_remover.py -i ryoukai.png -c white
  python bg_remover.py -i ryoukai.png -c 255,255,255  # RGB直接指定
"""

import argparse
import sys
from pathlib import Path

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
        help="単色背景透過の色指定（例: white, black, または 255,255,255）。"
             "これを指定するとrembgAIではなく色ベースの透過を行います（文字などを残したい場合に使用）。",
    )
    parser.add_argument(
        "--color-tolerance",
        type=int,
        default=15,
        help="色ベース透過の際の許容誤差（デフォルト: 15）",
    )
    parser.add_argument(
        "--alpha-matting",
        action="store_true",
        default=False,
        help="alpha matting を有効化（境界をより滑らかに）",
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


def parse_color(color_str: str) -> tuple[int, int, int]:
    """色文字列をRGBタプルに変換する"""
    color_str = color_str.lower().strip()
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


def remove_by_color(image: Image.Image, target_color: tuple[int, int, int], tolerance: int = 15) -> Image.Image:
    """
    指定された色（および許容誤差内の色）を透明にする
    """
    img = image.convert("RGBA")
    arr = np.array(img)

    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    tr, tg, tb = target_color

    # 許容誤差範囲内のピクセルを特定
    mask = (
        (np.abs(r.astype(int) - tr) <= tolerance) &
        (np.abs(g.astype(int) - tg) <= tolerance) &
        (np.abs(b.astype(int) - tb) <= tolerance)
    )

    # 該当ピクセルのアルファ値を0（透明）にする
    arr[mask, 3] = 0

    return Image.fromarray(arr)


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
            # 色指定による透過処理（文字などを消したくない場合）
            target_rgb = parse_color(color_key)
            result = remove_by_color(img, target_rgb, color_tolerance)
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

            # AIセグメンテーション時のみ中抜け防止処理を適用
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

    # isnet-anime セッションの初期化（色透過指定があれば不要だが、一旦常に作っておく）
    if not args.color_key:
        print("モデルを初期化中（isnet-anime）...")
        session = new_session("isnet-anime")
        print("モデル初期化完了！\n")
    else:
        session = None

    # 設定表示
    print("=" * 50)
    print("  背景透過ツール（イラスト特化版）")
    print("=" * 50)
    
    if args.color_key:
        print(f"  モード       : 色ベース透過 (クロマキー)")
        print(f"  対象色       : {args.color_key}")
        print(f"  許容誤差     : {args.color_tolerance}")
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
