from flask_sqlalchemy import SQLAlchemy
from extensions import db


class Round(db.Model):
    __tablename__ = "rounds"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"))

    round_order = db.Column(db.Integer)

    first_profile_id = db.Column(db.Integer)
    second_profile_id = db.Column(db.Integer)
    third_profile_id = db.Column(db.Integer)
    fourth_profile_id = db.Column(db.Integer)

    first_bombs = db.Column(db.Integer, default=0)
    second_bombs = db.Column(db.Integer, default=0)
    third_bombs = db.Column(db.Integer, default=0)
    fourth_bombs = db.Column(db.Integer, default=0)

    tichu_points_team1 = db.Column(db.Integer, default=50)
    tichu_points_team2 = db.Column(db.Integer, default=50)

    round_points_team1 = db.Column(db.Integer, default=0)
    round_points_team2 = db.Column(db.Integer, default=0)

    double_win_team1 = db.Column(db.Boolean, default=False)
    double_win_team2 = db.Column(db.Boolean, default=False)

    date = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())

    bool_win_round = db.Column(db.Boolean, nullable=False, default=False)
    announced_tichu = db.Column(db.JSON, default=list)
    announced_big_tichu = db.Column(db.JSON, default=list)
    announced_pingu = db.Column(db.JSON, default=list)

    # ------------------------
    # VALIDATION
    # ------------------------
    def validate(self):
        for b in [
            self.first_bombs,
            self.second_bombs,
            self.third_bombs,
            self.fourth_bombs
        ]:
            if b > 3:
                raise ValueError("Max 3 bombs per player")

        if self.tichu_points_team1 + self.tichu_points_team2 != 100:
            raise ValueError("Tichu points must sum to 100")

        all_ann = (
            self.announced_tichu +
            self.announced_big_tichu +
            self.announced_pingu
        )

        if len(all_ann) != len(set(all_ann)):
            raise ValueError("A player can only announce one type")

    # ------------------------
    # SERIALIZATION
    # ------------------------
    def to_dict(self):
        return {
            "id": self.id,
            "game_id": self.game_id,
            "round_order": self.round_order,

            "first_profile_id": self.first_profile_id,
            "second_profile_id": self.second_profile_id,
            "third_profile_id": self.third_profile_id,
            "fourth_profile_id": self.fourth_profile_id,

            "first_bombs": self.first_bombs,
            "second_bombs": self.second_bombs,
            "third_bombs": self.third_bombs,
            "fourth_bombs": self.fourth_bombs,

            "tichu_points_team1": self.tichu_points_team1,
            "tichu_points_team2": self.tichu_points_team2,

            "round_points_team1": self.round_points_team1,
            "round_points_team2": self.round_points_team2,

            "double_win_team1": self.double_win_team1,
            "double_win_team2": self.double_win_team2,

            "bool_win_round": self.bool_win_round,
            "announced_tichu": self.announced_tichu or [],
            "announced_big_tichu": self.announced_big_tichu or [],
            "announced_pingu": self.announced_pingu or [],

            "date": self.date.isoformat() if self.date else None,
        }