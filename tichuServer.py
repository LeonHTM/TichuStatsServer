#from gevent import monkey
#monkey.patch_all()

from flask import Flask, request, redirect, session, render_template
from flask_jwt_extended import create_access_token
from extensions import db, socketio, jwt
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME, UPLOAD_FOLDER, JWT_KEY, SECRET_KEY, BROWSER_PASSWORD, SESSION_MINUTES
from routes.auth_routes import auth_bp
from routes.profile_routes import profile_bp
from routes.friend_routes import friend_bp
from routes.game_routes import game_bp
from datetime import timedelta, datetime, timezone
import os
from routes.auth_routes import jwt_or_session_required
from logic.profileLogic import Profile




def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = JWT_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=SESSION_MINUTES)
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

        login_time_str = session.get("login_time")
        if not login_time_str:
            session.clear()
            return render_template("login.html")

        login_time = datetime.fromisoformat(login_time_str)
        elapsed = (datetime.now(timezone.utc) - login_time).total_seconds()
        remaining = int(SESSION_MINUTES * 60 - elapsed)

        if remaining <= 0:
            session.clear()  # kill session
            return render_template("login.html")  # or redirect(url_for("login"))

        profiles = Profile.query.all()

        return render_template(
            "dashboard.html",
            profiles=profiles,
            session_seconds=remaining
        )

    @app.route("/session_check")
    def session_check():
        if session.get("jwt"):
            return "", 200
        return "", 401

    @app.route("/dashlogin", methods=["POST"])
    def browser_login():
        password = request.form.get("password")
        if password == BROWSER_PASSWORD:
            session.permanent = True
            session["jwt"] = create_access_token(identity="browser")
            session["expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=SESSION_MINUTES)).isoformat()
            return redirect("/dashboard")
        return render_template("login.html", error=True)

    @app.route("/dashboard", methods=["GET"])
    @jwt_or_session_required
    def dashboard():
        profiles = Profile.query.all()

        remaining = 0
        expires_at_str = session.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            remaining = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

        return render_template("dashboard.html", profiles=profiles, session_seconds=remaining)

    @app.route("/dashlogout")
    def browser_logout():
        session.pop("jwt", None)
        session.pop("expires_at", None)
        return redirect("/")
    
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    
    return app
    


tichuServer = create_app()

if __name__ == "__main__":
    socketio.run(tichuServer, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)