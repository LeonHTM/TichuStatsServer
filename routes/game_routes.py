from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from extensions import db, socketio
from logic.profileLogic import Profile
from logic.gameLogic import Game, recalculate
from logic.roundLogic import Round
from routes.auth_routes import jwt_or_session_required

game_bp = Blueprint("game", __name__)

@game_bp.route("/add_game", methods=["POST"])
@jwt_required()
def add_game():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing data"}), 400

    game = Game(
        target=data.get("target", 1000),
        allow_pingus=data.get("allow_pingus", True),
        team1_player1_id=data.get("team1_player1_id"),
        team1_player2_id=data.get("team1_player2_id"),
        team2_player1_id=data.get("team2_player1_id"),
        team2_player2_id=data.get("team2_player2_id"),
    )

    db.session.add(game)
    db.session.commit()

    socketio.emit("game_created", game.to_dict())

    return jsonify(game.to_dict()), 201


@game_bp.route("/delete_game/<int:game_id>", methods=["DELETE"])
@jwt_or_session_required
def delete_game(game_id):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    db.session.delete(game)
    db.session.commit()

    socketio.emit("game_deleted", {"game_id": game_id})

    return jsonify({"success": True}), 200


@game_bp.route("/game/<int:game_id>/rounds", methods=["GET"])
#@jwt_or_session_required
def get_game_rounds(game_id):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    rounds = (
        Round.query
        .filter_by(game_id=game_id)
        .order_by(Round.round_order.asc())
        .all()
    )

    return jsonify({
        "game_id": game_id,
        "rounds": [r.to_dict() for r in rounds]
    }), 200


from sqlalchemy import or_

@game_bp.route("/profile/<int:profile_id>/games", methods=["GET"])
@jwt_required()
def get_profile_games(profile_id):
    profile = Profile.query.get(profile_id)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    games = (
        Game.query.filter(
            or_(
                Game.team1_player1_id == profile_id,
                Game.team1_player2_id == profile_id,
                Game.team2_player1_id == profile_id,
                Game.team2_player2_id == profile_id,
            )
        )
        .order_by(Game.date.desc())
        .all()
    )

    return jsonify({
        "profile_id": profile_id,
        "games": [g.to_dict() for g in games]
    }), 200

@game_bp.route("/recalculate_game/<int:game_id>", methods=["POST"])
@jwt_required()
def recalculate_route(game_id):
    return recalculate(game_id)

@game_bp.route("/game/<int:game_id>", methods=["GET"])
@jwt_required()
def get_game(game_id):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    return jsonify(game.to_dict()), 200

@game_bp.route("/test-route")
def test_route():
    return "OK"