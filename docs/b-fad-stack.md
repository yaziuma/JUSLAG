# B-FAD Stack

## 🛠 1. 採用技術 (The B-FAD Stack)
* **B**ootstrap (最新版 via CDN): UIコンポーネント、レスポンシブデザイン、グリッドシステム。
* **F**astAPI + Jinja2 (Python): サーバーサイドのルーティング、APIエンドポイント、HTMLの骨組み（Scaffolding）の構築。
* **A**lpine.js (最新版 via CDN): クライアントサイドのリアクティブなUI制御、状態管理。
* **D**exie.js (最新版 via CDN): ブラウザ内蔵のIndexedDBを扱うためのローカルデータベース（オフラインファーストの実現）。

## 🏛 2. 設計哲学と厳格なルール (Crucial Rules)
B-FAD Stackは「サーバーサイドの保守性」と「ローカルファーストの超高速UI」を両立させるハイブリッドな設計です。以下のルールを必ず守ってください。

1.  **フロントエンドのビルドは禁止**: Node.js、Vite、npm、Tailwindのビルドプロセスなどは一切使用しないでください。フロントエンドのライブラリはすべてJinja2テンプレート内のCDN経由で読み込みます。
2.  **Jinja2の役割（骨組みのみ）**: Jinja2は、ファイル分割（`{% extends %}`, `{% include %}`）や、サーバー側の環境変数・初期設定の埋め込みにのみ使用します。**絶対に Jinja2 の `{% for %}` を使って動的なデータリストをレンダリングしないでください。**
3.  **データの主導権はローカルに（Local-First）**: ユーザーが操作するデータの正（Source of Truth）は `Dexie.js` です。`Alpine.js` はDexie.jsからデータを読み書きし、画面を更新します（`x-for` や `x-model` を使用）。
4.  **FastAPIの役割（API Gateway）**: FastAPIはHTMLテンプレートを返すほか、ローカルDB（Dexie）だけでは処理できない重い計算、外部API連携、クラウドへのデータバックアップ用の JSON API エンドポイントとしてのみ機能します。
5.  **1コンポーネント・1関心**: UIの動きはAlpine.jsの `x-data` の中にカプセル化し、グローバルな変数を汚染しないでください。

## 📦 3. 出力フォーマット要件
コードを出力する際は、必ず以下の構成で提示し、コピペですぐに動く状態にしてください。

1.  **ディレクトリ構成**: 必要なファイル構造（`main.py`, `templates/base.html`, `templates/...`）を示してください。
2.  **`main.py`**: FastAPIのルーターとJinja2Templatesの設定を含むPythonコード。
3.  **`templates/base.html`**: Bootstrap, Alpine.js, Dexie.js のCDN読み込みと、共通レイアウトを含むベーステンプレート。
4.  **`templates/xxx.html`**: Alpine.js のロジックと Dexie.js のデータベース定義（スキーマ）を含む個別ページのテンプレート。
5.  **実行コマンド**: `pip install fastapi uvicorn jinja2` および `uvicorn main:app --reload` などの起動手順を添えてください。

---
