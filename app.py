import gradio as gr
from pathlib import Path
from rembg import new_session
import tempfile
import onnxruntime as ort

# コアロジックをインポート (bg_remover.py は一切変更せずに利用)
from bg_remover import process_image

# ==========================================
# 1. モデルの初期化 (起動時に1回だけ実行して高速化)
# ==========================================
# GPUが利用可能な環境（onnxruntime-gpuがインストール済み）であれば自動でGPUを使用
providers = ["CPUExecutionProvider"]
if "CUDAExecutionProvider" in ort.get_available_providers():
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

print(f"🎨 AIモデルを読み込み中... ({'GPU' if 'CUDA' in providers[0] else 'CPU'} モード)")
session = new_session("isnet-anime", providers=providers)


# ==========================================
# 2. UIから呼ばれる処理関数
# ==========================================
def process_gui(input_img_path, mode, color_str, color_tolerance, color_erode, alpha_matting, erode_size):
    if input_img_path is None:
        return None
    
    # モードに応じた背景色の設定
    color_key = color_str if "ハイブリッド" in mode else None
    
    # 出力用の一時ファイルを作成
    out_dir = Path(tempfile.gettempdir())
    out_path = out_dir / f"output_ui_{Path(input_img_path).name}.png"
    
    # bg_remover.py の既存の関数をそのまま利用
    success = process_image(
        input_path=Path(input_img_path),
        output_path=out_path,
        session=session,
        alpha_matting=alpha_matting,
        erode_size=erode_size,
        fg_threshold=240,
        bg_threshold=10,
        do_fill_holes=True,
        color_key=color_key,
        color_tolerance=color_tolerance,
        color_erode=color_erode
    )
    
    if success and out_path.exists():
        return str(out_path)
    return None


# ==========================================
# 3. オシャレなWeb UIの構築 (Gradio)
# ==========================================
# モダンで柔らかなテーマを使用
custom_theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="blue",
).set(
    button_primary_background_fill="*primary_500",
    button_primary_background_fill_hover="*primary_600",
)

with gr.Blocks(theme=custom_theme, title="BG Remover 3") as demo:
    gr.Markdown(
        """
        # 🎨 bg_remover_3 Web UI
        イラスト特化の高品質な背景透過ツールです。画像をドラッグ＆ドロップして処理を開始してください。
        """
    )
    
    with gr.Row():
        # 左側パネル: 入力と設定
        with gr.Column(scale=1):
            input_image = gr.Image(type="filepath", label="入力画像 (イラスト)")
            
            mode_radio = gr.Radio(
                ["ハイブリッド (単色背景抽出 / おすすめ)", "AI専用 (手前のキャラのみ自動抽出)"], 
                value="ハイブリッド (単色背景抽出 / おすすめ)", 
                label="動作モード"
            )
            
            with gr.Group():
                gr.Markdown("### 🔤 ハイブリッド設定（文字・装飾の維持）")
                color_input = gr.Textbox(value="auto", label="背景色指定", info="auto, white, black, 255,255,255 など。autoが最もおすすめ。")
                color_erode = gr.Slider(0, 10, value=2, step=1, label="文字側のフチ除去の強さ (color-erode)")
                color_tolerance = gr.Slider(0, 100, value=15, step=1, label="色の許容誤差")
                
            with gr.Group():
                gr.Markdown("### 👤 AIフチ削り設定（キャラ本体）")
                am_checkbox = gr.Checkbox(value=True, label="Alpha Matting (キャラの滑らかなフチ削り) を有効にする")
                erode_slider = gr.Slider(0, 50, value=2, step=1, label="キャラ境界の侵食サイズ (erode-size)")
                
            submit_btn = gr.Button("✨ 透過処理を開始", variant="primary", size="lg")
            
        # 右側パネル: 出力結果
        with gr.Column(scale=1):
            # 透過部分が市松模様で表示される画像コンポーネント
            output_image = gr.Image(type="filepath", label="透過結果 (PNG)", interactive=False, format="png")
            
    # ボタンクリック時のイベント紐付け
    submit_btn.click(
        fn=process_gui,
        inputs=[
            input_image, mode_radio, color_input, color_tolerance, color_erode, 
            am_checkbox, erode_slider
        ],
        outputs=output_image
    )

if __name__ == "__main__":
    # 自動でブラウザを開く設定で起動
    demo.launch(inbrowser=True)
