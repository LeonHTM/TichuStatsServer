from flask import Flask, request, redirect, session, render_template
from flask_jwt_extended import create_access_token
from extensions import db, socketio, jwt
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME, UPLOAD_FOLDER, JWT_KEY, SECRET_KEY, BROWSER_PASSWORD, SESSION_MINUTES
from routes.auth_routes import auth_bp
from routes.profile_routes import profile_bp
from routes.friend_routes import friend_bp
from routes.game_routes import game_bp
from routes.round_routes import round_bp
from routes.passkey_routes import passkey_bp
from datetime import timedelta, datetime, timezone
import os
from routes.auth_routes import jwt_or_session_required
from logic.profileLogic import Profile
from logic.gameLogic import Game
from flask import send_from_directory




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
    socketio.init_app(app, cors_allowed_BASE_URLs="*", async_mode="threading", ping_interval=2, ping_timeout=3)

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(friend_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(round_bp)
    app.register_blueprint(passkey_bp)


    @app.route("/.well-known/apple-app-site-association")
    def apple_app_site_association():
        return send_from_directory(
            "/Users/leon/Desktop/TichuServer/.well-known",
            "apple-app-site-association",
            mimetype="application/json"
        )


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
            session.clear()
            return render_template("login.html")

        from logic.profileLogic import ProfileStats
        profiles = Profile.query.all()
        for profile in profiles:
            profile.all_time_stats = ProfileStats.query.filter_by(
                profile_id=profile.id, timeframe="all_time"
            ).first()

        return render_template(
            "dashboard-profiles.html",
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
            return redirect("/dashboard/profiles")
        return render_template("login.html", error=True)

    @app.route("/dashboard/profiles", methods=["GET"])
    @jwt_or_session_required
    def dashboardprofiles():
        from logic.profileLogic import ProfileStats
        profiles = Profile.query.all()
        for profile in profiles:
            profile.all_time_stats = ProfileStats.query.filter_by(
                profile_id=profile.id, timeframe="all_time"
            ).first()

        remaining = 0
        expires_at_str = session.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            remaining = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

        return render_template("dashboard-profiles.html", profiles=profiles, session_seconds=remaining)
    
    @app.route("/dashboard/games", methods=["GET"])
    @jwt_or_session_required
    def dashboard_games():
        from logic.roundLogic import Round

        games = Game.query.order_by(Game.date.desc()).all()

        profile_ids = set()
        for g in games:
            for pid in [g.team1_player1_id, g.team1_player2_id, g.team2_player1_id, g.team2_player2_id]:
                if pid:
                    profile_ids.add(pid)

        profiles = Profile.query.filter(Profile.id.in_(profile_ids)).all()
        name_map = {p.id: (p.name or f"ID {p.id}") for p in profiles}

        game_ids = [g.id for g in games]


        all_rounds = Round.query.filter(
            Round.game_id.in_(game_ids),
            Round.bool_win_round == True
        ).order_by(Round.round_order.asc()).all()

        rounds_by_game = {}
        for r in all_rounds:
            rounds_by_game.setdefault(r.game_id, []).append({
                "order":      r.round_order,
                "round_pts1": r.round_points_team1,
                "round_pts2": r.round_points_team2,
                "tichu1":     r.tichu_points_team1,
                "tichu2":     r.tichu_points_team2,
                "double1":    r.double_win_team1,
                "double2":    r.double_win_team2,
                "win_round":  r.bool_win_round,
                "tichu":      r.announced_tichu or [],
                "big_tichu":  r.announced_big_tichu or [],
                "pingu":      r.announced_pingu or [],
                "bombs1":     r.first_bombs,
                "bombs2":     r.second_bombs,
                "bombs3":     r.third_bombs,
                "bombs4":     r.fourth_bombs,
                "first_profile_id":  r.first_profile_id,
                "second_profile_id": r.second_profile_id,
                "third_profile_id":  r.third_profile_id,
                "fourth_profile_id": r.fourth_profile_id,
            })

        games_data = []
        for g in games:
            games_data.append({
                "id":           g.id,
                "date":         g.date,
                "target":       g.target,
                "allow_pingus": g.allow_pingus,
                "team1_p1":     name_map.get(g.team1_player1_id, "?"),
                "team1_p2":     name_map.get(g.team1_player2_id, "?"),
                "team2_p1":     name_map.get(g.team2_player1_id, "?"),
                "team2_p2":     name_map.get(g.team2_player2_id, "?"),
                "team1_p1_id":  g.team1_player1_id,
                "team1_p2_id":  g.team1_player2_id,
                "team2_p1_id":  g.team2_player1_id,
                "team2_p2_id":  g.team2_player2_id,
                "points1":      g.current_points_team1,
                "points2":      g.current_points_team2,
                "winner":       g.winner,
                "rounds":       rounds_by_game.get(g.id, []),
            })

        remaining = 0
        expires_at_str = session.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            remaining = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

        return render_template("dashboard-games.html", games=games_data, session_seconds=remaining)
    
    @app.route("/dashboard/rounds", methods=["GET"])
    @jwt_or_session_required
    def dashboardrounds():
        from logic.profileLogic import ProfileStats
        profiles = Profile.query.all()
        for profile in profiles:
            profile.all_time_stats = ProfileStats.query.filter_by(
                profile_id=profile.id, timeframe="all_time"
            ).first()

        remaining = 0
        expires_at_str = session.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            remaining = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))

        return render_template("dashboard-rounds.html", profiles=profiles, session_seconds=remaining)

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