"""Development server: python run.py  (production: gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 'app:create_app()')"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("PT_HOST", "127.0.0.1"), port=int(os.environ.get("PT_PORT", "5000")),
            debug=os.environ.get("PT_DEBUG", "1") == "1")
