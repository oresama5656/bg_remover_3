@echo off
chcp 65001 > nul
echo ==========================================
echo   BG Remover 3 - Web UI 起動ツール
echo ==========================================

:: 仮想環境の存在確認
if not exist ".venv\Scripts\activate" (
    echo [情報] 仮想環境が見つかりません。初回セットアップを開始します...
    echo Pythonの仮想環境を作成中...
    python -m venv .venv
    
    echo 必須ライブラリをインストール中...
    call .venv\Scripts\activate
    pip install -r requirements.txt
    pip install -r requirements_ui.txt
    echo セットアップ完了！
) else (
    echo [情報] 仮想環境を有効化しています...
    call .venv\Scripts\activate
    
    :: gradioが入っているか簡易チェック
    python -c "import gradio" >nul 2>&1
    if errorlevel 1 (
        echo [情報] UIライブラリが不足しているため追加インストールします...
        pip install -r requirements_ui.txt
    )
)

echo.
echo ブラウザでUIを起動します...
python app.py

pause
