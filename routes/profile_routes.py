from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os

from flask import Blueprint, jsonify, request, send_from_directory, current_app, render_template, session
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from extensions import db, socketio
from logic.profileLogic import Profile, UserDeviceToken, ProfileSettings, calculateStats, ProfileStats
from config import SESSION_MINUTES, ALLOWED_EXTENSIONS, APP_SECRET_TOKEN, MAX_HISTORY_ENTRIES, TIMEFRAMES
from routes.auth_routes import jwt_or_session_required, app_token_required, current_identity, caller_is_admin, is_dashboard_session
from logic.gameLogic import EloHistory, handle_user_deleted


profile_bp = Blueprint("profile", __name__)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@profile_bp.route("/profiles", methods=["GET"])
@jwt_or_session_required
def get_profiles():
    if request.accept_mimetypes.accept_html and not request.accept_mimetypes.accept_json:
        if not caller_is_admin():
            return render_template("error.html"), 403

        profiles = Profile.query.all()
        for profile in profiles:
            profile.all_time_stats = ProfileStats.query.filter_by(
                            profile_id=profile.id, timeframe="all_time").order_by(ProfileStats.id.desc()).first()
        return render_template("dashboard-profiles.html", profiles=profiles, session_seconds=0)
    profiles = Profile.query.all()
    return jsonify([p.to_dict() for p in profiles])


@profile_bp.route("/profile/<int:profile_id>/in_open_game", methods=["GET"])
@jwt_or_session_required
def is_in_open_game(profile_id):
    from logic.gameLogic import Game

    open_game = Game.query.filter(
        Game.winner == None,
        db.or_(
            Game.team1_player1_id == profile_id,
            Game.team1_player2_id == profile_id,
            Game.team2_player1_id == profile_id,
            Game.team2_player2_id == profile_id,
        )
    ).first()

    return jsonify(open_game is not None), 200

@profile_bp.route("/profile/<int:profile_id>/settings", methods=["GET"])
@jwt_or_session_required
def get_profile_settings(profile_id):
    current_id = current_identity()
    if current_id is None or current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    settings = ProfileSettings.query.filter_by(user_id=profile_id).first()
    if not settings:
        return jsonify({
            "user_id": profile_id,
            "default_target": 1000,
            "show_pingu": True,
            "drag_mode": False,
            "show_all_profiles": False,
            "sort_by_profiles": 0,
            "sort_by_stats": 2
        }), 200
    return jsonify(settings.to_dict()), 200


# request key -> candidate model attribute names (first one that exists on the model wins).
# The old code used "show_all_players" / "sort_by_profile", which did not match the GET
# defaults ("show_all_profiles" / "sort_by_profiles"), so some updates were silently lost.
SETTINGS_FIELDS = {
    "default_target":    ("default_target",),
    "show_pingu":        ("show_pingu",),
    "drag_mode":         ("drag_mode",),
    "show_all_profiles": ("show_all_profiles", "show_all_players"),
    "show_all_players":  ("show_all_profiles", "show_all_players"),  # legacy client key
    "sort_by_profiles":  ("sort_by_profiles", "sort_by_profile"),
    "sort_by_stats":     ("sort_by_stats",),
}


@profile_bp.route("/profile/<int:profile_id>/settings", methods=["PATCH"])
@jwt_or_session_required
def update_profile_settings(profile_id):
    current_id = current_identity()
    if current_id is None or current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    settings = ProfileSettings.query.filter_by(user_id=profile_id).first()

    if not settings:
        settings = ProfileSettings(user_id=profile_id)
        db.session.add(settings)

    for key, candidates in SETTINGS_FIELDS.items():
        if key not in data:
            continue
        attr = next((a for a in candidates if hasattr(ProfileSettings, a)), None)
        if attr is None:
            current_app.logger.warning("ProfileSettings has no column for %r (tried %s)", key, candidates)
            continue
        setattr(settings, attr, data[key])

    try:
        db.session.commit()
        socketio.emit("settings_updated", {"id": profile_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

    return jsonify(settings.to_dict()), 200

#Day: 14 Entries: 14 Days -> 2 Weeks
#Week: 13 Entries: 2 per Week -> 6 Weeks / 1.5 Months
#Month: 13 Entries 2 Per Month -> 6 Months
#Year: 13 Entries: 4 times per Year : 3 Years
#Alltime: 13 Entries: 4 times per Year : 3 Years



#All the timeframe sedning entries is made by AI 
_YEAR = {"max_entries": 13, "per_period": 4, "period": lambda dt: dt.year}

_HISTORY_CONFIG = {
    "day":   {"max_entries": 14, "per_period": 1, "period": lambda dt: dt.date()},
    "week":  {"max_entries": 13, "per_period": 2,
              "period": lambda dt: tuple(dt.isocalendar())[:2]},  # (iso_year, iso_week)
    "month": {"max_entries": 13, "per_period": 2,
              "period": lambda dt: (dt.year, dt.month)},
    "year": _YEAR,
    "all_time": _YEAR,
}


def latest_stats_per_period(profile_id, timeframe, limit=MAX_HISTORY_ENTRIES):
    settings = _HISTORY_CONFIG.get(timeframe)
    if settings is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    max_entries = min(limit, settings["max_entries"])
    if max_entries <= 0:
        return []

    query = (
        ProfileStats.query
        .filter_by(profile_id=profile_id, timeframe=timeframe)
        .order_by(ProfileStats.calculated_at.desc(), ProfileStats.id.desc())
    )

    # year / all_time: at most one snapshot per calendar day and NO backfill,
    # so they only ever show what the per-period cap allows.
    # day / week / month never touch this: their code path below is unchanged.
    sparse_mode = timeframe in ("year", "all_time")
    used_days = set()

    counts = defaultdict(int)
    picked, skipped = [], []

    for stat in query.yield_per(100):
        if stat.calculated_at is None:
            continue
        if sparse_mode and stat.calculated_at.date() in used_days:
            continue  # same-day duplicate
        period = settings["period"](stat.calculated_at)
        if counts[period] >= settings["per_period"]:
            skipped.append(stat)
            continue
        counts[period] += 1
        picked.append(stat)
        if sparse_mode:
            used_days.add(stat.calculated_at.date())
        if len(picked) >= max_entries:
            break
    else:
        # Ran out of rows before filling the window (sparse data):
        # backfill with the newest rows that the per-period cap skipped.
        # (Not done for year / all_time.)
        if not sparse_mode:
            picked.extend(skipped[: max_entries - len(picked)])

    # Chronological order for charts.
    picked.sort(key=lambda s: (s.calculated_at, s.id))
    return picked

@profile_bp.route("/profilestats/history", methods=["POST"])
@jwt_or_session_required
def profilestatshistory():
    current_id = current_identity()
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400
    if "profile_id" not in data:
        return jsonify({"error": "profile_id is required"}), 400

    try:
        profile_id = int(data["profile_id"])
    except (TypeError, ValueError):
        return jsonify({"error": "invalid profile_id"}), 400

    if current_id is None or int(current_id) != profile_id:
        return jsonify({"error": "forbidden"}), 403

    stat = data.get("stat")  # currently unused

    try:
        result = {
            tf: [s.to_dict() for s in latest_stats_per_period(profile_id, tf)]
            for tf in TIMEFRAMES
        }
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(result)


@profile_bp.route("/profilesstats/<int:profile_id>", methods=["GET"])
@jwt_or_session_required
def get_profilesstats(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    timeframe = request.args.get("timeframe", "all_time")
    timezone_str = request.args.get("timezone", "UTC")

    try:
        ZoneInfo(timezone_str)  
    except Exception:
        return jsonify({"error": f"Invalid timezone: {timezone_str}"}), 400


    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = (
        ProfileStats.query
        .filter_by(profile_id=profile.id, timeframe="all_time")
        .order_by(ProfileStats.id.desc())
        .first()
    )
    # Limit: 5 Min or new round
    already_calculated_recently = (
        existing is not None
        and existing.calculated_at is not None
        and (now - existing.calculated_at) < timedelta(minutes=5)
    )

    if not already_calculated_recently:
        for tf in ("all_time", "year", "month", "week", "day"):
            print(f"Recalculating Stats: {tf}")
            calculateStats(profile_id, timeframe=tf, timezone_str=timezone_str)
    else:
        print("don't need to calculate, already have recent")
    return jsonify(profile.to_dict_stats(timeframe=timeframe))


@profile_bp.route("/profile/<int:profile_id>/is_admin", methods=["GET"])
@jwt_or_session_required
def is_admin(profile_id):
    current_id = current_identity()
    if current_id is None or current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify({"is_admin": profile.is_admin}), 200

@profile_bp.route("/profilessimple", methods=["GET"])
@jwt_required()
def get_profilessimple():
    profiles = Profile.query.all()
    return jsonify([p.to_dict_simple() for p in profiles])

@profile_bp.route("/add_profile", methods=["POST"])
@app_token_required
def create_profile():
    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify({"error": "Email is required"}), 400

    existing = Profile.query.filter_by(email=data["email"]).first()
    if existing:
        return jsonify({"error": "email_in_use"}), 409

    new_profile = Profile(email=data["email"], name=data.get("name"))
    db.session.add(new_profile)
    db.session.flush()

    db.session.add(EloHistory(profile_id=new_profile.id, game_id=None, elo_change=0))
    db.session.commit()

    from flask_jwt_extended import create_access_token
    token = create_access_token(identity=str(new_profile.id))
    socketio.emit("profile_created", {"id": new_profile.id, "email": new_profile.email, "name": new_profile.name})
    return jsonify({"id": new_profile.id, "token": token}), 201

@profile_bp.route("/dashboard/update_profile/<profile_id>", methods=["POST"])
@jwt_or_session_required
def dashboard_update_profile(profile_id):
    if not caller_is_admin():
        return jsonify({"error": "forbidden"}), 403

    try:
        profile_id = int(profile_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid profile ID"}), 400

    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    name = request.form.get("name")
    email = request.form.get("email")
    is_admin = request.form.get("is_admin")

    if name:
        profile.name = name
    if email:
        profile.email = email
    if is_admin is not None:
        profile.is_admin = is_admin.lower() == "true"

    image_updated = False
    filepath = None
    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"profile_{profile_id}.{file.filename.rsplit('.', 1)[1].lower()}")
            filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            with open(filepath, "rb") as f:
                f.flush()
                os.fsync(f.fileno())

            profile.profile_image_url = filepath
            image_updated = True

    db.session.commit()

    socketio.emit("username_updated", {"profile_id": profile_id, "name": profile.name})
    socketio.emit("admin_updated", {"profile_id": profile_id, "admin": profile.is_admin})
    if image_updated:
        socketio.emit("profile_image_updated", {"profile_id": profile_id, "image_url": filepath})

    return "ok", 200

@profile_bp.route("/delete_profile/<int:profile_id>", methods=["DELETE"])
@jwt_or_session_required
def delete_profile(profile_id):
    current_id = current_identity()
    if not (is_dashboard_session() or caller_is_admin() or current_id == profile_id):
        return jsonify({"error": "forbidden"}), 403
    error, status = handle_user_deleted(profile_id)
    if status != 200:
        return jsonify(error), status

    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if profile.profile_image_url and os.path.exists(profile.profile_image_url):
        os.remove(profile.profile_image_url)

    db.session.delete(profile)
    db.session.commit()
    socketio.emit("profile_deleted", {"id": profile_id})
    return jsonify({"message": f"Profile {profile_id} deleted"}), 200

@profile_bp.route("/check_username/<string:username>", methods=["GET"])
def check_username(username):
    existing = Profile.query.filter_by(name=username).first()
    return jsonify({"available": existing is None})

@profile_bp.route("/update_username/<int:profile_id>", methods=["PATCH"])
@jwt_required()
def update_username(profile_id):
    current_id = int(get_jwt_identity())
    if current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400

    profile.name = name
    db.session.commit()
    socketio.emit("username_updated", {"profile_id": profile_id, "name": name})
    return jsonify(profile.to_dict()), 200

@profile_bp.route("/check_email/<string:email>", methods=["GET"])
@app_token_required
def check_email(email):
    existing = Profile.query.filter_by(email=email).first()
    if existing:
        return jsonify({"available": False, "id": existing.id})
    return jsonify({"available": True, "id": None})

@profile_bp.route("/add_image/<int:profile_id>/", methods=["POST"])
@jwt_required()
def upload_profile_image(profile_id):
    current_id = int(get_jwt_identity())
    if current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400

    file = request.files["image"]
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    filename = secure_filename(f"profile_{profile_id}.{file.filename.rsplit('.', 1)[1].lower()}")
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    with open(filepath, "rb") as f:
        f.flush()
        os.fsync(f.fileno())

    profile.profile_image_url = filepath
    db.session.commit()
    socketio.emit("profile_image_updated", {"profile_id": profile_id, "image_url": filepath})
    return jsonify({"message": "Image uploaded", "path": filepath}), 200

@profile_bp.route("/uploads/profile_images/<filename>", methods=["GET"])
def serve_image(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)

@profile_bp.route("/logout/<int:profile_id>", methods=["POST"])
@jwt_required()
def logout(profile_id):
    current_id = int(get_jwt_identity())
    if current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    profile = Profile.query.get(profile_id)
    if not profile:
        print("profile not found")
        return jsonify({"error": "Profile not found"}), 404

    data = request.get_json() or {}
    device_token = data.get("device_token")

    if device_token:
        UserDeviceToken.query.filter_by(
            user_id=profile_id,
            device_token=device_token
        ).delete()
    else:
        UserDeviceToken.query.filter_by(user_id=profile_id).delete()

    db.session.commit()
    return jsonify({"success": True}), 200

@profile_bp.route("/register_device/<int:profile_id>", methods=["POST"])
@jwt_required()
def register_device(profile_id):
    current_id = int(get_jwt_identity())
    if current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    data = request.get_json() or {}
    device_token = data.get("device_token")
    if not device_token:
        return jsonify({"error": "device_token is required"}), 400

    existing = UserDeviceToken.query.filter_by(
        user_id=profile_id,
        device_token=device_token
    ).first()

    if not existing:
        new_token = UserDeviceToken(user_id=profile_id, device_token=device_token)
        db.session.add(new_token)
        db.session.commit()

    return jsonify({"success": True}), 200

#Testing Purposes only should not be made public or otherwise users can send notifaciotn to any other user
"""@profile_bp.route("/send_notification/<int:profile_id>", methods=["POST"])
@jwt_required()
def send_notification(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    from logic.notificationLogic import notify_user
    data = request.get_json()
    notify_user(
        profile_id=profile_id,
        sender_name=data.get("sender_name", ""),
        sender_id=data.get("sender_id", "unknown"),
        conversation_id=data.get("conversation_id", "default"),
        title_loc_key=data.get("title_loc_key", "GENERIC_NOTIFICATION_TITLE"),
        loc_key=data.get("loc_key", "GENERIC_NOTIFICATION_BODY"),
        title_loc_args=data.get("title_loc_args", []),
        loc_args=data.get("loc_args", [])
    )
    return jsonify({"success": True}), 200"""


@profile_bp.route("/elo_history/<int:profile_id>", methods=["GET"])
@jwt_or_session_required
def get_elo_history(profile_id):
    current_id = current_identity()
    if current_id is None or current_id != profile_id:
        return jsonify({"error": "forbidden"}), 403

    history = (
        EloHistory.query
        .filter_by(profile_id=profile_id)
        .order_by(EloHistory.changed_at.asc())
        .all()
    )

    return jsonify([
        {
            "id": entry.id,
            "game_id": entry.game_id,
            "elo_change": entry.elo_change,
            "changed_at": entry.changed_at.isoformat() if entry.changed_at else None,
        }
        for entry in history
    ]), 200