from flask import jsonify
from flask_sqlalchemy import SQLAlchemy
from extensions import db, socketio
from logic.roundLogic import Round

class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, server_default=db.func.now())

    target = db.Column(db.Integer, default=1000)
    allow_pingus = db.Column(db.Boolean, default=True)

    team1_player1_id = db.Column(db.Integer)
    team1_player2_id = db.Column(db.Integer)
    team2_player1_id = db.Column(db.Integer)
    team2_player2_id = db.Column(db.Integer)

    current_points_team1 = db.Column(db.Integer, default=0)
    current_points_team2 = db.Column(db.Integer, default=0)

    winner = db.Column(db.Integer)

    rounds = db.relationship("Round", back_populates="game", lazy=True, cascade="all, delete-orphan")

    # ------------------------
    # VALIDATION
    # ------------------------
    def validate(self):
        players = [
            self.team1_player1_id,
            self.team1_player2_id,
            self.team2_player1_id,
            self.team2_player2_id
        ]

        if None in players:
            raise ValueError("All 4 players must be set")

        if len(set(players)) != 4:
            raise ValueError("Players must be unique")

        if self.target <= 0:
            raise ValueError("Invalid target value")

    # ------------------------
    # SERIALIZATION
    # ------------------------
    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,

            "target": self.target,
            "allow_pingus": self.allow_pingus,

            "team1_player1_id": self.team1_player1_id,
            "team1_player2_id": self.team1_player2_id,
            "team2_player1_id": self.team2_player1_id,
            "team2_player2_id": self.team2_player2_id,

            "current_points_team1": self.current_points_team1,
            "current_points_team2": self.current_points_team2,

            "winner": self.winner,
        }

def recalculate(game_id):
    game = Game.query.get(game_id)

    if not game:
        return jsonify({"error": "Game not found"}), 404

    rounds = (
        Round.query
        .filter_by(game_id=game_id)
        .order_by(Round.round_order)
        .all()
    )

    game.current_points_team1 = 0
    game.current_points_team2 = 0
    game.winner = None

    def still_in_game(t1, t2, target):
        return not ((t1 >= target and t1 > t2) or (t2 >= target and t2 > t1))

    game_ended = False
    winning_round_found = False

    for r in rounds:

        if not game_ended:
            # add points ONLY while game is active
            game.current_points_team1 += r.tichu_points_team1 + r.round_points_team1
            game.current_points_team2 += r.tichu_points_team2 + r.round_points_team2

            cond = still_in_game(
                game.current_points_team1,
                game.current_points_team2,
                game.target
            )

            # game just ended at this round
            if not cond:
                game_ended = True
                winning_round_found = True

                if (
                    game.current_points_team1 >= game.target and
                    game.current_points_team1 > game.current_points_team2
                ):
                    game.winner = 1

                elif (
                    game.current_points_team2 >= game.target and
                    game.current_points_team2 > game.current_points_team1
                ):
                    game.winner = 2

                r.bool_win_round = True

        else:
            # after game ends: ignore all later rounds
            r.bool_win_round = False

    # safety: if no win detected, all rounds valid
    if not winning_round_found:
        for r in rounds:
            r.bool_win_round = True

    db.session.commit()

    socketio.emit("game_recalculated", {"game_id": game_id})

    return jsonify({
        "game_id": game_id,
        "current_points_team1": game.current_points_team1,
        "current_points_team2": game.current_points_team2,
        "winner": game.winner,
    }), 200