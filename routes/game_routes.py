from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from extensions import db, socketio
from logic.profileLogic import Profile, calculateStats
from logic.gameLogic import Game, recalculate, EloHistory, finish_game
from logic.roundLogic import Round
from routes.auth_routes import jwt_or_session_required

game_bp = Blueprint("game", __name__)

@game_bp.route("/add_game", methods=["POST"])
@jwt_required()
def add_game():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing data"}), 400

    player_ids = [
        data.get("team1_player1_id"),
        data.get("team1_player2_id"),
        data.get("team2_player1_id"),
        data.get("team2_player2_id"),
    ]

    real_ids = [pid for pid in player_ids if pid is not None and pid > 0]
    if real_ids:
        conflict = Game.query.filter(
            Game.winner == None,
            db.or_(
                Game.team1_player1_id.in_(real_ids),
                Game.team1_player2_id.in_(real_ids),
                Game.team2_player1_id.in_(real_ids),
                Game.team2_player2_id.in_(real_ids),
            )
        ).first()
        if conflict:
            return jsonify({"error": "One or more players are already in an open game"}), 409

    game = Game(
        target=data.get("target", 1000),
        allow_pingus=data.get("allow_pingus", True),
        team1_player1_id=data.get("team1_player1_id"),
        team1_player2_id=data.get("team1_player2_id"),
        team2_player1_id=data.get("team2_player1_id"),
        team2_player2_id=data.get("team2_player2_id"),
        guest2_name=data.get("guest2_name"),
        guest3_name=data.get("guest3_name"),
        guest4_name=data.get("guest4_name"),
    )

    db.session.add(game)
    db.session.commit()

    socketio.emit("game_created", game.to_dict())

    return jsonify(game.to_dict()), 201

@game_bp.route("/finish_game/<int:game_id>", methods=["POST"])
@jwt_or_session_required
def finish_game_route(game_id):
    from logic.gameLogic import Game
    
    game = Game.query.get(game_id)
    if not game:
        print("Game not found")
        return jsonify({"error": "Game not found"}), 404
    
    if game.calculated == True:
        print("Game already Calculated")
        print(f"{game.calculated}")
        return jsonify({"error": "Game already finished"}), 400

    recalculate(game_id)
    finish_game(game_id)
    socketio.emit("game_finished", {"game_id": game_id})
    return jsonify({"success": True}), 200

@game_bp.route("/game/edit_player/<int:game_id>", methods=["PATCH"])
@jwt_required()
def game_edit_player(game_id):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    if game.current_points_team1 != 0 or game.current_points_team2 != 0:
        return jsonify({"error": "Players can only be edited before the game has started (no points scored yet)"}), 409

    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing data"}), 400

    allowed_fields = {
        "team1_player1_id",
        "team1_player2_id",
        "team2_player1_id",
        "team2_player2_id",
        "guest2_name",
        "guest3_name",
        "guest4_name",
    }

    updated_fields = {k: v for k, v in data.items() if k in allowed_fields}

    if not updated_fields:
        return jsonify({"error": "No valid player fields provided"}), 400

    for field, value in updated_fields.items():
        setattr(game, field, value)

    db.session.commit()

    socketio.emit("game_updated", game.to_dict())

    return jsonify(game.to_dict()), 200

@game_bp.route("/delete_game/<int:game_id>", methods=["DELETE"])
@jwt_or_session_required
def delete_game(game_id):
    game = Game.query.get(game_id)


    playerIds = [game.team1_player1_id, game.team1_player2_id, game.team2_player1_id,game.team2_player2_id]


    #Calculate the Stats for the Player in all possible timeframes
    for playerId in playerIds:
        calculateStats(playerId,"all_time")
        calculateStats(playerId,"year")
        calculateStats(playerId,"month")
        calculateStats(playerId,"week")
        calculateStats(playerId,"day")

    if not game:
        return jsonify({"error": "Game not found"}), 404

    db.session.delete(game)
    db.session.commit()

    socketio.emit("game_deleted", {"game_id": game_id})

    return jsonify({"success": True}), 200


@game_bp.route("/game/<int:game_id>/rounds", methods=["GET"])
@jwt_or_session_required
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
@jwt_or_session_required
def recalculate_route(game_id):
    return recalculate(game_id)

@game_bp.route("/game/<int:game_id>", methods=["GET"])
@jwt_required()
def get_game(game_id):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    return jsonify(game.to_dict()), 200

