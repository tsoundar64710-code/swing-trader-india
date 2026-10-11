"""Flask entry point. Binds to 127.0.0.1 only — never expose publicly.

Run: python -m swingtrader.web.server
"""

from swingtrader.web import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8501, debug=False)
