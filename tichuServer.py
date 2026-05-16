from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
from profileLogic import db, Profile, ProfileFriend, FriendRequest
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME, UPLOAD_FOLDER, ALLOWED_EXTENSIONS
from werkzeug.utils import secure_filename
import os


# SERVER SETUP
tichuServer = Flask(__name__)

# SOCKET.IO SETUP
socketio = SocketIO(
    tichuServer,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_interval=2,
    ping_timeout=3
)

# CONFIG
tichuServer.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# MySQL config
tichuServer.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
)
tichuServer.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(tichuServer)


# BASIC ROUTE -----------------------
@tichuServer.route("/")
def hello_world():
    return "<p>Tichu Server!</p>"


# PROFILES -----------------------
@tichuServer.route("/profiles", methods=["GET"])
def get_profiles():
    profiles = Profile.query.all()
    return jsonify([p.to_dict() for p in profiles])

@tichuServer.route("/profilesM", methods=["GET"])
def get_profilesM():
    profiles = Profile.query.all()
    return jsonify([p.to_dictM() for p in profiles])

# PROFILES/STATS-----------------------
@tichuServer.route("/profilesstats/<int:profile_id>", methods=["GET"])
def get_profilesstats(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(profile.to_dict_stats())

# PROFILES/SIMPLE-----------------------
@tichuServer.route("/profilessimple", methods=["GET"])
def get_profilessimple():
    profiles = Profile.query.all()
    return jsonify([p.to_dict_simple() for p in profiles])


@tichuServer.route("/add_profile", methods=["POST"])
def create_profile():
    data = request.get_json()

    if not data or not data.get("email"):
        return jsonify({"error": "Email is required"}), 400

    existing = Profile.query.filter_by(email=data["email"]).first()
    if existing:
        return jsonify({"error": "Profile with this email already exists"}), 409

    new_profile = Profile(
        email=data["email"],
        name=data.get("name"),
        profile_image_url=data.get("profile_image_url"),
        date_added=data.get("date_added"),
        elo=data.get("elo"),
        winner_percentage=data.get("winner_percentage", 0),
        tichu_master=data.get("tichu_master", 0),
        visionary=data.get("visionary", 0),
        addict=data.get("addict", 0),
        teamplayer=data.get("teamplayer", 0),
        announcer=data.get("announcer", 0),
        saboteur=data.get("saboteur", 0),
        gambler=data.get("gambler", 0),
        big_gambler=data.get("big_gambler", 0),
        pingu_gambler=data.get("pingu_gambler", 0),
        bomber=data.get("bomber", 0),
    )

    db.session.add(new_profile)
    db.session.commit()

    payload = new_profile.to_dict()
    socketio.emit("profile_created", payload)

    return jsonify(payload), 201


@tichuServer.route("/delete_profile/<int:profile_id>", methods=["DELETE"])
def delete_profile(profile_id):
    profile = Profile.query.get(profile_id)

    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    db.session.delete(profile)
    db.session.commit()

    socketio.emit("profile_deleted", {"id": profile_id})

    return jsonify({"message": f"Profile {profile_id} deleted"}), 200


# FRIENDSHIPS -----------------------
@tichuServer.route("/friends/<int:profile_id>/", methods=["GET"])
def get_friends(profile_id):
    friendships = ProfileFriend.query.filter(
        (ProfileFriend.profile_id == profile_id) |
        (ProfileFriend.friend_id == profile_id)
    ).all()

    result = []
    for f in friendships:
        friend_id = f.friend_id if f.profile_id == profile_id else f.profile_id
        friend_profile = Profile.query.get(friend_id)
        if friend_profile:
            data = friend_profile.to_dict()
            data["friends_since"] = f.created_at.isoformat() if f.created_at else None
            result.append(data)

    return jsonify(result)


@tichuServer.route("/add_friendship/<int:profile_id>/friends/<int:friend_id>", methods=["POST"])
def add_friend(profile_id, friend_id):
    if profile_id == friend_id:
        return jsonify({"error": "A profile cannot be friends with itself"}), 400

    profile = Profile.query.get(profile_id)
    friend = Profile.query.get(friend_id)

    if not profile or not friend:
        return jsonify({"error": "One or both profiles not found"}), 404

    existing = ProfileFriend.query.filter_by(
        profile_id=profile_id, friend_id=friend_id
    ).first()
    if existing:
        return jsonify({"error": "Already friends"}), 409

    friendship = ProfileFriend(profile_id=profile_id, friend_id=friend_id)
    db.session.add(friendship)
    db.session.commit()

    socketio.emit("friendship_added", {
        "profile_id": profile_id,
        "friend_id": friend_id
    })

    return jsonify({"message": "Friendship created"}), 201


@tichuServer.route("/delete_friendship/<int:profile_id>/friends/<int:friend_id>", methods=["DELETE"])
def remove_friend(profile_id, friend_id):
    friendship = ProfileFriend.query.filter(
        ((ProfileFriend.profile_id == profile_id) &
         (ProfileFriend.friend_id == friend_id)) |
        ((ProfileFriend.profile_id == friend_id) &
         (ProfileFriend.friend_id == profile_id))
    ).first()

    if not friendship:
        return jsonify({"error": "Friendship not found"}), 404

    db.session.delete(friendship)
    db.session.commit()

    socketio.emit("friendship_removed", {
        "profile_id": profile_id,
        "friend_id": friend_id
    })

    return jsonify({"message": "Friendship removed"}), 200


# PROFILE IMAGE -----------------------
@tichuServer.route("/add_image/<int:profile_id>/", methods=["POST"])
def upload_profile_image(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400

    file = request.files["image"]

    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    filename = secure_filename(
        f"profile_{profile_id}.{file.filename.rsplit('.', 1)[1].lower()}"
    )
    filepath = os.path.join(tichuServer.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    profile.profile_image_url = filepath
    db.session.commit()

    payload = {
        "profile_id": profile_id,
        "image_url": filepath
    }
    socketio.emit("profile_image_updated", payload)

    return jsonify({"message": "Image uploaded", "path": filepath}), 200


@tichuServer.route("/uploads/profile_images/<filename>", methods=["GET"])
def serve_image(filename):
    return send_from_directory(tichuServer.config["UPLOAD_FOLDER"], filename)


# FRIEND REQUESTS -----------------------
@tichuServer.route("/add_request/<int:sender_id>/request/<int:receiver_id>", methods=["POST"])
def send_friend_request(sender_id, receiver_id):
    if sender_id == receiver_id:
        return jsonify({"error": "Cannot request yourself"}), 400

    existing = FriendRequest.query.filter_by(
        sender_id=sender_id,
        receiver_id=receiver_id,
        status="pending"
    ).first()

    if existing:
        return jsonify({"error": "Request already sent"}), 409

    req = FriendRequest(sender_id=sender_id, receiver_id=receiver_id)
    db.session.add(req)
    db.session.commit()

    payload = {
        "id": req.id,
        "sender_id": sender_id,
        "receiver_id": receiver_id
    }
    socketio.emit("friend_request_sent", payload)

    return jsonify({"message": "Friend request sent"}), 201


@tichuServer.route("/manage_requests/<int:request_id>", methods=["PATCH"])
def respond_to_request(request_id):
    data = request.get_json()
    action = data.get("action")

    if action not in ["accepted", "rejected"]:
        return jsonify({"error": "Invalid action"}), 400

    freq = FriendRequest.query.get(request_id)
    if not freq:
        return jsonify({"error": "Request not found"}), 404

    freq.status = action

    if action == "accepted":
        friendship = ProfileFriend(
            profile_id=freq.sender_id,
            friend_id=freq.receiver_id
        )
        db.session.add(friendship)

    db.session.commit()

    socketio.emit("friend_request_updated", {
        "request_id": request_id,
        "status": action,
        "sender_id": freq.sender_id,
        "receiver_id": freq.receiver_id
    })

    return jsonify({"message": f"Request {action}"}), 200


@tichuServer.route("/requests/<int:profile_id>/", methods=["GET"])
def get_requests(profile_id):
    reqs = FriendRequest.query.filter_by(
        receiver_id=profile_id,
        status="pending"
    ).all()

    return jsonify([{
        "id": r.id,
        "sender_id": r.sender_id,
        "created_at": r.created_at.isoformat()
    } for r in reqs]), 200


# RUN SERVER -----------------------
if __name__ == "__main__":
    socketio.run(tichuServer, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)