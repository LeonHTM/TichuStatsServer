from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token
from profileLogic import Profile

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

from functools import wraps
from flask import session, jsonify,redirect
from flask_jwt_extended import verify_jwt_in_request

def jwt_or_session_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Try JWT header first (SwiftUI app)
        try:
            verify_jwt_in_request()
            return fn(*args, **kwargs)
        except Exception:
            pass

        # Fall back to session cookie (browser)
        if session.get("jwt"):
            return fn(*args, **kwargs)

        # No valid auth — redirect browsers to login, return 401 for API
        from flask import request
        if request.accept_mimetypes.accept_html:
            return redirect("/")
        return jsonify({"error": "Unauthorized"}), 401

    return wrapper