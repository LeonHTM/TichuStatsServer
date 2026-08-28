from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from extensions import db, socketio
from logic.profileLogic import Profile, ProfileFriend, FriendRequest
from logic.notificationLogic import notify_user, notify_accepted
from config import BASE_URL

friend_bp = Blueprint("friend", __name__)

@friend_bp.route("/friends/<int:profile_id>", methods=["GET"])
@jwt_required()
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

@friend_bp.route("/add_friendship/<int:profile_id>/friends/<int:friend_id>", methods=["POST"])
@jwt_required()
def add_friend(profile_id, friend_id):
    if profile_id == friend_id:
        return jsonify({"error": "A profile cannot be friends with itself"}), 400

    profile = Profile.query.get(profile_id)
    friend = Profile.query.get(friend_id)
    if not profile or not friend:
        return jsonify({"error": "One or both profiles not found"}), 404

    existing = ProfileFriend.query.filter_by(profile_id=profile_id, friend_id=friend_id).first()
    if existing:
        return jsonify({"error": "Already friends"}), 409

    friendship = ProfileFriend(profile_id=profile_id, friend_id=friend_id)
    db.session.add(friendship)
    db.session.commit()

    socketio.emit("friendship_added", {"profile_id": profile_id, "friend_id": friend_id})

    conversation_id = f"friends-{min(profile_id, friend_id)}-{max(profile_id, friend_id)}"
    image_url = f"{BASE_URL}/{profile.profile_image_url}" if profile.profile_image_url else None
    notify_accepted(
        profile_id=friend_id,
        sender_name=profile.name,
        sender_id=str(profile_id),
        conversation_id=conversation_id,
        title_loc_key="notifictaion.friendRequest.accepted.title",
        loc_key="notification.friendRequest.accepted.body",
        loc_args=[profile.name],
        image_url=image_url
    )
    return jsonify({"message": "Friendship created"}), 201

@friend_bp.route("/delete_friendship/<int:profile_id>/friends/<int:friend_id>", methods=["DELETE"])
@jwt_required()
def remove_friend(profile_id, friend_id):
    friendship = ProfileFriend.query.filter(
        ((ProfileFriend.profile_id == profile_id) & (ProfileFriend.friend_id == friend_id)) |
        ((ProfileFriend.profile_id == friend_id) & (ProfileFriend.friend_id == profile_id))
    ).first()

    if not friendship:
        return jsonify({"error": "Friendship not found"}), 404

    db.session.delete(friendship)
    db.session.commit()
    socketio.emit("friendship_removed", {"profile_id": profile_id, "friend_id": friend_id})
    return jsonify({"message": "Friendship removed"}), 200

@friend_bp.route("/add_request/<int:sender_id>/request/<int:receiver_id>", methods=["POST"])
@jwt_required()
def send_friend_request(sender_id, receiver_id):
    if sender_id == receiver_id:
        return jsonify({"error": "Cannot request yourself"}), 400

    sender = Profile.query.get(sender_id)
    receiver = Profile.query.get(receiver_id)
    if not sender or not receiver:
        return jsonify({"error": "Invalid sender or receiver"}), 404

    existing = FriendRequest.query.filter_by(sender_id=sender_id, receiver_id=receiver_id, status="pending").first()
    if existing:
        return jsonify({"error": "Request already sent"}), 469

    mutual_request = FriendRequest.query.filter_by(sender_id=receiver_id, receiver_id=sender_id, status="pending").first()
    conversation_id = f"friends-{min(sender_id, receiver_id)}-{max(sender_id, receiver_id)}"

    try:
        if mutual_request:
            db.session.delete(mutual_request)
            if not ProfileFriend.query.filter_by(profile_id=sender_id, friend_id=receiver_id).first():
                db.session.add(ProfileFriend(profile_id=sender_id, friend_id=receiver_id))
            db.session.commit()

            socketio.emit("friend_request_updated", {"sender_id": sender_id, "receiver_id": receiver_id, "status": "accepted"})
            socketio.emit("remove_friend_request_notification", {"user_id": receiver_id, "sender_id": sender_id})
            socketio.emit("remove_friend_request_notification", {"user_id": sender_id, "sender_id": receiver_id})

            image_url = f"{BASE_URL}/{sender.profile_image_url}" if sender.profile_image_url else None
            notify_accepted(
                profile_id=receiver_id,
                sender_name=sender.name,
                sender_id=str(sender_id),
                conversation_id=conversation_id,
                title_loc_key="notification.friendRequest.accepted.title",
                loc_key="notification.friendRequest.accepted.body",
                loc_args=[sender.name],
                image_url=image_url
            )
            return jsonify({"message": "Mutual request detected — friendship automatically created"}), 201

        req = FriendRequest(sender_id=sender_id, receiver_id=receiver_id, status="pending")
        db.session.add(req)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    socketio.emit("friend_request_sent", {"id": req.id, "sender_id": sender_id, "receiver_id": receiver_id})

    image_url = f"{BASE_URL}/{sender.profile_image_url}" if sender.profile_image_url else None
    notify_user(
        profile_id=receiver_id,
        sender_name=sender.name,
        sender_id=str(sender_id),
        conversation_id=conversation_id,
        title_loc_key="notification.friendRequest.title",
        loc_key="notification.friendRequest.body",
        loc_args=[sender.name],
        image_url=image_url
    )
    return jsonify({"message": "Friend request sent"}), 201

@friend_bp.route("/manage_requests/<int:receiver_id>/from/<int:sender_id>", methods=["PATCH"])
@jwt_required()
def respond_to_request(receiver_id, sender_id):
    data = request.get_json()
    action = data.get("action")
    if action not in ["accepted", "rejected"]:
        return jsonify({"error": "Invalid action"}), 400

    freq = FriendRequest.query.filter_by(sender_id=sender_id, receiver_id=receiver_id, status="pending").first()
    if not freq:
        return jsonify({"error": "Friend request not found"}), 404

    sender = Profile.query.get(sender_id)
    receiver = Profile.query.get(receiver_id)

    try:
        if action == "accepted":
            if not ProfileFriend.query.filter_by(profile_id=sender_id, friend_id=receiver_id).first():
                db.session.add(ProfileFriend(profile_id=sender_id, friend_id=receiver_id))
                socketio.emit("remove_friend_request_notification", {"user_id": receiver_id, "sender_id": sender_id})
                socketio.emit("remove_friend_request_notification", {"user_id": sender_id, "sender_id": receiver_id})

        db.session.delete(freq)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    socketio.emit("friend_request_updated", {"sender_id": sender_id, "receiver_id": receiver_id, "status": action})

    if action == "accepted" and sender:
        conversation_id = f"friends-{min(sender_id, receiver_id)}-{max(sender_id, receiver_id)}"
        image_url = f"{BASE_URL}/{receiver.profile_image_url}" if receiver and receiver.profile_image_url else None
        notify_accepted(
            profile_id=sender_id,
            sender_name=receiver.name,
            sender_id=str(receiver_id),
            conversation_id=conversation_id,
            title_loc_key="notification.friendRequest.accepted.title",
            loc_key="notification.friendRequest.accepted.by.body",
            loc_args=[receiver.name],
            image_url=image_url
        )
    return jsonify({"message": f"Request {action}"}), 200

@friend_bp.route("/requests/<int:profile_id>/", methods=["GET"])
@jwt_required()
def get_requests(profile_id):
    reqs = FriendRequest.query.filter_by(receiver_id=profile_id, status="pending").all()
    return jsonify([{"id": r.id, "sender_id": r.sender_id, "created_at": r.created_at.isoformat()} for r in reqs]), 200

@friend_bp.route("/sent_requests/<int:profile_id>/", methods=["GET"])
@jwt_required()
def get_sent_requests(profile_id):
    reqs = FriendRequest.query.filter_by(sender_id=profile_id, status="pending").all()
    return jsonify([{"id": r.id, "receiver_id": r.receiver_id} for r in reqs]), 200