from flask import Blueprint, jsonify, request, session, redirect, render_template
from flask_jwt_extended import create_access_token, verify_jwt_in_request
from logic.profileLogic import Profile
from logic.authLogic import generate_and_send_code, verify_code
from functools import wraps
from config import APP_SECRET_TOKEN

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

#When first login in the App does not have an authToken yet, it uses appToken which is a Sectret String
def app_token_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != APP_SECRET_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

#JWT for Client or Session for webpage requeired
def jwt_or_session_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Client: JWT header
        try:
            verify_jwt_in_request()
            return fn(*args, **kwargs)
        except Exception:
            pass

        # Browser: session cookie
        if session.get("jwt"):
            return fn(*args, **kwargs)

        # No valid auth
        if request.accept_mimetypes.accept_html:
            return render_template("error.html"), 401  
        return jsonify({"error": "Unauthorized"}), 401  

    return wrapper


@auth_bp.route("/login/request-code/<email>", methods=["POST"])
@app_token_required
def request_login_code(email):
    email = email.strip().lower()

    if not email:
        return jsonify({"error": "Email required"}), 400

    # Works for both existing profiles (login) and new emails (sign up) —
    # a code is sent either way to verify ownership of the email.
    generate_and_send_code(email)

    return jsonify({"message": "Code sent."}), 200


@auth_bp.route("/login/verify-code/<email>/<code>", methods=["POST"])
@app_token_required
def verify_login_code(email, code):
    email = email.strip().lower()
    code = code.strip()

    if not email or not code:
        print("Email and code reuquired")
        return jsonify({"error": "Email and code required"}), 400

    if not verify_code(email, code):
        print("Expired code")
        return jsonify({"error": "Invalid or expired code"}), 401

    profile = Profile.query.filter_by(email=email).first()

    if profile:
        # Existing user — log them in
        token = create_access_token(identity=str(profile.id))
        return jsonify({"verified": True, "exists": True, "token": token, "id": profile.id}), 200

    
    return jsonify({"verified": True, "exists": False}), 200