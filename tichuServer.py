from flask import Flask, request, redirect, session
from flask_jwt_extended import create_access_token
from extensions import db, socketio, jwt
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME, UPLOAD_FOLDER, JWT_KEY, SECRET_KEY, BROWSER_PASSWORD
from routes.auth_routes import auth_bp
from routes.profile_routes import profile_bp
from routes.friend_routes import friend_bp
from routes.game_routes import game_bp
import os

def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = JWT_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["SECRET_KEY"] = SECRET_KEY
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    db.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading", ping_interval=2, ping_timeout=3)

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(friend_bp)
    app.register_blueprint(game_bp)

    @app.route("/browser-login", methods=["GET", "POST"])
    def browser_login():
        if request.method == "POST":
            password = request.form.get("password")
            if password == BROWSER_PASSWORD:
                token = create_access_token(identity="browser")
                session["jwt"] = token
                return redirect("/browser")
            return "<p>Wrong password</p>", 401

        return """
        <form method="POST">
            <input type="password" name="password" placeholder="Password" />
            <button type="submit">Login</button>
        </form>
        """

    @app.route("/browser")
    def browser_dashboard():
        token = session.get("jwt")
        if not token:
            return redirect("/browser-login")
        return "<p>Welcome! You're authenticated.</p>"

    return app  # now correctly outside the route definitions


tichuServer = create_app()

if __name__ == "__main__":
    socketio.run(tichuServer, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)