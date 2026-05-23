from flask import Flask, request, redirect, session, render_template
from flask_jwt_extended import create_access_token
from extensions import db, socketio, jwt
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME, UPLOAD_FOLDER, JWT_KEY, SECRET_KEY, BROWSER_PASSWORD
from routes.auth_routes import auth_bp
from routes.profile_routes import profile_bp
from routes.friend_routes import friend_bp
from routes.game_routes import game_bp
from datetime import timedelta
import os

def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = JWT_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    db.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading", ping_interval=2, ping_timeout=3)

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(friend_bp)
    app.register_blueprint(game_bp)

    @app.route("/", methods=["GET"])
    def browser_dashboard():
        if not session.get("jwt"):
            return render_template("login.html")
        return redirect("/dashboard")

    @app.route("/session_check")
    def session_check():
        if session.get("jwt"):
            return "", 200
        return "", 401

    @app.route("/dashlogin", methods=["POST"])
    def browser_login():
        password = request.form.get("password")
        if password == BROWSER_PASSWORD:
            session.permanent = True  # ← THIS is what makes the timeout work
            token = create_access_token(identity="browser")
            session["jwt"] = token
            return redirect("/dashboard")
        return render_template("login.html", error=True)

    @app.route("/dashlogout")
    def browser_logout():
        session.pop("jwt", None)
        return redirect("/")

    return app


tichuServer = create_app()

if __name__ == "__main__":
    socketio.run(tichuServer, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)