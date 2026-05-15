from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Profile(db.Model):
    __tablename__ = "profiles"

    # Basic Info
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=True)

    profile_image_url = db.Column(db.String(500), nullable=True)

    date_added = db.Column(db.DateTime, nullable=True)

    # Game Stats
    elo = db.Column(db.Integer, nullable=True)

    winner_percentage = db.Column(db.Integer, default=0)

    tichu_master = db.Column(db.Float, default=0)

    visionary = db.Column(db.Integer, default=0)
    addict = db.Column(db.Integer, default=0)
    teamplayer = db.Column(db.Integer, default=0)
    announcer = db.Column(db.Integer, default=0)
    saboteur = db.Column(db.Integer, default=0)
    gambler = db.Column(db.Integer, default=0)
    big_gambler = db.Column(db.Integer, default=0)
    pingu_gambler = db.Column(db.Integer, default=0)
    bomber = db.Column(db.Integer, default=0)

    # Timestamps (optional but recommended)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "profile_image_url": self.profile_image_url,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "elo": self.elo,
            "winner_percentage": self.winner_percentage,
            "tichu_master": self.tichu_master,
            "visionary": self.visionary,
            "addict": self.addict,
            "teamplayer": self.teamplayer,
            "announcer": self.announcer,
            "saboteur": self.saboteur,
            "gambler": self.gambler,
            "big_gambler": self.big_gambler,
            "pingu_gambler": self.pingu_gambler,
            "bomber": self.bomber,
        }
    
    
class ProfileFriend(db.Model):
        __tablename__ = "profile_friends"

        profile_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), primary_key=True)
        friend_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), primary_key=True)
        created_at = db.Column(db.DateTime, server_default=db.func.now())



class FriendRequest(db.Model):
    __tablename__ = "friend_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False)
    status = db.Column(db.Enum("pending", "accepted", "rejected"), default="pending")
    created_at = db.Column(db.DateTime, server_default=db.func.now())