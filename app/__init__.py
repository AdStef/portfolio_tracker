from flask import Flask, request

from app import db
from app.config import build_config
from app.constants import DISPLAY_CURRENCIES, LANGUAGES
from app.i18n import bundle, translate


def create_app(data_dir=None, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.update(build_config(data_dir))
    app.config.update(overrides)
    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    from app.routes.api import bp as api_bp
    from app.routes.pages import bp as pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.context_processor
    def inject_ui():
        lang = current_lang()
        return {
            "lang": lang,
            "display_ccy": current_ccy(),
            "t": lambda key: translate(key, lang),
            "i18n_bundle": bundle(lang),
            "languages": LANGUAGES,
            "display_currencies": DISPLAY_CURRENCIES,
        }

    return app


def current_lang() -> str:
    lang = request.cookies.get("lang", "pl")
    return lang if lang in LANGUAGES else "pl"


def current_ccy() -> str:
    ccy = request.cookies.get("ccy", "PLN")
    return ccy if ccy in DISPLAY_CURRENCIES else "PLN"
