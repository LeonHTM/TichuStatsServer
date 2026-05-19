from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
from profileLogic import db, Profile, ProfileFriend, FriendRequest
from config import DB_PASSWORD, DB_USER, DB_HOST, DB_NAME, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, BASE_URL
from werkzeug.utils import secure_filename
import os
from notificationLogic import *

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
        return jsonify({"id": existing.id}), 200

    new_profile = Profile(
        email=data["email"],
        name=data.get("name")
    )

    db.session.add(new_profile)
    db.session.commit()

    socketio.emit("profile_created", {"id": new_profile.id, "email": new_profile.email, "name": new_profile.name})

    return jsonify({"id": new_profile.id}), 201


@tichuServer.route("/delete_profile/<int:profile_id>", methods=["DELETE"])
def delete_profile(profile_id):
    profile = Profile.query.get(profile_id)

    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if profile.profile_image_url:
        if os.path.exists(profile.profile_image_url):
            os.remove(profile.profile_image_url)

    db.session.delete(profile)
    db.session.commit()

    socketio.emit("profile_deleted", {"id": profile_id})

    return jsonify({"message": f"Profile {profile_id} deleted"}), 200


# USERNAME----------------
@tichuServer.route("/check_username/<string:username>", methods=["GET"])
def check_username(username):
    existing = Profile.query.filter_by(name=username).first()
    return jsonify({"available": existing is None})

@tichuServer.route("/update_username/<int:profile_id>", methods=["PATCH"])
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


# EMAIL----------------
@tichuServer.route("/check_email/<string:email>", methods=["GET"])
def check_email(email):
    existing = Profile.query.filter_by(email=email).first()
    if existing:
        return jsonify({"available": False, "id": existing.id})
    return jsonify({"available": True, "id": None})

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

@tichuServer.route("/logout/<int:profile_id>", methods=["POST"])
def logout(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    profile.device_token = None
    db.session.commit()
    return jsonify({"success": True}), 200


# FRIEND REQUESTS -----------------------
@tichuServer.route("/add_request/<int:sender_id>/request/<int:receiver_id>", methods=["POST"])
def send_friend_request(sender_id, receiver_id):

    if sender_id == receiver_id:
        return jsonify({"error": "Cannot request yourself"}), 400

    sender = Profile.query.get(sender_id)
    receiver = Profile.query.get(receiver_id)

    if sender is None or receiver is None:
        return jsonify({
            "error": "Invalid sender or receiver (profile does not exist)"
        }), 404

    existing = FriendRequest.query.filter_by(
        sender_id=sender_id,
        receiver_id=receiver_id,
        status="pending"
    ).first()

    if existing:
        return jsonify({"error": "Request already sent"}), 469

    # Check if the other person has already sent a request to this sender
    mutual_request = FriendRequest.query.filter_by(
        sender_id=receiver_id,
        receiver_id=sender_id,
        status="pending"
    ).first()

    # Stable conversation ID: always sort the two user IDs so both sides
    # produce the same string regardless of who initiated
    conversation_id = f"friends-{min(sender_id, receiver_id)}-{max(sender_id, receiver_id)}"

    try:
        if mutual_request:
            # Auto-accept: delete both requests and create friendship
            db.session.delete(mutual_request)

            already_friends = ProfileFriend.query.filter_by(
                profile_id=sender_id,
                friend_id=receiver_id
            ).first()

            if not already_friends:
                friendship = ProfileFriend(
                    profile_id=sender_id,
                    friend_id=receiver_id
                )
                db.session.add(friendship)

            db.session.commit()

            socketio.emit("friend_request_updated", {
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "status": "accepted"
            })

            # Notify receiver that they are now friends
            if receiver.device_token:
                image_url = f"{BASE_URL}/{sender.profile_image_url}" if sender.profile_image_url else None
                print(f"Sending accepted notification to {receiver.name} with image_url: {image_url}")
                send_push_notification(
                    device_token=receiver.device_token,
                    title="Friend Request Accepted",
                    body=f"You and {sender.name} are now friends",
                    sender_name=sender.name,
                    sender_id=str(sender_id),
                    conversation_id=conversation_id,
                    image_url=image_url
                )

            return jsonify({"message": "Mutual request detected — friendship automatically created"}), 201

        else:
            req = FriendRequest(
                sender_id=sender_id,
                receiver_id=receiver_id,
                status="pending"
            )
            db.session.add(req)
            db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    socketio.emit("friend_request_sent", {
        "id": req.id,
        "sender_id": sender_id,
        "receiver_id": receiver_id
    })

    # Notify receiver of the friend request
    if receiver.device_token:
        image_url = f"{BASE_URL}/{sender.profile_image_url}" if sender.profile_image_url else None
        print(f"Sending request notification to {receiver.name} with image_url: {image_url}")
        send_push_notification(
            device_token=receiver.device_token,
            title="New Friend Request",
            body=f"{sender.name} sent you a friend request",
            sender_name=sender.name,
            sender_id=str(sender_id),
            conversation_id=conversation_id,
            image_url=image_url
        )

    return jsonify({"message": "Friend request sent"}), 201


@tichuServer.route("/manage_requests/<int:receiver_id>/from/<int:sender_id>", methods=["PATCH"])
def respond_to_request(receiver_id, sender_id):

    data = request.get_json()
    action = data.get("action")

    if action not in ["accepted", "rejected"]:
        return jsonify({"error": "Invalid action"}), 400

    freq = FriendRequest.query.filter_by(
        sender_id=sender_id,
        receiver_id=receiver_id,
        status="pending"
    ).first()

    if not freq:
        return jsonify({"error": "Friend request not found"}), 404

    try:
        if action == "accepted":
            existing_friendship = ProfileFriend.query.filter_by(
                profile_id=sender_id,
                friend_id=receiver_id
            ).first()

            if not existing_friendship:
                friendship = ProfileFriend(
                    profile_id=sender_id,
                    friend_id=receiver_id
                )
                db.session.add(friendship)

        # delete request in both cases
        db.session.delete(freq)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    socketio.emit("friend_request_updated", {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "status": action
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

@tichuServer.route("/send_notification/<int:profile_id>", methods=["POST"])
def send_notification(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile or not profile.device_token:
        return jsonify({"error": "Profile not found or no device token"}), 404

    data = request.get_json()

    # sender_id and conversation_id are optional for manual test notifications
    send_push_notification(
        device_token=profile.device_token,
        title=data.get("title", ""),
        body=data.get("body", ""),
        sender_name=data.get("sender_name", ""),
        sender_id=data.get("sender_id", "unknown"),
        conversation_id=data.get("conversation_id", "default")
    )
    return jsonify({"success": True}), 200

@tichuServer.route("/register_device/<int:profile_id>", methods=["POST"])
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


@tichuServer.route("/sent_requests/<int:profile_id>/", methods=["GET"])
def get_sent_requests(profile_id):
    reqs = FriendRequest.query.filter_by(
        sender_id=profile_id,
        status="pending"
    ).all()

    return jsonify([{
        "id": r.id,
        "receiver_id": r.receiver_id
    } for r in reqs]), 200


# RUN SERVER -----------------------
if __name__ == "__main__":
    socketio.run(tichuServer, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)