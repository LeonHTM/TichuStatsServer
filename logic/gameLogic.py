from flask import jsonify
from flask_sqlalchemy import SQLAlchemy
from extensions import db, socketio
from logic.roundLogic import Round
from logic.profileLogic import Profile, calculateStats

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
    rated = db.Column(db.Boolean, default=None, nullable=True)
    calculated = db.Column(db.Boolean, default=False)

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
            "rated": self.rated,
        }


class EloHistory(db.Model):
    __tablename__ = "elo_history"

    id         = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    game_id    = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"), nullable=True)
    elo_change = db.Column(db.Float, nullable=False)
    changed_at = db.Column(db.DateTime, server_default=db.func.now())


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
            game.current_points_team1 += r.tichu_points_team1 + r.round_points_team1
            game.current_points_team2 += r.tichu_points_team2 + r.round_points_team2

            cond = still_in_game(
                game.current_points_team1,
                game.current_points_team2,
                game.target
            )

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
                    print("would have finished")
                    game.winner = 2

                r.bool_win_round = True

        else:
            r.bool_win_round = False

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


def finish_game(game_id):
    game = Game.query.get(game_id)

    if not game:
        print("Could not finish game: Game Not found")
        return jsonify({"error": "Game not found"}), 404

    print("finish game")
    player_ids = [
        game.team1_player1_id,
        game.team1_player2_id,
        game.team2_player1_id,
        game.team2_player2_id
    ]

    if any(p in (-1, -2, -3, -4) for p in player_ids):
        game.rated = False
    else:
        game.rated = True

    db.session.commit()

    calculate_elo(game_id, game.winner)


def calculate_elo(game_id, winner):
    winner1 = 0
    winner2 = 0

    if winner == 2:
        winner2 = 1
        winner1 = 0
    elif winner == 1:
        winner2 = 0
        winner1 = 1
    else:
        print("ERROR NO WINNER WAS GIVEN TO ELO CALCULATION")
        return

    game = Game.query.get(game_id)

    # Use filter_by().first() instead of .get() so negative IDs work correctly
    team1_player1 = Profile.query.filter_by(id=game.team1_player1_id).first()
    team1_player2 = Profile.query.filter_by(id=game.team1_player2_id).first()
    team2_player1 = Profile.query.filter_by(id=game.team2_player1_id).first()
    team2_player2 = Profile.query.filter_by(id=game.team2_player2_id).first()

    if any(p is None for p in [team1_player1, team1_player2, team2_player1, team2_player2]):
        print("ERROR: One or more players not found in DB")
        return

    # Guest profiles have NULL elo — default to 1000
    def safe_elo(profile):
        return profile.elo if profile.elo is not None else 1000

    # Calculate avg Elo rating of teams
    team1_elo = (safe_elo(team1_player1) + safe_elo(team1_player2)) / 2
    team2_elo = (safe_elo(team2_player1) + safe_elo(team2_player2)) / 2

    # Calculate expected win probability
    Exp1 = 1 / (1 + 10 ** ((team2_elo - team1_elo) / 400))
    Exp2 = 1 - Exp1

    multiplier = (game.target / 1000) * 20
    delta1 = round(multiplier * (winner1 - Exp1), 2)
    delta2 = round(multiplier * (winner2 - Exp2), 2)

    print(f"Team 1 gets: {delta1}")
    print(f"Team 2 gets: {delta2}")

    if game.rated:
        # Only update elo and write history for real (positive ID) players
        for p, delta in [
            (team1_player1, delta1), (team1_player2, delta1),
            (team2_player1, delta2), (team2_player2, delta2)
        ]:
            if p.id > 0:
                p.elo = safe_elo(p) + delta
                db.session.add(EloHistory(profile_id=p.id, game_id=game_id, elo_change=delta))
    else:
        print("ADDING NOT RATED")
        # Only write zero-history for real players — guests have no EloHistory row
        for p in [team1_player1, team1_player2, team2_player1, team2_player2]:
            if p.id > 0:
                db.session.add(EloHistory(profile_id=p.id, game_id=game_id, elo_change=0))

    game.calculated = True

    # Only run calculateStats for real players
    playerIds = [
        p.id for p in [team1_player1, team1_player2, team2_player1, team2_player2]
        if p.id > 0
    ]

    for playerId in playerIds:
        calculateStats(playerId, "all_time")
        calculateStats(playerId, "year")
        calculateStats(playerId, "month")
        calculateStats(playerId, "week")
        calculateStats(playerId, "day")

    db.session.commit()

    socketio.emit("elo_updated", {
        "players": [
            {"id": p.id, "elo": safe_elo(p)}
            for p in [team1_player1, team1_player2, team2_player1, team2_player2]
            if p.id > 0
        ]
    })