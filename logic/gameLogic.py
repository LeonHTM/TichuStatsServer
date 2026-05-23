from flask_sqlalchemy import SQLAlchemy
from extensions import db

class Game(db.Model):
    __tablename__ = "tichu_games"

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


    