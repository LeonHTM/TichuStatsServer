from flask import Blueprint, jsonify, request, session, redirect, render_template
from flask_jwt_extended import create_access_token, verify_jwt_in_request
from profileLogic import Profile
from functools import wraps

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    profile_id = data.get("id")

    if not profile_id:
        return jsonify({"error": "ID required"}), 400

    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    token = create_access_token(identity=str(profile.id))
    return jsonify({"token": token, "id": profile.id}), 200


def jwt_or_session_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # SwiftUI app — JWT header
        try:
            verify_jwt_in_request()
            return fn(*args, **kwargs)
        except Exception:
            pass

        # Browser — session cookie
        if session.get("jwt"):
            return fn(*args, **kwargs)

        # No valid auth
        if request.accept_mimetypes.accept_html:
            return render_template("error.html"), 401  # ← error page for browsers
        return jsonify({"error": "Unauthorized"}), 401  # ← JSON for API clients

    return wrapper