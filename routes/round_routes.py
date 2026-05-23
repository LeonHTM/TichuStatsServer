from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from extensions import db, socketio
from logic.profileLogic import Profile
from logic.roundLogic import Round
from logic.gameLogic import Game

game_bp = Blueprint("round", __name__)

@game_bp.route("/add_round", methods=["POST"])
#@jwt_required()
def add_round():
    data = request.get_json()

    if not data or not data.get("game_id"):
        return jsonify({"error": "game_id is required"}), 400

    game = Game.query.get(data["game_id"])
    if not game:
        return jsonify({"error": "Game not found"}), 404

    round_obj = Round(
        game_id=data["game_id"],
        round_order=data.get("round_order", 1),

        first_profile_id=data.get("first_profile_id"),
        second_profile_id=data.get("second_profile_id"),
        third_profile_id=data.get("third_profile_id"),
        fourth_profile_id=data.get("fourth_profile_id"),

        first_bombs=data.get("first_bombs", 0),
        second_bombs=data.get("second_bombs", 0),
        third_bombs=data.get("third_bombs", 0),
        fourth_bombs=data.get("fourth_bombs", 0),

        tichu_points_team1=data.get("tichu_points_team1", 50),
        tichu_points_team2=data.get("tichu_points_team2", 50),

        round_points_team1=data.get("round_points_team1", 0),
        round_points_team2=data.get("round_points_team2", 0),

        double_win_team1=data.get("double_win_team1", False),
        double_win_team2=data.get("double_win_team2", False),

        bool_win_round=data.get("bool_win_round", False),  # NEW

        announced_tichu=data.get("announced_tichu", []),
        announced_big_tichu=data.get("announced_big_tichu", []),
        announced_pingu=data.get("announced_pingu", []),
    )

    db.session.add(round_obj)

    # update game score automatically (important)
    game.current_points_team1 += round_obj.round_points_team1
    game.current_points_team2 += round_obj.round_points_team2

    db.session.commit()

    socketio.emit("round_created", round_obj.to_dict())

    return jsonify(round_obj.to_dict()), 201


@game_bp.route("/edit_round/<int:round_id>", methods=["PATCH"])
#@jwt_required()
def edit_round(round_id):
    round_obj = Round.query.get(round_id)

    if not round_obj:
        return jsonify({"error": "Round not found"}), 404

    data = request.get_json()

    allowed_fields = [
        "round_order",
        "first_profile_id", "second_profile_id", "third_profile_id", "fourth_profile_id",
        "first_bombs", "second_bombs", "third_bombs", "fourth_bombs",
        "tichu_points_team1", "tichu_points_team2",
        "round_points_team1", "round_points_team2",
        "double_win_team1", "double_win_team2",
        "bool_win_round",  # NEW
        "announced_tichu", "announced_big_tichu", "announced_pingu",
    ]

    for field in allowed_fields:
        if field in data:
            setattr(round_obj, field, data[field])

    # RECALCULATE LOGIC HERE
    game = round_obj.game

    game.current_points_team1 = sum(r.round_points_team1 for r in game.rounds)
    game.current_points_team2 = sum(r.round_points_team2 for r in game.rounds)

    db.session.commit()

    socketio.emit("round_updated", round_obj.to_dict())

    return jsonify(round_obj.to_dict()), 200


@game_bp.route("/delete_round/<int:round_id>", methods=["DELETE"])
#@jwt_required()
def delete_round(round_id):
    round_obj = Round.query.get(round_id)

    if not round_obj:
        return jsonify({"error": "Round not found"}), 404

    game = round_obj.game

    db.session.delete(round_obj)
    db.session.flush()

    # RECALCULATE LOGIC HERE
    game.current_points_team1 = sum(r.round_points_team1 for r in game.rounds)
    game.current_points_team2 = sum(r.round_points_team2 for r in game.rounds)

    db.session.commit()

    socketio.emit("round_deleted", {"round_id": round_id, "game_id": game.id})

    return jsonify({"success": True}), 200