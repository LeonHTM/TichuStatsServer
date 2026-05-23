from flask import Blueprint, jsonify, request, send_from_directory, current_app, render_template, session
from flask_jwt_extended import jwt_required
from extensions import db, socketio
from logic.profileLogic import Profile
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
from config import SESSION_MINUTES, ALLOWED_EXTENSIONS
import os
from routes.auth_routes import jwt_or_session_required

profile_bp = Blueprint("profile", __name__)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@profile_bp.route("/profiles", methods=["GET"])
@jwt_or_session_required
def get_profiles():
    if request.accept_mimetypes.accept_html and not request.accept_mimetypes.accept_json:
        profiles = Profile.query.all()
        return render_template("dashboard.html", profiles=profiles, session_seconds=0)
    profiles = Profile.query.all()
    return jsonify([p.to_dict() for p in profiles])



@profile_bp.route("/profilesM", methods=["GET"])
@jwt_or_session_required
def get_profilesM():
    profiles = Profile.query.all()
    return jsonify([p.to_dictM() for p in profiles])

@profile_bp.route("/profilesstats/<int:profile_id>", methods=["GET"])
@jwt_or_session_required
def get_profilesstats(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(profile.to_dict_stats())

@profile_bp.route("/profilessimple", methods=["GET"])
@jwt_required()
def get_profilessimple():
    profiles = Profile.query.all()
    return jsonify([p.to_dict_simple() for p in profiles])

@profile_bp.route("/add_profile", methods=["POST"])
def create_profile():
    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify({"error": "Email is required"}), 400

    existing = Profile.query.filter_by(email=data["email"]).first()
    if existing:
        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(existing.id))
        return jsonify({"id": existing.id, "token": token}), 200

    new_profile = Profile(email=data["email"], name=data.get("name"))
    db.session.add(new_profile)
    db.session.commit()

    from flask_jwt_extended import create_access_token
    token = create_access_token(identity=str(new_profile.id))
    socketio.emit("profile_created", {"id": new_profile.id, "email": new_profile.email, "name": new_profile.name})
    return jsonify({"id": new_profile.id, "token": token}), 201

@profile_bp.route("/dashboard/update_profile/<int:profile_id>", methods=["POST"])
@jwt_or_session_required
def dashboard_update_profile(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    name = request.form.get("name")
    email = request.form.get("email")

    if name:
        profile.name = name
    if email:
        profile.email = email

    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"profile_{profile_id}.{file.filename.rsplit('.', 1)[1].lower()}")
            filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            profile.profile_image_url = filepath
            socketio.emit("profile_image_updated", {"profile_id": profile_id, "image_url": filepath})

    db.session.commit()
    socketio.emit("username_updated", {"profile_id": profile_id, "name": profile.name})
    return "ok", 200

@profile_bp.route("/delete_profile/<int:profile_id>", methods=["DELETE"])
@jwt_required()
def delete_profile(profile_id):
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
@jwt_required()
def check_username(username):
    existing = Profile.query.filter_by(name=username).first()
    return jsonify({"available": existing is None})

@profile_bp.route("/update_username/<int:profile_id>", methods=["PATCH"])
@jwt_required()
def update_username(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400

    profile.name = name
    db.session.commit()
    socketio.emit("username_updated", {"profile_id": profile_id, "name": name})
    return jsonify(profile.to_dict()), 200

@profile_bp.route("/check_email/<string:email>", methods=["GET"])
def check_email(email):
    existing = Profile.query.filter_by(email=email).first()
    if existing:
        return jsonify({"available": False, "id": existing.id})
    return jsonify({"available": True, "id": None})

@profile_bp.route("/add_image/<int:profile_id>/", methods=["POST"])
@jwt_required()
def upload_profile_image(profile_id):
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
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    profile.device_token = None
    db.session.commit()
    return jsonify({"success": True}), 200

@profile_bp.route("/register_device/<int:profile_id>", methods=["POST"])
@jwt_required()
def register_device(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    data = request.get_json()
    device_token = data.get("device_token")
    if not device_token:
        return jsonify({"error": "device_token is required"}), 400
    profile.device_token = device_token
    db.session.commit()
    return jsonify({"success": True}), 200

@profile_bp.route("/send_notification/<int:profile_id>", methods=["POST"])
@jwt_required()
def send_notification(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile or not profile.device_token:
        return jsonify({"error": "Profile not found or no device token"}), 404
    from notificationLogic import send_push_notification
    data = request.get_json()
    send_push_notification(
        device_token=profile.device_token,
        title=data.get("title", ""),
        body=data.get("body", ""),
        sender_name=data.get("sender_name", ""),
        sender_id=data.get("sender_id", "unknown"),
        conversation_id=data.get("conversation_id", "default")
    )
    return jsonify({"success": True}), 200


